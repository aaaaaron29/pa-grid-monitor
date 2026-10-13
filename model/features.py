"""Builds the feature matrix the isolation forest actually scores.

Architecture.md Section 6 ("Feature design"): "residual plus calendar context (hour-of-day,
day-of-week, holiday flag) and short-window rate of change. Deliberately not weather, at
least at first."

Everything here is a pure function of (actual values, forecast) -- no I/O, no fitting state,
fully unit-testable with synthetic series. The isolation forest itself (model/detector.py)
owns the only stateful fit step.
"""
from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

_HOLIDAY_CALENDAR = USFederalHolidayCalendar()


def build_features(
    actual: pd.Series,
    forecast: pd.Series,
    rate_of_change_lag_hours: int = 1,
) -> pd.DataFrame:
    """Returns a DataFrame indexed the same as `actual`, columns:
    residual, hour, dayofweek, is_holiday, rate_of_change.

    `forecast` must already be aligned to `actual`'s index (e.g. baselines.seasonal_naive_
    predict's output) -- this function does not shift or lag it.

    Rows are NOT dropped here even where residual/rate_of_change end up NaN (cold-start, a
    gap excluded by the missing-data policy) -- the caller decides what to do with NaN rows
    (drop before fitting, keep for inspection), consistent with model/evaluate.py's own
    "never impute, the caller decides" convention.
    """
    index = actual.index
    residual = actual - forecast
    rate_of_change = actual.diff(rate_of_change_lag_hours)

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
        },
        index=index,
    )
