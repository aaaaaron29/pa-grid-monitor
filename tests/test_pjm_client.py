from __future__ import annotations

import json as json_mod
from datetime import UTC, datetime

import pytest
import responses

from ingestion.pjm_poller.client import (
    BASE_URL,
    PjmApiError,
    fetch_page,
    fetch_range,
    fetch_range_for_date,
)

FEED = "rt_unverified_fivemin_lmps"
FEED_URL = f"{BASE_URL}/{FEED}"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch, tmp_path):
    """The client paces real PJM requests at least 11s apart to stay under the 6/min rate
    limit (ingestion.pjm_poller.client._throttle) — without this, every test in this file
    would actually sleep, since _last_request_at is a module-level global shared across the
    whole test run. Reset it and no-op the sleep so tests stay fast and independent. The
    cross-process pacing files are also redirected into tmp_path, so tests never read or
    write the files a live poller on the same machine is using."""
    import ingestion.pjm_poller.client as client_module

    monkeypatch.setattr(client_module, "_THROTTLE_BASE", str(tmp_path / "pjm_throttle"))
    monkeypatch.setattr(client_module, "_last_request_at", 0.0)
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)


@responses.activate
def test_fetch_page_returns_items_and_total(load_fixture):
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1.json"), status=200
    )

    page = fetch_page(
        api_key="k", feed=FEED, datetime_filter="5minutesago", pnode_ids=[51297]
    )

    assert page["totalRows"] == 2
    assert len(page["items"]) == 2


@responses.activate
def test_fetch_page_sends_post_with_json_body_not_get_querystring(load_fixture):
    """Regression guard: a GET with a `filters` querystring was tried first and consistently
    rejected by the live API ("A datetime is missing") — the fix was switching to POST with
    a JSON body. Pin the request method here so nobody "simplifies" this back to GET."""
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1.json"), status=200
    )

    fetch_page(api_key="k", feed=FEED, datetime_filter="5minutesago")

    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "POST"
    body = json_mod.loads(responses.calls[0].request.body)
    assert body["filters"] == [{"datetime_beginning_ept": "5minutesago"}]


@responses.activate
def test_fetch_page_rejects_multiple_pnode_ids():
    with pytest.raises(ValueError):
        fetch_page(
            api_key="k",
            feed=FEED,
            datetime_filter="5minutesago",
            pnode_ids=[51297, 51299],
        )


@responses.activate
def test_fetch_page_sends_zone_filter_for_the_load_feed(load_fixture):
    """hrl_load_metered filters server-side by a `zone` text field, confirmed live
    2026-10-14 -- a completely different mechanism from the LMP feeds' pnode_id, so it gets
    its own body shape, not a reuse of the pnode_ids path."""
    load_url = f"{BASE_URL}/hrl_load_metered"
    responses.add(
        responses.POST, load_url, json=load_fixture("pjm_response_page1.json"), status=200
    )

    fetch_page(api_key="k", feed="hrl_load_metered", datetime_filter="lastweek", zone="PL")

    body = json_mod.loads(responses.calls[0].request.body)
    assert {"zone": "PL"} in body["filters"]
    assert not any("pnode_id" in f for f in body["filters"])


@responses.activate
def test_fetch_range_paginates_across_pages(load_fixture):
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1_of2.json"), status=200
    )
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page2_of2.json"), status=200
    )

    rows = list(
        fetch_range(api_key="k", feed=FEED, datetime_filter="today", row_count=5)
    )

    assert len(rows) == 7
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_range_stops_when_items_empty():
    responses.add(responses.POST, FEED_URL, json={"items": [], "totalRows": 0}, status=200)

    rows = list(fetch_range(api_key="k", feed=FEED, datetime_filter="today"))

    assert rows == []
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_range_for_date_filters_on_utc_field(load_fixture):
    """Regression guard: using the EPT field with UTC timestamps would silently misalign
    results by the EPT/UTC offset — confirmed live that datetime_beginning_utc accepts the
    same range syntax, so fetch_range_for_date must use it, not the EPT field."""
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1.json"), status=200
    )

    start = datetime(2026, 10, 13, 19, 0, tzinfo=UTC)
    end = datetime(2026, 10, 13, 19, 5, tzinfo=UTC)
    list(fetch_range_for_date(api_key="k", feed=FEED, start=start, end=end))

    body = json_mod.loads(responses.calls[0].request.body)
    (filter_entry,) = [f for f in body["filters"] if "datetime_beginning_utc" in f]
    assert filter_entry["datetime_beginning_utc"] == "2026-10-13T19:00 to 2026-10-13T19:05"


