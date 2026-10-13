"""Live PJM poller: polls rt_unverified_fivemin_lmps every 5 minutes for dashboard
freshness (verified=False). Architecture.md Section 3/6: this data is explicitly
not settlement-quality and gets reconciled the next day when the verified feed posts —
that reconciliation is a separate scheduled job (verify_refresh.py), not this poller.

Unlike the EIA poller's rolling-window re-pull, this feed has no meaningful revision
history of its own within a single poll cycle (each 5-min interval is posted once, as-is);
the "revision" that matters here is the verified feed overwriting these rows later, which
the upsert in common.db.upsert_pjm_lmp_readings already protects correctly (verified always
wins, never the reverse).

Phase 3 (Architecture.md Section 9): produces to Kafka instead of writing directly to
Postgres, same reasoning and same shape as ingestion/eia_poller/poller.py's equivalent
change -- a separate consumer (ingestion/pjm_poller/consumer.py) does the write.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from confluent_kafka import Producer

from common.config import Settings
from common.kafka import TOPIC_PJM_RAW, make_producer, produce_row
from common.metrics import INGEST_RUNS_TOTAL, LAST_SUCCESSFUL_INGEST_TS, ROWS_WRITTEN_TOTAL
from common.normalize_pjm import ZONE_PNODE_IDS, normalize_pjm_rows
from ingestion.pjm_poller.client import fetch_range

log = logging.getLogger(__name__)

SOURCE = "pjm"
FEED = "rt_unverified_fivemin_lmps"


def run_once(settings: Settings, producer: Producer) -> int:
    """One poll cycle across all five PA zones. Returns rows produced to Kafka. Raises on
    failure — the caller (run_forever) decides whether/how to keep going."""
    retrieved_at = datetime.now(UTC)
    total_produced = 0

    for zone, pnode_id in ZONE_PNODE_IDS.items():
        raw_rows = list(
            fetch_range(
                api_key=settings.pjm_api_key,
                feed=FEED,
                datetime_filter="5minutesago",
                pnode_ids=[pnode_id],
            )
        )
        rows = normalize_pjm_rows(raw_rows, verified=False, retrieved_at=retrieved_at)
        for row in rows:
            key = f"{row['zone']}:{row['period_start'].isoformat()}"
            produce_row(producer, TOPIC_PJM_RAW, key=key, row=row)
        total_produced += len(rows)
        ROWS_WRITTEN_TOTAL.labels(source=SOURCE, table=TOPIC_PJM_RAW).inc(len(rows))
        log.info("poll cycle: zone done", extra={"zone": zone, "rows": len(rows)})

    producer.flush(30)
    LAST_SUCCESSFUL_INGEST_TS.labels(source=SOURCE).set(time.time())
    INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="success").inc()
    return total_produced


def run_forever(settings: Settings) -> None:
    log.info(
        "pjm poller starting",
        extra={
            "interval_seconds": settings.pjm_poll_interval_seconds,
            "feed": FEED,
            "kafka_topic": TOPIC_PJM_RAW,
        },
    )
    producer = make_producer(settings.kafka_bootstrap_servers)
    while True:
        try:
            written = run_once(settings, producer)
            log.info("poll cycle complete", extra={"rows_produced": written})
        except Exception:
            INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
            # Same reasoning as the EIA poller: one bad cycle shouldn't kill the process,
            # LAST_SUCCESSFUL_INGEST_TS just stops advancing and the staleness alert fires.
            log.exception("poll cycle failed, will retry next interval")
        time.sleep(settings.pjm_poll_interval_seconds)
