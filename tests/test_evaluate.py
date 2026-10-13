from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.evaluate import evaluate


def test_evaluate_perfect_prediction_is_zero_error():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    actual = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0], index=idx)

    metrics = evaluate(actual, actual.copy())

    assert metrics.mae == 0.0
    assert metrics.mape == 0.0
    assert metrics.rmse == 0.0
    assert metrics.n == 5


def test_evaluate_known_errors():
    idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    actual = pd.Series([100.0, 200.0], index=idx)
    predicted = pd.Series([110.0, 180.0], index=idx)  # errors: +10, -20

    metrics = evaluate(actual, predicted)

    assert metrics.mae == pytest.approx(15.0)  # (10 + 20) / 2
    assert metrics.mape == pytest.approx((0.1 + 0.1) / 2)  # 10/100, 20/200
    assert metrics.rmse == pytest.approx(((10**2 + 20**2) / 2) ** 0.5)
    assert metrics.n == 2


def test_evaluate_drops_nan_rows_from_either_side():
    idx = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    actual = pd.Series([100.0, np.nan, 300.0, 400.0], index=idx)  # an excluded gap
    predicted = pd.Series([100.0, 200.0, np.nan, 400.0], index=idx)  # a cold-start NaN

    metrics = evaluate(actual, predicted)

    assert metrics.n == 2  # only rows 0 and 3 have both sides present
    assert metrics.mae == 0.0  # both remaining rows are exact matches


def test_evaluate_raises_on_no_overlap():
    idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    actual = pd.Series([np.nan, np.nan], index=idx)
    predicted = pd.Series([100.0, 200.0], index=idx)

    with pytest.raises(ValueError):
        evaluate(actual, predicted)


def test_evaluate_reports_mape_as_none_when_actual_crosses_zero():
    """Regression guard: this is the exact real-data finding from PJM LMP baselines -- a
    single $0.00/MWh actual price makes MAPE literally divide by zero (-> inf), which would
    otherwise silently print a meaningless "inf%" instead of signaling the metric doesn't
    apply here. Confirmed live (2026-10-13): PJM zone prices routinely cross zero."""
    idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    actual = pd.Series([50.0, 0.0, -20.0], index=idx)
    predicted = pd.Series([55.0, 5.0, -15.0], index=idx)

    metrics = evaluate(actual, predicted)

    assert metrics.mape is None
    assert metrics.mae == pytest.approx(5.0)  # MAE and RMSE stay valid even when MAPE can't
    assert "n/a" in str(metrics)


def test_evaluate_mape_is_a_normal_float_when_actual_never_crosses_zero():
    idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    actual = pd.Series([100.0, 200.0], index=idx)
    predicted = pd.Series([110.0, 180.0], index=idx)

    metrics = evaluate(actual, predicted)

    assert metrics.mape is not None
    assert "%" in str(metrics)
