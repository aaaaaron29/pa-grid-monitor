"""Historical PJM hrl_load_metered backfill.

Writes straight to Postgres (no Kafka), through common.normalize_pjm, same reasoning as
the EIA and PJM LMP backfills.

Confirmed live (2026-10-14): unlike rt_fivemin_hrl_lmps (see pjm_backfill.py's long
"ARCHIVED DATA" section), this feed's server-side `zone` filter and custom sort both still
work for data nearly two years old -- tested against January 2024 directly, got a clean 200
with real rows, not the "invalid attribute(s) for archived data" 400 the LMP feed returns
past its ~186-day archive cutoff. No fast/archived split needed here; one path, same
zone-by-zone chunking the LMP backfill uses.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.config import Settings
from common.db import connect, upsert_pjm_load_readings
from common.metrics import INGEST_RUNS_TOTAL, ROWS_WRITTEN_TOTAL
from common.normalize_pjm import ZONE_LOAD_CODES, normalize_pjm_load_rows
from ingestion.pjm_poller.client import fetch_range_for_date

log = logging.getLogger(__name__)

FEED = "hrl_load_metered"

# One API call per (zone, chunk). Hourly data, up to 2 load_area rows per zone per hour
# (PPL's PLCO + UGI is the only zone of the five with more than one) -- 60 days x 24 hours
# x 2 is 2,880 rows at the high end, comfortably under the 5,000-row page cap, so each
# chunk fits in one page without fetch_range needing to paginate.
_CHUNK = timedelta(days=60)


def _chunks(start: datetime, end: datetime, step: timedelta):
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end


def run_pjm_load_backfill(
    settings: Settings,
    start: datetime,
    end: datetime | None = None,
    zones: list[str] | None = None,
) -> int:
    """Backfills pjm_load_readings for all five PA zones over [start, end), or just `zones`
    when given -- lets a failed run resume the zone it stopped on instead of re-pulling
    zones that already finished (upsert is idempotent either way, but re-pulling wastes the
    6 req/min non-member rate budget). `verified` comes through per-row from the feed itself
    (normalize_pjm_load_rows), not passed in -- unlike the LMP backfill, which always writes
    verified=True since it deliberately targets the settlement-quality feed."""
    end = end or datetime.now(UTC)
    total_written = 0
    retrieved_at = datetime.now(UTC)
    codes = {z: ZONE_LOAD_CODES[z] for z in zones} if zones else ZONE_LOAD_CODES

    with connect(settings.postgres_dsn) as conn:
        for zone, feed_code in codes.items():
            for chunk_start, chunk_end in _chunks(start, end, _CHUNK):
                log.info(
                    "backfilling chunk",
                    extra={
                        "zone": zone,
                        "start": chunk_start.isoformat(),
                        "end": chunk_end.isoformat(),
                    },
                )
                try:
                    raw_rows = list(
                        fetch_range_for_date(
                            api_key=settings.pjm_api_key,
                            feed=FEED,
                            start=chunk_start,
                            end=chunk_end,
                            zone=feed_code,
                        )
                    )
                except Exception:
                    INGEST_RUNS_TOTAL.labels(source="pjm_load_backfill", outcome="error").inc()
                    log.exception(
                        "chunk failed, re-run this date range to retry",
                        extra={"zone": zone, "start": chunk_start.isoformat()},
                    )
                    raise

                rows = normalize_pjm_load_rows(raw_rows, retrieved_at=retrieved_at)
                written = upsert_pjm_load_readings(conn, rows)
                conn.commit()
                total_written += written
                ROWS_WRITTEN_TOTAL.labels(
                    source="pjm_load_backfill", table="pjm_load_readings"
                ).inc(written)
                INGEST_RUNS_TOTAL.labels(source="pjm_load_backfill", outcome="success").inc()
                log.info("chunk done", extra={"zone": zone, "rows": written})

    return total_written
