"""Forecast baselines the real model has to beat, not just reference points.

Architecture.md Section 6: "The forecast model carries the quantitative claim... reported
against two baselines: seasonal-naive (same hour, previous week) and a day-of-week x
hour-of-day profile regression. Both baseline numbers get published alongside the model's.
If [the model] doesn't beat them, the README says so and the baseline stays in production."

The "profile regression" is implemented as a grouped mean over (day-of-week, hour-of-day)
buckets fit on train only. That IS the closed-form OLS solution for a linear regression on
one-hot-encoded (dow, hour) dummies with no other regressors and no intercept — same model,
simpler code, exact same numbers. Noted here so nobody "fixes" this into an actual
LinearRegression call expecting different results; there wouldn't be any.
"""
from __future__ import annotations

import pandas as pd


def seasonal_naive_predict(series: pd.Series, lag_periods: int = 24 * 7) -> pd.Series:
    """Predicts each row as the value exactly `lag_periods` earlier (default: 168, "same
    hour, previous week" for hourly data). Grain-agnostic -- it just shifts by row count, so
    a 5-minute series needs its own explicit lag_periods (e.g. 2016 for "same time, previous
    week" at 5-minute resolution), not this hourly-tuned default. The first `lag_periods`
    rows have no prediction (NaN) -- there's nothing earlier to reference."""
    return series.shift(lag_periods)


class DowHourProfile:
    """Day-of-week x hour-of-day profile baseline. fit() on train only, predict() on
    anything — Architecture.md Section 6: "Scalers, thresholds, and contamination
    parameters are fit on train only."""

    def __init__(self) -> None:
        self._profile: pd.Series | None = None  # indexed by (dayofweek, hour)

    def fit(self, train_series: pd.Series) -> DowHourProfile:
        # Group by a LIST of two arrays, not a pre-built MultiIndex object — passing a
        # MultiIndex directly to groupby() collapses the result's index into plain tuples
        # rather than a real MultiIndex (confirmed live: pandas 3.0.6), which then silently
        # fails to match in predict()'s reindex(), scoring almost every row as NaN-vs-wrong
        # and corrupting the baseline into something far worse than it actually is.
        self._profile = train_series.groupby(
            [train_series.index.dayofweek, train_series.index.hour]
        ).mean()
        self._profile.index.set_names(["dayofweek", "hour"], inplace=True)
        return self

    def predict(self, index: pd.DatetimeIndex) -> pd.Series:
        if self._profile is None:
            raise RuntimeError("DowHourProfile.predict() called before fit()")
        key = pd.MultiIndex.from_arrays(
            [index.dayofweek, index.hour], names=["dayofweek", "hour"]
        )
        # reindex rather than .loc[key] so an (dow, hour) combo never seen in train (shouldn't
        # happen with a multi-year training window, but stay honest about it) predicts NaN
        # instead of raising.
        values = self._profile.reindex(key).to_numpy()
        return pd.Series(values, index=index)
