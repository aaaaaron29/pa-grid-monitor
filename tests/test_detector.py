from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.detector import FEATURE_COLUMNS, Detector


def _synthetic_features(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "residual": rng.normal(0, 100, n),
            "hour": idx.hour,
            "dayofweek": idx.dayofweek,
            "is_holiday": 0,
            "rate_of_change": rng.normal(0, 50, n),
        },
        index=idx,
    )


def test_fit_raises_on_all_nan_input():
    features = _synthetic_features(10)
    features[FEATURE_COLUMNS] = np.nan
    with pytest.raises(ValueError):
        Detector().fit(features)


def test_score_raises_before_fit():
    with pytest.raises(RuntimeError):
        Detector().score(_synthetic_features(10))


def test_flag_raises_before_calibration():
    features = _synthetic_features(200)
    det = Detector().fit(features)
    scores = det.score(features)
    with pytest.raises(RuntimeError):
        det.flag(scores)


def test_calibrate_threshold_raises_on_all_nan_scores():
    det = Detector().fit(_synthetic_features(200))
    all_nan = pd.Series(np.nan, index=pd.RangeIndex(10))
    with pytest.raises(ValueError):
        det.calibrate_threshold(all_nan)


def test_nan_rows_score_nan_not_a_placeholder():
    features = _synthetic_features(200)
    det = Detector().fit(features)

    with_gap = features.copy()
    with_gap.loc[with_gap.index[5], "residual"] = np.nan
    scores = det.score(with_gap)

    assert scores.iloc[5] != scores.iloc[5]  # NaN
    assert scores.drop(scores.index[5]).notna().all()


def test_nan_scores_never_get_flagged():
    features = _synthetic_features(500)
    det = Detector().fit(features)
    scores = det.score(features)
    scores.iloc[0] = np.nan
    det.calibrate_threshold(scores, alert_budget=0.5)  # generous budget, easy to flag
    flags = det.flag(scores)
    assert not flags.iloc[0]  # NaN >= threshold is False in pandas, confirm it stays that way


def test_calibrate_threshold_respects_alert_budget_approximately():
    features = _synthetic_features(2000)
    det = Detector().fit(features)
    scores = det.score(features)
    det.calibrate_threshold(scores, alert_budget=0.01)
    flags = det.flag(scores)
    # exact count depends on ties at the quantile boundary; stay within a small tolerance
    assert 15 <= flags.sum() <= 25  # budget targets ~20 of 2000


def test_higher_score_means_more_anomalous_not_sklearns_inverted_convention():
    """Regression guard for the sign-flip: sklearn's own decision_function scores LOWER as
    more anomalous. This project's convention (stated in detector.py's docstring) is the
    opposite -- higher score = more anomalous, matching the intuitive reading. A single very
    extreme point (in a single-feature setup, so isolation-forest dilution across multiple
    unrelated dimensions doesn't confound the comparison) should clearly outscore ordinary
    points under THIS project's convention."""
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=500, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "residual": rng.normal(0, 10, 500),
            "hour": 0,
            "dayofweek": 0,
            "is_holiday": 0,
            "rate_of_change": 0.0,
        },
        index=idx,
    )
    det = Detector().fit(df)

    df_test = df.copy()
    df_test.loc[df_test.index[0], "residual"] = 10_000.0  # wildly extreme in the one varying dim
    scores = det.score(df_test)

    assert scores.iloc[0] > scores.iloc[1:].mean()
