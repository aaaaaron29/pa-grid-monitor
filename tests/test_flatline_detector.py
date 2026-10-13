from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.flatline_detector import calibrate_floor, detect_flatline


def _hourly_index(n: int, start: str = "2024-01-01"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def test_calibrate_floor_is_a_low_percentile_of_train():
    idx = _hourly_index(1000)
    rng = np.random.default_rng(0)
    rolling_std = pd.Series(rng.normal(50, 10, 1000).clip(min=0), index=idx)

    floor = calibrate_floor(rolling_std, percentile=0.01)

    assert floor == pytest.approx(rolling_std.quantile(0.01))
    assert floor < rolling_std.median()  # a floor, not a typical value


def test_calibrate_floor_raises_on_all_nan():
    idx = _hourly_index(10)
    all_nan = pd.Series(np.nan, index=idx)
    with pytest.raises(ValueError):
        calibrate_floor(all_nan)


def test_detect_flatline_flags_a_sustained_quiet_run():
    idx = _hourly_index(10)
    # quiet (below floor) for rows 3-7, normal elsewhere
    rolling_std = pd.Series([50, 50, 50, 2, 2, 2, 2, 2, 50, 50], index=idx, dtype=float)

    flags = detect_flatline(rolling_std, floor=5.0, min_consecutive_periods=4)

    assert list(flags) == [False, False, False, True, True, True, True, True, False, False]


def test_detect_flatline_does_not_flag_a_short_dip():
    """A brief quiet moment (shorter than min_consecutive_periods) is real variation, not a
    stuck sensor -- must not be flagged."""
    idx = _hourly_index(10)
    rolling_std = pd.Series([50, 50, 2, 2, 50, 50, 50, 50, 50, 50], index=idx, dtype=float)

    flags = detect_flatline(rolling_std, floor=5.0, min_consecutive_periods=4)

    assert not flags.any()


def test_detect_flatline_exactly_at_the_minimum_duration_is_flagged():
    idx = _hourly_index(6)
    rolling_std = pd.Series([50, 2, 2, 2, 2, 50], index=idx, dtype=float)

    flags = detect_flatline(rolling_std, floor=5.0, min_consecutive_periods=4)

    assert list(flags) == [False, True, True, True, True, False]


def test_detect_flatline_nan_rolling_std_never_flagged():
    idx = _hourly_index(6)
    rolling_std = pd.Series([np.nan, np.nan, np.nan, np.nan, np.nan, np.nan], index=idx)

    flags = detect_flatline(rolling_std, floor=5.0, min_consecutive_periods=4)

    assert not flags.any()


def test_detect_flatline_exactly_at_floor_counts_as_below():
    idx = _hourly_index(6)
    rolling_std = pd.Series([50, 5.0, 5.0, 5.0, 5.0, 50], index=idx, dtype=float)

    flags = detect_flatline(rolling_std, floor=5.0, min_consecutive_periods=4)

    assert list(flags) == [False, True, True, True, True, False]
