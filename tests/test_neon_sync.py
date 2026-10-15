"""The Neon sync against a real Postgres: two throwaway schemas stand in for the local database
(source) and Neon (destination). Skipped automatically when no Postgres is reachable, like the
other integration tests."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from common.neon_sync import TABLES, TableSpec, sync_all, sync_table

DSN = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "POSTGRES_DSN", "postgresql://pjm_grid_watch:pjm_grid_watch@localhost:5432/pjm_grid_watch"
    ),
)
SQL_DIR = Path(__file__).parent.parent / "infra" / "sql"
SRC, DST = "sync_test_src", "sync_test_dst"

pytestmark = pytest.mark.integration


def _db_reachable() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2):
            return True
    except Exception:
        return False


if not _db_reachable():
    pytest.skip(f"no reachable Postgres at {DSN!r}", allow_module_level=True)

LMP = next(t for t in TABLES if t.name == "pjm_lmp_readings")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _conn(schema: str) -> psycopg.Connection:
    return psycopg.connect(DSN, options=f"-c search_path={schema}")


@pytest.fixture
def pair():
    with psycopg.connect(DSN, autocommit=True) as admin:
        for schema in (SRC, DST):
            admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            admin.execute(f"CREATE SCHEMA {schema}")
    conns = {}
    for schema in (SRC, DST):
        conn = _conn(schema)
        for path in sorted(SQL_DIR.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()
        conns[schema] = conn
    yield conns[SRC], conns[DST]
    for conn in conns.values():
        conn.close()
    with psycopg.connect(DSN, autocommit=True) as admin:
        for schema in (SRC, DST):
            admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def _put(conn, zone: str, minute: int, price: float, stamp: datetime) -> None:
    conn.execute(
        "INSERT INTO pjm_lmp_readings (zone, period_start, lmp_price, retrieved_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (zone, period_start) DO UPDATE "
        "SET lmp_price = EXCLUDED.lmp_price, retrieved_at = EXCLUDED.retrieved_at",
        (zone, T0 + timedelta(minutes=minute), price, stamp),
    )
    conn.commit()


def _prices(conn) -> dict[tuple[str, int], float]:
    rows = conn.execute("SELECT zone, period_start, lmp_price FROM pjm_lmp_readings").fetchall()
    return {(z, int((p - T0).total_seconds() // 60)): v for z, p, v in rows}


def test_first_run_copies_everything(pair):
    src, dst = pair
    for i in range(5):
        _put(src, "PECO", i * 5, 20.0 + i, T0 + timedelta(hours=i))

    result = sync_table(src, dst, LMP)

    assert result.since is None  # destination was empty, so this was a full copy
    assert result.rows_written == 5
    assert _prices(dst) == _prices(src)


def test_second_run_with_no_changes_writes_nothing(pair):
    src, dst = pair
    for i in range(5):
        _put(src, "PECO", i * 5, 20.0 + i, T0 + timedelta(hours=i))
    sync_table(src, dst, LMP)

    result = sync_table(src, dst, LMP)

    assert result.rows_written == 0


def test_only_new_rows_are_sent_on_the_next_run(pair):
    src, dst = pair
    for i in range(5):
        _put(src, "PECO", i * 5, 20.0 + i, T0 + timedelta(hours=i))
    sync_table(src, dst, LMP)
    _put(src, "PECO", 100, 99.0, T0 + timedelta(hours=40))
    _put(src, "PPL", 100, 98.0, T0 + timedelta(hours=41))

    result = sync_table(src, dst, LMP)

    assert result.rows_written == 2
    assert result.source_count == result.destination_count == 7
    assert _prices(dst) == _prices(src)


def test_a_revised_value_replaces_the_old_one(pair):
    src, dst = pair
    _put(src, "PECO", 0, 10.0, T0)
    sync_table(src, dst, LMP)
    _put(src, "PECO", 0, 12.5, T0 + timedelta(hours=30))  # the verified feed corrects it

    result = sync_table(src, dst, LMP)

    assert result.rows_written == 1
    assert _prices(dst)[("PECO", 0)] == 12.5
    assert result.destination_count == 1  # updated in place, not duplicated


def test_overlap_window_recovers_a_row_that_was_missed(pair):
    src, dst = pair
    _put(src, "PECO", 0, 10.0, T0 + timedelta(hours=10))
    sync_table(src, dst, LMP)
    # a row stamped slightly BEFORE what Neon already holds, e.g. written late by another poller
    _put(src, "PECO", 5, 11.0, T0 + timedelta(hours=8))

    narrow = sync_table(src, dst, LMP, overlap=timedelta(0), dry_run=True)
    assert narrow.destination_count == 1  # dry run wrote nothing
    sync_table(src, dst, LMP, overlap=timedelta(hours=6))

    assert _prices(dst)[("PECO", 5)] == 11.0


def test_without_overlap_a_row_older_than_the_watermark_is_missed(pair):
    """Documents why the overlap exists: with none, the same row is never picked up."""
    src, dst = pair
    _put(src, "PECO", 0, 10.0, T0 + timedelta(hours=10))
    sync_table(src, dst, LMP)
    _put(src, "PECO", 5, 11.0, T0 + timedelta(hours=8))

    sync_table(src, dst, LMP, overlap=timedelta(0))

    assert ("PECO", 5) not in _prices(dst)


def test_full_flag_resends_everything_but_changes_nothing_that_matches(pair):
    src, dst = pair
    for i in range(4):
        _put(src, "PECO", i * 5, 20.0 + i, T0 + timedelta(hours=i))
    sync_table(src, dst, LMP)

    result = sync_table(src, dst, LMP, full=True)

    assert result.since is None
    assert result.rows_written == 0  # every row already matched, so none were touched


def test_dry_run_writes_nothing(pair):
    src, dst = pair
    _put(src, "PECO", 0, 10.0, T0)

    result = sync_table(src, dst, LMP, dry_run=True)

    assert result.rows_written == 0
    assert result.source_count == 1 and result.destination_count == 0


def test_sync_all_covers_every_table_including_empty_ones(pair):
    src, dst = pair
    _put(src, "PECO", 0, 10.0, T0)
    src.execute(
        "INSERT INTO eia_readings (respondent, reading_type, period_start, value_mw, retrieved_at) "
        "VALUES ('PJM', 'D', %s, 90000, %s)",
        (T0, T0),
    )
    src.commit()

    results = sync_all(src, dst)

    assert [r.table for r in results] == [t.name for t in TABLES]
    assert {r.table: r.destination_count for r in results}["eia_readings"] == 1
    assert {r.table: r.destination_count for r in results}["pjm_lmp_readings"] == 1


def test_a_missing_destination_table_is_reported_clearly(pair):
    src, dst = pair
    ghost = TableSpec("no_such_table", ("id",), "retrieved_at")

    with pytest.raises(RuntimeError, match="does not exist in the destination"):
        sync_table(src, dst, ghost)
