"""Prometheus instrumentation shared by every ingestion and inference service.

Architecture.md Section 7: "the pipeline must alert on its own death — one Prometheus
alert on ingest staleness is worth more than all the others combined." These are the
metrics that alert is built from, defined once here so every poller and inference service
reports them the same way.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

LAST_SUCCESSFUL_INGEST_TS = Gauge(
    "ingest_last_success_timestamp_seconds",
    "Unix time of the last successful ingest cycle, per source. "
    "staleness = time() - this; alert when staleness exceeds a few poll intervals.",
    ["source"],
)

INGEST_RUNS_TOTAL = Counter(
    "ingest_runs_total",
    "Ingest cycles attempted, per source and outcome.",
    ["source", "outcome"],  # outcome: success | error
)

API_ERRORS_TOTAL = Counter(
    "upstream_api_errors_total",
    "Upstream API errors, per source and HTTP status (or 'exception').",
    ["source", "status"],
)

ROWS_WRITTEN_TOTAL = Counter(
    "rows_written_total",
    "Rows upserted into Postgres, per source and table.",
    ["source", "table"],
)

LAST_SUCCESSFUL_SCORE_TS = Gauge(
    "score_last_success_timestamp_seconds",
    "Unix time of the last successful scoring write, per tier. Same staleness-alert pattern "
    "as LAST_SUCCESSFUL_INGEST_TS, for the inference side of the pipeline.",
    ["tier"],
)

SCORING_RUNS_TOTAL = Counter(
    "scoring_runs_total",
    "Kafka messages the inference services attempted to score, per tier and outcome.",
    ["tier", "outcome"],  # outcome: scored | skipped | error
)

ANOMALIES_FLAGGED_TOTAL = Counter(
    "anomalies_flagged_total",
    "Anomalies flagged, per tier, zone ('none' for EIA, which has no zones), and detector.",
    ["tier", "zone", "detector"],  # detector: forest | flatline
)

SCORING_LATENCY_SECONDS = Histogram(
    "scoring_latency_seconds",
    "Time to score one message: history load + feature build + detector score + DB write.",
    ["tier"],
)


def start_metrics_server(port: int) -> None:
    start_http_server(port)
