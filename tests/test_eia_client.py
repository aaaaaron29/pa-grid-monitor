from __future__ import annotations

from datetime import UTC, datetime

import pytest
import responses

from ingestion.eia_poller.client import BASE_URL, EiaApiError, fetch_page, fetch_range

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 2, tzinfo=UTC)


@responses.activate
def test_fetch_page_returns_response_section(load_fixture):
    responses.add(responses.GET, BASE_URL, json=load_fixture("eia_response_page1.json"), status=200)

    page = fetch_page(api_key="k", reading_type="D", start=START, end=END)

    assert page["total"] == "3"
    assert len(page["data"]) == 3


@responses.activate
def test_fetch_range_paginates_across_pages(load_fixture):
    responses.add(
        responses.GET, BASE_URL, json=load_fixture("eia_response_page1_of2.json"), status=200
    )
    responses.add(
        responses.GET, BASE_URL, json=load_fixture("eia_response_page2_of2.json"), status=200
    )

    rows = list(fetch_range(api_key="k", reading_type="D", start=START, end=END, page_size=5))

    assert len(rows) == 7
    assert len(responses.calls) == 2
    # second request's offset should advance past the first page
    assert "offset=5" in responses.calls[1].request.url


@responses.activate
def test_fetch_range_stops_when_data_empty():
    responses.add(
        responses.GET,
        BASE_URL,
        json={"response": {"total": "0", "data": []}},
        status=200,
    )

    rows = list(fetch_range(api_key="k", reading_type="D", start=START, end=END))

    assert rows == []
    assert len(responses.calls) == 1


@responses.activate
def test_retries_on_500_then_succeeds(load_fixture, monkeypatch):
    monkeypatch.setattr("ingestion.eia_poller.client.time.sleep", lambda _: None)
    responses.add(responses.GET, BASE_URL, status=500)
    responses.add(responses.GET, BASE_URL, json=load_fixture("eia_response_page1.json"), status=200)

    page = fetch_page(api_key="k", reading_type="D", start=START, end=END)

    assert page["total"] == "3"
    assert len(responses.calls) == 2


@responses.activate
def test_raises_immediately_on_non_retryable_4xx(monkeypatch):
    monkeypatch.setattr("ingestion.eia_poller.client.time.sleep", lambda _: None)
    responses.add(responses.GET, BASE_URL, json={"error": {"code": "API_KEY_MISSING"}}, status=403)

    with pytest.raises(EiaApiError):
        fetch_page(api_key="", reading_type="D", start=START, end=END)

    assert len(responses.calls) == 1  # no retry burned on a non-retryable error


@responses.activate
def test_raises_after_exhausting_retries_on_persistent_500(monkeypatch):
    monkeypatch.setattr("ingestion.eia_poller.client.time.sleep", lambda _: None)
    responses.add(responses.GET, BASE_URL, status=500)
    responses.add(responses.GET, BASE_URL, status=500)
    responses.add(responses.GET, BASE_URL, status=500)
    responses.add(responses.GET, BASE_URL, status=500)

    with pytest.raises(EiaApiError):
        fetch_page(api_key="k", reading_type="D", start=START, end=END)

    assert len(responses.calls) == 4
