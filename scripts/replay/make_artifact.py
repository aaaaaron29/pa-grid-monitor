"""Fit the model artifact the replay test loads, on the scenario's own clean series.

The artifact is deliberately fitted on the event-free version of the very values the replay
publishes. That makes the only flags the replay can legitimately produce the planted ones:
every clean interval was in the training set, and the threshold sits just above the highest
training score. It tests that the pipeline carries the right values to the right place and
reports what the detector says, not how good the detector is; the real artifacts are fitted
and evaluated by scripts/train_detector_pjm.py.

Usage: python -m scripts.replay.make_artifact [artifacts_dir]
Writes pjm_detector_<ZONE>.joblib for the scenario zone and, so every service has something
to load, a copy for each of the other four zones.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from model.artifact import ModelArtifact
from model.detector import Detector
from model.features import build_features
from model.flatline_detector import calibrate_floor
from scripts.replay import data

TRAIN_BACK = 4 * data.PER_DAY  # extra clean history before T0 so training is not tiny
OTHER_ZONES = ("PECO", "METED", "PENELEC", "DUQ")


def clean_series(first: int, last: int) -> pd.Series:
    idx = pd.date_range(data.when(first), periods=last - first, freq="5min", tz="UTC")
    return pd.Series([data.clean_value(i) for i in range(first, last)], index=idx)


def fit(zone: str, series: pd.Series) -> ModelArtifact:
    forecast = series.shift(data.LAG)
    feats = build_features(
        series, forecast, rate_of_change_lag_periods=1, rolling_window_periods=data.ROLLING_WINDOW
    ).dropna()
    detector = Detector().fit(feats)
    scores = detector.score(feats)
    # Budget zero puts the threshold at the highest training score. Flags are score >= threshold,
    # so step just above it to leave that one training point unflagged as well.
    threshold = detector.calibrate_threshold(scores, alert_budget=0.0)
    detector._threshold = float(np.nextafter(threshold, np.inf))
    return ModelArtifact(
        tier="pjm",
        zone=zone,
        detector=detector,
        flatline_floor=calibrate_floor(feats["rolling_std"]),
        rolling_window_periods=data.ROLLING_WINDOW,
        rate_of_change_lag_periods=1,
        seasonal_naive_lag_periods=data.LAG,
        trained_at=datetime.now(UTC),
        train_rows=len(feats),
    )


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
    out.mkdir(parents=True, exist_ok=True)
    first = -data.LAG - TRAIN_BACK  # early enough that the lag still leaves TRAIN_BACK rows
    last = data.HISTORY + data.LIVE
    series = clean_series(first, last)
    fit(data.ZONE, series).save(out / f"pjm_detector_{data.ZONE}.joblib")
    for zone in OTHER_ZONES:  # never published to; they only need to load
        fit(zone, series).save(out / f"pjm_detector_{zone}.joblib")
    print(f"wrote artifacts for {data.ZONE} and {len(OTHER_ZONES)} idle zones to {out}")


if __name__ == "__main__":
    main()
