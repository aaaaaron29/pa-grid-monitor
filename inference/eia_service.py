"""FastAPI inference service for the EIA (public) tier. Architecture.md Section 9 Phase 3:
"FastAPI inference service(s)". Loads a pre-trained ModelArtifact (Section 7: training
happens off-cluster, this only serves it), runs a background thread consuming eia.grid.raw,
scores each demand row, writes results to eia_anomalies.

The artifact was trained on reading_type="D" (demand) specifically (model/train.py) -- NG
and TI rows are still raw-ingested by ingestion/eia_poller/consumer.py but not scored here;
a generation/interchange detector is future work, not silently approximated by this one.

Race-condition note (the reason this isn't a naive "re-query Postgres for the latest row"):
this service and ingestion/eia_poller/consumer.py both consume eia.grid.raw independently,
with no ordering guarantee between them. Scoring must not depend on the raw-write consumer
having already committed the current row to Postgres. Instead, the CURRENT point's value
comes directly from the Kafka message itself; Postgres is only queried for history strictly
BEFORE it, which is always already-settled data by the time a new point arrives.

Shutdown note: a clean shutdown (SIGTERM, or this process's own lifespan teardown) lets the
consumer leave the group immediately, so the next instance can take over without waiting out
a rebalance. A hard kill (SIGKILL, `Stop-Process -Force`) skips that, and the group
coordinator won't hand off the partitions until the old session times out -- confirmed
locally: a force-killed instance left scoring stalled for the next instance under the same
group_id until a fresh group_id was used, even though the broker-side lag was already 0.
Production deploys should terminate this process with a grace period, not a force-kill.
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
from common.db import connect, upsert_eia_anomalies
from common.kafka import TOPIC_EIA_RAW, commit_offsets, make_consumer, poll_row
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
from model.data import apply_missing_data_policy, load_eia_series
from model.score import has_context, min_history_periods, score_latest

log = logging.getLogger(__name__)
_skips = SkipTracker(log)

ARTIFACT_PATH = "artifacts/eia_detector.joblib"
SCORED_READING_TYPE = "D"
TIER = "eia"
ZONE_LABEL = "none"  # EIA has no zones; see common/metrics.py's ANOMALIES_FLAGGED_TOTAL

_state: dict = {"artifact": None, "last_scored_at": None, "consumer_alive": False}
_stop_event = threading.Event()


def _build_history_plus_current(
    settings: Settings, artifact: ModelArtifact, row: dict
) -> pd.Series | None:
    period_start = datetime.fromisoformat(row["period_start"])
    needed = min_history_periods(artifact)
    # +5 hours of safety margin: the missing-data policy can exclude a short gap, so ask for
    # slightly more than the bare minimum to still end up with `needed` usable rows.
    history_start = period_start - timedelta(hours=needed + 5)

    raw = load_eia_series(
        settings.postgres_dsn,
        start=history_start,
        end=period_start,  # exclusive -- never includes the row this call is about to score
        reading_type=row["reading_type"],
        respondent=row["respondent"],
    )
    values, quality = apply_missing_data_policy(raw)
    # Excluded periods stay in as NaN: dropping them would shift the seasonal-naive lag onto the
    # wrong hour (see model.score.score_latest).
    history = values

    value_mw = row.get("value_mw")
    if value_mw is None:
        return None  # can't score a row with no value (quality='missing')

    combined = pd.concat([history, pd.Series([float(value_mw)], index=[period_start])])
    if len(combined) < needed:
        return None  # not enough settled history yet (e.g. near the start of backfill)
    return combined


def _score_and_store(settings: Settings, artifact: ModelArtifact, row: dict) -> None:
    if row["reading_type"] != SCORED_READING_TYPE:
        return  # this artifact only knows demand; see module docstring -- not a "skipped"
        # scoring run, this row was never a candidate for this detector in the first place

    series = _build_history_plus_current(settings, artifact, row)
    if series is None:
        log.debug(
            "skipping score, insufficient settled history",
            extra={"period_start": row["period_start"]},
        )
        # DEBUG alone hides a halt; this warns once per halt (see skip_tracker).
        _skips.skipped("demand", period_start=row["period_start"])
        # Worth tracking: a persistently high skip rate here is exactly the symptom of a
        # real upstream history gap (confirmed live for PJM, 2026-10-13: the raw-ingestion
        # consumer wasn't running continuously), not routine noise like the reading_type
        # filter above.
        SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="skipped").inc()
        return

    started = time.monotonic()
    try:
        result = score_latest(series, artifact)
        declined = not has_context(result)
        if not declined:
            result["reading_type"] = row["reading_type"]
            result["scored_at"] = datetime.now(UTC)
            with connect(settings.postgres_dsn) as conn:
                upsert_eia_anomalies(conn, [result])
    except Exception:
        SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="error").inc()
        raise
    finally:
        SCORING_LATENCY_SECONDS.labels(tier=TIER).observe(time.monotonic() - started)

    if declined:
        # The reading a week earlier, or one the rolling features need, is missing.
        _skips.skipped("demand", period_start=row["period_start"])
        SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="skipped").inc()
        return

    SCORING_RUNS_TOTAL.labels(tier=TIER, outcome="scored").inc()
    _skips.scored("demand")
    LAST_SUCCESSFUL_SCORE_TS.labels(tier=TIER).set(result["scored_at"].timestamp())
    if result["forest_flagged"]:
        ANOMALIES_FLAGGED_TOTAL.labels(tier=TIER, zone=ZONE_LABEL, detector="forest").inc()
    if result["flatline_flagged"]:
        ANOMALIES_FLAGGED_TOTAL.labels(tier=TIER, zone=ZONE_LABEL, detector="flatline").inc()

    _state["last_scored_at"] = result["scored_at"]
    if result["forest_flagged"] or result["flatline_flagged"]:
        log.info(
            "anomaly flagged",
            extra={
                "period_start": row["period_start"],
                "forest_flagged": result["forest_flagged"],
                "flatline_flagged": result["flatline_flagged"],
                "residual": result["residual"],
            },
        )


def _consume_forever(settings: Settings, artifact: ModelArtifact) -> None:
    consumer = make_consumer(settings.kafka_bootstrap_servers, "eia-inference", [TOPIC_EIA_RAW])
    _state["consumer_alive"] = True
    log.info("eia inference consumer loop starting")
    while not _stop_event.is_set():
        try:
            row = poll_row(consumer, timeout=1.0)
            if row is None:
                continue
            _score_and_store(settings, artifact, row)
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
    _state["artifact"] = ModelArtifact.load(ARTIFACT_PATH)
    thread = threading.Thread(
        target=_consume_forever, args=(settings, _state["artifact"]), daemon=True
    )
    thread.start()
    yield
    _stop_event.set()


def create_app() -> FastAPI:
    app = FastAPI(title="EIA inference service", lifespan=_lifespan)

    @app.get("/health")
    def health() -> dict:
        return {
            "model_loaded": _state["artifact"] is not None,
            "consumer_alive": _state["consumer_alive"],
            "last_scored_at": _state["last_scored_at"],
        }

    return app


app = create_app()
