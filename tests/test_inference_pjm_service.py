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
from inference.pjm_service import _build_history_plus_current, _score_and_store
from model.artifact import ModelArtifact
from model.detector import Detector
from model.features import build_features


def test_score_and_store_skips_rows_for_unknown_zones():
    """Regression guard: a row whose zone isn't one of the five tracked PA zones (the raw
    topic is PJM-wide-filtered at the poller, but this is the one place that assumption is
    actually enforced for scoring) must never crash on a dict lookup miss."""
    calls = []
    with patch(
        "inference.pjm_service._build_history_plus_current",
        side_effect=lambda *a, **k: calls.append("called"),
    ):
        row = {"zone": "NOT_A_REAL_ZONE", "period_start": "2026-01-01T00:00:00+00:00"}
        _score_and_store(settings=_fake_settings(), artifacts={"PECO": _fake_artifact()}, row=row)
    assert calls == []


def test_build_history_plus_current_returns_none_for_missing_value():
    row = {
        "zone": "PECO",
        "period_start": "2026-01-01T00:00:00+00:00",
        "lmp_price": None,
    }
    with patch("inference.pjm_service.load_pjm_series") as mock_load:
        mock_load.return_value = pd.Series(dtype=float)
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )
    assert result is None


def test_build_history_plus_current_appends_current_value_without_requiring_it_in_postgres():
    """Same core correctness property as the EIA service: the current point's value comes
    from the Kafka message itself, never from re-querying Postgres -- so scoring cannot
    depend on ingestion/pjm_poller/consumer.py having already written this exact row."""
    row = {
        "zone": "PECO",
        "period_start": "2026-01-01T00:05:00+00:00",
        "lmp_price": 42.5,
    }
    history_index = pd.date_range("2025-12-01", periods=2500, freq="5min", tz="UTC")
    history = pd.Series(30.0, index=history_index)

    with patch("inference.pjm_service.load_pjm_series", return_value=history):
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )

    assert result is not None
    assert result.iloc[-1] == 42.5
    assert result.index[-1] == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)


def test_build_history_plus_current_returns_none_when_not_enough_settled_history():
    """This is exactly the condition hit live on 2026-10-13 against the real database: a
    genuine gap in pjm_lmp_readings right before the current point must decline to score,
    not score on a thin window."""
    row = {
        "zone": "PECO",
        "period_start": "2026-01-01T00:00:00+00:00",
        "lmp_price": 30.0,
    }
    with patch("inference.pjm_service.load_pjm_series", return_value=pd.Series(dtype=float)):
        result = _build_history_plus_current(
            settings=_fake_settings(), artifact=_fake_artifact(), row=row
        )
    assert result is None


def test_score_and_store_records_success_and_anomaly_metrics(monkeypatch):
    """Same as the EIA service's equivalent test: a real ModelArtifact (score_latest needs a
    real .detector), checking the actual Prometheus counters/gauge get updated, zone-labeled
    this time since PJM has real zones unlike EIA."""
    artifact = _real_artifact()
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    history = pd.Series(30.0 + rng.normal(0, 2, 100), index=idx)
    row = {
        "zone": "PECO",
        "period_start": "2024-01-01T08:20:00+00:00",  # history's next 5-min tick, no gap
        "lmp_price": 50_000.0,  # wildly extreme -- forces a real forest-flagged anomaly
    }
    written = []

    monkeypatch.setattr("inference.pjm_service.load_pjm_series", lambda *a, **k: history)
    monkeypatch.setattr("inference.pjm_service.connect", _fake_connect)
    monkeypatch.setattr(
        "inference.pjm_service.upsert_pjm_lmp_anomalies",
        lambda conn, rows: written.extend(rows),
    )

    scored_before = SCORING_RUNS_TOTAL.labels(tier="pjm", outcome="scored")._value.get()
    forest_before = ANOMALIES_FLAGGED_TOTAL.labels(
        tier="pjm", zone="PECO", detector="forest"
    )._value.get()

    _score_and_store(settings=_fake_settings(), artifacts={"PECO": artifact}, row=row)

    assert len(written) == 1
    assert written[0]["forest_flagged"] is True
    assert SCORING_RUNS_TOTAL.labels(tier="pjm", outcome="scored")._value.get() == scored_before + 1
    assert (
        ANOMALIES_FLAGGED_TOTAL.labels(tier="pjm", zone="PECO", detector="forest")._value.get()
        == forest_before + 1
    )
    assert LAST_SUCCESSFUL_SCORE_TS.labels(tier="pjm")._value.get() > 0


def test_score_and_store_records_skipped_metric_on_insufficient_history(monkeypatch):
    monkeypatch.setattr(
        "inference.pjm_service._build_history_plus_current", lambda *a, **k: None
    )
    row = {"zone": "PECO", "period_start": "2026-01-01T00:00:00+00:00"}

    skipped_before = SCORING_RUNS_TOTAL.labels(tier="pjm", outcome="skipped")._value.get()
    _score_and_store(
        settings=_fake_settings(), artifacts={"PECO": _fake_artifact()}, row=row
    )
    skipped_after = SCORING_RUNS_TOTAL.labels(tier="pjm", outcome="skipped")._value.get()
    assert skipped_after == skipped_before + 1


@contextmanager
def _fake_connect(dsn):
    yield object()


def _real_artifact(lag_periods: int = 24, rolling_window: int = 12) -> ModelArtifact:
    rng = np.random.default_rng(0)
    n = lag_periods * 3
    idx = pd.date_range("2023-01-01", periods=n, freq="5min", tz="UTC")
    train = pd.Series(30.0 + rng.normal(0, 3, n), index=idx)
    forecast = train.shift(lag_periods)
    feats = build_features(
        train, forecast, rate_of_change_lag_periods=1, rolling_window_periods=rolling_window
    ).dropna()
    detector = Detector().fit(feats)
    detector.calibrate_threshold(detector.score(feats), alert_budget=0.1)
    return ModelArtifact(
        tier="pjm",
        zone="PECO",
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
        seasonal_naive_lag_periods = 2016
        rate_of_change_lag_periods = 1
        rolling_window_periods = 12
        flatline_floor = 1.0

    return _Fake()


def _fake_settings():
    class _Fake:
        postgres_dsn = "postgresql://fake/fake"

    return _Fake()
