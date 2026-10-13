from __future__ import annotations

from datetime import UTC, datetime

from common.normalize import normalize_eia_row, normalize_eia_rows, parse_period


def test_parse_period_is_utc_hour_beginning():
    dt = parse_period("2024-01-01T05")
    assert dt == datetime(2024, 1, 1, 5, tzinfo=UTC)
    assert dt.tzinfo is UTC


def test_normalize_eia_row_ok_value():
    raw = {"period": "2024-01-01T00", "respondent": "PJM", "type": "D", "value": "87654"}
    row = normalize_eia_row(raw, retrieved_at=datetime(2024, 1, 2, tzinfo=UTC))

    assert row["respondent"] == "PJM"
    assert row["reading_type"] == "D"
    assert row["period_start"] == datetime(2024, 1, 1, tzinfo=UTC)
    assert row["value_mw"] == 87654.0
    assert row["quality"] == "ok"
    assert row["retrieved_at"] == datetime(2024, 1, 2, tzinfo=UTC)


def test_normalize_eia_row_null_value_is_missing_not_dropped():
    raw = {"period": "2024-01-01T02", "respondent": "PJM", "type": "D", "value": None}
    row = normalize_eia_row(raw)

    assert row["value_mw"] is None
    assert row["quality"] == "missing"


def test_normalize_eia_row_empty_string_value_is_missing():
    raw = {"period": "2024-01-01T02", "respondent": "PJM", "type": "D", "value": ""}
    row = normalize_eia_row(raw)

    assert row["value_mw"] is None
    assert row["quality"] == "missing"


def test_normalize_eia_rows_batch_shares_one_retrieved_at(load_fixture):
    raw_rows = load_fixture("eia_response_page1.json")["response"]["data"]
    rows = normalize_eia_rows(raw_rows)

    assert len(rows) == 3
    assert rows[0]["quality"] == "ok"
    assert rows[2]["quality"] == "missing"  # the null-value row in the fixture
    assert len({r["retrieved_at"] for r in rows}) == 1  # one batch, one timestamp
