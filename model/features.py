"""Builds the feature matrix the isolation forest actually scores.

Architecture.md Section 6 ("Feature design"): "residual plus calendar context (hour-of-day,
day-of-week, holiday flag) and short-window rate of change. Deliberately not weather, at
least at first."

Everything here is a pure function of (actual values, forecast) -- no I/O, no fitting state,
fully unit-testable with synthetic series. The isolation forest itself (model/detector.py)
owns the only stateful fit step.

Two rolling-window columns (rolling_std, rolling_rate_of_change_mean) were added after
running the synthetic-injection harness against real data and finding the original
single-row feature set structurally couldn't see flatline (stuck-sensor) or abnormal-ramp
anomalies at all (0% recall on both) -- both are multi-hour PATTERN anomalies, and every
original feature was computed from one row. See Architecture.md Section 6 for the full
before/after numbers; this docstring just explains what the two columns are for.
"""
from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

_HOLIDAY_CALENDAR = USFederalHolidayCalendar()


def build_features(
    actual: pd.Series,
    forecast: pd.Series,
    rate_of_change_lag_periods: int = 1,
    rolling_window_periods: int = 4,
) -> pd.DataFrame:
    """Returns a DataFrame indexed the same as `actual`, columns:
    residual, hour, dayofweek, is_holiday, rate_of_change, rolling_std,
    rolling_rate_of_change_mean.

    `forecast` must already be aligned to `actual`'s index (e.g. baselines.seasonal_naive_
    predict's output) -- this function does not shift or lag it.

    Grain-agnostic: both lag/window parameters are counted in rows ("periods"), not hours --
    the defaults (1, 4) suit hourly data (Architecture.md Section 6's "short-window rate of
    change"); a different cadence (e.g. PJM's 5-minute data) needs its own explicit values
    with their own stated reasoning, not these hourly-tuned defaults.

    `rolling_std` is the trailing rolling_window_periods standard deviation of `actual` -- a
    stuck sensor (flatline) drives this toward zero, which is itself unusual (real demand
    essentially never holds dead flat for multiple periods), unlike a single-period
    `rate_of_change` of ~0 which happens naturally during calm periods and can't tell the
    two apart.

    `rolling_rate_of_change_mean` is the trailing rolling_window_periods mean of
    `rate_of_change` -- captures a SUSTAINED directional drift (an abnormal ramp) that a
    single-period diff reads as an unremarkable small step, since by construction a ramp's
    per-period change is spread thin.

    Rows are NOT dropped here even where any column ends up NaN (cold-start, a gap excluded
    by the missing-data policy) -- the caller decides what to do with NaN rows (drop before
    fitting, keep for inspection), consistent with model/evaluate.py's own "never impute,
    the caller decides" convention.
    """
    index = actual.index
    residual = actual - forecast
    rate_of_change = actual.diff(rate_of_change_lag_periods)
    rolling_std = actual.rolling(rolling_window_periods).std()
    rolling_rate_of_change_mean = rate_of_change.rolling(rolling_window_periods).mean()

    holidays = _HOLIDAY_CALENDAR.holidays(
        start=index.min().normalize(), end=index.max().normalize()
    )
    is_holiday = index.normalize().isin(holidays).astype(int)

    return pd.DataFrame(
        {
            "residual": residual,
            "hour": index.hour,
            "dayofweek": index.dayofweek,
            "is_holiday": is_holiday,
            "rate_of_change": rate_of_change,
            "rolling_std": rolling_std,
            "rolling_rate_of_change_mean": rolling_rate_of_change_mean,
        },
        index=index,
    )
