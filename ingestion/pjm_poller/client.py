"""Thin client for PJM Data Miner 2's REST API. Confirmed live (2026-10-13) against
api.pjm.com — see Architecture.md Section 3 ("PJM Data Miner: confirmed feed behavior") for
the full investigation. Key findings this client is built around:

  - Requests are POST with a JSON body, not GET with a `filters` querystring — the GET form
    was tried first and consistently rejected ("A datetime is missing") even with a
    correctly-shaped filters param; POST with the same JSON as the body works.
  - `pnode_name` and `type` are not server-filterable on these feeds (their column metadata
    has enableFiltering unset); only `pnode_id` is. Zone filtering is therefore by pnode_id,
    with the zone -> pnode_id mapping in common.normalize_pjm.ZONE_PNODE_IDS.
  - Two feeds matter here: rt_unverified_fivemin_lmps (posts every 5 min, not
    settlement-quality, 30-day retention) and rt_fivemin_hrl_lmps (posts once daily,
    settlement-quality, deep history). Same client, different feed name + page size.
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

BASE_URL = "https://api.pjm.com/api/v1"
FeedName = Literal["rt_unverified_fivemin_lmps", "rt_fivemin_hrl_lmps"]

_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.5
_MAX_ROW_COUNT = 5000  # observed cap; same ceiling as EIA's response page size


class PjmApiError(RuntimeError):
    pass


def _post_with_retry(
    url: str, body: dict[str, Any], headers: dict[str, str], timeout: float = 30.0
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            API_ERRORS_TOTAL.labels(source="pjm", status="exception").inc()
            log.warning(
                "pjm request exception, retrying",
                extra={"attempt": attempt, "error": str(exc)},
            )
        else:
            if resp.status_code == 200:
                return resp.json()
            API_ERRORS_TOTAL.labels(source="pjm", status=str(resp.status_code)).inc()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = PjmApiError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                log.warning(
                    "pjm request failed, retrying",
                    extra={"attempt": attempt, "status": resp.status_code},
                )
            else:
                # 4xx other than 429 (bad filter, bad key, etc.) won't fix itself on retry.
                raise PjmApiError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
    raise PjmApiError(f"exhausted retries ({_MAX_RETRIES})") from last_exc


def fetch_page(
    *,
    api_key: str,
    feed: FeedName,
    datetime_filter: str,
    datetime_field: str = "datetime_beginning_ept",
    pnode_ids: list[int] | None = None,
    start_row: int = 1,
    row_count: int = _MAX_ROW_COUNT,
) -> dict[str, Any]:
    """One page of a feed's `items` list, plus `totalRows` for pagination.

    `datetime_filter` is PJM's own relative/range syntax, e.g. "5minutesago" or
    "2024-01-01T00:00 to 2024-01-02T00:00" (confirmed format live). `datetime_field` is
    which column that filter applies to — confirmed live that both
    "datetime_beginning_ept" and "datetime_beginning_utc" accept it; default is EPT since
    that's what PJM's own relative keywords ("5minutesago") were demonstrated against,
    fetch_range_for_date overrides it to UTC since it builds absolute UTC timestamps.
    `sort` is always `datetime_beginning_ept` regardless — confirmed live that
    `datetime_beginning_utc` is filterable but NOT sortable (its column metadata has no
    enableSorting flag; sorting by it returns HTTP 400 "Sort field is not sortable").
    `pnode_ids` filters server-side to a single zone when given (one `pnode_id` filter per
    call — the API takes one value per filter object, not a list); omit to pull every node
    in the interval and filter client-side via common.normalize_pjm.
    """
    filters: list[dict[str, Any]] = [{datetime_field: datetime_filter}]
    if pnode_ids:
        if len(pnode_ids) != 1:
            raise ValueError("PJM's filter takes one pnode_id per request; call once per zone")
        filters.append({"pnode_id": pnode_ids[0]})

    body = {
        "rowCount": min(row_count, _MAX_ROW_COUNT),
        "startRow": start_row,
        "filters": filters,
        "sort": "datetime_beginning_ept",
        "order": 1,
    }
    headers = {"Ocp-Apim-Subscription-Key": api_key, "Content-Type": "application/json"}
    data = _post_with_retry(f"{BASE_URL}/{feed}", body, headers)
    if "items" not in data:
        raise PjmApiError(f"unexpected response shape: {list(data.keys())}")
    return data


def fetch_range(
    *,
    api_key: str,
    feed: FeedName,
    datetime_filter: str,
    datetime_field: str = "datetime_beginning_ept",
    pnode_ids: list[int] | None = None,
    row_count: int = _MAX_ROW_COUNT,
) -> Iterator[dict[str, Any]]:
    """Yields raw row dicts across the full result set for one datetime_filter, paginating
    past the row-count cap automatically. For a single zone, pass a one-element pnode_ids;
    for all five, call this once per zone (PJM's filter doesn't support an IN-list) or omit
    pnode_ids and filter client-side on the (typically few thousand) rows per interval."""
    start_row = 1
    while True:
        page = fetch_page(
            api_key=api_key,
            feed=feed,
            datetime_filter=datetime_filter,
            datetime_field=datetime_field,
            pnode_ids=pnode_ids,
            start_row=start_row,
            row_count=row_count,
        )
        items = page.get("items", [])
        if not items:
            return
        yield from items
        start_row += len(items)
        total = int(page.get("totalRows", start_row - 1))
        if start_row > total:
            return


def fetch_range_for_date(
    *,
    api_key: str,
    feed: FeedName,
    start: datetime,
    end: datetime,
    pnode_ids: list[int] | None = None,
    row_count: int = _MAX_ROW_COUNT,
) -> Iterator[dict[str, Any]]:
    """Convenience wrapper building PJM's "X to Y" range syntax from two UTC datetimes,
    filtering on datetime_beginning_utc directly (confirmed live) so callers never need to
    hand-convert to Eastern Prevailing Time (Architecture.md Section 3/7)."""
    datetime_filter = f"{start:%Y-%m-%dT%H:%M} to {end:%Y-%m-%dT%H:%M}"
    yield from fetch_range(
        api_key=api_key,
        feed=feed,
        datetime_filter=datetime_filter,
        datetime_field="datetime_beginning_utc",
        pnode_ids=pnode_ids,
        row_count=row_count,
    )
