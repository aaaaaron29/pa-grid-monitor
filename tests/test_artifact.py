from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from model.artifact import ModelArtifact
from model.detector import Detector


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
            "rolling_std": rng.normal(50, 10, n).clip(min=0),
            "rolling_rate_of_change_mean": rng.normal(0, 20, n),
        },
        index=idx,
    )


def test_save_then_load_round_trips_everything(tmp_path):
    features = _synthetic_features(500)
    detector = Detector().fit(features)
    detector.calibrate_threshold(detector.score(features), alert_budget=0.01)

    artifact = ModelArtifact(
        tier="eia",
        zone=None,
        detector=detector,
        flatline_floor=12.3,
        rolling_window_periods=4,
        rate_of_change_lag_periods=1,
        seasonal_naive_lag_periods=168,
        trained_at=datetime(2026, 10, 13, tzinfo=UTC),
        train_rows=500,
    )

    path = tmp_path / "test_artifact.joblib"
    artifact.save(path)
    loaded = ModelArtifact.load(path)

    assert loaded.tier == "eia"
    assert loaded.zone is None
    assert loaded.flatline_floor == 12.3
    assert loaded.rolling_window_periods == 4
    assert loaded.trained_at == datetime(2026, 10, 13, tzinfo=UTC)
    assert loaded.train_rows == 500


def test_loaded_detector_scores_identically_to_the_original():
    """The whole point of persistence: scoring after save/load must match scoring before,
    exactly -- not approximately."""
    features = _synthetic_features(500)
    detector = Detector().fit(features)
    detector.calibrate_threshold(detector.score(features), alert_budget=0.01)
    original_scores = detector.score(features)

    artifact = ModelArtifact(
        tier="pjm",
        zone="PECO",
        detector=detector,
        flatline_floor=1.0,
        rolling_window_periods=12,
        rate_of_change_lag_periods=1,
        seasonal_naive_lag_periods=2016,
        trained_at=datetime.now(UTC),
        train_rows=500,
    )

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "a.joblib"
        artifact.save(path)
        loaded = ModelArtifact.load(path)

    loaded_scores = loaded.detector.score(features)
    assert (original_scores == loaded_scores).all()
    assert loaded.detector._threshold == detector._threshold


def test_load_rejects_a_file_that_is_not_a_model_artifact(tmp_path):
    path = tmp_path / "not_an_artifact.joblib"
    joblib.dump({"not": "an artifact"}, path)

    with pytest.raises(TypeError):
        ModelArtifact.load(path)
