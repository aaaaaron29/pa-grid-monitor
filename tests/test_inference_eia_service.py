from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd

from inference.eia_service import SCORED_READING_TYPE, _build_history_plus_current, _score_and_store


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
