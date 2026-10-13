"""CLI entry point: python -m ingestion.backfill --source eia --start 2019-01-01
(Architecture.md Section 6). Runnable the same way as a K8s Job.
"""
from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from common.config import get_settings
from common.logging import configure_logging
from common.metrics import start_metrics_server
from ingestion.backfill.eia_backfill import run_eia_backfill
from ingestion.backfill.pjm_backfill import run_pjm_backfill

log = logging.getLogger("backfill")


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=["eia", "pjm", "queue"])
    parser.add_argument("--start", required=True, type=_parse_date, help="YYYY-MM-DD, UTC")
    parser.add_argument(
        "--end", type=_parse_date, default=None, help="YYYY-MM-DD, UTC; default now"
    )
    parser.add_argument("--respondent", default="PJM")
    parser.add_argument("--no-metrics-server", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    if not args.no_metrics_server:
        start_metrics_server(settings.metrics_port)

    if args.source == "eia":
        written = run_eia_backfill(
            settings, start=args.start, end=args.end, respondent=args.respondent
        )
        log.info("backfill complete", extra={"source": "eia", "rows_written": written})
    elif args.source == "pjm":
        written = run_pjm_backfill(settings, start=args.start, end=args.end)
        log.info("backfill complete", extra={"source": "pjm", "rows_written": written})
    else:
        raise NotImplementedError(
            f"'{args.source}' backfill isn't built yet — the queue scraper's source is "
            "still TBD (Architecture.md Section 4/9), unlike EIA and PJM which are both "
            "confirmed and built."
        )


if __name__ == "__main__":
    main()
