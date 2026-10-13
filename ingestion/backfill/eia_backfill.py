"""Historical EIA-930 backfill. Writes straight to Postgres (bypassing Kafka, which doesn't
exist yet in this phase per Architecture.md Section 9 — Kafka wiring is Phase 3), through
the same common.normalize code path the live poller will use, so backfilled and live rows
are indistinguishable in shape (Architecture.md Section 6).

Idempotent and resumable: re-running any date range is always safe (the upsert in
common.db.upsert_eia_readings only writes when a value actually changed), so a failed run
can simply be re-invoked rather than requiring cleanup.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.config import Settings
from common.db import connect, upsert_eia_readings
from common.metrics import INGEST_RUNS_TOTAL, ROWS_WRITTEN_TOTAL
from common.normalize import normalize_eia_rows
from ingestion.eia_poller.client import ReadingType, fetch_range

log = logging.getLogger(__name__)

READING_TYPES: tuple[ReadingType, ...] = ("D", "NG", "TI")

# One API call per (reading_type, chunk) pair; chunking by calendar year keeps each
# response bounded and gives resumable, observable progress on a multi-year pull.
_CHUNK = timedelta(days=365)


def _year_chunks(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + _CHUNK, end)
        yield cursor, chunk_end
        cursor = chunk_end


def run_eia_backfill(
    settings: Settings,
    start: datetime,
    end: datetime | None = None,
    reading_types: tuple[ReadingType, ...] = READING_TYPES,
    respondent: str = "PJM",
) -> int:
    end = end or datetime.now(UTC)
    total_written = 0
    retrieved_at = datetime.now(UTC)

    with connect(settings.postgres_dsn) as conn:
        for reading_type in reading_types:
            for chunk_start, chunk_end in _year_chunks(start, end):
                log.info(
                    "backfilling chunk",
                    extra={
                        "reading_type": reading_type,
                        "start": chunk_start.isoformat(),
                        "end": chunk_end.isoformat(),
                    },
                )
                try:
                    raw_rows = list(
                        fetch_range(
                            api_key=settings.eia_api_key,
                            reading_type=reading_type,
                            start=chunk_start,
                            end=chunk_end,
                            page_size=settings.eia_backfill_page_size,
                            respondent=respondent,
                        )
                    )
                except Exception:
                    INGEST_RUNS_TOTAL.labels(source="eia_backfill", outcome="error").inc()
                    log.exception(
                        "chunk failed, re-run this date range to retry",
                        extra={"reading_type": reading_type, "start": chunk_start.isoformat()},
                    )
                    raise

                rows = normalize_eia_rows(raw_rows, retrieved_at=retrieved_at)
                written = upsert_eia_readings(conn, rows)
                conn.commit()
                total_written += written
                ROWS_WRITTEN_TOTAL.labels(source="eia_backfill", table="eia_readings").inc(written)
                INGEST_RUNS_TOTAL.labels(source="eia_backfill", outcome="success").inc()
                log.info(
                    "chunk done",
                    extra={"reading_type": reading_type, "rows": written},
                )

    return total_written
