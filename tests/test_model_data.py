from __future__ import annotations

import numpy as np
import pandas as pd

from model.data import PLAUSIBLE_BOUNDS_MW, apply_missing_data_policy, mask_implausible


def _hourly_index(n: int, start: str = "2024-01-01"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def test_mask_implausible_catches_sentinel_values():
    """Regression guard: this is the exact real-data incident found running Phase 2 against
    live data — 3 rows out of 68,226 had values up to 2,147,480,000 MW (suspiciously close
    to 2^31-1, a classic 32-bit overflow sentinel), which silently corrupted a baseline's
    MAPE from ~11% to ~88% before this filter existed. Confirmed live it hit both D and NG."""
    series = pd.Series([85000.0, 90000.0, 2_147_480_000.0, 88000.0], index=_hourly_index(4))

    masked = mask_implausible(series, "D")

    assert masked.iloc[2] != masked.iloc[2]  # NaN
    assert list(masked.dropna()) == [85000.0, 90000.0, 88000.0]


def test_mask_implausible_leaves_normal_demand_alone():
    low, high = PLAUSIBLE_BOUNDS_MW["D"]
    series = pd.Series([low + 1, high - 1], index=_hourly_index(2))
    masked = mask_implausible(series, "D")
    assert masked.equals(series)


def test_mask_implausible_catches_too_low_too():
    series = pd.Series([0.5, 50000.0], index=_hourly_index(2))
    masked = mask_implausible(series, "D")
    assert masked.isna().iloc[0]
    assert masked.iloc[1] == 50000.0


def test_mask_implausible_does_not_mask_normal_negative_interchange():
    """Regression guard: TI (interchange) is legitimately signed — confirmed live, observed
    range is -4,456 to 15,772 MW, ordinary imports/exports. Reusing D's floor (which treats
    anything below 1,000 as implausible) would wrongly mask every negative interchange hour,
    which is most of them in practice."""
    series = pd.Series([-4456.0, -100.0, 0.0, 15772.0], index=_hourly_index(4))
    masked = mask_implausible(series, "TI")
    assert masked.equals(series)  # nothing masked; all of this is ordinary


def test_mask_implausible_unknown_reading_type_raises():
    import pytest

    series = pd.Series([100.0], index=_hourly_index(1))
    with pytest.raises(ValueError):
        mask_implausible(series, "NOT_A_REAL_TYPE")


def test_apply_missing_data_policy_forward_fills_short_gap():
    series = pd.Series([100.0, 101.0, np.nan, np.nan, 104.0], index=_hourly_index(5))

    processed, quality = apply_missing_data_policy(series, max_forward_fill_periods=2)

    assert list(processed) == [100.0, 101.0, 101.0, 101.0, 104.0]
    assert list(quality) == ["ok", "ok", "filled", "filled", "ok"]


def test_apply_missing_data_policy_excludes_long_gap():
    series = pd.Series([100.0, np.nan, np.nan, np.nan, 104.0], index=_hourly_index(5))

    processed, quality = apply_missing_data_policy(series, max_forward_fill_periods=2)

    assert processed.iloc[0] == 100.0
    assert processed.iloc[1:4].isna().all()
    assert processed.iloc[4] == 104.0
    assert list(quality) == ["ok", "excluded", "excluded", "excluded", "ok"]


def test_apply_missing_data_policy_preserves_index_length():
    """Excluded rows stay in the index as NaN rather than being dropped -- anything aligned
    to this series by position (calendar features, etc.) must not shift."""
    series = pd.Series([100.0] + [np.nan] * 10 + [100.0], index=_hourly_index(12))
    processed, quality = apply_missing_data_policy(series)
    assert len(processed) == len(series)
    assert len(quality) == len(series)
