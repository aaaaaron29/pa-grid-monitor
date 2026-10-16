"""A snapshot of how the pipeline looks from the server's side, written to Neon after each
hourly sync so the private pipeline page can show it.

The website reads only the Neon copy. That copy can look healthy while the server is down (the
data is simply old) and cannot say whether the lag is a stalled feed, a failed sync or a dead
machine. The snapshot carries what only the server knows: how old each stream is in the
pipeline's own database, whether the Neon copy is complete, and the state of the host. The
page treats a missing or old snapshot as news in itself.

Only timestamps, counts and states go in the snapshot, never PJM values.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1
KEEP_DAYS = 90


@dataclass(frozen=True)
class Stream:
    key: str
    label: str
    table: str
    where: str  # extra filter, constant (never from input)
    limit_minutes: int  # older than this and the watchdog calls the stream stalled
    normal: str  # what a healthy age looks like, for the page


# Limits match deploy/vps/ops.sh and scripts/windows/watchdog.ps1. Normal ages: PJM LMP a few
# minutes; EIA-930 about 2 to 6 hours; PJM metered load 1 to 2 days.
STREAMS: tuple[Stream, ...] = (
    Stream("pjm_lmp", "PJM prices (5-minute)", "pjm_lmp_readings", "", 25, "a few minutes"),
    Stream("pjm_lmp_scored", "PJM prices, scored", "pjm_lmp_anomalies", "", 40, "under 15 minutes"),
    Stream(
        "eia_demand", "EIA demand (hourly)", "eia_readings", "WHERE reading_type = 'D'",
        480, "2 to 6 hours",
    ),
    Stream("eia_scored", "EIA demand, scored", "eia_anomalies", "", 540, "2 to 7 hours"),
    Stream("pjm_load", "PJM zone load (hourly)", "pjm_load_readings", "", 5760, "1 to 2 days"),
)


def stream_ages(conn: psycopg.Connection) -> dict[str, float | None]:
    """Minutes between now and each stream's newest period_start; None when it has no rows."""
    ages: dict[str, float | None] = {}
    with conn.cursor() as cur:
        for s in STREAMS:
            cur.execute(
                f"SELECT EXTRACT(EPOCH FROM (now() - max(period_start))) / 60 "  # noqa: S608
                f"FROM {s.table} {s.where}"
            )
            value = cur.fetchone()[0]
            ages[s.key] = None if value is None else round(float(value), 1)
    return ages


def _stream_detail(conn: psycopg.Connection, s: Stream) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT max(period_start), EXTRACT(EPOCH FROM (now() - max(period_start))) / 60 "  # noqa: S608
            f"FROM {s.table} {s.where}"
        )
        newest, age = cur.fetchone()
    return {
        "label": s.label,
        "newest": None if newest is None else newest.astimezone(UTC).isoformat(),
        "age_minutes": None if age is None else round(float(age), 1),
        "limit_minutes": s.limit_minutes,
        "normal": s.normal,
    }


def parse_ops(raw: str | None) -> dict[str, Any] | None:
    """The host's own state, passed in by deploy/vps/ops.sh as JSON. Anything unreadable is
    dropped rather than failing the sync; the page shows the section as unavailable."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("OPS_HEALTH_JSON is not valid JSON; leaving host state out")
        return None
    return parsed if isinstance(parsed, dict) else None


def build_snapshot(
    source: psycopg.Connection,
    sync_results: list[Any],
    ops: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    captured = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "version": SNAPSHOT_VERSION,
        "captured_at": captured.isoformat(),
        "streams": {s.key: _stream_detail(source, s) for s in STREAMS},
        "sync": [
            {
                "table": r.table,
                "rows_written": r.rows_written,
                "source_count": r.source_count,
                "destination_count": r.destination_count,
                "seconds": r.seconds,
            }
            for r in sync_results
        ],
        "host": ops,
    }


def write_snapshot(destination: psycopg.Connection, snapshot: dict[str, Any]) -> None:
    with destination.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_health (captured_at, payload) VALUES (%s, %s) "
            "ON CONFLICT (captured_at) DO UPDATE SET payload = EXCLUDED.payload",
            (snapshot["captured_at"], json.dumps(snapshot)),
        )
        cur.execute(
            "DELETE FROM pipeline_health WHERE captured_at < now() - make_interval(days => %s)",
            (KEEP_DAYS,),
        )
    destination.commit()


def snapshot_from_env_ops() -> dict[str, Any] | None:
    return parse_ops(os.environ.get("OPS_HEALTH_JSON"))
