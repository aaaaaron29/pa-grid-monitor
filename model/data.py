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

# Sanity bounds per EIA reading_type (MW). Confirmed live (2026-10-13): the same sentinel
# incident hit BOTH demand (D) and net generation (NG) -- 3 rows each, same exact
# 2,147,480,000 value, suspiciously close to 2^31-1, a classic 32-bit overflow/sentinel,
# strongly suggesting a data-quality incident on EIA's own side, not anything in this
# project's ingestion path. D and NG share demand-scale bounds (PJM's actual all-time peak
# demand is roughly 165,000 MW, summer 2006; generation tracks demand closely in a
# self-sufficient RTO). Total interchange (TI) is legitimately SIGNED -- observed live range
# is -4,456 to 15,772 MW, ordinary imports/exports -- so reusing the demand floor would wrongly
# mask every negative (but completely normal) interchange hour. TI gets a wide, symmetric band
# that only catches genuinely overflow-scale garbage, not real interchange swings.
# Values outside these bounds are treated as gaps (NaN) before apply_missing_data_policy
# runs, so a single implausible reading flows through the exact same fill/exclude logic as
# any other missing hour -- no separate code path.
PLAUSIBLE_BOUNDS_MW: dict[str, tuple[float, float]] = {
    "D": (1_000, 250_000),
    "NG": (1_000, 250_000),
    "TI": (-100_000, 100_000),
}

_QUERY = """
SELECT period_start, value_mw, quality
FROM eia_readings
WHERE respondent = %(respondent)s AND reading_type = %(reading_type)s
  AND period_start >= %(start)s AND period_start < %(end)s
ORDER BY period_start
"""


def mask_implausible(series: pd.Series, reading_type: str) -> pd.Series:
    """Pure function: anything outside PLAUSIBLE_BOUNDS_MW[reading_type] becomes NaN, same
    as any other gap. Split out from load_eia_series so this is unit-testable without a DB.
    Bounds are reading-type-specific on purpose (see PLAUSIBLE_BOUNDS_MW) — TI is legitimately
    signed, D/NG are not, reusing one bound for all three was the original (wrong) version."""
    try:
        low, high = PLAUSIBLE_BOUNDS_MW[reading_type]
    except KeyError:
        raise ValueError(
            f"no plausibility bounds defined for reading_type={reading_type!r}; "
            f"add one to PLAUSIBLE_BOUNDS_MW before using this reading type"
        ) from None
    implausible = (series < low) | (series > high)
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

    series = mask_implausible(series, reading_type)

    full_index = pd.date_range(start=start, end=end, freq="h", inclusive="left", tz="UTC")
    return series.reindex(full_index)


def apply_missing_data_policy(
    series: pd.Series, max_forward_fill_periods: int = 2
) -> tuple[pd.Series, pd.Series]:
    """Pure function, no I/O — forward-fills NaN runs of length <= max_forward_fill_periods,
    leaves longer runs as NaN (excluded). Returns (processed_values, quality_labels) where
    quality_labels is one of 'ok' (never missing), 'filled' (forward-filled), or 'excluded'
    (gap too long, left NaN) per row.

    Grain-agnostic despite living in this (EIA-authored) module — it only counts consecutive
    NaN runs, nothing here assumes hourly data. The default of 2 matches Architecture.md
    Section 6's "forward-fill gaps of 1-2 hours" for EIA's hourly series specifically; a
    caller on a different cadence (e.g. PJM's 5-minute data) should pass an explicit value
    with its own stated reasoning, not silently inherit this default's intent.

    This is the one place the project's missing-data policy is actually enforced — train and
    score must both go through it, never consume raw series output directly.
    """
    is_na = series.isna()
    # Group consecutive NaNs into runs: each time is_na flips, start a new group id.
    run_id = is_na.ne(is_na.shift()).cumsum()
    run_length = is_na.groupby(run_id).transform("size")

    short_gap = is_na & (run_length <= max_forward_fill_periods)
    long_gap = is_na & (run_length > max_forward_fill_periods)

    filled = series.ffill()
    processed = series.copy()
    processed[short_gap] = filled[short_gap]
    # long_gap stays NaN in `processed` — explicitly excluded, not silently dropped, so the
    # index length (and therefore anything aligned to it, like calendar features) is unchanged.

    quality = pd.Series("ok", index=series.index, dtype="object")
    quality[short_gap] = "filled"
    quality[long_gap] = "excluded"

    return processed, quality
