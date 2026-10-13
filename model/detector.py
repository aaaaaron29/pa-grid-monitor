"""Isolation forest anomaly detector, scoring the features model/features.py builds (residual
plus calendar context plus rate-of-change), not raw demand -- Architecture.md Section 6.

Architecture.md Section 6 ("Train/validation/test split"): "Scalers, thresholds, and
contamination parameters are fit on train only." The forest itself fits on TRAIN; the
operating threshold is chosen on VALIDATION (Section 6, "Evaluating an unsupervised
detector": "Operating threshold is chosen on validation, frozen, then reported on test").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURE_COLUMNS = ["residual", "hour", "dayofweek", "is_holiday", "rate_of_change"]


class Detector:
    def __init__(self, random_state: int = 0, n_estimators: int = 200) -> None:
        self._model = IsolationForest(
            n_estimators=n_estimators, random_state=random_state, contamination="auto"
        )
        self._threshold: float | None = None
        self._fitted = False

    def fit(self, train_features: pd.DataFrame) -> Detector:
        """Fits on complete rows only (any NaN -- a cold-start or excluded gap -- is dropped,
        never imputed, same convention as model/evaluate.py). contamination='auto' at fit
        time; the actual operating point is set separately by calibrate_threshold on
        validation, not by sklearn's own contamination estimate."""
        clean = train_features[FEATURE_COLUMNS].dropna()
        if clean.empty:
            raise ValueError("no complete (non-NaN) rows to fit on")
        # .to_numpy() consistently here and in score() -- fitting on a DataFrame (with
        # column names) and later scoring plain arrays, or vice versa, triggers a sklearn
        # feature-name mismatch warning even when column order genuinely matches.
        self._model.fit(clean.to_numpy())
        self._fitted = True
        return self

    def score(self, features: pd.DataFrame) -> pd.Series:
        """Higher = more anomalous (note: this is the NEGATIVE of sklearn's own
        decision_function, which scores higher = more normal -- inverted here so "higher
        score" means the same thing everywhere in this project, matching how a reader
        intuitively expects an anomaly score to work). NaN rows score NaN, not some
        placeholder value -- the caller already knows they were excluded gaps."""
        if not self._fitted:
            raise RuntimeError("Detector.score() called before fit()")
        clean_mask = features[FEATURE_COLUMNS].notna().all(axis=1)
        scores = pd.Series(np.nan, index=features.index)
        if clean_mask.any():
            clean_values = features.loc[clean_mask, FEATURE_COLUMNS].to_numpy()
            raw = self._model.decision_function(clean_values)
            scores.loc[clean_mask] = -raw
        return scores

    def calibrate_threshold(
        self, validation_scores: pd.Series, alert_budget: float = 0.01
    ) -> float:
        """Sets the operating threshold so that at most `alert_budget` fraction of valid
        (non-NaN) validation rows would be flagged -- Architecture.md Section 6: "report
        recall at a fixed alert budget (at most 1% of intervals flagged)." Frozen once set;
        call this on validation only, never on test."""
        clean = validation_scores.dropna()
        if clean.empty:
            raise ValueError("no non-NaN validation scores to calibrate against")
        self._threshold = float(np.quantile(clean, 1 - alert_budget))
        return self._threshold

    def flag(self, scores: pd.Series) -> pd.Series:
        """Boolean Series, True where scores >= the frozen threshold. NaN scores never flag
        (an excluded gap is not an anomaly, it's a data-quality exclusion)."""
        if self._threshold is None:
            raise RuntimeError("Detector.flag() called before calibrate_threshold()")
        return scores >= self._threshold
