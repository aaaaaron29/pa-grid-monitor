"""The synthetic scenario the CI replay test pushes through the full stack.

Nothing here is PJM data. It is a made-up 5-minute price series for one zone, built so the
right answer is known in advance: a smooth daily cycle plus bounded noise, with two price
spikes and one stuck-sensor stretch planted at known intervals, and one stretch of intervals
that never arrive (a feed outage).

The series is a pure function of the interval index, so the model artifact the test loads can
be fitted on exactly the same clean values (scripts/replay/make_artifact.py) and the replay
driver can regenerate them without sharing any files. Standard library only, because the
driver runs in the slim ingestion image.

Timeline, in 5-minute intervals counted from T0:

    [0, HISTORY)                  loaded straight into Postgres, as a backfill would
    [HISTORY, HISTORY + LIVE)     published to Kafka one interval at a time

Planted events (offsets are intervals from the start of the live window):

    spike up      one interval, +SPIKE_UP
    spike down    one interval, -SPIKE_DOWN
    flatline      FLAT_LEN intervals pinned at one value
    outage        OUTAGE_LEN intervals never published, late in the window
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ZONE = "PPL"
T0 = datetime(2026, 1, 5, tzinfo=UTC)  # a Monday, so the weekly lag lines up with weekdays
PERIOD = timedelta(minutes=5)
PER_DAY = 288

LAG = 7 * PER_DAY  # seasonal-naive lag, same as the real PJM artifacts
ROLLING_WINDOW = 12
HISTORY = LAG  # exactly enough history for the first live interval to have a forecast
LIVE_HOURS = 48
LIVE = LIVE_HOURS * 12

BASE_LEVEL = 100.0
DAILY_SWING = 20.0
NOISE = 3.0  # uniform, so bounded: residuals never exceed 2 * NOISE
SEED = 20260105

SPIKE_UP = 80.0
SPIKE_DOWN = 70.0
FLAT_LEN = 36

# Offsets into the live window, in intervals.
SPIKE_UP_AT = 6 * 12
SPIKE_DOWN_AT = 14 * 12
FLAT_AT = 22 * 12
OUTAGE_AT = 36 * 12
OUTAGE_LEN = 42  # 3.5 hours, longer than the 3-interval forward fill

def when(i: int) -> datetime:
    return T0 + i * PERIOD


def clean_value(i: int) -> float:
    """The event-free price at interval i. Defined for negative i too, so training can use
    more history than the scenario replays."""
    phase = (i % PER_DAY) / PER_DAY
    noise = random.Random(SEED * 1_000_003 + i).uniform(-NOISE, NOISE)
    return round(BASE_LEVEL + DAILY_SWING * math.sin(2 * math.pi * phase) + noise, 4)


@dataclass(frozen=True)
class Event:
    name: str
    start: int  # absolute interval index
    length: int
    expect: str  # the detector that must flag it: "forest" | "flatline"


LIVE_START = HISTORY
EVENTS = (
    Event("spike up", LIVE_START + SPIKE_UP_AT, 1, "forest"),
    Event("spike down", LIVE_START + SPIKE_DOWN_AT, 1, "forest"),
    Event("flatline", LIVE_START + FLAT_AT, FLAT_LEN, "flatline"),
)
OUTAGE = range(LIVE_START + OUTAGE_AT, LIVE_START + OUTAGE_AT + OUTAGE_LEN)


def value(i: int) -> float:
    """The price at interval i with the planted events applied."""
    if i == EVENTS[0].start:
        return round(clean_value(i) + SPIKE_UP, 4)
    if i == EVENTS[1].start:
        return round(clean_value(i) - SPIKE_DOWN, 4)
    flat = EVENTS[2]
    if flat.start <= i < flat.start + flat.length:
        return clean_value(flat.start)  # stuck at the first value of the stretch
    return clean_value(i)


def live_indices() -> list[int]:
    """Intervals published to Kafka, in order; the outage is simply absent."""
    return [i for i in range(LIVE_START, LIVE_START + LIVE) if i not in OUTAGE]


def row(i: int, retrieved_at: datetime, *, verified: bool) -> dict:
    """One normalized pjm_lmp_readings row, the shape common.normalize_pjm produces."""
    return {
        "zone": ZONE,
        "period_start": when(i),
        "lmp_price": value(i),
        "quality": "ok",
        "verified": verified,
        "retrieved_at": retrieved_at,
    }


# What the real detector does with this scenario, measured offline by
# tests/test_replay_scenario.py (which fails if these drift) and then required of the whole
# stack by the replay driver. Absolute interval indices.
EXPECTED_FOREST = frozenset({EVENTS[0].start, EVENTS[1].start})
# The stuck-sensor rule looks at a run of rows whose rolling spread is at or below the floor.
# That spread first drops to the floor 10 rows into the flat stretch, and live scoring only
# sees the run so far, so it fires once the run is a full rolling window long.
EXPECTED_FLATLINE = frozenset(
    range(EVENTS[2].start + 10 + ROLLING_WINDOW - 1, EVENTS[2].start + FLAT_LEN)
)
# A hole leaves the next ROLLING_WINDOW intervals without a complete recent window, so they
# come back unscored instead of scored on partial context.
EXPECTED_DECLINED = frozenset(range(OUTAGE.stop, OUTAGE.stop + ROLLING_WINDOW))
