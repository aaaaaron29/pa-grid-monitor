#!/usr/bin/env python
"""Re-score the trailing days of stored readings and write the results to the anomaly tables.

Why this exists: the live inference services score each reading as it arrives, and decline to
score when the stored history before it has a hole (they need about a week of dense history for
the seasonal-naive forecast). A hole therefore leaves a stretch with no forecast and no
residuals, so the dashboards' forecast lines and residual charts come up empty for it even
after the underlying readings are backfilled. This fills that stretch using the same detector
artifacts, the same missing-data policy, and the same scoring code (model.score.score_since,
which a test pins to score_latest, the function the live services call).

Only real observed readings are scored. Forward-filled and excluded periods are skipped, as the
live services never score a value that was not actually observed.

Usage:
  python scripts/rescore_recent.py                  both tiers, last 7 days
  python scripts/rescore_recent.py --tier pjm --days 10
  python scripts/rescore_recent.py --dry-run        score and report, write nothing

Safe to repeat: rows are upserted on their primary key.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.db import connect, upsert_eia_anomalies, upsert_pjm_lmp_anomalies  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from model.artifact import ModelArtifact  # noqa: E402
from model.data import apply_missing_data_policy, load_eia_series  # noqa: E402
from model.data_pjm import ZONES, load_pjm_series  # noqa: E402
from model.score import min_history_periods, score_since  # noqa: E402

log = logging.getLogger("rescore_recent")

PJM_MAX_FORWARD_FILL_PERIODS = 3  # matches inference/pjm_service.py and model/train.py
EIA_ARTIFACT = "artifacts/eia_detector.joblib"
PJM_ARTIFACT = "artifacts/pjm_detector_{zone}.joblib"


def _real_rows(results: list[dict], quality: pd.Series) -> list[dict]:
    """Keep rows that had a real observation and enough context to have a residual."""
    return [
        r
        for r in results
        if r["residual"] is not None and quality.get(r["period_start"]) == "ok"
    ]


def rescore_pjm(dsn: str, days: int, dry_run: bool) -> int:
    # End is exclusive, so the interval still in progress is left out.
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    since = end - pd.Timedelta(days=days)
    written = 0
    for zone in ZONES:
        artifact = ModelArtifact.load(PJM_ARTIFACT.format(zone=zone))
        needed = min_history_periods(artifact)
        start = since - pd.Timedelta(minutes=5 * (needed + 30))
        raw = load_pjm_series(dsn, zone, start=start.to_pydatetime(), end=end.to_pydatetime())
        values, quality = apply_missing_data_policy(
            raw, max_forward_fill_periods=PJM_MAX_FORWARD_FILL_PERIODS
        )
        # Excluded periods stay in as NaN so the seasonal lag still lands on the same time of day
        # (see model.score.score_latest); points they leave without context come back unscored.
        rows = _real_rows(score_since(values, artifact, since), quality)
        now = datetime.now(UTC)
        for r in rows:
            r["zone"] = zone
            r["scored_at"] = now
        if rows and not dry_run:
            with connect(dsn) as conn:
                upsert_pjm_lmp_anomalies(conn, rows)
        flagged = sum(r["forest_flagged"] or r["flatline_flagged"] for r in rows)
        log.info("zone rescored", extra={"zone": zone, "rows": len(rows), "flagged": flagged})
        written += len(rows)
    return written


def rescore_eia(dsn: str, days: int, dry_run: bool) -> int:
    end = pd.Timestamp.now(tz="UTC").floor("h")
    since = end - pd.Timedelta(days=days)
    artifact = ModelArtifact.load(EIA_ARTIFACT)
    needed = min_history_periods(artifact)
    start = since - pd.Timedelta(hours=needed + 5)
    raw = load_eia_series(
        dsn,
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        reading_type="D",
        respondent="PJM",
    )
    values, quality = apply_missing_data_policy(raw)
    rows = _real_rows(score_since(values, artifact, since), quality)
    now = datetime.now(UTC)
    for r in rows:
        r["reading_type"] = "D"
        r["scored_at"] = now
    if rows and not dry_run:
        with connect(dsn) as conn:
            upsert_eia_anomalies(conn, rows)
    flagged = sum(r["forest_flagged"] or r["flatline_flagged"] for r in rows)
    log.info("eia rescored", extra={"rows": len(rows), "flagged": flagged})
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", choices=["pjm", "eia", "all"], default="all")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true", help="score and report; write nothing")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    dsn = settings.postgres_dsn
    if "neon.tech" in dsn:
        log.error("POSTGRES_DSN points at Neon; this writes to the pipeline's own database")
        return 2

    total = 0
    if args.tier in ("pjm", "all"):
        total += rescore_pjm(dsn, args.days, args.dry_run)
    if args.tier in ("eia", "all"):
        total += rescore_eia(dsn, args.days, args.dry_run)
    log.info("rescore complete", extra={"rows": total, "dry_run": args.dry_run, "days": args.days})
    return 0


if __name__ == "__main__":
    sys.exit(main())