@responses.activate
def test_raises_immediately_on_non_retryable_4xx(monkeypatch):
    monkeypatch.setattr("ingestion.pjm_poller.client.time.sleep", lambda _: None)
    responses.add(
        responses.POST,
        FEED_URL,
        json={"errors": [{"message": "A datetime is missing"}]},
        status=400,
    )

    with pytest.raises(PjmApiError):
        fetch_page(api_key="bad", feed=FEED, datetime_filter="5minutesago")

    assert len(responses.calls) == 1


@responses.activate
def test_retries_on_429_then_succeeds(load_fixture, monkeypatch):
    monkeypatch.setattr("ingestion.pjm_poller.client.time.sleep", lambda _: None)
    responses.add(responses.POST, FEED_URL, status=429)
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1.json"), status=200
    )

    page = fetch_page(api_key="k", feed=FEED, datetime_filter="5minutesago")

    assert page["totalRows"] == 2
    assert len(responses.calls) == 2


@responses.activate
def test_use_custom_sort_false_omits_sort_and_order_from_body(load_fixture):
    """Regression guard: confirmed live that PJM's archived data (anything past
    archiveCutoffDays) rejects a request carrying a custom sort/order with HTTP 400
    ("invalid attribute(s) for archived data") — the fix is to omit those keys entirely,
    not send some "default" value, when querying a range that might be archived."""
    responses.add(
        responses.POST, FEED_URL, json=load_fixture("pjm_response_page1.json"), status=200
    )

    fetch_page(
        api_key="k",
        feed=FEED,
        datetime_filter="2024-01-01T00:00 to 2024-01-01T01:00",
        use_custom_sort=False,
    )

    body = json_mod.loads(responses.calls[0].request.body)
    assert "sort" not in body
    assert "order" not in body


@responses.activate
def test_use_custom_sort_true_is_still_the_default():
    responses.add(responses.POST, FEED_URL, json={"items": [], "totalRows": 0}, status=200)

    fetch_page(api_key="k", feed=FEED, datetime_filter="5minutesago")

    body = json_mod.loads(responses.calls[0].request.body)
    assert body["sort"] == "datetime_beginning_ept"
    assert body["order"] == 1


def test_throttle_waits_for_a_request_made_by_another_process(monkeypatch):
    """The rate limit is per API key, so a request recorded by a different process must delay
    this one even though this process's own in-memory clock says it is free to go. Simulated
    by having the shared file say a request happened just now while _last_request_at is 0."""
    import time as real_time

    import ingestion.pjm_poller.client as client_module

    client_module._write_shared_last_request(real_time.time())
    monkeypatch.setattr(client_module, "_last_request_at", 0.0)
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda s: slept.append(s))

    client_module._throttle()

    assert len(slept) == 1
    assert 10.0 < slept[0] <= client_module._MIN_SECONDS_BETWEEN_REQUESTS


def test_throttle_ignores_a_last_request_time_in_the_future(monkeypatch):
    """If the clock moved backwards, a stored timestamp ahead of 'now' must not stall the
    poller for however long that gap happens to be."""
    import time as real_time

    import ingestion.pjm_poller.client as client_module

    client_module._write_shared_last_request(real_time.time() + 3600)
    monkeypatch.setattr(client_module, "_last_request_at", 0.0)
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda s: slept.append(s))

    client_module._throttle()

    assert all(s <= client_module._MIN_SECONDS_BETWEEN_REQUESTS for s in slept)


def test_two_real_processes_share_one_request_clock(tmp_path):
    """The behaviour the fix exists for: two separate Python processes each calling the
    throttle must never get closer together than the minimum interval, taken together."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import sys, time
        import ingestion.pjm_poller.client as c
        c._MIN_SECONDS_BETWEEN_REQUESTS = 0.6
        stamps = []
        for _ in range(3):
            c._throttle()
            stamps.append(time.time())
        print(",".join(repr(s) for s in stamps))
        """
    )
    env = {**__import__("os").environ, "PJM_THROTTLE_FILE": str(tmp_path / "shared")}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, env=env
        )
        for _ in range(2)
    ]
    stamps: list[float] = []
    for p in procs:
        out, _ = p.communicate(timeout=60)
        assert p.returncode == 0
        stamps += [float(x) for x in out.strip().split(",")]

    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert len(stamps) == 6
    # The stamps are taken after _throttle() returns, so a busy CI runner can delay one by tens
    # of milliseconds and shrink the measured gap (seen: 0.31 against a 0.4 interval). Allow a
    # third of the interval; unshared clocks would give a gap near zero.
    assert min(gaps) >= 0.4, gaps
