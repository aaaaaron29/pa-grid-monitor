from __future__ import annotations

import pandas as pd

from model.baselines import DowHourProfile, seasonal_naive_predict


def test_seasonal_naive_predict_shifts_by_lag():
    idx = pd.date_range("2024-01-01", periods=24 * 10, freq="h", tz="UTC")
    series = pd.Series(range(len(idx)), index=idx, dtype=float)

    pred = seasonal_naive_predict(series, lag_hours=24)

    # hour 24 should predict hour 0's value (24), etc.
    assert pred.iloc[24] == series.iloc[0]
    assert pred.iloc[25] == series.iloc[1]
    assert pred.iloc[:24].isna().all()  # nothing earlier to reference


def test_dow_hour_profile_predicts_correct_bucket_not_misaligned():
    """Regression guard: this is the exact real-data bug found running Phase 2 -- fitting
    via groupby() on a pre-built MultiIndex produces a plain Index of tuples, not a real
    MultiIndex, which then silently fails to match in predict()'s reindex() and corrupted a
    baseline's MAPE from ~11% to ~88% on real data before this fix. Use deliberately distinct
    per-bucket values so any misalignment shows up as a wrong number, not a coincidentally
    -close one."""
    # two full weeks, so every (dayofweek, hour) bucket has exactly 2 observations
    idx = pd.date_range("2024-01-01", periods=24 * 14, freq="h", tz="UTC")
    # value = dayofweek * 100 + hour, so each bucket's mean is trivially predictable
    values = idx.dayofweek * 100 + idx.hour
    train = pd.Series(values.astype(float), index=idx)

    profile = DowHourProfile().fit(train)

    # predict on a THIRD week (not seen during fit) with the same dow/hour pattern
    target_idx = pd.date_range("2024-01-15", periods=24 * 7, freq="h", tz="UTC")
    pred = profile.predict(target_idx)

    assert pred.isna().sum() == 0  # every bucket was seen during fit
    expected = target_idx.dayofweek * 100 + target_idx.hour
    assert (pred.to_numpy() == expected.to_numpy()).all()


def test_dow_hour_profile_predict_before_fit_raises():
    import pytest

    profile = DowHourProfile()
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    with pytest.raises(RuntimeError):
        profile.predict(idx)


def test_dow_hour_profile_unseen_bucket_predicts_nan_not_crash():
    # fit on a single Monday-only slice; Tuesday buckets are never seen
    idx = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")  # 2024-01-01 is a Monday
    train = pd.Series([50.0] * 24, index=idx)
    profile = DowHourProfile().fit(train)

    tuesday = pd.date_range("2024-01-02", periods=24, freq="h", tz="UTC")
    pred = profile.predict(tuesday)

    assert pred.isna().all()
