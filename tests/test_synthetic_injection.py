from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.synthetic_injection import (
    Injection,
    inject_abnormal_ramp,
    inject_flatline,
    inject_many,
    inject_spike,
    inject_step_change,
    recall_at_budget,
)


def _flat_series(n: int, value: float = 100.0) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.Series(value, index=idx, dtype=float)


def test_inject_spike_changes_only_one_position():
    series = _flat_series(20)
    perturbed, mask = inject_spike(series, at=10, magnitude=500.0)

    assert perturbed.iloc[10] == 600.0
    assert mask.sum() == 1
    assert mask.iloc[10]
    # everything else untouched
    assert (perturbed.drop(perturbed.index[10]) == series.drop(series.index[10])).all()


def test_inject_spike_original_series_not_mutated():
    series = _flat_series(10)
    inject_spike(series, at=5, magnitude=100.0)
    assert series.iloc[5] == 100.0  # unchanged


def test_inject_step_change_shifts_whole_window():
    series = _flat_series(20)
    perturbed, mask = inject_step_change(series, start=5, duration=4, magnitude=50.0)

    assert list(perturbed.iloc[5:9]) == [150.0, 150.0, 150.0, 150.0]
    assert mask.sum() == 4
    assert mask.iloc[4] is np.False_ or not mask.iloc[4]  # just before the window
    assert not mask.iloc[9]  # just after the window


def test_inject_flatline_pins_to_value_before_window():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    series = pd.Series([10.0, 20.0, 30.0, 999.0, 999.0, 999.0, 70.0, 80.0, 90.0, 100.0], index=idx)

    perturbed, mask = inject_flatline(series, start=3, duration=3)

    # pinned to series[2] == 30.0, regardless of what the real values (999...) were
    assert list(perturbed.iloc[3:6]) == [30.0, 30.0, 30.0]
    assert mask.sum() == 3


def test_inject_abnormal_ramp_reaches_total_magnitude_by_window_end():
    series = _flat_series(10)
    perturbed, mask = inject_abnormal_ramp(series, start=2, duration=5, total_magnitude=100.0)

    # linspace(0, 100, 5) -> last point in window gets the full +100
    assert perturbed.iloc[2] == pytest.approx(100.0)  # start of ramp: +0
    assert perturbed.iloc[6] == pytest.approx(200.0)  # end of ramp: +100 on top of 100
    assert mask.sum() == 5


def test_inject_many_unions_masks_and_applies_all():
    series = _flat_series(30)
    injections = [
        Injection("spike", {"at": 2, "magnitude": 500.0}),
        Injection("step_change", {"start": 10, "duration": 3, "magnitude": 20.0}),
        Injection("flatline", {"start": 20, "duration": 2}),
    ]

    perturbed, mask = inject_many(series, injections)

    assert mask.sum() == 1 + 3 + 2
    assert perturbed.iloc[2] == 600.0
    assert list(perturbed.iloc[10:13]) == [120.0, 120.0, 120.0]
    assert perturbed.iloc[20] == perturbed.iloc[19]


def test_recall_at_budget_all_caught():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    injected = pd.Series([False] * 3 + [True] * 2 + [False] * 5, index=idx)
    flagged = injected.copy()  # perfect detector

    assert recall_at_budget(injected, flagged) == 1.0


def test_recall_at_budget_partial():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    injected = pd.Series(
        [False, False, True, True, True, False, False, False, False, False], index=idx
    )
    flagged = pd.Series(
        [False, True, True, False, False, False, False, False, False, False], index=idx
    )
    # of 3 injected (idx 2,3,4), only idx 2 was flagged -> recall 1/3
    assert recall_at_budget(injected, flagged) == pytest.approx(1 / 3)


def test_recall_at_budget_raises_when_nothing_injected():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    injected = pd.Series(False, index=idx)
    flagged = pd.Series(False, index=idx)
    with pytest.raises(ValueError):
        recall_at_budget(injected, flagged)
