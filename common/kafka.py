"""Kafka producer/consumer wrappers. Architecture.md Section 9 Phase 3: "Kafka producers/
consumers for both tiers." Topics (Section 5's diagram): eia.grid.raw, pjm.lmp.raw,
pjm.lmp.anomalies.

Serialization is pure, dependency-free functions -- fully unit-testable without a broker.
The Producer/Consumer wrappers themselves are thin glue around confluent-kafka and are
exercised by tests/test_kafka_integration.py, which (same pattern as common/db.py's
integration tests) skips cleanly when no broker is reachable rather than requiring one.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer

log = logging.getLogger(__name__)

TOPIC_EIA_RAW = "eia.grid.raw"
TOPIC_PJM_RAW = "pjm.lmp.raw"
TOPIC_PJM_ANOMALIES = "pjm.lmp.anomalies"


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    raise TypeError(f"not JSON serializable: {type(obj)}")


def serialize_row(row: dict) -> bytes:
    """Pure: dict -> JSON bytes, datetimes as ISO 8601. The one place every producer in this
    project turns a normalized row into wire bytes, so every consumer can assume the same
    shape regardless of which poller produced it."""
    return json.dumps(row, default=_json_default).encode("utf-8")


def deserialize_row(data: bytes) -> dict:
    """Pure: JSON bytes -> dict. Does NOT parse ISO datetime strings back into datetime
    objects -- callers already know which fields are dates (e.g. period_start) and parse
    them explicitly, same as common/normalize.py does for the HTTP response path. Guessing
    generically here would silently mis-parse a field that merely looks date-shaped."""
    return json.loads(data.decode("utf-8"))


def make_producer(bootstrap_servers: str) -> Producer:
    return Producer({"bootstrap.servers": bootstrap_servers})


def make_consumer(bootstrap_servers: str, group_id: str, topics: Iterable[str]) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe(list(topics))
    return consumer


def _delivery_callback(err, msg) -> None:
    if err is not None:
        log.error("Kafka delivery failed", extra={"topic": msg.topic(), "error": str(err)})


def produce_row(producer: Producer, topic: str, key: str, row: dict) -> None:
    """Produces one row, non-blocking (delivery confirmed/logged asynchronously via the
    callback) -- callers should still call producer.flush() before process exit so pending
    deliveries aren't silently dropped."""
    producer.produce(
        topic, key=key.encode("utf-8"), value=serialize_row(row), callback=_delivery_callback
    )
    producer.poll(0)  # serve any pending delivery callbacks without blocking


# Error codes treated as "nothing to read right now," not a fatal condition. Confirmed live
# against a real broker, not assumed: KafkaError.retriable() looked like the obviously
# correct general-purpose signal for this and turned out NOT to be -- a freshly-subscribed
# topic that doesn't exist yet in the client's cached metadata (routine on consumer startup,
# not an exotic edge case) surfaces as UNKNOWN_TOPIC_OR_PART with retriable()==False, even
# though polling again a moment later (once metadata refreshes) just works with no special
# handling needed. So this is a deliberately curated list for THIS use case, not a borrowed
# semantic from elsewhere in the client -- add to it only after confirming the same way.
_NON_FATAL_POLL_ERROR_CODES = frozenset(
    {KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART}
)


def poll_row(consumer: Consumer, timeout: float = 1.0) -> dict | None:
    """One poll cycle. Returns the deserialized row, or None when there's simply nothing to
    read right now (see _NON_FATAL_POLL_ERROR_CODES). Raises KafkaException on anything else
    -- auth failures, authorization, and the like -- which callers should not swallow."""
    msg: Message | None = consumer.poll(timeout)
    if msg is None:
        return None
    err = msg.error()
    if err is not None:
        if err.code() in _NON_FATAL_POLL_ERROR_CODES:
            log.debug("transient Kafka poll condition, will retry", extra={"error": str(err)})
            return None
        raise KafkaException(err)
    return deserialize_row(msg.value())
