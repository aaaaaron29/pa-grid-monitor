from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.features import build_features


def _hourly_index(n: int, start: str = "2024-01-01"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def test_residual_is_actual_minus_forecast():
    idx = _hourly_index(5)
    actual = pd.Series([100.0, 110.0, 90.0, 95.0, 105.0], index=idx)
    forecast = pd.Series([95.0, 100.0, 100.0, 95.0, 100.0], index=idx)

    feats = build_features(actual, forecast)

    assert list(feats["residual"]) == [5.0, 10.0, -10.0, 0.0, 5.0]


def test_hour_and_dayofweek_match_the_index():
    idx = _hourly_index(26)  # spans two days
    actual = pd.Series(range(26), index=idx, dtype=float)
    feats = build_features(actual, actual)

    assert list(feats["hour"][:3]) == [0, 1, 2]
    assert feats["hour"].iloc[24] == 0  # wraps to next day
    assert feats["dayofweek"].nunique() == 2  # Jan 1 2024 is a Monday, Jan 2 a Tuesday


def test_holiday_flag_set_for_known_us_federal_holiday():
    idx = _hourly_index(48, start="2024-07-03")  # covers July 3 and July 4 (Independence Day)
    actual = pd.Series(range(48), index=idx, dtype=float)

    feats = build_features(actual, actual)

    holiday_hours = feats[feats["is_holiday"] == 1]
    assert len(holiday_hours) == 24
    assert all(ts.date().month == 7 and ts.date().day == 4 for ts in holiday_hours.index)


def test_holiday_flag_zero_on_an_ordinary_day():
    idx = _hourly_index(24, start="2024-03-12")  # an ordinary Tuesday, no US federal holiday
    actual = pd.Series(range(24), index=idx, dtype=float)
    feats = build_features(actual, actual)
    assert feats["is_holiday"].sum() == 0


def test_rate_of_change_default_lag_is_one_hour():
    idx = _hourly_index(4)
    actual = pd.Series([100.0, 105.0, 95.0, 95.0], index=idx)

    feats = build_features(actual, actual)

    assert feats["rate_of_change"].iloc[0] != feats["rate_of_change"].iloc[0]  # NaN
    assert list(feats["rate_of_change"][1:]) == [5.0, -10.0, 0.0]


def test_rate_of_change_respects_custom_lag():
    idx = _hourly_index(5)
    actual = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0], index=idx)

    feats = build_features(actual, actual, rate_of_change_lag_hours=3)

    assert feats["rate_of_change"].iloc[:3].isna().all()
    assert feats["rate_of_change"].iloc[3] == 30.0  # 130 - 100
    assert feats["rate_of_change"].iloc[4] == 30.0  # 140 - 110


def test_nan_rows_are_kept_not_dropped():
    """Matches model/evaluate.py's convention: this module never decides what to do with a
    gap, the caller does."""
    idx = _hourly_index(5)
    actual = pd.Series([100.0, np.nan, np.nan, 100.0, 105.0], index=idx)
    forecast = pd.Series([95.0, 95.0, 95.0, 95.0, 100.0], index=idx)

    feats = build_features(actual, forecast)

    assert len(feats) == 5  # nothing dropped
    assert feats["residual"].isna().sum() == 2


def test_rolling_std_near_zero_during_a_flat_window():
    idx = _hourly_index(10)
    actual = pd.Series([100.0, 110.0, 90.0, 105.0, 95.0, 50.0, 50.0, 50.0, 50.0, 50.0], index=idx)
    feats = build_features(actual, actual, rolling_window_hours=4)
    # last 4 points are perfectly flat -> rolling std of that window is 0
    assert feats["rolling_std"].iloc[-1] == 0.0
    # the earlier, genuinely varying window has nonzero rolling std
    assert feats["rolling_std"].iloc[4] > 0.0


def test_rolling_std_respects_window_length():
    idx = _hourly_index(10)
    actual = pd.Series(range(10), index=idx, dtype=float)
    feats = build_features(actual, actual, rolling_window_hours=4)
    assert feats["rolling_std"].iloc[:3].isna().all()  # fewer than 4 points available yet
    assert feats["rolling_std"].iloc[3:].notna().all()


def test_rolling_rate_of_change_mean_captures_sustained_drift():
    idx = _hourly_index(10)
    # steady +10/hour drift throughout
    actual = pd.Series([100.0 + 10 * i for i in range(10)], index=idx)
    feats = build_features(actual, actual, rolling_window_hours=4)
    # once warmed up, a steady +10/hr series has rolling mean rate-of-change == 10
    assert feats["rolling_rate_of_change_mean"].iloc[-1] == pytest.approx(10.0)


def test_rolling_rate_of_change_mean_near_zero_for_flat_series():
    idx = _hourly_index(10)
    actual = pd.Series([100.0] * 10, index=idx)
    feats = build_features(actual, actual, rolling_window_hours=4)
    assert feats["rolling_rate_of_change_mean"].iloc[-1] == pytest.approx(0.0)
