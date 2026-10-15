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


# Composite key (zone, period_start). Unlike EIA, there are two independent writers here —
# the live poller (rt_unverified_fivemin_lmps, every 5 min) and backfill/the verified refresh
# (rt_fivemin_hrl_lmps, daily) — so "did the value change" isn't the only upsert condition:
# a verified row must never be downgraded back to unverified by a late/retried unverified
# poll. verified data always wins; unverified data only writes while the row isn't already
# verified (Architecture.md Section 3/6).
_UPSERT_PJM_LMP_READING = """
INSERT INTO pjm_lmp_readings
    (zone, period_start, lmp_price, quality, verified, retrieved_at)
VALUES
    (%(zone)s, %(period_start)s, %(lmp_price)s, %(quality)s, %(verified)s,
     %(retrieved_at)s)
ON CONFLICT (zone, period_start) DO UPDATE SET
    lmp_price = EXCLUDED.lmp_price,
    quality = EXCLUDED.quality,
    verified = EXCLUDED.verified,
    retrieved_at = EXCLUDED.retrieved_at
WHERE (EXCLUDED.verified OR NOT pjm_lmp_readings.verified)
  AND (
    pjm_lmp_readings.lmp_price IS DISTINCT FROM EXCLUDED.lmp_price
    OR pjm_lmp_readings.quality IS DISTINCT FROM EXCLUDED.quality
    OR pjm_lmp_readings.verified IS DISTINCT FROM EXCLUDED.verified
  )
"""


def upsert_pjm_lmp_readings(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Upsert a batch of normalized PJM LMP rows (see common.normalize_pjm). Same caveat as
    upsert_eia_readings: returns rows passed, not rows actually changed."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_PJM_LMP_READING, rows)
    return len(rows)


# Same verified-always-wins protection as pjm_lmp_readings, for the same reason: a re-poll of
# hrl_load_metered during the feed's up-to-90-day revision window could see a row that was
# unverified on a previous poll become verified on this one -- that transition must never be
# able to run in reverse from a stale/retried poll.
_UPSERT_PJM_LOAD_READING = """
INSERT INTO pjm_load_readings
    (zone, period_start, load_mw, quality, verified, retrieved_at)
VALUES
    (%(zone)s, %(period_start)s, %(load_mw)s, %(quality)s, %(verified)s,
     %(retrieved_at)s)
ON CONFLICT (zone, period_start) DO UPDATE SET
    load_mw = EXCLUDED.load_mw,
    quality = EXCLUDED.quality,
    verified = EXCLUDED.verified,
    retrieved_at = EXCLUDED.retrieved_at
WHERE (EXCLUDED.verified OR NOT pjm_load_readings.verified)
  AND (
    pjm_load_readings.load_mw IS DISTINCT FROM EXCLUDED.load_mw
    OR pjm_load_readings.quality IS DISTINCT FROM EXCLUDED.quality
    OR pjm_load_readings.verified IS DISTINCT FROM EXCLUDED.verified
  )
"""


def upsert_pjm_load_readings(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Upsert a batch of normalized PJM zone-load rows (see
    common.normalize_pjm.normalize_pjm_load_rows). Same caveat as upsert_eia_readings:
    returns rows passed, not rows actually changed."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_PJM_LOAD_READING, rows)
    return len(rows)


def fetch_pjm_load_readings(
    conn: psycopg.Connection,
    zone: str,
    start,
    end,
) -> Iterable[dict[str, Any]]:
    """Mainly for tests/debugging — the model and Grafana read Postgres directly."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT zone, period_start, load_mw, quality, verified, retrieved_at
            FROM pjm_load_readings
            WHERE zone = %s AND period_start >= %s AND period_start < %s
            ORDER BY period_start
            """,
            (zone, start, end),
        )
        return cur.fetchall()


def fetch_pjm_lmp_readings(
    conn: psycopg.Connection,
    zone: str,
    start,
    end,
) -> Iterable[dict[str, Any]]:
    """Mainly for tests/debugging — the model and Grafana read Postgres directly."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT zone, period_start, lmp_price, quality, verified, retrieved_at
            FROM pjm_lmp_readings
            WHERE zone = %s AND period_start >= %s AND period_start < %s
            ORDER BY period_start
            """,
            (zone, start, end),
        )
        return cur.fetchall()


# Anomaly results, written by the FastAPI inference services (Phase 3). Plain REPLACE
# semantics (not a change-aware WHERE guard like the readings upserts) -- a re-score always
# reflects the current model/threshold, so the latest score should always win, unlike a raw
# reading where an unverified value shouldn't be allowed to clobber a verified one.
_UPSERT_EIA_ANOMALY = """
INSERT INTO eia_anomalies
    (period_start, reading_type, residual, forest_score, forest_flagged, flatline_flagged,
     scored_at)
VALUES
    (%(period_start)s, %(reading_type)s, %(residual)s, %(forest_score)s,
     %(forest_flagged)s, %(flatline_flagged)s, %(scored_at)s)
ON CONFLICT (period_start, reading_type) DO UPDATE SET
    residual = EXCLUDED.residual,
    forest_score = EXCLUDED.forest_score,
    forest_flagged = EXCLUDED.forest_flagged,
    flatline_flagged = EXCLUDED.flatline_flagged,
    scored_at = EXCLUDED.scored_at
"""


def upsert_eia_anomalies(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_EIA_ANOMALY, rows)
    return len(rows)


_UPSERT_PJM_LMP_ANOMALY = """
INSERT INTO pjm_lmp_anomalies
    (zone, period_start, residual, forest_score, forest_flagged, flatline_flagged, scored_at)
VALUES
    (%(zone)s, %(period_start)s, %(residual)s, %(forest_score)s,
     %(forest_flagged)s, %(flatline_flagged)s, %(scored_at)s)
ON CONFLICT (zone, period_start) DO UPDATE SET
    residual = EXCLUDED.residual,
    forest_score = EXCLUDED.forest_score,
    forest_flagged = EXCLUDED.forest_flagged,
    flatline_flagged = EXCLUDED.flatline_flagged,
    scored_at = EXCLUDED.scored_at
"""


def upsert_pjm_lmp_anomalies(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_PJM_LMP_ANOMALY, rows)
    return len(rows)
