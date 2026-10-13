"""Loads PJM zone-level LMP data from Postgres into a clean, 5-minute-indexed pandas Series.

Mirrors model/data.py's load_eia_series in shape (reindex onto a complete period range so
gaps surface as NaN, same apply_missing_data_policy from model/data.py handles them), but
deliberately does NOT reuse EIA's plausibility-masking approach. Architecture.md Section 6:
real PJM prices range from about -$611/MWh to +$4,251/MWh across the five PA zones, and both
extremes are genuine market phenomena (oversupply, scarcity), not sensor errors -- clipping
them the way EIA demand is clipped would delete the signal the private tier exists to find.
Confirmed live (2026-10-13) that the backfilled data has zero gaps and zero quality='missing'
rows across all 5 zones, so apply_missing_data_policy is applied defensively here for when
the live poller eventually contributes rows, not because the current data needs it.
"""
from __future__ import annotations

import pandas as pd
import psycopg

ZONES = ("PECO", "PPL", "METED", "PENELEC", "DUQ")

_QUERY = """
SELECT period_start, lmp_price, quality
FROM pjm_lmp_readings
WHERE zone = %(zone)s
  AND period_start >= %(start)s AND period_start < %(end)s
ORDER BY period_start
"""


def load_pjm_series(dsn: str, zone: str, start, end) -> pd.Series:
    """Raw 5-minute series for one PA zone, reindexed onto a complete 5-minute range so any
    gap shows up as NaN. Does NOT apply the missing-data policy -- call
    model.data.apply_missing_data_policy on the result, same as the EIA path."""
    if zone not in ZONES:
        raise ValueError(f"unknown PJM zone {zone!r}; expected one of {ZONES}")

    with psycopg.connect(dsn) as conn:
        df = pd.read_sql_query(_QUERY, conn, params={"zone": zone, "start": start, "end": end})

    if df.empty:
        raise ValueError(f"no pjm_lmp_readings rows for zone={zone!r} in [{start}, {end})")

    df["period_start"] = pd.to_datetime(df["period_start"], utc=True)
    df = df[df["quality"] == "ok"][["period_start", "lmp_price"]]
    series = df.set_index("period_start")["lmp_price"].sort_index()

    full_index = pd.date_range(start=start, end=end, freq="5min", inclusive="left", tz="UTC")
    return series.reindex(full_index)
