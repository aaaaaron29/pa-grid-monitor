"""Turns raw PJM Data Miner 2 API rows into rows shaped for `pjm_lmp_readings`.

Imported by both the live poller/consumer path and the backfill path, same reasoning as
common/normalize.py for EIA: train-time and serve-time data must be identical in shape.

Confirmed live (2026-10-13) against api.pjm.com. Two feeds write through this module:
  - rt_unverified_fivemin_lmps (live poller): posts every 5 min, verified=False
  - rt_fivemin_hrl_lmps (backfill / verified refresh): posts daily, verified=True
Both return rows shaped the same way for our purposes: datetime_beginning_utc, pnode_id,
total_lmp_rt. zone -> pnode_id mapping is fixed (Architecture.md Section 3):
  PECO 51297, PPL 51299, METED 51296, PENELEC 51300, DUQ 37737283.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

ZONE_PNODE_IDS: dict[str, int] = {
    "PECO": 51297,
    "PPL": 51299,
    "METED": 51296,
    "PENELEC": 51300,
    "DUQ": 37737283,
}
PNODE_ID_TO_ZONE: dict[int, str] = {v: k for k, v in ZONE_PNODE_IDS.items()}

# PJM's datetime_beginning_utc comes back as "2026-10-13T19:05:00" (no offset, confirmed
# via the live rt_unverified_fivemin_lmps response) — already UTC, no EPT conversion needed
# (Architecture.md Section 3: "UTC is native, not derived").
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S"


class NormalizedPjmRow(TypedDict):
    zone: str
    period_start: datetime
    lmp_price: float | None
    quality: str
    verified: bool
    retrieved_at: datetime


def parse_pjm_utc(value: str) -> datetime:
    return datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=UTC)


def normalize_pjm_row(
    raw: dict[str, Any], *, verified: bool, retrieved_at: datetime | None = None
) -> NormalizedPjmRow | None:
    """`raw` is one element of a Data Miner 2 response's `items` list. Returns None for rows
    whose pnode_id isn't one of our five tracked PA zones (the feed returns thousands of
    other bus/hub/aggregate rows per interval) — callers should filter out None results."""
    pnode_id = raw.get("pnode_id")
    zone = PNODE_ID_TO_ZONE.get(int(pnode_id)) if pnode_id is not None else None
    if zone is None:
        return None

    value = raw.get("total_lmp_rt")
    lmp_price = float(value) if value not in (None, "") else None
    return NormalizedPjmRow(
        zone=zone,
        period_start=parse_pjm_utc(raw["datetime_beginning_utc"]),
        lmp_price=lmp_price,
        quality="ok" if lmp_price is not None else "missing",
        verified=verified,
        retrieved_at=retrieved_at or datetime.now(UTC),
    )


def normalize_pjm_rows(
    raw_rows: list[dict[str, Any]], *, verified: bool, retrieved_at: datetime | None = None
) -> list[NormalizedPjmRow]:
    ts = retrieved_at or datetime.now(UTC)
    out = []
    for row in raw_rows:
        normalized = normalize_pjm_row(row, verified=verified, retrieved_at=ts)
        if normalized is not None:
            out.append(normalized)
    return out
