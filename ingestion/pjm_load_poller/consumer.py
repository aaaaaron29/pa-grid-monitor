"""PJM load Kafka consumer: reads normalized rows from pjm.load.raw, upserts to Postgres.

Same reasoning as ingestion/pjm_poller/consumer.py: no normalization here (the producer
already ran rows through common.normalize_pjm.normalize_pjm_load_rows), just parse the two
ISO-serialized datetime fields and call common.db.upsert_pjm_load_readings.

Larger batch / longer wait than the LMP consumer: each poll cycle re-pulls a 14-day rolling
window across 5 zones (hundreds of rows per cycle, once a day), not a steady small trickle
every 5 minutes, so there is no freshness reason to flush quickly.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from common.config import Settings, get_settings
from common.db import connect, upsert_pjm_load_readings
from common.kafka import TOPIC_PJM_LOAD_RAW, commit_offsets, make_consumer, poll_row
from common.logging import configure_logging
from common.metrics import (
    INGEST_RUNS_TOTAL,
    LAST_SUCCESSFUL_INGEST_TS,
    ROWS_WRITTEN_TOTAL,
    start_metrics_server,
)

log = logging.getLogger(__name__)

SOURCE = "pjm_load_consumer"
BATCH_SIZE = 500
MAX_BATCH_WAIT_SECONDS = 5.0


def _parse_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row["period_start"] = datetime.fromisoformat(row["period_start"])
    row["retrieved_at"] = datetime.fromisoformat(row["retrieved_at"])
    return row


def run_forever(settings: Settings, group_id: str = "pjm-load-consumer") -> None:
    log.info(
        "pjm load consumer starting", extra={"topic": TOPIC_PJM_LOAD_RAW, "group_id": group_id}
    )
    consumer = make_consumer(settings.kafka_bootstrap_servers, group_id, [TOPIC_PJM_LOAD_RAW])

    batch: list[dict[str, Any]] = []
    batch_started_at = time.monotonic()

    while True:
        try:
            raw = poll_row(consumer, timeout=1.0)
        except Exception:
            INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
            log.exception("poll failed, retrying")
            time.sleep(1.0)
            continue

        if raw is not None:
            batch.append(_parse_row(raw))

        batch_is_full = len(batch) >= BATCH_SIZE
        batch_has_waited_too_long = (
            batch and (time.monotonic() - batch_started_at) >= MAX_BATCH_WAIT_SECONDS
        )
        if batch and (batch_is_full or batch_has_waited_too_long):
            try:
                with connect(settings.postgres_dsn) as conn:
                    written = upsert_pjm_load_readings(conn, batch)
                commit_offsets(consumer)  # only after the write durably succeeds
                ROWS_WRITTEN_TOTAL.labels(source=SOURCE, table="pjm_load_readings").inc(written)
                LAST_SUCCESSFUL_INGEST_TS.labels(source=SOURCE).set(time.time())
                INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="success").inc()
                log.info("batch upserted", extra={"rows": written})
            except Exception:
                INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
                log.exception("batch upsert failed, will retry")
            else:
                batch = []
            batch_started_at = time.monotonic()


def main() -> None:
    """Entry point: python -m ingestion.pjm_load_poller.consumer"""
    settings = get_settings()
    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)
    run_forever(settings)


if __name__ == "__main__":
    main()
