#!/usr/bin/env python
"""Copy new rows from the local Postgres into Neon. Run hourly by a scheduled task; safe to run
any time and as often as you like, because it only upserts and skips unchanged rows.

Usage:
  python scripts/sync_to_neon.py               incremental sync (what the schedule runs)
  python scripts/sync_to_neon.py --full        re-send everything (use after a long outage)
  python scripts/sync_to_neon.py --dry-run     report counts and lag, write nothing
  python scripts/sync_to_neon.py --log-file C:/path/neon-sync.log

Reads POSTGRES_DSN (the local database the pipeline writes to) and NEON_DIRECT_URL (Neon's
direct, unpooled connection string) from the environment or .env. See common/neon_sync.py for
why this is a sync rather than pointing the pipeline at Neon.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

# Under pythonw.exe (how the scheduled task runs, so no console window flashes up) there is no
# stdout or stderr at all. Give logging somewhere harmless to write; --log-file is the record.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from common.neon_sync import connect_with_retry, sync_all  # noqa: E402
from scripts.apply_migrations import apply_migrations  # noqa: E402

log = logging.getLogger("sync_to_neon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="copy every row, not just new ones")
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    parser.add_argument("--overlap-hours", type=float, default=6.0)
    parser.add_argument("--log-file", default=None, help="also append log lines to this file")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    if args.log_file:
        handler = logging.FileHandler(args.log_file, encoding="utf-8")
        handler.setFormatter(logging.getLogger().handlers[0].formatter)
        logging.getLogger().addHandler(handler)

    local, neon = settings.postgres_dsn, settings.neon_direct_url
    if not neon:
        log.error("NEON_DIRECT_URL is not set; nothing to sync to")
        return 2
    if "neon.tech" in local:
        log.error("POSTGRES_DSN points at Neon; refusing to sync Neon onto itself")
        return 2
    if "-pooler" in neon:
        log.error("NEON_DIRECT_URL is a pooled URL; use the direct (unpooled) one for batch writes")
        return 2

    try:
        if not args.dry_run:
            apply_migrations(neon)  # carry any schema change across before copying rows
        with connect_with_retry(local) as src, connect_with_retry(neon) as dst:
            results = sync_all(
                src,
                dst,
                overlap=timedelta(hours=args.overlap_hours),
                full=args.full,
                dry_run=args.dry_run,
            )
    except Exception:
        log.exception("neon sync failed")
        return 1

    behind = {r.table: r.source_count - r.destination_count for r in results}
    log.info(
        "neon sync complete",
        extra={
            "rows_written": sum(r.rows_written for r in results),
            "rows_behind_after": {t: n for t, n in behind.items() if n},
            "dry_run": args.dry_run,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
