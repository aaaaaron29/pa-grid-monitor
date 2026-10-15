from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from model.artifact import ModelArtifact
from model.detector import Detector
from model.features import build_features
from model.flatline_detector import calibrate_floor
from model.score import min_history_periods, score_latest


def _hourly_index(n: int, start: str = "2024-01-01"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def _make_artifact(lag_periods: int = 24, rolling_window: int = 4) -> ModelArtifact:
    rng = np.random.default_rng(0)
    n = lag_periods * 3
    idx = _hourly_index(n)
    train = pd.Series(100.0 + rng.normal(0, 5, n), index=idx)

    forecast = train.shift(lag_periods)
    feats = build_features(
        train, forecast, rate_of_change_lag_periods=1, rolling_window_periods=rolling_window
    ).dropna()
    detector = Detector().fit(feats)
    detector.calibrate_threshold(detector.score(feats), alert_budget=0.1)
    floor = calibrate_floor(feats["rolling_std"])

    return ModelArtifact(
        tier="eia",
        zone=None,
        detector=detector,
        flatline_floor=floor,
        rolling_window_periods=rolling_window,
        rate_of_change_lag_periods=1,
        seasonal_naive_lag_periods=lag_periods,
        trained_at=datetime.now(UTC),
        train_rows=len(feats),
    )


def test_min_history_periods_is_lag_plus_one():
    artifact = _make_artifact(lag_periods=168)
    assert min_history_periods(artifact) == 169


def test_score_latest_raises_on_too_little_history():
    artifact = _make_artifact(lag_periods=24)
    short_history = pd.Series([100.0] * 10, index=_hourly_index(10))
    with pytest.raises(ValueError):
        score_latest(short_history, artifact)


def test_score_latest_returns_expected_keys_on_real_shaped_data():
    artifact = _make_artifact(lag_periods=24)
    idx = _hourly_index(30)
    history = pd.Series(100.0 + np.random.default_rng(1).normal(0, 5, 30), index=idx)

    result = score_latest(history, artifact)

    assert set(result.keys()) == {
        "period_start",
        "residual",
        "forest_score",
        "forest_flagged",
        "flatline_flagged",
    }
    assert result["period_start"] == idx[-1]
    assert isinstance(result["forest_flagged"], bool)
    assert isinstance(result["flatline_flagged"], bool)


def test_score_latest_flags_an_obvious_spike():
    artifact = _make_artifact(lag_periods=24)
    idx = _hourly_index(30)
    rng = np.random.default_rng(2)
    history = pd.Series(100.0 + rng.normal(0, 2, 30), index=idx)
    history.iloc[-1] = 100_000.0  # wildly extreme relative to lag-24 forecast and local history

    result = score_latest(history, artifact)

    assert result["forest_flagged"] is True
    assert result["residual"] > 1000


def test_score_latest_flags_a_sustained_flatline():
    """rolling_std only reads as "quiet" once its trailing window is entirely inside the
    pinned region -- with rolling_window_periods=4, the first (4-1)=3 points of a pinned
    run still have a noisy value inside their window. Needs at least
    rolling_window + min_consecutive_periods - 1 pinned points for the LAST point to be
    part of a full qualifying run; confirmed by this exact mechanic on real EIA data
    (Architecture.md Section 6: "75%, not 100%" recall from the same warm-up lag)."""
    artifact = _make_artifact(lag_periods=24, rolling_window=4)
    idx = _hourly_index(30)
    rng = np.random.default_rng(3)
    history = pd.Series(100.0 + rng.normal(0, 5, 30), index=idx)
    history.iloc[-10:] = 100.0  # comfortably longer than the 4+4-1=7 minimum

    result = score_latest(history, artifact)

    assert result["flatline_flagged"] is True


def test_score_since_matches_scoring_each_point_as_it_arrives():
    """The batch scorer must give exactly what score_latest gives point by point; that is the
    whole basis for using it to fill in a stretch the live service skipped."""
    from model.score import score_since

    artifact = _make_artifact(lag_periods=24)
    n = 24 * 6
    idx = _hourly_index(n)
    rng = np.random.default_rng(7)
    values = 100.0 + rng.normal(0, 5, n)
    values[100] += 80.0  # a spike the detector should react to
    history = pd.Series(values, index=idx)
    since = idx[24 * 4]

    batch = score_since(history, artifact, since)

    assert [r["period_start"] for r in batch] == list(idx[idx >= since])
    for row in batch:
        one_at_a_time = score_latest(history.loc[: row["period_start"]], artifact)
        assert row["period_start"] == one_at_a_time["period_start"]
        assert row["forest_flagged"] == one_at_a_time["forest_flagged"]
        assert row["flatline_flagged"] == one_at_a_time["flatline_flagged"]
        for key in ("residual", "forest_score"):
            if one_at_a_time[key] is None:
                assert row[key] is None
            else:
                assert row[key] == pytest.approx(one_at_a_time[key])
    assert any(r["forest_flagged"] for r in batch), "the injected spike should be flagged"


def test_score_since_raises_on_too_little_history():
    from model.score import score_since

    artifact = _make_artifact(lag_periods=24)
    short = pd.Series([100.0] * 10, index=_hourly_index(10))
    with pytest.raises(ValueError):
        score_since(short, artifact, short.index[0])
