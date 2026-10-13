"""Exercises make_producer/make_consumer/produce_row/poll_row against a real Kafka broker.
Same pattern as tests/test_db_integration.py: skipped automatically if TEST_KAFKA_BROKER
(or the default localhost:9092) isn't reachable, so `pytest` still runs clean with no broker
at all.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient

from common.kafka import commit_offsets, make_consumer, make_producer, poll_row, produce_row

BROKER = os.environ.get("TEST_KAFKA_BROKER", "localhost:9092")


def _broker_reachable() -> bool:
    try:
        admin = AdminClient({"bootstrap.servers": BROKER})
        metadata = admin.list_topics(timeout=3.0)
        return metadata is not None
    except KafkaException:
        return False


pytestmark = pytest.mark.integration

if not _broker_reachable():
    pytest.skip(f"no reachable Kafka broker at {BROKER!r}, skipping", allow_module_level=True)


def test_produce_then_poll_round_trip():
    topic = f"test.kafka-integration.{uuid.uuid4().hex[:8]}"
    producer = make_producer(BROKER)
    row = {
        "zone": "PECO",
        "period_start": datetime(2026, 10, 13, 19, 5, tzinfo=UTC),
        "lmp_price": 18.44,
    }
    produce_row(producer, topic, key="PECO", row=row)
    producer.flush(10)

    consumer = make_consumer(BROKER, group_id=f"test-group-{uuid.uuid4().hex[:8]}", topics=[topic])
    try:
        received = None
        for _ in range(20):  # poll up to ~10s total; broker-assigned partitions take a moment
            received = poll_row(consumer, timeout=0.5)
            if received is not None:
                break
        assert received is not None, "no message received within the polling window"
        assert received["zone"] == "PECO"
        assert received["lmp_price"] == 18.44
        assert received["period_start"] == "2026-10-13T19:05:00+00:00"
    finally:
        consumer.close()


def test_poll_row_returns_none_on_timeout_with_no_messages():
    topic = f"test.kafka-integration.{uuid.uuid4().hex[:8]}"
    consumer = make_consumer(BROKER, group_id=f"test-group-{uuid.uuid4().hex[:8]}", topics=[topic])
    try:
        assert poll_row(consumer, timeout=1.0) is None
    finally:
        consumer.close()


def _poll_until(consumer, attempts: int = 20, timeout: float = 0.5):
    for _ in range(attempts):
        row = poll_row(consumer, timeout=timeout)
        if row is not None:
            return row
    return None


def test_uncommitted_offset_redelivers_on_next_consumer_with_same_group():
    """Regression guard for the real correctness fix this session made: enable.auto.commit
    defaults to True in confluent-kafka, which can commit a message's offset on its own
    timer even if the application never finished processing it -- silently losing data on
    a crash between poll and write. make_consumer turns that off; this proves a message
    that's polled but never explicitly committed really does come back."""
    topic = f"test.kafka-integration.{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"

    producer = make_producer(BROKER)
    produce_row(producer, topic, key="k1", row={"n": 1})
    producer.flush(10)

    consumer_a = make_consumer(BROKER, group_id=group, topics=[topic])
    try:
        first = _poll_until(consumer_a)
        assert first == {"n": 1}
        # deliberately NOT committing here -- simulates a crash after poll, before write
    finally:
        consumer_a.close()

    consumer_b = make_consumer(BROKER, group_id=group, topics=[topic])
    try:
        redelivered = _poll_until(consumer_b)
        assert redelivered == {"n": 1}  # same message, same group, came back
    finally:
        consumer_b.close()


def test_committed_offset_is_not_redelivered():
    topic = f"test.kafka-integration.{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"

    producer = make_producer(BROKER)
    produce_row(producer, topic, key="k1", row={"n": 1})
    produce_row(producer, topic, key="k2", row={"n": 2})
    producer.flush(10)

    consumer_a = make_consumer(BROKER, group_id=group, topics=[topic])
    try:
        first = _poll_until(consumer_a)
        assert first == {"n": 1}
        commit_offsets(consumer_a)
    finally:
        consumer_a.close()

    consumer_b = make_consumer(BROKER, group_id=group, topics=[topic])
    try:
        second = _poll_until(consumer_b)
        assert second == {"n": 2}  # not {"n": 1} again -- the commit was honored
    finally:
        consumer_b.close()
