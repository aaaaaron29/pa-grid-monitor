"""Turns raw EIA API v2 response rows into rows shaped for `eia_readings`.

Imported by both the live poller/consumer path and the backfill path (Architecture.md
Section 7: "normalization lives in /common, not in the Kafka consumer" — the
train-sees-what-serve-sees guarantee in Section 6 only holds if both write paths share this
code, not two copies that drift).

This module does NOT impute missing values — a null EIA value becomes quality='missing' and
is stored as-is. Forward-filling short gaps and excluding long ones is a modeling-time
decision (Architecture.md Section 6, "Feature design") made in /model, not an ingest-time one;
the ingest layer's job is to record what actually happened, including the gaps.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

# EIA API v2's documented hourly period format is "YYYY-MM-DDTHH" (no offset). EIA-930 hourly
# series are published in UTC. TODO(verify): confirm both the literal format and the UTC
# assumption against a live response's "response.dateFormat" field — run
# scripts/smoke_test_eia.py once EIA_API_KEY is loaded, before trusting this past Phase 1.
_PERIOD_FORMAT = "%Y-%m-%dT%H"


class NormalizedEiaRow(TypedDict):
    respondent: str
    reading_type: str
    period_start: datetime
    value_mw: float | None
    quality: str
    retrieved_at: datetime


def parse_period(period: str) -> datetime:
    """Parse an EIA API v2 'period' string into a UTC-aware, hour-beginning datetime."""
    return datetime.strptime(period, _PERIOD_FORMAT).replace(tzinfo=UTC)


def normalize_eia_row(
    raw: dict[str, Any], retrieved_at: datetime | None = None
) -> NormalizedEiaRow:
    """`raw` is one element of the API's response.data list, e.g.:
    {"period": "2019-01-01T00", "respondent": "PJM", "type": "D", "value": "87654", ...}
    """
    value = raw.get("value")
    value_mw = float(value) if value not in (None, "") else None
    return NormalizedEiaRow(
        respondent=raw["respondent"],
        reading_type=raw["type"],
        period_start=parse_period(raw["period"]),
        value_mw=value_mw,
        quality="ok" if value_mw is not None else "missing",
        retrieved_at=retrieved_at or datetime.now(UTC),
    )


def normalize_eia_rows(
    raw_rows: list[dict[str, Any]], retrieved_at: datetime | None = None
) -> list[NormalizedEiaRow]:
    ts = retrieved_at or datetime.now(UTC)
    return [normalize_eia_row(row, retrieved_at=ts) for row in raw_rows]
