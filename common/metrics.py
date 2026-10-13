"""Prometheus instrumentation shared by every ingestion service.

Architecture.md Section 7: "the pipeline must alert on its own death... one Prometheus
alert on ingest staleness is worth more than all the others combined." These are the
metrics that alert is built from — defined once here so every poller reports them the
same way.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, start_http_server

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


def start_metrics_server(port: int) -> None:
    start_http_server(port)
