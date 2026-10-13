"""Exercises the real upsert SQL against a real Postgres. Skipped automatically if
TEST_DATABASE_URL (or POSTGRES_DSN) isn't set or isn't reachable — these are the only
DB-dependent tests in the suite, kept separate so `pytest` still runs clean with no
database at all (Architecture.md Section 7: CI makes no live API calls, and by the same
logic shouldn't hard-require infra that isn't spun up yet in Phase 1 CI)."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from common.db import connect, fetch_eia_readings, upsert_eia_readings

DSN = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get("POSTGRES_DSN", "postgresql://pjm_grid_watch:pjm_grid_watch@localhost:5432/pjm_grid_watch"),
)
SCHEMA_SQL = Path(__file__).parent.parent / "infra" / "sql" / "0001_init.sql"


def _db_reachable() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.integration

if not _db_reachable():
    pytest.skip(
        f"no reachable Postgres at {DSN!r} — skipping integration tests", allow_module_level=True
    )


@pytest.fixture(autouse=True)
def _schema_and_cleanup():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    yield
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM eia_readings WHERE respondent = 'TEST'")


def _row(value_mw: float | None, retrieved_at: datetime, quality: str = "ok"):
    return {
        "respondent": "TEST",
        "reading_type": "D",
        "period_start": datetime(2024, 1, 1, tzinfo=UTC),
        "value_mw": value_mw,
        "quality": quality if value_mw is not None else "missing",
        "retrieved_at": retrieved_at,
    }


def test_upsert_inserts_new_row():
    with connect(DSN) as conn:
        written = upsert_eia_readings(conn, [_row(100.0, datetime(2024, 1, 2, tzinfo=UTC))])
        rows = fetch_eia_readings(
            conn, "TEST", "D", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        )

    assert written == 1
    assert len(rows) == 1
    assert rows[0]["value_mw"] == 100.0


def test_upsert_revises_changed_value():
    with connect(DSN) as conn:
        upsert_eia_readings(conn, [_row(100.0, datetime(2024, 1, 2, tzinfo=UTC))])
        upsert_eia_readings(conn, [_row(150.0, datetime(2024, 1, 3, tzinfo=UTC))])  # EIA revision
        rows = fetch_eia_readings(
            conn, "TEST", "D", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        )

    assert len(rows) == 1  # same composite key, not a duplicate row
    assert rows[0]["value_mw"] == 150.0
    assert rows[0]["retrieved_at"] == datetime(2024, 1, 3, tzinfo=UTC)


def test_upsert_is_a_noop_when_value_unchanged():
    """Re-running the same window (the live poller's normal behavior every cycle) shouldn't
    bump retrieved_at on rows that didn't actually change."""
    with connect(DSN) as conn:
        upsert_eia_readings(conn, [_row(100.0, datetime(2024, 1, 2, tzinfo=UTC))])
        # same value, later poll
        upsert_eia_readings(conn, [_row(100.0, datetime(2024, 1, 3, tzinfo=UTC))])
        rows = fetch_eia_readings(
            conn, "TEST", "D", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        )

    assert rows[0]["retrieved_at"] == datetime(2024, 1, 2, tzinfo=UTC)  # untouched


def test_upsert_handles_missing_value():
    with connect(DSN) as conn:
        upsert_eia_readings(conn, [_row(None, datetime(2024, 1, 2, tzinfo=UTC))])
        rows = fetch_eia_readings(
            conn, "TEST", "D", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        )

    assert rows[0]["value_mw"] is None
    assert rows[0]["quality"] == "missing"
