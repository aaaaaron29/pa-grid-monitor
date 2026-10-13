from __future__ import annotations

from common.config import Settings


def test_defaults_are_sane_without_any_env(monkeypatch):
    # isolate from a real .env / real OS env so defaults are what's actually asserted
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    settings = Settings(_env_file=None)

    assert settings.eia_poll_interval_seconds == 3600
    assert settings.eia_rolling_window_hours == 72
    assert settings.eia_backfill_page_size == 5000
    assert settings.environment == "development"
    assert settings.metrics_port == 9100


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "test-key")
    monkeypatch.setenv("EIA_POLL_INTERVAL_SECONDS", "60")
    settings = Settings(_env_file=None)

    assert settings.eia_api_key == "test-key"
    assert settings.eia_poll_interval_seconds == 60


def test_unknown_env_vars_are_ignored(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "whatever")
    Settings(_env_file=None)  # must not raise
