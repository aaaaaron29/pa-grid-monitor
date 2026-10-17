"""Replay the synthetic scenario through the running stack and assert on what comes out.

Runs inside the cluster (infra/ci/replay-job.yaml), where it can reach Kafka, Postgres and the
inference service by name. Needs the PJM consumer and the PJM inference service already up,
with the replay artifact on the inference service's volume (scripts/replay/make_artifact.py).

What it does, in order:
  1. Loads the first week into Postgres directly, the way a backfill would.
  2. Publishes the next 48 hours to Kafka one interval at a time, skipping the outage. It waits
     for each interval to land in Postgres before sending the next, because the inference
     service reads its history back from there (a real poller is five minutes apart, so the
     race cannot happen live; a replay has to respect it).
  3. Waits for the inference service to work through every message.
  4. Re-publishes a block of intervals it already sent.
  5. Checks the result against the answer the scenario was built to have.

Exit status is 0 only if every check passes. Every check prints, pass or fail, so a red run
shows how far the data got.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime

import psycopg
import requests

from common.config import get_settings
from common.db import connect, upsert_pjm_lmp_readings
from common.kafka import TOPIC_PJM_RAW, make_producer, produce_row
from scripts.replay import data

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://pjm-inference")
HEALTH = f"{INFERENCE_URL}:8000/health"
METRICS = f"{INFERENCE_URL}:9100/metrics"

READY_TIMEOUT = 240
ROW_TIMEOUT = 60
# The first row can take far longer than the rest. CI restarts the consumer just before this
# runs (to shorten its batch wait), and a consumer that is killed rather than shut down leaves
# its partition assigned to it until the group's session timeout (45 seconds by default), so the
# replacement reads nothing until then.
FIRST_ROW_TIMEOUT = 240
DRAIN_TIMEOUT = 300
DUPLICATES = 24

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


def wait_until(predicate, timeout: float, what: str, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout:.0f}s waiting for {what}")


def inference_ready() -> bool:
    try:
        body = requests.get(HEALTH, timeout=5).json()
    except (requests.RequestException, ValueError):
        return False
    return bool(body.get("model_loaded") and body.get("consumer_alive"))


def counter(text: str, name: str, **labels: str) -> float:
    """Value of one Prometheus counter series from the text exposition, 0 if absent."""
    for line in text.splitlines():
        if not line.startswith(f"{name}{{"):
            continue
        if all(f'{k}="{v}"' in line for k, v in labels.items()):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def runs(text: str, outcome: str) -> float:
    return counter(text, "scoring_runs_total", tier="pjm", outcome=outcome)


def flags(text: str, detector: str) -> float:
    return counter(
        text, "anomalies_flagged_total", tier="pjm", zone=data.ZONE, detector=detector
    )


def metrics_text() -> str:
    return requests.get(METRICS, timeout=10).text


def index_of(ts: datetime) -> int:
    return round((ts - data.T0).total_seconds() / 300)


def fetch_readings(conn: psycopg.Connection) -> dict[int, float]:
    rows = conn.execute(
        "SELECT period_start, lmp_price FROM pjm_lmp_readings WHERE zone = %s", (data.ZONE,)
    ).fetchall()
    return {index_of(ts): price for ts, price in rows}


def fetch_scores(conn: psycopg.Connection) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT period_start, residual, forest_flagged, flatline_flagged "
        "FROM pjm_lmp_anomalies WHERE zone = %s",
        (data.ZONE,),
    ).fetchall()
    return {
        index_of(ts): {"residual": res, "forest": forest, "flatline": flat}
        for ts, res, forest, flat in rows
    }


def publish(producer, indices: list[int], conn: psycopg.Connection, *, pace: bool) -> None:
    for n, i in enumerate(indices):
        row = data.row(i, datetime.now(UTC), verified=False)
        key = f"{data.ZONE}:{row['period_start'].isoformat()}"
        produce_row(producer, TOPIC_PJM_RAW, key=key, row=row)
        producer.flush(30)
        if pace:
            wait_until(
                lambda i=i: conn.execute(
                    "SELECT 1 FROM pjm_lmp_readings WHERE zone = %s AND period_start = %s",
                    (data.ZONE, data.when(i)),
                ).fetchone(),
                FIRST_ROW_TIMEOUT if n == 0 else ROW_TIMEOUT,
                f"interval {i - data.LIVE_START} to reach Postgres",
            )


def offsets(indices) -> str:
    """Interval indices as offsets into the live window, for readable failure messages."""
    shown = sorted(i - data.LIVE_START for i in indices)
    return str(shown[:20]) + (" ..." if len(shown) > 20 else "")


def main() -> int:
    settings = get_settings()
    started = time.monotonic()
    print(
        f"replay: {data.HISTORY} intervals of history, {data.LIVE_HOURS}h live "
        f"({len(data.live_indices())} published, {len(data.OUTAGE)} withheld as an outage)",
        flush=True,
    )

    wait_until(inference_ready, READY_TIMEOUT, "the inference service to be ready", interval=2)

    now = datetime.now(UTC)
    with connect(settings.postgres_dsn) as conn:
        history = [data.row(i, now, verified=True) for i in range(data.HISTORY)]
        upsert_pjm_lmp_readings(conn, history)

    published = data.live_indices()
    producer = make_producer(settings.kafka_bootstrap_servers)
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        publish(producer, published, conn, pace=True)
        took = time.monotonic() - started
        print(f"published {len(published)} intervals in {took:.0f}s", flush=True)

        def drained() -> bool:
            text = metrics_text()
            return runs(text, "scored") + runs(text, "skipped") >= len(published)

        wait_until(drained, DRAIN_TIMEOUT, "the inference service to score every message", 1.0)
        text = metrics_text()

        readings = fetch_readings(conn)
        scores = fetch_scores(conn)

        # --- ingest ---------------------------------------------------------------------
        live_rows = {i: v for i, v in readings.items() if i >= data.LIVE_START}
        check(
            "every published interval reached Postgres",
            set(live_rows) == set(published),
            f"{len(live_rows)} stored, {len(published)} published",
        )
        wrong = [i for i, v in live_rows.items() if v != data.value(i)]
        check("stored prices equal the published prices", not wrong, f"{len(wrong)} differ")
        check(
            "the withheld outage left a hole, with nothing invented to fill it",
            not (set(readings) & set(data.OUTAGE)),
        )
        other = conn.execute(
            "SELECT count(*) FROM pjm_lmp_readings WHERE zone <> %s", (data.ZONE,)
        ).fetchone()[0]
        check("no other zone received any rows", other == 0, f"{other} rows")

        # --- scoring --------------------------------------------------------------------
        live_scores = {i: s for i, s in scores.items() if i >= data.LIVE_START}
        scored = set(live_scores)
        declined = set(published) - scored
        check(
            "exactly the intervals after the outage were declined, every other one scored",
            declined == data.EXPECTED_DECLINED,
            f"declined {offsets(declined)}, expected {offsets(data.EXPECTED_DECLINED)}",
        )
        forest = {i for i, s in live_scores.items() if s["forest"]}
        check(
            "the isolation forest flagged the two planted spikes and nothing else",
            forest == data.EXPECTED_FOREST,
            f"flagged {offsets(forest)}, expected {offsets(data.EXPECTED_FOREST)}",
        )
        flatline = {i for i, s in live_scores.items() if s["flatline"]}
        check(
            "the stuck-sensor rule flagged the flat stretch and nothing else",
            flatline == data.EXPECTED_FLATLINE,
            f"flagged {offsets(flatline)}, expected {offsets(data.EXPECTED_FLATLINE)}",
        )

        # --- the service's own counters agree with the database -----------------------------
        check(
            "scoring_runs_total matches the rows written",
            runs(text, "scored") == len(scored) and runs(text, "skipped") == len(declined),
            f"scored {runs(text, 'scored'):.0f}/{len(scored)}, "
            f"skipped {runs(text, 'skipped'):.0f}/{len(declined)}",
        )
        check(
            "anomalies_flagged_total matches the flags written",
            flags(text, "forest") == len(forest) and flags(text, "flatline") == len(flatline),
            f"forest {flags(text, 'forest'):.0f}/{len(forest)}, "
            f"flatline {flags(text, 'flatline'):.0f}/{len(flatline)}",
        )

        # --- replaying the same messages again changes nothing --------------------------------
        before_readings, before_scores = dict(readings), dict(scores)
        again = [i for i in published if i not in data.EXPECTED_DECLINED][:DUPLICATES]
        publish(producer, again, conn, pace=False)
        time.sleep(15)  # nothing new to wait for: let the consumer and scorer take them
        check(
            "re-publishing a block of intervals changed no stored price",
            fetch_readings(conn) == before_readings,
        )
        after_scores = fetch_scores(conn)
        check(
            "and changed no score or flag",
            {i: (s["residual"], s["forest"], s["flatline"]) for i, s in after_scores.items()}
            == {i: (s["residual"], s["forest"], s["flatline"]) for i, s in before_scores.items()},
        )

    failed = [name for name, ok, _ in results if not ok]
    print(
        f"\n{len(results) - len(failed)} of {len(results)} checks passed "
        f"in {time.monotonic() - started:.0f}s",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TimeoutError as exc:
        print(f"FAIL  {exc}", flush=True)
        sys.exit(1)
