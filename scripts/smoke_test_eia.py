#!/usr/bin/env python
"""One-shot manual check against the REAL EIA API — not part of the pytest suite (CI makes
no live API calls, Architecture.md Section 7). Run this once, by hand, after loading a real
EIA_API_KEY, to confirm the assumptions baked into common/normalize.py:

  - the 'period' field format (assumed "YYYY-MM-DDTHH")
  - that EIA-930 hourly values are UTC
  - the response field names (respondent, type, value, ...)

If response.dateFormat or the actual period strings don't match what's printed below as
"assumed", fix _PERIOD_FORMAT / the UTC assumption in common/normalize.py and remove the
TODO(verify) comment there.

Usage: python scripts/smoke_test_eia.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from ingestion.eia_poller.client import fetch_page  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.eia_api_key:
        print("EIA_API_KEY is not set (check your .env) — nothing to test against.")
        sys.exit(1)

    now = datetime.now(UTC)
    start = now - timedelta(hours=6)

    page = fetch_page(
        api_key=settings.eia_api_key,
        reading_type="D",
        start=start,
        end=now,
        length=5,
    )

    print("--- raw response.* keys ---")
    print(sorted(page.keys()))
    print("\n--- response.dateFormat (if present) ---")
    print(page.get("dateFormat", "(not present in response)"))
    print("\n--- first row ---")
    rows = page.get("data", [])
    if not rows:
        print("(no rows returned for the last 6 hours — try a wider window)")
        sys.exit(0)
    print(json.dumps(rows[0], indent=2))
    print("\nassumed period format in common/normalize.py: %Y-%m-%dT%H")
    print(f"actual period string:                          {rows[0].get('period')!r}")
    print("\nassumed timezone: UTC — cross-check the period above against a known UTC time.")


if __name__ == "__main__":
    main()
