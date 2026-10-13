"""Postgres access. Plain psycopg3 + hand-written SQL — no ORM, no migration framework
(Architecture.md Section 7: the schema is a handful of tables, and a migration framework
is a dependency and a failure mode this project doesn't need to buy). Migrations are the
plain numbered SQL files in /infra/sql, applied by scripts/apply_migrations.py.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg


@contextmanager
def connect(dsn: str):
    """One connection per call — these services do infrequent, bursty writes (one batch per
    poll cycle), not a steady request rate, so a pool is unneeded complexity for now."""
    conn = psycopg.connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Composite key (respondent, reading_type, period_start) matches the PK in
# infra/sql/0001_init.sql. ON CONFLICT ... DO UPDATE only when the value actually changed is
# what makes this revision-aware per Architecture.md Section 6 — EIA restates published
# figures, and first-write-wins would permanently freeze whichever value arrived first.
_UPSERT_EIA_READING = """
INSERT INTO eia_readings
    (respondent, reading_type, period_start, value_mw, quality, retrieved_at)
VALUES
    (%(respondent)s, %(reading_type)s, %(period_start)s, %(value_mw)s, %(quality)s,
     %(retrieved_at)s)
ON CONFLICT (respondent, reading_type, period_start) DO UPDATE SET
    value_mw = EXCLUDED.value_mw,
    quality = EXCLUDED.quality,
    retrieved_at = EXCLUDED.retrieved_at
WHERE eia_readings.value_mw IS DISTINCT FROM EXCLUDED.value_mw
   OR eia_readings.quality IS DISTINCT FROM EXCLUDED.quality
"""


def upsert_eia_readings(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Upsert a batch of normalized EIA reading rows (see common.normalize). Returns the
    number of rows passed, not the number actually changed (Postgres doesn't report that
    cheaply through executemany) — adequate for the ROWS_WRITTEN_TOTAL counter's purpose."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_EIA_READING, rows)
    return len(rows)


def fetch_eia_readings(
    conn: psycopg.Connection,
    respondent: str,
    reading_type: str,
    start,
    end,
) -> Iterable[dict[str, Any]]:
    """Mainly for tests/debugging — the model and Grafana read Postgres directly."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT respondent, reading_type, period_start, value_mw, quality, retrieved_at
            FROM eia_readings
            WHERE respondent = %s AND reading_type = %s
              AND period_start >= %s AND period_start < %s
            ORDER BY period_start
            """,
            (respondent, reading_type, start, end),
        )
        return cur.fetchall()
