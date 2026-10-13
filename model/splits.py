"""Frozen train/validation/test split boundaries for the public (EIA) tier.

Architecture.md Section 6: "These dates live as frozen constants in /model/splits.py, not
as notebook variables that quietly drift between runs." Strictly time-ordered, never
shuffled — scalers, thresholds, and any fitted parameters are fit on TRAIN only.

FREEZE_DATE is the point past which the test window is considered final. Set once, here,
to the date this split was decided (the backfill run that first made 2026 data available) -
not recomputed as "today" on every run, which would silently grow the test window.
"""
from __future__ import annotations

from datetime import UTC, datetime

TRAIN_START = datetime(2019, 1, 1, tzinfo=UTC)
TRAIN_END = datetime(2025, 6, 30, tzinfo=UTC)  # exclusive

VALIDATION_START = datetime(2025, 7, 1, tzinfo=UTC)
VALIDATION_END = datetime(2025, 12, 31, tzinfo=UTC)  # exclusive

TEST_START = datetime(2026, 1, 1, tzinfo=UTC)
FREEZE_DATE = datetime(2026, 10, 13, tzinfo=UTC)  # exclusive; frozen 2026-10-13, don't bump


def split_mask(period_start, start: datetime, end: datetime):
    """Boolean mask for a pandas datetime-like Series: start <= period_start < end."""
    return (period_start >= start) & (period_start < end)
