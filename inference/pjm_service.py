"""FastAPI inference service for the PJM (private) tier. Architecture.md Section 9 Phase 3:
"FastAPI inference service(s)". One process, not five -- Section 7/9's "two inference
services, kept separate so PJM and EIA data never share a serving path" means one service
per TIER, not one per zone. Loads all five zone artifacts (model/train.py's
train_pjm_detector, one per zone) at startup and routes each incoming row to the matching
zone's artifact.

Mirrors inference/eia_service.py's design exactly for the parts that don't depend on zoning:
background consumer thread, manual offset commits only after a successful write, and the
same race-condition avoidance (the current point's value comes from the Kafka message
itself, Postgres is only queried for history strictly before it -- see that module's
docstring for the full reasoning, including the graceful-shutdown/rebalance-delay finding).

History requirement note: the seasonal-naive lag (model/train.py's
PJM_SEASONAL_NAIVE_LAG_PERIODS, 7 days at 5-minute grain) means this needs roughly a full
week of dense trailing history in pjm_lmp_readings before it can score anything. Confirmed
live (2026-10-13): this correctly declines to score, rather than scoring on a thin window,
when pjm_lmp_readings has a real multi-hour gap right before the current point -- which
happens whenever ingestion/pjm_poller hasn't been running continuously, since PJM's live
feed only ever returns "the most recent interval" and can't be backfilled after the fact
(the verified feed that can backfill reconciles the next day, so it won't have it either).
This is expected behavior, not a bug to silence.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi import FastAPI

from common.config import Settings, get_settings
from common.db import connect, upsert_pjm_lmp_anomalies
from common.kafka import TOPIC_PJM_RAW, commit_offsets, make_consumer, poll_row
from common.logging import configure_logging
from common.metrics import (
    ANOMALIES_FLAGGED_TOTAL,
    LAST_SUCCESSFUL_SCORE_TS,
    SCORING_LATENCY_SECONDS,
    SCORING_RUNS_TOTAL,
    start_metrics_server,
)
from inference.skip_tracker import SkipTracker
from model.artifact import ModelArtifact
from model.data import apply_missing_data_policy
from model.data_pjm import ZONES, load_pjm_series
from model.score import min_history_periods, score_latest

log = logging.getLogger(__name__)
_skips = SkipTracker(log)

ARTIFACT_PATH_TEMPLATE = "artifacts/pjm_detector_{zone}.joblib"
MAX_FORWARD_FILL_PERIODS = 3  # matches model/train.py's PJM_MAX_FORWARD_FILL_PERIODS
TIER = "pjm"

_state: dict = {"artifacts": {}, "last_scored_at": None, "consumer_alive": False}
_stop_event = threading.Event()


def _load_artifacts() -> dict[str, ModelArtifact]:
    artifacts = {}
    for zone in ZONES:
        artifacts[zone] = ModelArtifact.load(ARTIFACT_PATH_TEMPLATE.format(zone=zone))
    return artifacts


def _build_history_plus_current(
    settings: Settings, artifact: ModelArtifact, row: dict
) -> pd.Series | None:
    period_start = datetime.fromisoformat(row["period_start"])
    needed = min_history_periods(artifact)
    # +30 periods of safety margin (5-min grain, so this is 2.5 hours) -- same reasoning as
    # eia_service.py's margin, scaled for PJM's much shorter period length.
    history_start = period_start - timedelta(minutes=5 * (needed + 30))

    raw = load_pjm_series(settings.postgres_dsn, row["zone"], start=history_start, end=period_start)
    values, quality = apply_missing_data_policy(
        raw, max_forward_fill_periods=MAX_FORWARD_FILL_PERIODS
    )
    history = values[quality != "excluded"]

    lmp_price = row.get("lmp_price")
    if lmp_price is None:
        return None  # can't score a row with no value (quality='missing')

    combined = pd.concat([history, pd.Series([float(lmp_price)], index=[period_start])])
    if len(combined) < needed:
        return None  # not enough settled history yet
    return combined


def _score_and_store(settings: Settings, artifacts: dict[str, ModelArtifact], row: dict) -> None:
    artifact = artifacts.get(row["zone"])
    if artifact is None:
        return  # not one of our five tracked PA zones

    series = _build_history_plus_current(settings, artifact, row)
    if series is None:
        log.debug(
            "skipping score, insufficient settled history",
            extra={"zone": row["zone"], "period_start": row["period_start"]},
        )
        # DEBUG alone hid a multi-day halt for days; this warns once per halt (see skip_tracker).
        _skips.skipped(row["zone"], period_start=row["period_start"])
        # Worth tracking: this is exactly the symptom of the real pjm_lmp_readings gap
        # confirmed live 2026-10-13 (see module docstring), not routine noise.
        SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="skipped").inc()
        return

    started = time.monotonic()
    try:
        result = score_latest(series, artifact)
        result["zone"] = row["zone"]
        result["scored_at"] = datetime.now(UTC)

        with connect(settings.postgres_dsn) as conn:
            upsert_pjm_lmp_anomalies(conn, [result])
    except Exception:
        SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="error").inc()
        raise
    finally:
        SCORING_LATENCY_SECONDS.labels(tier=TIER).observe(time.monotonic() - started)

    SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="scored").inc()
    _skips.scored(row["zone"])
    LAST_SUCCESSFUL_SCORE_TS.labels(tier=TIER).set(result["scored_at"].timestamp())
    if result["forest_flagged"]:
        ANOMALIES_FLAGGED_TOTAL.labels(tier=TIER, zone=row["zone"], detector="forest").inc()
    if result["flatline_flagged"]:
        ANOMALIES_FLAGGED_TOTAL.labels(tier=TIER, zone=row["zone"], detector="flatline").inc()

    _state["last_scored_at"] = result["scored_at"]
    if result["forest_flagged"] or result["flatline_flagged"]:
        log.info(
            "anomaly flagged",
            extra={
                "zone": row["zone"],
                "period_start": row["period_start"],
                "forest_flagged": result["forest_flagged"],
                "flatline_flagged": result["flatline_flagged"],
                "residual": result["residual"],
            },
        )


def _consume_forever(settings: Settings, artifacts: dict[str, ModelArtifact]) -> None:
    consumer = make_consumer(settings.kafka_bootstrap_servers, "pjm-inference", [TOPIC_PJM_RAW])
    _state["consumer_alive"] = True
    log.info("pjm inference consumer loop starting")
    while not _stop_event.is_set():
        try:
            row = poll_row(consumer, timeout=1.0)
            if row is None:
                continue
            _score_and_store(settings, artifacts, row)
            commit_offsets(consumer)
        except Exception:
            log.exception("scoring loop error, continuing")
    consumer.close()
    _state["consumer_alive"] = False


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)
    _state["artifacts"] = _load_artifacts()
    thread = threading.Thread(
        target=_consume_forever, args=(settings, _state["artifacts"]), daemon=True
    )
    thread.start()
    yield
    _stop_event.set()


def create_app() -> FastAPI:
    app = FastAPI(title="PJM inference service", lifespan=_lifespan)

    @app.get("/health")
    def health() -> dict:
        return {
            "model_loaded": len(_state["artifacts"]) == len(ZONES),
            "zones_loaded": sorted(_state["artifacts"].keys()),
            "consumer_alive": _state["consumer_alive"],
            "last_scored_at": _state["last_scored_at"],
        }

    return app


app = create_app()
