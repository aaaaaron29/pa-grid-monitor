from __future__ import annotations

from datetime import UTC, datetime

from common.normalize_pjm import (
    ZONE_LOAD_CODES,
    ZONE_PNODE_IDS,
    normalize_pjm_load_rows,
    normalize_pjm_row,
    normalize_pjm_rows,
    parse_pjm_utc,
)


def test_zone_pnode_ids_confirmed_live():
    # Architecture.md Section 3 — confirmed 2026-10-13 against the real API; this test pins
    # them so a future edit can't silently drift from what was actually verified.
    assert ZONE_PNODE_IDS == {
        "PECO": 51297,
        "PPL": 51299,
        "METED": 51296,
        "PENELEC": 51300,
        "DUQ": 37737283,
    }


def test_parse_pjm_utc_no_offset_in_source_string():
    dt = parse_pjm_utc("2026-10-13T19:05:00")
    assert dt == datetime(2026, 10, 13, 19, 5, tzinfo=UTC)
    assert dt.tzinfo is UTC


def test_normalize_pjm_row_known_zone():
    raw = {
        "datetime_beginning_utc": "2026-10-13T19:00:00",
        "pnode_id": 51297,
        "total_lmp_rt": 18.52,
    }
    row = normalize_pjm_row(raw, verified=False, retrieved_at=datetime(2026, 10, 14, tzinfo=UTC))

    assert row["zone"] == "PECO"
    assert row["period_start"] == datetime(2026, 10, 13, 19, 0, tzinfo=UTC)
    assert row["lmp_price"] == 18.52
    assert row["quality"] == "ok"
    assert row["verified"] is False
    assert row["retrieved_at"] == datetime(2026, 10, 14, tzinfo=UTC)


def test_normalize_pjm_row_verified_flag_propagates():
    raw = {
        "datetime_beginning_utc": "2026-10-13T19:00:00",
        "pnode_id": 37737283,
        "total_lmp_rt": 24.7,
    }
    row = normalize_pjm_row(raw, verified=True)
    assert row["zone"] == "DUQ"
    assert row["verified"] is True


def test_normalize_pjm_row_unknown_pnode_is_dropped():
    raw = {
        "datetime_beginning_utc": "2026-10-13T19:00:00",
        "pnode_id": 999999,
        "total_lmp_rt": 10.0,
    }
    assert normalize_pjm_row(raw, verified=False) is None


def test_normalize_pjm_row_null_value_is_missing():
    raw = {"datetime_beginning_utc": "2026-10-13T19:10:00", "pnode_id": 51297, "total_lmp_rt": None}
    row = normalize_pjm_row(raw, verified=False)
    assert row["lmp_price"] is None
    assert row["quality"] == "missing"


def test_normalize_pjm_rows_filters_unknown_nodes_and_shares_retrieved_at(load_fixture):
    raw_rows = load_fixture("pjm_response_page1.json")["items"]
    # mix in an unknown node (pnode_id=1, PJM-RTO) to confirm it gets dropped, not errored on
    raw_rows = raw_rows + [
        {"datetime_beginning_utc": "2026-10-13T19:00:00", "pnode_id": 1, "total_lmp_rt": 50.1}
    ]

    rows = normalize_pjm_rows(raw_rows, verified=False)

    assert len(rows) == 2  # the pnode_id=1 (PJM-RTO) row was dropped, not one of our 5 zones
    assert len({r["retrieved_at"] for r in rows}) == 1


def test_zone_load_codes_confirmed_live():
    # Confirmed live 2026-10-14 against the real hrl_load_metered feed -- a completely
    # different code set from ZONE_PNODE_IDS, pinned so a future edit can't silently drift.
    assert ZONE_LOAD_CODES == {
        "PECO": "PE",
        "PPL": "PL",
        "METED": "ME",
        "PENELEC": "PN",
        "DUQ": "DUQ",
    }


def test_normalize_pjm_load_rows_single_load_area():
    raw_rows = [
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "DUQ",
            "load_area": "DUQ",
            "mw": 1200.5,
            "is_verified": True,
        }
    ]
    rows = normalize_pjm_load_rows(raw_rows, retrieved_at=datetime(2026, 10, 14, tzinfo=UTC))

    assert len(rows) == 1
    assert rows[0]["zone"] == "DUQ"
    assert rows[0]["period_start"] == datetime(2026, 10, 13, 19, 0, tzinfo=UTC)
    assert rows[0]["load_mw"] == 1200.5
    assert rows[0]["quality"] == "ok"
    assert rows[0]["verified"] is True
    assert rows[0]["retrieved_at"] == datetime(2026, 10, 14, tzinfo=UTC)


def test_normalize_pjm_load_rows_sums_ppl_load_areas():
    """The real case confirmed live: PPL's feed zone ("PL") reports two separate load_area
    components, PLCO and UGI, that must be summed into one PPL total."""
    raw_rows = [
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "PLCO",
            "mw": 3426.364,
            "is_verified": False,
        },
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "UGI",
            "mw": 83.479,
            "is_verified": False,
        },
    ]
    rows = normalize_pjm_load_rows(raw_rows)

    assert len(rows) == 1
    assert rows[0]["zone"] == "PPL"
    assert rows[0]["load_mw"] == 3426.364 + 83.479


def test_normalize_pjm_load_rows_verified_requires_every_constituent_row():
    raw_rows = [
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "PLCO",
            "mw": 3426.364,
            "is_verified": True,
        },
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "UGI",
            "mw": 83.479,
            "is_verified": False,
        },
    ]
    rows = normalize_pjm_load_rows(raw_rows)
    assert rows[0]["verified"] is False  # one unverified component makes the whole total so


def test_normalize_pjm_load_rows_unknown_zone_code_is_dropped():
    raw_rows = [
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "AEP",
            "load_area": "AEPAPT",
            "mw": 3319.8,
            "is_verified": True,
        }
    ]
    assert normalize_pjm_load_rows(raw_rows) == []


def test_normalize_pjm_load_rows_missing_component_makes_whole_sum_missing():
    """A partial sum would understate the real total, so one missing load_area row drops
    the whole (zone, period_start) group to missing rather than silently undercounting."""
    raw_rows = [
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "PLCO",
            "mw": 3426.364,
            "is_verified": True,
        },
        {
            "datetime_beginning_utc": "2026-10-13T19:00:00",
            "zone": "PL",
            "load_area": "UGI",
            "mw": None,
            "is_verified": True,
        },
    ]
    rows = normalize_pjm_load_rows(raw_rows)
    assert rows[0]["load_mw"] is None
    assert rows[0]["quality"] == "missing"
