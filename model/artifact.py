"""Trained model artifact: bundles everything the inference service needs to score live
data without re-fitting on every container start.

Architecture.md Section 7: "Training happens off-cluster... the image ships with the
artifact baked in" (public/EIA tier) / "lives on a PVC on the VM... mounted at runtime"
(private/PJM tier, since a PJM-trained artifact is PJM-derived material and can't ride in a
public image -- Section 2's publication policy). This is the object that gets baked in or
mounted; model/train.py produces it, scripts/train_detector_*.py save it to disk, the
inference service loads it at startup.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib

from model.detector import Detector


@dataclass
class ModelArtifact:
    tier: str  # "eia" | "pjm"
    zone: str | None  # None for EIA (one series); zone name for PJM (one per zone)
    detector: Detector
    flatline_floor: float
    rolling_window_periods: int
    rate_of_change_lag_periods: int
    seasonal_naive_lag_periods: int
    trained_at: datetime
    train_rows: int

    def save(self, path: str | Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: str | Path) -> ModelArtifact:
        artifact = joblib.load(path)
        if not isinstance(artifact, ModelArtifact):
            raise TypeError(f"{path} did not contain a ModelArtifact (got {type(artifact)})")
        return artifact
