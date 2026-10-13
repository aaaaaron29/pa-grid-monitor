"""EIA Kafka consumer: reads normalized rows from eia.grid.raw, upserts to Postgres.

Architecture.md Section 7: "Normalization lives in /common, not in the Kafka consumer" --
this consumer does NO normalization of its own. The producer (ingestion/eia_poller/poller.py)
already ran rows through common.normalize before putting them on the wire; this just parses
the two datetime fields serialized as ISO strings back into datetime objects and calls the
exact same common.db.upsert_eia_readings the backfill path uses, so both write paths stay
provably identical in shape.

Micro-batches rather than one upsert per message: drains whatever's immediately available
(up to BATCH_SIZE) before committing, since EIA's cadence (hourly, ~200 rows/cycle across
3 reading types) makes one-row-per-upsert an unnecessary Postgres round trip per row.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from common.config import Settings, get_settings
from common.db import connect, upsert_eia_readings
from common.kafka import TOPIC_EIA_RAW, commit_offsets, make_consumer, poll_row
from common.logging import configure_logging
from common.metrics import (
    INGEST_RUNS_TOTAL,
    LAST_SUCCESSFUL_INGEST_TS,
    ROWS_WRITTEN_TOTAL,
    start_metrics_server,
)

log = logging.getLogger(__name__)

SOURCE = "eia_consumer"
BATCH_SIZE = 500
MAX_BATCH_WAIT_SECONDS = 5.0  # flush even a partial batch after this long with no new rows


def _parse_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row["period_start"] = datetime.fromisoformat(row["period_start"])
    row["retrieved_at"] = datetime.fromisoformat(row["retrieved_at"])
    return row


def run_forever(settings: Settings, group_id: str = "eia-consumer") -> None:
    log.info("eia consumer starting", extra={"topic": TOPIC_EIA_RAW, "group_id": group_id})
    consumer = make_consumer(settings.kafka_bootstrap_servers, group_id, [TOPIC_EIA_RAW])

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
                    written = upsert_eia_readings(conn, batch)
                # Offsets committed ONLY after the write durably succeeds (common.kafka's
                # make_consumer disables auto-commit for exactly this reason) -- if the
                # process dies between poll and here, the next consumer in this group
                # re-reads the same messages instead of silently losing them. The upsert is
                # idempotent, so re-processing is harmless.
                commit_offsets(consumer)
                ROWS_WRITTEN_TOTAL.labels(source=SOURCE, table="eia_readings").inc(written)
                LAST_SUCCESSFUL_INGEST_TS.labels(source=SOURCE).set(time.time())
                INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="success").inc()
                log.info("batch upserted", extra={"rows": written})
            except Exception:
                INGEST_RUNS_TOTAL.labels(source=SOURCE, outcome="error").inc()
                # Offsets deliberately NOT committed on failure -- the batch is retried
                # (not dropped) on the next loop iteration.
                log.exception("batch upsert failed, will retry")
            else:
                batch = []
            batch_started_at = time.monotonic()


def main() -> None:
    """Entry point: python -m ingestion.eia_poller.consumer"""
    settings = get_settings()
    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)
    run_forever(settings)


if __name__ == "__main__":
    main()
