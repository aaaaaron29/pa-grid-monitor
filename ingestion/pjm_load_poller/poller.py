"""Live PJM load poller: polls hrl_load_metered on a daily cadence, re-pulling a rolling
window each cycle to catch revisions. Confirmed live (2026-10-14): this feed posts once
daily (05:30 a.m.) and the electric distribution companies can revise a value for up to 90
days after the fact ("Data adjustments can occur up to 90 days after the actual date" --
the feed's own metadata). That is a real, meaningful revision pattern within this feed
itself, unlike ingestion/pjm_poller/poller.py's LMP feed, where "revision" only ever means
the separate verified feed overwriting these rows later. Re-pulling a trailing window
(settings.pjm_load_rolling_window_days, default 14) on every cycle, same shape as
ingestion/eia_poller/poller.py's rolling re-pull, not a fixed single-day snapshot.

Phase 3 wiring, same reasoning as the other pollers: produces to Kafka, a separate consumer
(ingestion/pjm_load_poller/consumer.py) does the Postgres write.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from confluent_kafka import Producer

from common.config import Settings
from common.kafka import TOPIC_PJM_LOAD_RAW, make_producer, produce_row
from common.metrics import INGEST_RUNS_TOTAL, LAST_SUCCESSFUL_INGEST_TS, ROWS_WRITTEN_TOTAL
from common.normalize_pjm import ZONE_LOAD_CODES, normalize_pjm_load_rows
from ingestion.pjm_poller.client import fetch_range_for_date

log = logging.getLogger(__name__)

SOURCE = "pjm_load"
FEED = "hrl_load_metered"


def run_once(settings: Settings, producer: Producer) -> int:
    """One poll cycle across all five PA zones, each re-pulling the rolling window.
    Returns rows produced to Kafka. Raises on failure -- the caller (run_forever) decides
    whether/how to keep going."""
    retrieved_at = datetime.now(UTC)
    end = retrieved_at
    start = end - timedelta(days=settings.pjm_load_rolling_window_days)
    total_produced = 0

    for zone, feed_code in ZONE_LOAD_CODES.items():
        raw_rows = list(
            fetch_range_for_date(
                api_key=settings.pjm_api_key,
                feed=FEED,
                start=start,
                end=end,
                zone=feed_code,
            )
        )
        rows = normalize_pjm_load_rows(raw_rows, retrieved_at=retrieved_at)
        for row in rows:
            key = f"{row['zone']}:{row['period_start'].isoformat()}"
            produce_row(producer, TOPIC_PJM_LOAD_RAW, key=key, row=row)
        total_produced += len(rows)
        ROWS_WRITTEN_TOTAL.labels(source=SOURCE, table=TOPIC_PJM_LOAD_RAW).inc(len(rows))
        log.info("poll cycle: zone done", extra={"zone": zone, "rows": len(rows)})

    producer.flush(30)
    LAST_SUCCESSFUL_INGEST_TS.labels(source=SOURCE).set(time.time())
    INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="success").inc()
    return total_produced


def run_forever(settings: Settings) -> None:
    log.info(
        "pjm load poller starting",
        extra={
            "interval_seconds": settings.pjm_load_poll_interval_seconds,
            "rolling_window_days": settings.pjm_load_rolling_window_days,
            "feed": FEED,
            "kafka_topic": TOPIC_PJM_LOAD_RAW,
        },
    )
    producer = make_producer(settings.kafka_bootstrap_servers)
    while True:
        try:
            written = run_once(settings, producer)
            log.info("poll cycle complete", extra={"rows_produced": written})
        except Exception:
            INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
            log.exception("poll cycle failed, will retry next interval")
        time.sleep(settings.pjm_load_poll_interval_seconds)
