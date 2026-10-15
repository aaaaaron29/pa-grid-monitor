"""Incremental copy of the pipeline's tables from the local Postgres (where the pollers and
consumers write) into Neon (which the website reads).

Why this exists instead of pointing the pipeline at Neon: Neon's free plan meters compute
time and suspends the database after 5 idle minutes. A pipeline that writes every 5 minutes
would keep it awake around the clock, well past the monthly allowance, and the site would go
down when the allowance ran out. Syncing in batches lets Neon sleep between runs.

How a run works, per table
  1. Read the newest "last written" timestamp (retrieved_at / scored_at) already in Neon and
     step back by an overlap window, so late or revised rows are picked up again.
  2. Stream every local row at or after that point into a temporary table in Neon (COPY).
  3. Upsert from the temporary table on the primary key, and only touch rows whose values
     actually differ, so a re-run changes nothing and costs Neon almost no writes.

Rows are only ever inserted or updated, never deleted: the pipeline does not delete either.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: tuple[str, ...]  # primary key columns
    stamp: str  # column recording when the row was last written


# Order matters only for readability; there are no foreign keys between these tables.
TABLES: tuple[TableSpec, ...] = (
    TableSpec("eia_readings", ("respondent", "reading_type", "period_start"), "retrieved_at"),
    TableSpec("eia_anomalies", ("period_start", "reading_type"), "scored_at"),
    TableSpec("pjm_lmp_readings", ("zone", "period_start"), "retrieved_at"),
    TableSpec("pjm_lmp_anomalies", ("zone", "period_start"), "scored_at"),
    TableSpec("pjm_load_readings", ("zone", "period_start"), "retrieved_at"),
    TableSpec("interconnection_queue", ("snapshot_date", "project_id"), "retrieved_at"),
)


@dataclass
class TableResult:
    table: str
    since: datetime | None  # None means a full copy
    rows_written: int  # rows inserted or changed in the destination
    source_count: int
    destination_count: int
    seconds: float


def connect_with_retry(dsn: str, attempts: int = 4) -> psycopg.Connection:
    """Neon's compute may be asleep and take a few seconds to wake; retry before giving up."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return psycopg.connect(dsn, connect_timeout=30)
        except psycopg.OperationalError as exc:
            last = exc
            wait = 2.0 * (attempt + 1)
            log.warning("connect failed, retrying", extra={"attempt": attempt, "wait": wait})
            time.sleep(wait)
    raise RuntimeError("could not connect") from last


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def _max_stamp(conn: psycopg.Connection, spec: TableSpec) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT max({}) FROM {}").format(
                sql.Identifier(spec.stamp), sql.Identifier(spec.name)
            )
        )
        return cur.fetchone()[0]


def _count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return cur.fetchone()[0]


def sync_table(
    source: psycopg.Connection,
    destination: psycopg.Connection,
    spec: TableSpec,
    *,
    overlap: timedelta = timedelta(hours=6),
    full: bool = False,
    dry_run: bool = False,
) -> TableResult:
    started = time.monotonic()
    src_cols = _columns(source, spec.name)
    dst_cols = _columns(destination, spec.name)
    if not dst_cols:
        raise RuntimeError(f"{spec.name} does not exist in the destination; run the migrations")
    missing = [c for c in dst_cols if c not in src_cols]
    if missing:
        raise RuntimeError(f"{spec.name}: destination has columns the source lacks: {missing}")
    cols = dst_cols  # copy exactly what the destination expects, in its order

    watermark = None if full else _max_stamp(destination, spec)
    since = None if watermark is None else watermark - overlap
    written = 0

    if not dry_run:
        col_list = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        where = (
            sql.SQL("")
            if since is None
            else sql.SQL(" WHERE {} >= {}").format(sql.Identifier(spec.stamp), sql.Literal(since))
        )
        non_key = [c for c in cols if c not in spec.key]
        key_list = sql.SQL(", ").join(sql.Identifier(c) for c in spec.key)
        changed = sql.SQL("({}) IS DISTINCT FROM ({})").format(
            sql.SQL(", ").join(sql.SQL("t.") + sql.Identifier(c) for c in non_key),
            sql.SQL(", ").join(sql.SQL("EXCLUDED.") + sql.Identifier(c) for c in non_key),
        )
        assignments = sql.SQL(", ").join(
            sql.Identifier(c) + sql.SQL(" = EXCLUDED.") + sql.Identifier(c) for c in non_key
        )

        with destination.cursor() as dcur:
            # LIKE without INCLUDING CONSTRAINTS keeps column types and NOT NULLs but not the
            # primary key, so the stage never rejects a batch on its own.
            dcur.execute(
                sql.SQL("CREATE TEMP TABLE _stage (LIKE {}) ON COMMIT DROP").format(
                    sql.Identifier(spec.name)
                )
            )
            copy_out = sql.SQL("COPY (SELECT {} FROM {}{}) TO STDOUT").format(
                col_list, sql.Identifier(spec.name), where
            )
            copy_in = sql.SQL("COPY _stage ({}) FROM STDIN").format(col_list)
            with source.cursor() as scur, scur.copy(copy_out) as out, dcur.copy(copy_in) as inn:
                for chunk in out:
                    inn.write(chunk)
            dcur.execute(
                sql.SQL(
                    "INSERT INTO {} AS t ({}) SELECT {} FROM _stage "
                    "ON CONFLICT ({}) DO UPDATE SET {} WHERE {}"
                ).format(
                    sql.Identifier(spec.name), col_list, col_list, key_list, assignments, changed
                )
            )
            written = dcur.rowcount
        destination.commit()
        source.rollback()  # end the read-only snapshot; nothing was written there

    return TableResult(
        table=spec.name,
        since=since,
        rows_written=written,
        source_count=_count(source, spec.name),
        destination_count=_count(destination, spec.name),
        seconds=round(time.monotonic() - started, 2),
    )


def sync_all(
    source: psycopg.Connection,
    destination: psycopg.Connection,
    *,
    overlap: timedelta = timedelta(hours=6),
    full: bool = False,
    dry_run: bool = False,
    tables: tuple[TableSpec, ...] = TABLES,
) -> list[TableResult]:
    results = []
    for spec in tables:
        result = sync_table(
            source, destination, spec, overlap=overlap, full=full, dry_run=dry_run
        )
        log.info(
            "table synced",
            extra={
                "table": result.table,
                "since": result.since.isoformat() if result.since else "full",
                "rows_written": result.rows_written,
                "source_count": result.source_count,
                "destination_count": result.destination_count,
                "seconds": result.seconds,
            },
        )
        if result.destination_count > result.source_count:
            log.warning(
                "destination has more rows than the source",
                extra={"table": result.table},
            )
        results.append(result)
    return results
