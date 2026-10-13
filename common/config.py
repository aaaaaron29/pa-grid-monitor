"""Central settings. One source of truth for env vars — Compose and k8s both set these,
Compose via .env, k8s via Secrets/ConfigMaps — so the same Settings class works unmodified
in either place (Architecture.md Section 7, "config is env-var driven")."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Public tier (EIA) ---
    eia_api_key: str = ""
    eia_poll_interval_seconds: int = 3600
    eia_rolling_window_hours: int = 72
    eia_backfill_page_size: int = Field(default=5000, le=5000)  # API v2 hard cap

    # --- Private tier (PJM) --- unused until the PJM poller ships; present so .env.example
    # documents every var the stack will eventually read.
    pjm_api_key: str = ""
    pjm_poll_interval_seconds: int = 300

    # --- Storage ---
    postgres_dsn: str = "postgresql://pjm_grid_watch:pjm_grid_watch@localhost:5432/pjm_grid_watch"

    # --- App ---
    environment: str = "development"
    log_level: str = "INFO"
    metrics_port: int = 9100


def get_settings() -> Settings:
    # Deliberately uncached: a cached singleton makes tests that twiddle env vars
    # order-dependent, and settings are cheap enough to rebuild per call.
    return Settings()
