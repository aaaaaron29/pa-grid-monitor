"""Scores the single most recent point in a trailing history series.

Reuses model/features.py, model/detector.py, and model/flatline_detector.py exactly as the
batch evaluation scripts (scripts/run_detector*.py) do -- scoring logic lives in exactly one
place. The only thing that differs between batch evaluation (score a whole held-out window
at once) and live inference (score the one new point that just arrived) is how much history
is needed and what gets thrown away afterward.
"""
from __future__ import annotations

import pandas as pd

from model.artifact import ModelArtifact
from model.baselines import seasonal_naive_predict
from model.features import build_features
from model.flatline_detector import detect_flatline


def min_history_periods(artifact: ModelArtifact) -> int:
    """Trailing periods needed (including the point being scored) to compute a real feature
    row for the latest point. seasonal_naive_lag_periods dominates -- a residual needs data
    from exactly that far back; rolling_window_periods is always smaller in practice."""
    return artifact.seasonal_naive_lag_periods + 1


def score_latest(history: pd.Series, artifact: ModelArtifact) -> dict:
    """`history` must be a complete, gap-handled series (already through
    model.data.apply_missing_data_policy) ending at the point to be scored, with at least
    min_history_periods(artifact) rows -- raises ValueError rather than silently scoring on
    too little context."""
    required = min_history_periods(artifact)
    if len(history) < required:
        raise ValueError(f"need at least {required} trailing periods, got {len(history)}")

    forecast = seasonal_naive_predict(history, lag_periods=artifact.seasonal_naive_lag_periods)
    features = build_features(
        history,
        forecast,
        rate_of_change_lag_periods=artifact.rate_of_change_lag_periods,
        rolling_window_periods=artifact.rolling_window_periods,
    )
    latest = features.iloc[[-1]]  # 1-row DataFrame, matching Detector.score()'s expected shape

    score_series = artifact.detector.score(latest)
    score = score_series.iloc[0]
    forest_flagged = False
    if pd.notna(score):
        forest_flagged = bool(artifact.detector.flag(score_series).iloc[0])

    flatline_mask = detect_flatline(
        features["rolling_std"], artifact.flatline_floor, artifact.rolling_window_periods
    )
    flatline_flagged = bool(flatline_mask.iloc[-1])

    residual = latest["residual"].iloc[0]
    return {
        "period_start": history.index[-1],
        "residual": None if pd.isna(residual) else float(residual),
        "forest_score": None if pd.isna(score) else float(score),
        "forest_flagged": forest_flagged,
        "flatline_flagged": flatline_flagged,
    }


def score_since(history: pd.Series, artifact: ModelArtifact, since: pd.Timestamp) -> list[dict]:
    """Score every point at or after `since` in one pass, returning the same dicts that
    score_latest would have returned for each of those points had they been scored one at a
    time as they arrived.

    That equivalence holds because nothing in the pipeline looks forward: the seasonal-naive
    forecast, the lagged and rolling features, and the detector are all causal, and the
    detector scores each row on its own. It is what lets the dashboards show a forecast and
    residuals for a stretch the live service skipped (for example, while a gap in the stored
    prices made it decline to score), and it is pinned by a test that compares the two.

    `history` has the same requirements as for score_latest and must begin at least
    min_history_periods(artifact) - 1 periods before `since`; points with too little context
    before them come back with a null residual and score rather than a made-up one."""
    required = min_history_periods(artifact)
    if len(history) < required:
        raise ValueError(f"need at least {required} trailing periods, got {len(history)}")

    forecast = seasonal_naive_predict(history, lag_periods=artifact.seasonal_naive_lag_periods)
    features = build_features(
        history,
        forecast,
        rate_of_change_lag_periods=artifact.rate_of_change_lag_periods,
        rolling_window_periods=artifact.rolling_window_periods,
    )
    scores = artifact.detector.score(features)
    forest_flags = artifact.detector.flag(scores) & scores.notna()
    flatline_flags = detect_flatline(
        features["rolling_std"], artifact.flatline_floor, artifact.rolling_window_periods
    )

    out = []
    for ts in features.index[features.index >= since]:
        residual, score = features.at[ts, "residual"], scores.at[ts]
        out.append(
            {
                "period_start": ts,
                "residual": None if pd.isna(residual) else float(residual),
                "forest_score": None if pd.isna(score) else float(score),
                "forest_flagged": bool(forest_flags.at[ts]),
                "flatline_flagged": bool(flatline_flags.at[ts]),
            }
        )
    return out
