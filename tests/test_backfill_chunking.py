from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingestion.backfill.eia_backfill import _year_chunks
from ingestion.backfill.pjm_backfill import ARCHIVE_CUTOFF_DAYS, _clamp_to_fast_window


def test_chunks_cover_the_full_range_with_no_gaps_or_overlaps():
    start = datetime(2019, 1, 1, tzinfo=UTC)
    end = datetime(2024, 6, 15, tzinfo=UTC)

    chunks = list(_year_chunks(start, end))

    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:], strict=False):
        assert prev_end == next_start  # contiguous, no gap or overlap


def test_range_shorter_than_one_chunk_yields_a_single_chunk():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=10)

    chunks = list(_year_chunks(start, end))

    assert chunks == [(start, end)]


def test_empty_range_yields_nothing():
    start = datetime(2024, 1, 1, tzinfo=UTC)

    assert list(_year_chunks(start, start)) == []


def test_clamp_leaves_start_untouched_when_already_inside_fast_window():
    end = datetime(2026, 10, 13, tzinfo=UTC)
    start = end - timedelta(days=30)  # well inside ARCHIVE_CUTOFF_DAYS

    effective_start, skipped_days = _clamp_to_fast_window(start, end)

    assert effective_start == start
    assert skipped_days == 0


def test_clamp_pushes_start_forward_when_in_archived_territory():
    """Regression guard: this is the exact bug that broke a real backfill run — requesting
    a start older than PJM's archive boundary and sending it straight to the server-side
    zone-filtered path, which archived data rejects outright."""
    end = datetime(2026, 10, 13, tzinfo=UTC)
    start = datetime(2024, 1, 1, tzinfo=UTC)  # ~846 days back, well past the cutoff

    effective_start, skipped_days = _clamp_to_fast_window(start, end)

    assert effective_start == end - timedelta(days=ARCHIVE_CUTOFF_DAYS)
    assert effective_start > start
    assert skipped_days > 0


def test_clamp_boundary_is_exactly_the_cutoff():
    end = datetime(2026, 10, 13, tzinfo=UTC)
    start = end - timedelta(days=ARCHIVE_CUTOFF_DAYS)  # exactly on the boundary

    effective_start, skipped_days = _clamp_to_fast_window(start, end)

    assert effective_start == start  # not < cutoff, so no clamping
    assert skipped_days == 0
