"""Thin client for PJM Data Miner 2's REST API. Confirmed live (2026-10-13) against
api.pjm.com — see Architecture.md Section 3 ("PJM Data Miner: confirmed feed behavior") for
the full investigation. Key findings this client is built around:

  - Requests are POST with a JSON body, not GET with a `filters` querystring — the GET form
    was tried first and consistently rejected ("A datetime is missing") even with a
    correctly-shaped filters param; POST with the same JSON as the body works.
  - `pnode_name` and `type` are not server-filterable on these feeds (their column metadata
    has enableFiltering unset); only `pnode_id` is. Zone filtering is therefore by pnode_id,
    with the zone -> pnode_id mapping in common.normalize_pjm.ZONE_PNODE_IDS.
  - Three feeds matter here: rt_unverified_fivemin_lmps (posts every 5 min, not
    settlement-quality, 30-day retention), rt_fivemin_hrl_lmps (posts once daily,
    settlement-quality, deep history), and hrl_load_metered (real zone-level metered
    demand, confirmed live 2026-10-14, posts once daily, up to 90-day revision window,
    first available 1993). Same client, different feed name + page size. The load feed
    filters by a `zone` text field instead of `pnode_id` -- see fetch_page's `zone` param
    and common.normalize_pjm.ZONE_LOAD_CODES.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal

import requests

from common.metrics import API_ERRORS_TOTAL

log = logging.getLogger(__name__)

BASE_URL = "https://api.pjm.com/api/v1"
FeedName = Literal["rt_unverified_fivemin_lmps", "rt_fivemin_hrl_lmps", "hrl_load_metered"]

_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.5
_MAX_ROW_COUNT = 5000  # observed cap; same ceiling as EIA's response page size

# Non-member rate limit is 6 req/min (Architecture.md Section 3, empirically confirmed —
# this session tripped a 429 hitting it). A multi-year, 5-zone backfill makes a couple
# hundred requests, so without proactive pacing it would spend most of its time hitting 429s
# and leaning on the retry/backoff below, which only allows 4 attempts per call — nowhere
# near enough headroom for a sustained run. Space every call at least 11s apart (≈5.5/min)
# instead, so the limit is simply never hit in the first place.
_MIN_SECONDS_BETWEEN_REQUESTS = 11.0
_last_request_at: float = 0.0

# The limit is per API key, not per process. The LMP poller, the load poller and any backfill
# all share one key, and each one pacing itself in isolation still adds up to well over 6/min
# when they run together (confirmed live 2026-10-15: both pollers started at once and tripped
# 429s). So pacing state lives in a pair of files that every process on the host shares: an
# OS-level lock to take turns, and the wall-clock time of the last request. Separate pods or
# hosts sharing one key are NOT covered by this; they would need an external limiter.
_THROTTLE_BASE = os.environ.get("PJM_THROTTLE_FILE") or os.path.join(
    tempfile.gettempdir(), "pjm_grid_watch_pjm_api_throttle"
)


class PjmApiError(RuntimeError):
    pass


@contextmanager
def _cross_process_lock(path: str) -> Iterator[None]:
    """Exclusive lock on `path`, blocking until it is free. Windows has no flock, so it takes
    a one-byte region lock and retries; POSIX uses flock directly."""
    fh = open(path, "a+b")  # noqa: SIM115 - closed in the finally below
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def _read_shared_last_request() -> float:
    try:
        with open(f"{_THROTTLE_BASE}.ts") as fh:
            return float(fh.read().strip() or 0.0)
    except (OSError, ValueError):
        return 0.0


def _write_shared_last_request(ts: float) -> None:
    with open(f"{_THROTTLE_BASE}.ts", "w") as fh:
        fh.write(repr(ts))


def _throttle() -> None:
    """Block until at least _MIN_SECONDS_BETWEEN_REQUESTS have passed since the last PJM
    request made by ANY process on this host, then record this one. The lock is held while
    waiting, so concurrent processes queue up behind each other instead of racing."""
    global _last_request_at
    try:
        with _cross_process_lock(f"{_THROTTLE_BASE}.lock"):
            now = time.time()
            # A last-request time in the future means the clock moved backwards; ignore it
            # rather than stalling for an arbitrary stretch.
            last = min(max(_last_request_at, _read_shared_last_request()), now)
            wait = _MIN_SECONDS_BETWEEN_REQUESTS - (now - last)
            if wait > 0:
                time.sleep(wait)
            _last_request_at = time.time()
            _write_shared_last_request(_last_request_at)
    except OSError:
        # No usable lock file (read-only temp dir, etc.): fall back to pacing this process
        # alone, which is the old behaviour, rather than failing the poll.
        wait = _MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def _post_with_retry(
    url: str, body: dict[str, Any], headers: dict[str, str], timeout: float = 30.0
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        _throttle()
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
    zone: str | None = None,
    use_custom_sort: bool = True,
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
    When `use_custom_sort` is True, sort is always `datetime_beginning_ept` regardless of
    `datetime_field` — confirmed live that `datetime_beginning_utc` is filterable but NOT
    sortable (its column metadata has no enableSorting flag; sorting by it returns HTTP 400
    "Sort field is not sortable").

    `pnode_ids` filters server-side to a single zone when given (one `pnode_id` filter per
    call — the API takes one value per filter object, not a list); omit to pull every node
    in the interval and filter client-side via common.normalize_pjm.

    `zone` is the equivalent server-side filter for hrl_load_metered, confirmed live
    2026-10-14 — that feed identifies zones by a `zone` text field (its own codes: PE, PL,
    ME, PN, DUQ — see common.normalize_pjm.ZONE_LOAD_CODES), not pnode_id, so it needs its
    own filter parameter rather than reusing pnode_ids.

    `use_custom_sort=False` AND `pnode_ids=None` together are required once a query reaches
    PJM's "archived" window (confirmed live: `rt_fivemin_hrl_lmps` archives data after
    `archiveCutoffDays` — 186 in its metadata as of 2026-10-13, ~6 months, not the "two
    years" originally assumed from the feed's prose description). An archived-data request
    with either a pnode_id filter or a custom sort/order gets a 400: "The API request
    contains invalid attribute(s) for archived data." Backfill (ingestion/backfill/
    pjm_backfill.py) therefore never sends either — it's the one caller that routinely
    queries data old enough to be archived, and omitting both works for recent data too,
    just at the cost of a bigger per-request result set filtered client-side.
    """
    filters: list[dict[str, Any]] = [{datetime_field: datetime_filter}]
    if pnode_ids:
        if len(pnode_ids) != 1:
            raise ValueError("PJM's filter takes one pnode_id per request; call once per zone")
        filters.append({"pnode_id": pnode_ids[0]})
    if zone:
        filters.append({"zone": zone})

    body: dict[str, Any] = {
        "rowCount": min(row_count, _MAX_ROW_COUNT),
        "startRow": start_row,
        "filters": filters,
    }
    if use_custom_sort:
        body["sort"] = "datetime_beginning_ept"
        body["order"] = 1

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
    zone: str | None = None,
    use_custom_sort: bool = True,
    row_count: int = _MAX_ROW_COUNT,
) -> Iterator[dict[str, Any]]:
    """Yields raw row dicts across the full result set for one datetime_filter, paginating
    past the row-count cap automatically. For a single zone, pass a one-element pnode_ids
    (LMP feeds) or a zone code (hrl_load_metered); for all five, call this once per zone
    (PJM's filter doesn't support an IN-list) or omit both and filter client-side on the
    (typically few thousand) rows per interval — the latter is required once the range
    might be archived (see fetch_page)."""
    start_row = 1
    while True:
        page = fetch_page(
            api_key=api_key,
            feed=feed,
            datetime_filter=datetime_filter,
            datetime_field=datetime_field,
            pnode_ids=pnode_ids,
            zone=zone,
            use_custom_sort=use_custom_sort,
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
    zone: str | None = None,
    use_custom_sort: bool = True,
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
        zone=zone,
        use_custom_sort=use_custom_sort,
        row_count=row_count,
    )
