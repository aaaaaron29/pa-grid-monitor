"""Live EIA poller: re-pulls a rolling window every cycle and produces to Kafka.

Architecture.md Section 6: re-pulling (not just fetching the newest hour) absorbs both
EIA's publication lag and its post-publication revisions in one mechanism, so the live path
and the backfill path converge on identical values instead of drifting apart.

Phase 3 (Architecture.md Section 9): fetch+normalize feeds a Kafka producer instead of
calling upsert_eia_readings directly; a separate consumer (ingestion/eia_poller/consumer.py)
does the Postgres write, importing the exact same common.normalize code so the two write
paths (live and backfill, which still writes straight to Postgres) stay identical in shape.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from confluent_kafka import Producer

from common.config import Settings
from common.kafka import TOPIC_EIA_RAW, make_producer, produce_row
from common.metrics import INGEST_RUNS_TOTAL, LAST_SUCCESSFUL_INGEST_TS, ROWS_WRITTEN_TOTAL
from common.normalize import normalize_eia_rows
from ingestion.backfill.eia_backfill import READING_TYPES
from ingestion.eia_poller.client import fetch_range

log = logging.getLogger(__name__)

SOURCE = "eia"


def run_once(settings: Settings, producer: Producer, respondent: str = "PJM") -> int:
    """One poll cycle across all reading types. Returns rows produced to Kafka. Raises on
    failure — the caller (run_forever) decides whether/how to keep going."""
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=settings.eia_rolling_window_hours)
    retrieved_at = now
    total_produced = 0

    for reading_type in READING_TYPES:
        raw_rows = list(
            fetch_range(
                api_key=settings.eia_api_key,
                reading_type=reading_type,
                start=window_start,
                end=now,
                page_size=settings.eia_backfill_page_size,
                respondent=respondent,
            )
        )
        rows = normalize_eia_rows(raw_rows, retrieved_at=retrieved_at)
        for row in rows:
            key = f"{row['respondent']}:{row['reading_type']}:{row['period_start'].isoformat()}"
            produce_row(producer, TOPIC_EIA_RAW, key=key, row=row)
        total_produced += len(rows)
        ROWS_WRITTEN_TOTAL.labels(source=SOURCE, table=TOPIC_EIA_RAW).inc(len(rows))
        log.info(
            "poll cycle: reading type done",
            extra={"reading_type": reading_type, "rows": len(rows)},
        )

    producer.flush(30)  # don't advance the staleness gauge on undelivered messages
    LAST_SUCCESSFUL_INGEST_TS.labels(source=SOURCE).set(time.time())
    INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="success").inc()
    return total_produced


def run_forever(settings: Settings, respondent: str = "PJM") -> None:
    log.info(
        "eia poller starting",
        extra={
            "interval_seconds": settings.eia_poll_interval_seconds,
            "window_hours": settings.eia_rolling_window_hours,
            "kafka_topic": TOPIC_EIA_RAW,
        },
    )
    producer = make_producer(settings.kafka_bootstrap_servers)
    while True:
        try:
            written = run_once(settings, producer, respondent=respondent)
            log.info("poll cycle complete", extra={"rows_produced": written})
        except Exception:
            INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
            # Deliberately swallowed: one bad cycle (a transient EIA outage, a network blip)
            # should not kill the process — LAST_SUCCESSFUL_INGEST_TS simply stops advancing,
            # which is exactly what the staleness alert (Architecture.md Section 7) is for.
            log.exception("poll cycle failed, will retry next interval")
        time.sleep(settings.eia_poll_interval_seconds)
