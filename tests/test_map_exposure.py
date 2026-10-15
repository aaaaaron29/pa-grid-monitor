"""The pure parts of scripts/map/exposure.py: distance math, summing people within a radius,
parsing a Census geography row, and choosing which neighboring states a circle reaches. The
network-facing functions are exercised by running the build script itself."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "map"))
import exposure as ex  # noqa: E402

LAT, LON = 40.0, -76.0
MILE_LAT = 1 / ex.MILES_PER_DEGREE_LAT  # degrees of latitude in one mile


def test_one_degree_of_latitude_is_about_69_miles():
    assert ex.haversine_miles(40.0, -76.0, 41.0, -76.0) == pytest.approx(69.1, abs=0.2)


def test_haversine_matches_a_known_city_pair():
    # Philadelphia to Pittsburgh is roughly 258 miles in a straight line.
    assert ex.haversine_miles(39.9526, -75.1652, 40.4406, -79.9959) == pytest.approx(258, abs=4)


def test_people_within_sums_blocks_inside_each_radius_only():
    blocks = [
        (LAT + 0.3 * MILE_LAT, LON, 100, 40),  # 0.3 mi: inside every radius
        (LAT + 0.8 * MILE_LAT, LON, 200, 80),  # 0.8 mi: inside 1, 2 and 5
        (LAT + 1.5 * MILE_LAT, LON, 400, 160),  # 1.5 mi: inside 2 and 5
        (LAT + 4.0 * MILE_LAT, LON, 800, 320),  # 4.0 mi: inside 5 only
        (LAT + 9.0 * MILE_LAT, LON, 1600, 640),  # 9.0 mi: outside every radius
    ]

    got = ex.people_within(blocks, LAT, LON)

    assert got["radiiMiles"] == [0.5, 1, 2, 5]
    assert got["people"] == [100, 300, 700, 1500]
    assert got["homes"] == [40, 120, 280, 600]
    assert got["nearestHomesMiles"] == pytest.approx(0.3, abs=0.01)


def test_nearest_homes_is_reported_even_when_nothing_is_inside_the_radii():
    blocks = [(LAT + 8.0 * MILE_LAT, LON, 50, 20)]

    got = ex.people_within(blocks, LAT, LON)

    assert got["people"] == [0, 0, 0, 0]
    assert got["nearestHomesMiles"] == pytest.approx(8.0, abs=0.05)


def test_a_block_east_west_is_measured_by_true_distance_not_degrees():
    one_mile_east = 1 / (ex.MILES_PER_DEGREE_LAT * math.cos(math.radians(LAT)))
    blocks = [(LAT, LON + 0.9 * one_mile_east, 10, 4), (LAT, LON + 1.2 * one_mile_east, 20, 8)]

    got = ex.people_within(blocks, LAT, LON)

    assert got["people"][1] == 10  # only the 0.9-mile block is within one mile


def test_no_blocks_at_all_gives_zeroes_and_no_nearest():
    got = ex.people_within([], LAT, LON)

    assert got["people"] == [0, 0, 0, 0] and got["nearestHomesMiles"] is None


def _geo_row(summary_level: str, pop: str, homes: str, lat: str, lon: str) -> str:
    fields = ["x"] * 97
    fields[2] = summary_level
    fields[-7], fields[-6], fields[-5], fields[-4] = pop, homes, lat, lon
    return "|".join(fields) + "\n"


def test_parse_geo_line_reads_a_block_row():
    row = _geo_row("750", "37", "15", "+41.4641324", "-075.6668088")

    assert ex.parse_geo_line(row) == (41.4641324, -75.6668088, 37, 15)


def test_parse_geo_line_ignores_non_block_rows_and_bad_lines():
    assert ex.parse_geo_line(_geo_row("050", "103852", "43007", "+39.8", "-077.2")) is None
    assert ex.parse_geo_line("too|short") is None
    assert ex.parse_geo_line(_geo_row("750", "n/a", "1", "+41.0", "-075.0")) is None


def test_a_blank_population_field_counts_as_zero():
    assert ex.parse_geo_line(_geo_row("750", "", "", "+41.0", "-075.0")) == (41.0, -75.0, 0, 0)


def test_inland_site_needs_only_pennsylvania():
    everywhere_in_pa = lambda lat, lon: True  # noqa: E731

    assert ex.states_needed(41.5, -75.6, everywhere_in_pa) == ["PA"]


def test_site_near_the_new_jersey_line_pulls_in_new_jersey_only():
    # Treat everything west of the Delaware (lon -74.74) as Pennsylvania.
    in_pa = lambda lat, lon: lon < -74.74  # noqa: E731

    assert ex.states_needed(40.155, -74.7469, in_pa) == ["NJ", "PA"]


def test_site_whose_circle_leaves_the_state_in_two_directions_gets_both_neighbors():
    # The circle crosses the line into Maryland (south) and into Ohio (west); in practice the
    # boxes are checked against the sample points that fall outside Pennsylvania.
    in_pa = lambda lat, lon: lat > 39.72 and lon > -80.51  # noqa: E731

    needed = ex.states_needed(39.74, -80.50, in_pa)

    assert "PA" in needed and ("MD" in needed or "WV" in needed or "OH" in needed)


def test_fuel_codes_get_readable_labels_and_unknowns_fall_back():
    assert ex.FUEL_LABELS["NUC"] == "Nuclear" and ex.FUEL_LABELS["NG"] == "Natural gas"


def test_operating_plants_filters_on_status_and_size():
    plants = [
        {"name": "Big", "status": "OP", "mw": 500, "lat": 0, "lon": 0, "fuel": "Coal"},
        {"name": "Small", "status": "OP", "mw": 40, "lat": 0, "lon": 0, "fuel": "Solar"},
        {"name": "Retired", "status": "RE", "mw": 900, "lat": 0, "lon": 0, "fuel": "Coal"},
        {"name": "Unknown", "status": "OP", "mw": None, "lat": 0, "lon": 0, "fuel": "Other"},
    ]

    assert [p["name"] for p in ex.operating_plants(plants, min_mw=100)] == ["Big"]


def test_nearest_plant_picks_the_closest_and_rounds_the_distance():
    plants = [
        {"name": "Far", "fuel": "Coal", "mw": 800, "lat": LAT + 20 * MILE_LAT, "lon": LON},
        {"name": "Near", "fuel": "Nuclear", "mw": 2000, "lat": LAT + 3 * MILE_LAT, "lon": LON},
    ]

    got = ex.nearest_plant(LAT, LON, plants)

    assert got == {"name": "Near", "fuel": "Nuclear", "mw": 2000, "miles": 3.0}


def test_nearest_plant_with_no_plants_is_none():
    assert ex.nearest_plant(LAT, LON, []) is None
