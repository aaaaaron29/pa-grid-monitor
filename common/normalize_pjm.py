"""Turns raw PJM Data Miner 2 API rows into rows shaped for `pjm_lmp_readings` and
`pjm_load_readings`.

Imported by both the live poller/consumer path and the backfill path, same reasoning as
common/normalize.py for EIA: train-time and serve-time data must be identical in shape.

Confirmed live (2026-10-13) against api.pjm.com. Two LMP feeds write through the
normalize_pjm_row(s) functions:
  - rt_unverified_fivemin_lmps (live poller): posts every 5 min, verified=False
  - rt_fivemin_hrl_lmps (backfill / verified refresh): posts daily, verified=True
Both return rows shaped the same way for our purposes: datetime_beginning_utc, pnode_id,
total_lmp_rt. zone -> pnode_id mapping is fixed (Architecture.md Section 3):
  PECO 51297, PPL 51299, METED 51296, PENELEC 51300, DUQ 37737283.

A third feed, hrl_load_metered (real zone-level metered demand), confirmed live
2026-10-14, writes through normalize_pjm_load_rows -- see that function's docstring for why
it needs its own zone-code mapping and its own summing logic, not a reuse of the above.
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


# hrl_load_metered: real zone-level metered demand, confirmed live 2026-10-14. A completely
# different zone-identification scheme from the LMP feed's pnode_id -- this feed filters and
# reports by a `zone` text field with its own codes, not the pnode-based ones above. PPL
# ("PL") further splits into two load_area components, PLCO (the bulk of it) and UGI (a much
# smaller utility PPL's zone also covers for load-metering purposes), which must be summed
# to get one PPL total -- confirmed live by comparing their actual MW values side by side.
ZONE_LOAD_CODES: dict[str, str] = {
    "PECO": "PE",
    "PPL": "PL",
    "METED": "ME",
    "PENELEC": "PN",
    "DUQ": "DUQ",
}
LOAD_CODE_TO_ZONE: dict[str, str] = {v: k for k, v in ZONE_LOAD_CODES.items()}


class NormalizedPjmLoadRow(TypedDict):
    zone: str
    period_start: datetime
    load_mw: float | None
    quality: str
    verified: bool
    retrieved_at: datetime


def normalize_pjm_load_rows(
    raw_rows: list[dict[str, Any]], *, retrieved_at: datetime | None = None
) -> list[NormalizedPjmLoadRow]:
    """`raw_rows` is a Data Miner 2 hrl_load_metered response's `items` list, already
    filtered server-side to one zone code (see ingestion/pjm_load_poller). Sums every
    load_area row for a given (zone, period_start) into one total -- the raw per-load_area
    breakdown isn't kept, matching pjm_lmp_readings' one-row-per-zone-per-interval shape.
    `is_verified` is a real per-row field on this feed (unlike LMP, where verification comes
    from which feed was called, not a response field); a summed group only counts as
    verified once every row that went into it is."""
    ts = retrieved_at or datetime.now(UTC)
    groups: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    for row in raw_rows:
        code = row.get("zone")
        zone = LOAD_CODE_TO_ZONE.get(code) if code is not None else None
        if zone is None:
            continue
        period_start = parse_pjm_utc(row["datetime_beginning_utc"])
        groups.setdefault((zone, period_start), []).append(row)

    out = []
    for (zone, period_start), rows in groups.items():
        values = [r.get("mw") for r in rows]
        if any(v in (None, "") for v in values):
            load_mw = None
        else:
            load_mw = sum(float(v) for v in values)
        out.append(
            NormalizedPjmLoadRow(
                zone=zone,
                period_start=period_start,
                load_mw=load_mw,
                quality="ok" if load_mw is not None else "missing",
                verified=all(bool(r.get("is_verified")) for r in rows),
                retrieved_at=ts,
            )
        )
    return out
