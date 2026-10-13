from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingestion.backfill.eia_backfill import _year_chunks


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
