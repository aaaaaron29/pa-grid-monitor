"""Thin client for the EIA API v2 "electricity/rto/region-data" route (EIA-930: hourly
demand, net generation, and total interchange by Balancing Authority).

Architecture.md Section 3 calls out using `gridstatus` for PJM once that poller exists —
that recommendation is about PJM Data Miner specifically; EIA has no such wrapper worth
preferring over a direct, well-tested client this small.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal

import requests

from common.metrics import API_ERRORS_TOTAL

log = logging.getLogger(__name__)

BASE_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
ReadingType = Literal["D", "NG", "TI"]

_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.5


class EiaApiError(RuntimeError):
    pass


def _get_with_retry(params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            API_ERRORS_TOTAL.labels(source="eia", status="exception").inc()
            log.warning(
                "eia request exception, retrying",
                extra={"attempt": attempt, "error": str(exc)},
            )
        else:
            if resp.status_code == 200:
                return resp.json()
            API_ERRORS_TOTAL.labels(source="eia", status=str(resp.status_code)).inc()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = EiaApiError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                log.warning(
                    "eia request failed, retrying",
                    extra={"attempt": attempt, "status": resp.status_code},
                )
            else:
                # 4xx other than 429 won't fix itself on retry (bad key, bad params, etc.)
                raise EiaApiError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
    raise EiaApiError(f"exhausted retries ({_MAX_RETRIES})") from last_exc


def fetch_page(
    *,
    api_key: str,
    reading_type: ReadingType,
    start: datetime,
    end: datetime,
    offset: int = 0,
    length: int = 5000,
    respondent: str = "PJM",
) -> dict[str, Any]:
    """One page of the API's response.data list, plus response.total for pagination."""
    params = {
        "api_key": api_key,
        "frequency": "hourly",
        "data[0]": "value",
        "facets[respondent][]": respondent,
        "facets[type][]": reading_type,
        "start": start.strftime("%Y-%m-%dT%H"),
        "end": end.strftime("%Y-%m-%dT%H"),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "offset": offset,
        "length": min(length, 5000),
    }
    body = _get_with_retry(params)
    if "response" not in body:
        raise EiaApiError(f"unexpected response shape: {list(body.keys())}")
    return body["response"]


def fetch_range(
    *,
    api_key: str,
    reading_type: ReadingType,
    start: datetime,
    end: datetime,
    page_size: int = 5000,
    respondent: str = "PJM",
) -> Iterator[dict[str, Any]]:
    """Yields raw row dicts (API's response.data elements) across the full [start, end)
    range, paginating past the 5,000-row cap automatically."""
    offset = 0
    while True:
        page = fetch_page(
            api_key=api_key,
            reading_type=reading_type,
            start=start,
            end=end,
            offset=offset,
            length=page_size,
            respondent=respondent,
        )
        rows = page.get("data", [])
        if not rows:
            return
        yield from rows
        offset += len(rows)
        total = int(page.get("total", offset))
        if offset >= total:
            return
