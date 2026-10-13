"""Rule-based flatline (stuck-sensor) detector, running ALONGSIDE the isolation forest
rather than as one more input feature.

Confirmed necessary live, twice, on two different tiers (Architecture.md Section 6): the
isolation forest structurally can't see a stuck sensor, because the one informative signal
(rolling_std collapsing toward zero) gets diluted across the other 6 features in its random
per-split feature choice -- and that doesn't improve with longer flatline duration, since the
problem is dilution, not insufficient evidence. A plain threshold rule doesn't have a
dilution problem because it only ever looks at one feature.

Two pieces: calibrate_floor (fit on train only, same rule as everything else in this
project) picks how quiet is "too quiet"; detect_flatline flags runs of at least
min_consecutive_periods where rolling_std stays at or below that floor. A single quiet row
is not flagged -- only a run long enough to plausibly be a stuck sensor rather than genuinely
calm real data.
"""
from __future__ import annotations

import pandas as pd


def calibrate_floor(train_rolling_std: pd.Series, percentile: float = 0.01) -> float:
    """Picks the flatline floor as a low percentile of TRAIN rolling_std -- fit on train
    only (Architecture.md Section 6: "thresholds... are fit on train only")."""
    clean = train_rolling_std.dropna()
    if clean.empty:
        raise ValueError("no non-NaN rolling_std values to calibrate a floor from")
    return float(clean.quantile(percentile))


def detect_flatline(
    rolling_std: pd.Series, floor: float, min_consecutive_periods: int
) -> pd.Series:
    """Boolean mask, True for every row that's part of a run of at least
    min_consecutive_periods consecutive rows where rolling_std <= floor. NaN rolling_std
    (cold-start, excluded gap) counts as "not below the floor" -- never flagged."""
    below = (rolling_std <= floor).fillna(False)
    run_id = below.ne(below.shift()).cumsum()
    run_length = below.groupby(run_id).transform("size")
    return below & (run_length >= min_consecutive_periods)
