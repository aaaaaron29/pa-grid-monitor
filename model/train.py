"""Trains a Detector + flatline rule for one tier/zone, bundled as a ModelArtifact.

This is the "fit on train, calibrate on validation" logic from scripts/run_detector.py and
scripts/run_detector_pjm.py, factored out so both the evaluation scripts (which report
metrics against known results) and this module (which produces a deployable artifact for
the inference service) build the model the same way -- "fit on train only" (Architecture.md
Section 6) enforced in exactly one place, not two copies that could silently drift apart.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.config import Settings
from model import splits
from model.artifact import ModelArtifact
from model.baselines import seasonal_naive_predict
from model.data import apply_missing_data_policy, load_eia_series
from model.data_pjm import load_pjm_series
from model.detector import Detector
from model.features import build_features
from model.flatline_detector import calibrate_floor

log = logging.getLogger(__name__)

# Matches scripts/run_detector.py's constants exactly -- see that file for the reasoning.
EIA_ROLLING_WINDOW_PERIODS = 4
EIA_RATE_OF_CHANGE_LAG_PERIODS = 1
EIA_SEASONAL_NAIVE_LAG_PERIODS = 24 * 7
EIA_FLATLINE_MIN_CONSECUTIVE_PERIODS = EIA_ROLLING_WINDOW_PERIODS

# Matches scripts/run_detector_pjm.py's constants exactly -- see that file for the reasoning.
PJM_ROLLING_WINDOW_PERIODS = 12
PJM_RATE_OF_CHANGE_LAG_PERIODS = 1
PJM_SEASONAL_NAIVE_LAG_PERIODS = 7 * 24 * 12
PJM_FLATLINE_MIN_CONSECUTIVE_PERIODS = PJM_ROLLING_WINDOW_PERIODS
PJM_MAX_FORWARD_FILL_PERIODS = 3


def train_eia_detector(settings: Settings, alert_budget: float = 0.01) -> ModelArtifact:
    log.info("training EIA detector")
    raw = load_eia_series(
        settings.postgres_dsn, start=splits.EIA_TRAIN_START, end=splits.EIA_FREEZE_DATE
    )
    values, quality = apply_missing_data_policy(raw)
    usable = values[quality != "excluded"]
    forecast = seasonal_naive_predict(usable, lag_periods=EIA_SEASONAL_NAIVE_LAG_PERIODS)

    train_mask = splits.split_mask(usable.index, splits.EIA_TRAIN_START, splits.EIA_TRAIN_END)
    val_mask = splits.split_mask(
        usable.index, splits.EIA_VALIDATION_START, splits.EIA_VALIDATION_END
    )

    train_features = build_features(
        usable[train_mask],
        forecast[train_mask],
        rate_of_change_lag_periods=EIA_RATE_OF_CHANGE_LAG_PERIODS,
        rolling_window_periods=EIA_ROLLING_WINDOW_PERIODS,
    )
    val_features = build_features(
        usable[val_mask],
        forecast[val_mask],
        rate_of_change_lag_periods=EIA_RATE_OF_CHANGE_LAG_PERIODS,
        rolling_window_periods=EIA_ROLLING_WINDOW_PERIODS,
    )

    detector = Detector().fit(train_features)
    detector.calibrate_threshold(detector.score(val_features), alert_budget=alert_budget)
    flatline_floor = calibrate_floor(train_features["rolling_std"])

    return ModelArtifact(
        tier="eia",
        zone=None,
        detector=detector,
        flatline_floor=flatline_floor,
        rolling_window_periods=EIA_ROLLING_WINDOW_PERIODS,
        rate_of_change_lag_periods=EIA_RATE_OF_CHANGE_LAG_PERIODS,
        seasonal_naive_lag_periods=EIA_SEASONAL_NAIVE_LAG_PERIODS,
        trained_at=datetime.now(UTC),
        train_rows=len(train_features),
    )


def train_pjm_detector(
    settings: Settings, zone: str, alert_budget: float = 0.01
) -> ModelArtifact:
    log.info("training PJM detector", extra={"zone": zone})
    raw = load_pjm_series(
        settings.postgres_dsn, zone, splits.PJM_TRAIN_START, splits.PJM_FREEZE_DATE
    )
    values, quality = apply_missing_data_policy(
        raw, max_forward_fill_periods=PJM_MAX_FORWARD_FILL_PERIODS
    )
    usable = values[quality != "excluded"]
    forecast = seasonal_naive_predict(usable, lag_periods=PJM_SEASONAL_NAIVE_LAG_PERIODS)

    train_mask = splits.split_mask(usable.index, splits.PJM_TRAIN_START, splits.PJM_TRAIN_END)
    val_mask = splits.split_mask(
        usable.index, splits.PJM_VALIDATION_START, splits.PJM_VALIDATION_END
    )

    train_features = build_features(
        usable[train_mask],
        forecast[train_mask],
        rate_of_change_lag_periods=PJM_RATE_OF_CHANGE_LAG_PERIODS,
        rolling_window_periods=PJM_ROLLING_WINDOW_PERIODS,
    )
    val_features = build_features(
        usable[val_mask],
        forecast[val_mask],
        rate_of_change_lag_periods=PJM_RATE_OF_CHANGE_LAG_PERIODS,
        rolling_window_periods=PJM_ROLLING_WINDOW_PERIODS,
    )

    detector = Detector().fit(train_features)
    detector.calibrate_threshold(detector.score(val_features), alert_budget=alert_budget)
    flatline_floor = calibrate_floor(train_features["rolling_std"])

    return ModelArtifact(
        tier="pjm",
        zone=zone,
        detector=detector,
        flatline_floor=flatline_floor,
        rolling_window_periods=PJM_ROLLING_WINDOW_PERIODS,
        rate_of_change_lag_periods=PJM_RATE_OF_CHANGE_LAG_PERIODS,
        seasonal_naive_lag_periods=PJM_SEASONAL_NAIVE_LAG_PERIODS,
        trained_at=datetime.now(UTC),
        train_rows=len(train_features),
    )
