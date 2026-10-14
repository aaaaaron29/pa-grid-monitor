from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import numpy as np
import pandas as pd

from common.metrics import (
    ANOMALIES_FLAGGED_TOTAL,
    LAST_SUCCESSFUL_SCORE_TS,
    SCORING_RUNS_TOTAL,
)
from inference.eia_service import SCORED_READING_TYPE, _build_history_plus_current, _score_and_store
from model.artifact import ModelArtifact
from model.detector import Detector
from model.features import build_features


def test_scored_reading_type_is_demand():
    """Regression guard: the artifact (model/train.py's train_eia_detector) is trained on
    demand specifically -- scoring an NG/TI row against it would silently apply the wrong
    model. This constant is the one gate preventing that."""
    assert SCORED_READING_TYPE == "D"


def test_score_and_store_skips_non_demand_rows(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "inference.eia_service._build_history_plus_current",
        lambda *a, **k: calls.append("called"),
    )
    row = {"reading_type": "NG", "period_start": "2026-01-01T00:00:00+00:00"}
    _score_and_store(settings=_fake_settings(), artifact=object(), row=row)
    assert calls == []  # never even tried to build history for a non-demand row


def test_build_history_plus_current_returns_none_for_missing_value():
    row = {
        "reading_type": "D",
        "respondent": "PJM",
        "period_start": "2026-01-01T00:00:00+00:00",
        "value_mw": None,
    }
    with patch("inference.eia_service.load_eia_series") as mock_load:
        mock_load.return_value = pd.Series(dtype=float)
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )
    assert result is None


def test_build_history_plus_current_appends_current_value_without_requiring_it_in_postgres():
    """The core correctness property this module exists for: the current point's value
    comes from the Kafka message itself, never from re-querying Postgres -- so scoring
    cannot depend on another consumer having already written this exact row."""
    row = {
        "reading_type": "D",
        "respondent": "PJM",
        "period_start": "2026-01-01T05:00:00+00:00",
        "value_mw": 12345.0,
    }
    history_index = pd.date_range("2025-12-01", periods=200, freq="h", tz="UTC")
    history = pd.Series(100.0, index=history_index)

    with patch("inference.eia_service.load_eia_series", return_value=history):
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )

    assert result is not None
    assert result.iloc[-1] == 12345.0
    assert result.index[-1] == datetime(2026, 1, 1, 5, tzinfo=UTC)


def test_build_history_plus_current_returns_none_when_not_enough_settled_history():
    row = {
        "reading_type": "D",
        "respondent": "PJM",
        "period_start": "2026-01-01T00:00:00+00:00",
        "value_mw": 100.0,
    }
    with patch("inference.eia_service.load_eia_series", return_value=pd.Series(dtype=float)):
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )
    assert result is None


def test_score_and_store_records_success_and_anomaly_metrics(monkeypatch):
    """Exercises the real happy path (real ModelArtifact, not the bare stub the other tests
    use, since score_latest needs a real .detector) and checks the Prometheus counters/gauge
    this module exists to update, not just that no exception was raised."""
    artifact = _real_artifact()
    idx = pd.date_range("2024-01-01", periods=30, freq="h", tz="UTC")
    rng = np.random.default_rng(5)
    history = pd.Series(100.0 + rng.normal(0, 2, 30), index=idx)
    row = {
        "reading_type": "D",
        "respondent": "PJM",
        "period_start": "2024-01-02T06:00:00+00:00",  # history's next hour, no gap
        "value_mw": 100_000.0,  # wildly extreme -- forces a real forest-flagged anomaly
    }
    written = []

    monkeypatch.setattr("inference.eia_service.load_eia_series", lambda *a, **k: history)
    monkeypatch.setattr("inference.eia_service.connect", _fake_connect)
    monkeypatch.setattr(
        "inference.eia_service.upsert_eia_anomalies",
        lambda conn, rows: written.extend(rows),
    )

    scored_before = SCORING_RUNS_TOTAL.labels(tier="eia", outcome="scored")._value.get()
    forest_before = ANOMALIES_FLAGGED_TOTAL.labels(
        tier="eia", zone="none", detector="forest"
    )._value.get()

    _score_and_store(settings=_fake_settings(), artifact=artifact, row=row)

    assert len(written) == 1
    assert written[0]["forest_flagged"] is True
    assert SCORING_RUNS_TOTAL.labels(tier="eia", outcome="scored")._value.get() == scored_before + 1
    assert (
        ANOMALIES_FLAGGED_TOTAL.labels(tier="eia", zone="none", detector="forest")._value.get()
        == forest_before + 1
    )
    assert LAST_SUCCESSFUL_SCORE_TS.labels(tier="eia")._value.get() > 0


def test_score_and_store_records_skipped_metric_on_insufficient_history(monkeypatch):
    monkeypatch.setattr(
        "inference.eia_service._build_history_plus_current", lambda *a, **k: None
    )
    row = {"reading_type": "D", "period_start": "2026-01-01T00:00:00+00:00"}

    skipped_before = SCORING_RUNS_TOTAL.labels(tier="eia", outcome="skipped")._value.get()
    _score_and_store(settings=_fake_settings(), artifact=object(), row=row)
    skipped_after = SCORING_RUNS_TOTAL.labels(tier="eia", outcome="skipped")._value.get()
    assert skipped_after == skipped_before + 1


@contextmanager
def _fake_connect(dsn):
    yield object()


def _real_artifact(lag_periods: int = 24, rolling_window: int = 4) -> ModelArtifact:
    rng = np.random.default_rng(0)
    n = lag_periods * 3
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    train = pd.Series(100.0 + rng.normal(0, 5, n), index=idx)
    forecast = train.shift(lag_periods)
    feats = build_features(
        train, forecast, rate_of_change_lag_periods=1, rolling_window_periods=rolling_window
    ).dropna()
    detector = Detector().fit(feats)
    detector.calibrate_threshold(detector.score(feats), alert_budget=0.1)
    return ModelArtifact(
        tier="eia",
        zone=None,
        detector=detector,
        flatline_floor=1.0,  # high enough that the extreme-value test case never flatlines
        rolling_window_periods=rolling_window,
        rate_of_change_lag_periods=1,
        seasonal_naive_lag_periods=lag_periods,
        trained_at=datetime.now(UTC),
        train_rows=len(feats),
    )


def _fake_artifact():
    class _Fake:
        seasonal_naive_lag_periods = 168
        rate_of_change_lag_periods = 1
        rolling_window_periods = 4
        flatline_floor = 1.0

    return _Fake()


def _fake_settings():
    class _Fake:
        postgres_dsn = "postgresql://fake/fake"

    return _Fake()
