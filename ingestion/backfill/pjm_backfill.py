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

# One API call per (zone, chunk); 30-day chunks keep each response well under the 5,000-row
# cap (5 zones x 1 reading per 5 min x 30 days is ~8,640 rows per zone per chunk before
# pagination kicks in, which fetch_range already handles) while giving resumable, observable
# progress on a multi-year pull.
_CHUNK = timedelta(days=30)


def _chunks(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + _CHUNK, end)
        yield cursor, chunk_end
        cursor = chunk_end


def run_pjm_backfill(
    settings: Settings,
    start: datetime,
    end: datetime | None = None,
) -> int:
    end = end or datetime.now(UTC)
    total_written = 0
    retrieved_at = datetime.now(UTC)

    with connect(settings.postgres_dsn) as conn:
        for zone, pnode_id in ZONE_PNODE_IDS.items():
            for chunk_start, chunk_end in _chunks(start, end):
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
