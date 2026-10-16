#!/usr/bin/env python
"""Print how fresh each stream in the local database is, as one line of JSON.

Read-only. Used by the Windows watchdog (scripts/windows/watchdog.ps1) to decide whether the
pipeline has stalled, and handy by hand:

  python scripts/pipeline_status.py            JSON on one line
  python scripts/pipeline_status.py --pretty   a small table

Each age is minutes between now and the newest row's period_start. Normal ranges, so a reader
knows what "stale" means: PJM LMP posts every 5 minutes (a few minutes old is normal); EIA-930
publishes hours after the hour (about 3 to 6 hours old is normal); PJM metered load posts once a
day with a lag of a day or two. A stream with no rows yet reports null.
"""
from __future__ import annotations

import argparse
import json
import sys

import psycopg

from common.config import get_settings
from common.health import stream_ages


def collect(dsn: str) -> dict[str, float | None]:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        return stream_ages(conn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        ages = collect(get_settings().postgres_dsn)
    except Exception as exc:  # the watchdog treats any failure here as "database unreachable"
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"[:200]}))
        return 1
    if args.pretty:
        for key, age in ages.items():
            print(f"{key:16} {'no rows' if age is None else f'{age:,.0f} min old'}")
    else:
        print(json.dumps(ages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
