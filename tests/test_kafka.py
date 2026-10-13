from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from common.kafka import deserialize_row, serialize_row


def test_serialize_then_deserialize_round_trips():
    row = {"zone": "PECO", "lmp_price": 18.44, "verified": False}
    assert deserialize_row(serialize_row(row)) == row


def test_serialize_datetime_as_iso_8601():
    row = {"period_start": datetime(2026, 10, 13, 19, 5, tzinfo=UTC)}
    result = deserialize_row(serialize_row(row))
    assert result["period_start"] == "2026-10-13T19:05:00+00:00"


def test_serialize_date_as_iso_8601():
    row = {"snapshot_date": date(2026, 10, 13)}
    result = deserialize_row(serialize_row(row))
    assert result["snapshot_date"] == "2026-10-13"


def test_serialize_none_value_round_trips():
    row = {"value_mw": None}
    assert deserialize_row(serialize_row(row)) == row


def test_serialize_rejects_truly_unserializable_object():
    class NotSerializable:
        pass

    with pytest.raises(TypeError):
        serialize_row({"bad": NotSerializable()})


def test_deserialize_returns_a_plain_dict():
    row = {"a": 1, "b": [1, 2, 3]}
    result = deserialize_row(serialize_row(row))
    assert isinstance(result, dict)
    assert result == row
