"""Loads EIA demand data from Postgres into a clean, hourly-indexed pandas Series, applying
the missing-data policy from Architecture.md Section 6 ("Feature design"):

    Rule: forward-fill gaps of 1-2 hours, mark longer gaps as quality='missing' and exclude
    them from both training and scoring, and surface gap counts on the dashboard rather than
    hiding them.

Two gap sources, both end up as the same thing here (a missing hour in a continuous
hourly index): an explicit null value (ingestion/eia_poller normalize.py's quality='missing'
rows) and an hour EIA simply never published a row for at all (confirmed live, documented in
common/normalize.py — EIA omits, it doesn't always null). Reindexing onto a complete hourly
range surfaces both the same way, which is the point: the model shouldn't have to care which
kind of gap it was.
"""
from __future__ import annotations

import pandas as pd
import psycopg

# Sanity bounds for PJM-wide hourly demand (MW). Confirmed live (2026-10-13): 3 rows out of
# 68,226 (around 2021-10-18/19) had values in the hundreds-of-millions to 2.1 billion MW
# range -- 2,147,480,000 is suspiciously close to 2^31-1, a classic 32-bit sentinel/overflow
# value, strongly suggesting a data-quality incident on EIA's own side, not anything in this
# project's ingestion path. PJM's actual all-time peak demand is roughly 165,000 MW (summer
# 2006); 250,000 MW leaves generous headroom above any plausible real reading while sitting
# nowhere near the garbage values actually observed. Values outside these bounds are treated
# as gaps (NaN) before apply_missing_data_policy runs, so a single implausible reading flows
# through the exact same fill/exclude logic as any other missing hour -- no separate code path.
MIN_PLAUSIBLE_MW = 1_000
MAX_PLAUSIBLE_MW = 250_000

_QUERY = """
SELECT period_start, value_mw, quality
FROM eia_readings
WHERE respondent = %(respondent)s AND reading_type = %(reading_type)s
  AND period_start >= %(start)s AND period_start < %(end)s
ORDER BY period_start
"""


def mask_implausible(series: pd.Series) -> pd.Series:
    """Pure function: anything outside [MIN_PLAUSIBLE_MW, MAX_PLAUSIBLE_MW] becomes NaN, same
    as any other gap. Split out from load_eia_series so this is unit-testable without a DB."""
    implausible = (series < MIN_PLAUSIBLE_MW) | (series > MAX_PLAUSIBLE_MW)
    return series.mask(implausible)


def load_eia_series(
    dsn: str,
    start,
    end,
    reading_type: str = "D",
    respondent: str = "PJM",
) -> pd.Series:
    """Raw hourly series, reindexed onto a complete hourly range so every gap (explicit null
    or an hour EIA never published) shows up as NaN rather than a missing index entry. Does
    NOT apply the missing-data policy — call apply_missing_data_policy on the result."""
    with psycopg.connect(dsn) as conn:
        df = pd.read_sql_query(
            _QUERY,
            conn,
            params={
                "respondent": respondent,
                "reading_type": reading_type,
                "start": start,
                "end": end,
            },
        )

    if df.empty:
        raise ValueError(
            f"no eia_readings rows for {respondent}/{reading_type} in [{start}, {end})"
        )

    df["period_start"] = pd.to_datetime(df["period_start"], utc=True)
    # quality='missing' rows carry an explicit NULL value already; treat identically to a
    # genuinely absent row by dropping them before reindexing.
    df = df[df["quality"] == "ok"][["period_start", "value_mw"]]
    series = df.set_index("period_start")["value_mw"].sort_index()

    series = mask_implausible(series)

    full_index = pd.date_range(start=start, end=end, freq="h", inclusive="left", tz="UTC")
    return series.reindex(full_index)


def apply_missing_data_policy(
    series: pd.Series, max_forward_fill_hours: int = 2
) -> tuple[pd.Series, pd.Series]:
    """Pure function, no I/O — forward-fills NaN runs of length <= max_forward_fill_hours,
    leaves longer runs as NaN (excluded). Returns (processed_values, quality_labels) where
    quality_labels is one of 'ok' (never missing), 'filled' (forward-filled), or 'excluded'
    (gap too long, left NaN) per hour.

    This is the one place the project's missing-data policy is actually enforced — train and
    score must both go through it, never consume load_eia_series's raw output directly.
    """
    is_na = series.isna()
    # Group consecutive NaNs into runs: each time is_na flips, start a new group id.
    run_id = is_na.ne(is_na.shift()).cumsum()
    run_length = is_na.groupby(run_id).transform("size")

    short_gap = is_na & (run_length <= max_forward_fill_hours)
    long_gap = is_na & (run_length > max_forward_fill_hours)

    filled = series.ffill()
    processed = series.copy()
    processed[short_gap] = filled[short_gap]
    # long_gap stays NaN in `processed` — explicitly excluded, not silently dropped, so the
    # index length (and therefore anything aligned to it, like calendar features) is unchanged.

    quality = pd.Series("ok", index=series.index, dtype="object")
    quality[short_gap] = "filled"
    quality[long_gap] = "excluded"

    return processed, quality
