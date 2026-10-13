"""Historical PJM LMP backfill, and doubles as the daily verified-feed reconciliation job
Architecture.md Section 6 promises: "unverified LMP getting corrected the next day... through
the same revision-aware upsert `eia_readings` already uses." That reconciliation is just this
same function run nightly over the previous day's window — a separate code path isn't needed,
since common.db.upsert_pjm_lmp_readings already guarantees verified data overwrites
unverified and never the reverse.

Writes straight to Postgres (no Kafka yet, Phase 3), through common.normalize_pjm, same
reasoning as the EIA backfill.

Confirmed live (2026-10-13): the verified feed has a real lag, not just a daily posting
label — a 2-hours-ago window returned zero rows while a 2-days-ago window returned real
data. Don't schedule the reconciliation CronJob to reconcile "the last few hours"; target
"yesterday" (a full UTC day, at minimum) or later.

ARCHIVED DATA — a real constraint discovered running this for real, not assumed up front:
`rt_fivemin_hrl_lmps` archives data after `archiveCutoffDays` (186 in its live metadata as
of 2026-10-13, ~6 months — the feed's prose description said "two years", which is wrong;
trust the metadata field). Once a query's range crosses that boundary, PJM rejects both a
`pnode_id` filter and a custom sort/order (HTTP 400: "invalid attribute(s) for archived
data"), so there's no server-side way to narrow to our 5 zones for old data — every request
returns ALL ~14,700 PJM nodes for whatever interval it covers, and the 5 zone rows have to
be picked out client-side.

That makes deep archived history expensive in a way the original "2+ years" plan didn't
account for: even at the coarsest (hourly) granularity, pulling ~14,700 nodes/interval needs
~3 pages per hour just to enumerate everything once. Backfilling, say, a year of archived
hourly data is on the order of 24*365*3 ≈ 26,000 requests — at the 11s/request pacing this
client enforces to respect PJM's non-member rate limit (ingestion/pjm_poller/client.py),
that's roughly 3.5 days of continuous polling, not something to launch casually inside an
interactive session.

Default behavior therefore clamps backfill to the non-archived window (fast, server-side
zone-filtered, the path already proven live) and logs clearly when older history was
requested but skipped. Reaching further back is possible (`allow_archived=True`,
`run_archived_backfill`) and is implemented and correct, but is opt-in and multi-day by
design — run it as a long-lived background job when actually wanted, not by default.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.config import Settings
from common.db import connect, upsert_pjm_lmp_readings
from common.metrics import INGEST_RUNS_TOTAL, ROWS_WRITTEN_TOTAL
from common.normalize_pjm import ZONE_PNODE_IDS, normalize_pjm_rows
from ingestion.pjm_poller.client import FeedName, fetch_range_for_date

log = logging.getLogger(__name__)

VERIFIED_FEED: FeedName = "rt_fivemin_hrl_lmps"
ARCHIVED_FEED: FeedName = "rt_hrl_lmps"  # hourly — 12x fewer intervals than the 5-min feed
                                          # for the same calendar span, which is the only
                                          # lever that actually helps once zone filtering
                                          # is unavailable (see module docstring)

# Confirmed live archiveCutoffDays is 186; a safety margin keeps us clear of the exact
# boundary (which could shift by a day as "now" advances) without ever touching the slow,
# all-nodes archived path unintentionally.
_ARCHIVE_SAFETY_MARGIN_DAYS = 16
ARCHIVE_CUTOFF_DAYS = 186 - _ARCHIVE_SAFETY_MARGIN_DAYS

# One API call per (zone, chunk); 30-day chunks keep each response well under the 5,000-row
# cap (5 zones x 1 reading per 5 min x 30 days is ~8,640 rows per zone per chunk before
# pagination kicks in, which fetch_range already handles) while giving resumable, observable
# progress on a multi-year pull.
_CHUNK = timedelta(days=30)

# Archived path: one call per hour (see module docstring for why hourly, not 5-min). No
# chunking beyond that — each hourly call already needs its own pagination since ~14,700
# nodes exceeds the 5,000-row page cap.
_ARCHIVED_CHUNK = timedelta(hours=1)


def _chunks(start: datetime, end: datetime, step: timedelta):
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end


def _clamp_to_fast_window(
    start: datetime, end: datetime, cutoff_days: int = ARCHIVE_CUTOFF_DAYS
) -> tuple[datetime, int]:
    """Pure clamping logic, split out from run_pjm_backfill so it's unit-testable without
    mocking the DB/API. Returns (effective_start, days_skipped) — days_skipped is 0 when
    `start` is already inside the fast (non-archived) window."""
    cutoff = end - timedelta(days=cutoff_days)
    if start < cutoff:
        return cutoff, (cutoff - start).days
    return start, 0


def run_pjm_backfill(
    settings: Settings,
    start: datetime,
    end: datetime | None = None,
) -> int:
    """Fast path: server-side zone-filtered, 5-minute granularity. Silently clamps `start`
    forward to the archive boundary if it's older than that — call run_archived_backfill
    separately (and deliberately) for anything further back."""
    end = end or datetime.now(UTC)
    requested_start = start
    start, skipped_days = _clamp_to_fast_window(start, end)
    if skipped_days:
        log.warning(
            "requested start is in PJM's archived window; clamping to the fast-path "
            "boundary. Call run_archived_backfill explicitly for the skipped range — "
            "it's slow by design (see ingestion/backfill/pjm_backfill.py docstring).",
            extra={
                "requested_start": requested_start.isoformat(),
                "clamped_start": start.isoformat(),
                "skipped_days": skipped_days,
            },
        )

    total_written = 0
    retrieved_at = datetime.now(UTC)

    with connect(settings.postgres_dsn) as conn:
        for zone, pnode_id in ZONE_PNODE_IDS.items():
            for chunk_start, chunk_end in _chunks(start, end, _CHUNK):
                log.info(
                    "backfilling chunk",
                    extra={
                        "zone": zone,
                        "start": chunk_start.isoformat(),
                        "end": chunk_end.isoformat(),
                    },
                )
                try:
                    raw_rows = list(
                        fetch_range_for_date(
                            api_key=settings.pjm_api_key,
                            feed=VERIFIED_FEED,
                            start=chunk_start,
                            end=chunk_end,
                            pnode_ids=[pnode_id],
                        )
                    )
                except Exception:
                    INGEST_RUNS_TOTAL.labels(source="pjm_backfill", outcome="error").inc()
                    log.exception(
                        "chunk failed, re-run this date range to retry",
                        extra={"zone": zone, "start": chunk_start.isoformat()},
                    )
                    raise

                rows = normalize_pjm_rows(raw_rows, verified=True, retrieved_at=retrieved_at)
                written = upsert_pjm_lmp_readings(conn, rows)
                conn.commit()
                total_written += written
                ROWS_WRITTEN_TOTAL.labels(
                    source="pjm_backfill", table="pjm_lmp_readings"
                ).inc(written)
                INGEST_RUNS_TOTAL.labels(source="pjm_backfill", outcome="success").inc()
                log.info("chunk done", extra={"zone": zone, "rows": written})

    return total_written


def run_archived_backfill(
    settings: Settings,
    start: datetime,
    end: datetime | None = None,
) -> int:
    """Slow path for data older than PJM's archive cutoff: no server-side zone filter is
    available, so every hourly call pulls all ~14,700 PJM nodes and this filters down to our
    5 zones client-side (common.normalize_pjm already drops anything else). Expect roughly
    11 seconds per hour of history, i.e. ~4.4 minutes per day, ~3.5 days per year — run this
    as a background job you deliberately kick off, not as part of routine setup."""
    end = end or (datetime.now(UTC) - timedelta(days=ARCHIVE_CUTOFF_DAYS))
    total_written = 0
    retrieved_at = datetime.now(UTC)

    with connect(settings.postgres_dsn) as conn:
        for chunk_start, chunk_end in _chunks(start, end, _ARCHIVED_CHUNK):
            log.info(
                "backfilling archived hour",
                extra={"start": chunk_start.isoformat(), "end": chunk_end.isoformat()},
            )
            try:
                raw_rows = list(
                    fetch_range_for_date(
                        api_key=settings.pjm_api_key,
                        feed=ARCHIVED_FEED,
                        start=chunk_start,
                        end=chunk_end,
                        pnode_ids=None,  # not allowed on archived data — filter client-side
                        use_custom_sort=False,  # also not allowed on archived data
                    )
                )
            except Exception:
                INGEST_RUNS_TOTAL.labels(source="pjm_archived_backfill", outcome="error").inc()
                log.exception(
                    "archived hour failed, re-run this range to retry",
                    extra={"start": chunk_start.isoformat()},
                )
                raise

            rows = normalize_pjm_rows(raw_rows, verified=True, retrieved_at=retrieved_at)
            written = upsert_pjm_lmp_readings(conn, rows)
            conn.commit()
            total_written += written
            ROWS_WRITTEN_TOTAL.labels(
                source="pjm_archived_backfill", table="pjm_lmp_readings"
            ).inc(written)
            INGEST_RUNS_TOTAL.labels(source="pjm_archived_backfill", outcome="success").inc()
            log.info(
                "archived hour done",
                extra={"rows": written, "nodes_seen": len(raw_rows)},
            )

    return total_written
