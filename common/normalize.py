"""Turns raw EIA API v2 response rows into rows shaped for `eia_readings`.

Imported by both the live poller/consumer path and the backfill path (Architecture.md
Section 7: "normalization lives in /common, not in the Kafka consumer" — the
train-sees-what-serve-sees guarantee in Section 6 only holds if both write paths share this
code, not two copies that drift).

This module does NOT impute missing values — a null EIA value becomes quality='missing' and
is stored as-is. Forward-filling short gaps and excluding long ones is a modeling-time
decision (Architecture.md Section 6, "Feature design") made in /model, not an ingest-time one;
the ingest layer's job is to record what actually happened, including the gaps.

Confirmed live (2026-10-13): EIA mostly represents "not yet published" by OMITTING the row
entirely, not by sending value=null — in a 48h pull, type D (demand) had all 48 rows, but NG
and TI (generation mix, interchange) only had 34, because they lag demand's publication. The
quality='missing' path here handles an explicit null when EIA does send one; detecting an
omitted hour requires comparing the expected period sequence against what's actually in
eia_readings (a gap in the data, not a flagged row) — that comparison belongs in /model
alongside the rest of the missing-data policy, not here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

# Confirmed 2026-10-13 via scripts/smoke_test_eia.py against the live API: a request made
# at 18:36 UTC returned "2026-10-13T12" as its most recent non-null row (dateFormat in the
# response: YYYY-MM-DD"T"HH24, i.e. no offset) — a 6.6h lag, consistent with EIA-930's
# documented near-real-time publication delay. Eastern Time would imply an atypically fast
# ~2.6h lag instead, so UTC is both the documented convention and the better fit here.
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
