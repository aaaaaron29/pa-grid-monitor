"""Frozen train/validation/test split boundaries, one set per tier.

Architecture.md Section 6: "These dates live as frozen constants in /model/splits.py, not
as notebook variables that quietly drift between runs." Strictly time-ordered, never
shuffled -- scalers, thresholds, and any fitted parameters are fit on TRAIN only.

Each tier's FREEZE_DATE is the point past which the test window is considered final. Set
once, here, to the date that tier's split was actually decided against real backfilled
data -- never recomputed as "today" on every run, which would silently grow the test window.
"""
from __future__ import annotations

from datetime import UTC, datetime


def split_mask(period_start, start: datetime, end: datetime):
    """Boolean mask for a pandas datetime-like Series: start <= period_start < end."""
    return (period_start >= start) & (period_start < end)


# --- Public (EIA) tier --- real data: 2019-01-01 onward (backfilled 2026-10-13).
EIA_TRAIN_START = datetime(2019, 1, 1, tzinfo=UTC)
EIA_TRAIN_END = datetime(2025, 6, 30, tzinfo=UTC)  # exclusive

EIA_VALIDATION_START = datetime(2025, 7, 1, tzinfo=UTC)
EIA_VALIDATION_END = datetime(2025, 12, 31, tzinfo=UTC)  # exclusive

EIA_TEST_START = datetime(2026, 1, 1, tzinfo=UTC)
EIA_FREEZE_DATE = datetime(2026, 10, 13, tzinfo=UTC)  # exclusive; don't bump


# --- Private (PJM) tier --- real data only covers 2026-04-26 onward (Architecture.md
# Section 3: the verified feed's archive boundary makes deep history expensive, so backfill
# was deliberately clamped to the fast, non-archived window rather than matching EIA's
# multi-year depth). A 65/21/14 train/val/test split of that ~169-day window, proportioned
# the same way as the EIA split rather than copying its absolute dates, which would make no
# sense against 6 months of history instead of 7 years.
PJM_TRAIN_START = datetime(2026, 4, 27, tzinfo=UTC)  # first full day; real data starts mid-day 4/26
PJM_TRAIN_END = datetime(2026, 8, 15, tzinfo=UTC)  # exclusive; 110 days, ~65%

PJM_VALIDATION_START = datetime(2026, 8, 15, tzinfo=UTC)
PJM_VALIDATION_END = datetime(2026, 9, 20, tzinfo=UTC)  # exclusive; 36 days, ~21%

PJM_TEST_START = datetime(2026, 9, 20, tzinfo=UTC)
PJM_FREEZE_DATE = datetime(2026, 10, 13, tzinfo=UTC)  # exclusive; 23 days, ~14%; don't bump
