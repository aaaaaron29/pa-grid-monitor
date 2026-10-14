from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd

from inference.pjm_service import _build_history_plus_current, _score_and_store


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
