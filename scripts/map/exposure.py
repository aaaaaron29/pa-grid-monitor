"""Who and what is near a site: population, homes, community facilities, and power plants.

Everything here is public data and none of it is PJM Data Miner data:
  - People and homes: the U.S. Census Bureau's 2020 redistricting (PL 94-171) block file, which
    is published as a plain download (no API key). Each Census block has a population, a
    housing-unit count and an internal point, so people within N miles is the sum over blocks
    whose point falls inside the circle.
  - Schools, hospitals, nursing homes, child-care centers, and power plants: the federal HIFLD
    layers, served by Penn State's PASDA.

Proximity is exposure, not impact. These figures say how many people live near a marker; they
say nothing about whether a project will affect them, which depends on cooling, generators,
noise and water use that most projects have not disclosed. The site says so wherever it shows
them.

Limits worth knowing: counts are April 2020 and have changed since; a block's point is an
interior point, not each house; distances run from the map marker, not the property line;
and the HIFLD layers carry different vintages.
"""
from __future__ import annotations

import gzip
import json
import math
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

RADII_MILES = (0.5, 1, 2, 5)
EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE_LAT = 69.05

CENSUS_URL = (
    "https://www2.census.gov/programs-surveys/decennial/2020/data/"
    "01-Redistricting_File--PL_94-171/{name}/{abbr}2020.pl.zip"
)

# State name (as the Census names its folders) and a rough bounding box (south, north, west,
# east). The boxes only decide which neighboring files to download for a site near a border,
# so being slightly generous costs a download and never causes a wrong number.
STATES = {
    "PA": ("Pennsylvania", (39.71, 42.27, -80.53, -74.68)),
    "NJ": ("New_Jersey", (38.92, 41.36, -75.60, -73.89)),
    "NY": ("New_York", (40.49, 45.02, -79.77, -71.85)),
    "OH": ("Ohio", (38.40, 42.33, -84.82, -80.52)),
    "WV": ("West_Virginia", (37.20, 40.64, -82.64, -77.72)),
    "MD": ("Maryland", (37.91, 39.73, -79.49, -75.05)),
    "DE": ("Delaware", (38.45, 39.84, -75.79, -75.05)),
}

PASDA = "https://mapservices.pasda.psu.edu/server/rest/services/pasda/HIFLD_FEMA_PA/MapServer"
PLACE_LAYERS = {  # layer id -> kind shown to the reader
    174: "School",
    172: "School",
    90: "Hospital",
    153: "Nursing home",
    25: "Child care",
}
POWER_PLANT_LAYER = 168

FUEL_LABELS = {
    "NUC": "Nuclear",
    "NG": "Natural gas",
    "BIT": "Coal",
    "WC": "Coal",
    "RC": "Coal",
    "WAT": "Hydro",
    "WND": "Wind",
    "SUN": "Solar",
    "DFO": "Oil",
    "RFO": "Oil",
    "LFG": "Landfill gas",
    "MSW": "Waste",
    "WDS": "Wood",
    "OBG": "Biogas",
    "OBS": "Biomass",
    "MWH": "Battery storage",
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


# ----------------------------------------------------------------------------- Census blocks


def parse_geo_line(line: str) -> tuple[float, float, int, int] | None:
    """One row of a state's PL 94-171 geography file, or None if it is not a Census block.

    The file is pipe-delimited with 97 fields; block rows have summary level 750 in field 3, and
    the last seven fields run: population, housing units, internal latitude, internal longitude,
    then three trailing fields. Returns (lat, lon, population, housing_units)."""
    parts = line.rstrip("\r\n").split("|")
    if len(parts) < 90 or parts[2] != "750":
        return None
    try:
        return float(parts[-5]), float(parts[-4]), int(parts[-7] or 0), int(parts[-6] or 0)
    except ValueError:
        return None


def _state_total(zf: zipfile.ZipFile, geo_name: str) -> int | None:
    with zf.open(geo_name) as fh:
        for raw in fh:
            parts = raw.decode("latin1").rstrip("\r\n").split("|")
            if len(parts) >= 90 and parts[2] == "040":
                return int(parts[-7])
    return None


def load_blocks(abbr: str, cache_dir: Path) -> list[tuple[float, float, int, int]]:
    """Populated Census blocks for one state as (lat, lon, population, housing_units).

    Downloads the state's file once, checks that the block populations add up to the state
    total printed in the same file (so a layout change fails loudly instead of silently giving
    wrong numbers), and caches a compact copy for later runs."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    compact = cache_dir / f"{abbr}_blocks.json.gz"
    if compact.exists():
        with gzip.open(compact, "rt", encoding="utf8") as fh:
            return [tuple(b) for b in json.load(fh)]

    name = STATES[abbr][0]
    zip_path = cache_dir / f"{abbr.lower()}2020.pl.zip"
    if not zip_path.exists():
        req = urllib.request.Request(
            CENSUS_URL.format(name=name, abbr=abbr.lower()),
            headers={"User-Agent": "pa-grid-monitor-map-build/1.0"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp, open(zip_path, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)

    blocks: list[tuple[float, float, int, int]] = []
    with zipfile.ZipFile(zip_path) as zf:
        geo_name = next(n for n in zf.namelist() if n.endswith("geo2020.pl"))
        total_expected = _state_total(zf, geo_name)
        with zf.open(geo_name) as fh:
            for raw in fh:
                row = parse_geo_line(raw.decode("latin1"))
                if row and row[2] > 0:
                    blocks.append(row)
    total_found = sum(b[2] for b in blocks)
    if total_expected is not None and total_found != total_expected:
        raise RuntimeError(
            f"{abbr}: block populations sum to {total_found:,}, but the file's own state total "
            f"is {total_expected:,}; the file layout has probably changed"
        )
    with gzip.open(compact, "wt", encoding="utf8") as fh:
        json.dump(blocks, fh)
    return blocks


def states_needed(
    lat: float,
    lon: float,
    in_pennsylvania,
    radius_miles: float = 5.0,
    samples: int = 48,
) -> list[str]:
    """Pennsylvania plus any neighboring state the `radius_miles` circle around the point reaches,
    so people just across a state line are counted.

    The circle is sampled at two distances; wherever a sample falls outside Pennsylvania (the
    caller supplies `in_pennsylvania(lat, lon)`), the neighbor whose bounding box holds that
    sample is added. Testing the actual circle, rather than asking whether a site sits inside
    a neighbor's bounding box, matters because those boxes are rectangles: New York's covers
    most of eastern Pennsylvania."""
    dlat = radius_miles / MILES_PER_DEGREE_LAT
    dlon = radius_miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    needed = {"PA"}
    for i in range(samples):
        angle = 2 * math.pi * i / samples
        for fraction in (0.5, 1.0):
            sample_lat = lat + fraction * dlat * math.cos(angle)
            sample_lon = lon + fraction * dlon * math.sin(angle)
            if in_pennsylvania(sample_lat, sample_lon):
                continue
            for abbr, (_, (south, north, west, east)) in STATES.items():
                if abbr != "PA" and south <= sample_lat <= north and west <= sample_lon <= east:
                    needed.add(abbr)
    return sorted(needed)


def people_within(
    blocks: list[tuple[float, float, int, int]],
    lat: float,
    lon: float,
    radii: tuple[float, ...] = RADII_MILES,
) -> dict:
    """People and housing units within each radius, and the distance to the nearest populated
    block point."""
    biggest = max(radii)
    dlat = biggest / MILES_PER_DEGREE_LAT
    dlon = biggest / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    people = [0] * len(radii)
    homes = [0] * len(radii)
    nearest = None
    # The nearest populated block can be farther than the biggest radius in empty country;
    # searching a wider box keeps that number honest instead of reporting "none".
    wide_lat, wide_lon = dlat * 4, dlon * 4
    for blat, blon, pop, hu in blocks:
        if abs(blat - lat) > wide_lat or abs(blon - lon) > wide_lon:
            continue
        d = haversine_miles(lat, lon, blat, blon)
        if nearest is None or d < nearest:
            nearest = d
        if d > biggest:
            continue
        for i, r in enumerate(radii):
            if d <= r:
                people[i] += pop
                homes[i] += hu
    return {
        "radiiMiles": list(radii),
        "people": people,
        "homes": homes,
        "nearestHomesMiles": None if nearest is None else round(nearest, 2),
    }


# ------------------------------------------------------------------------------ HIFLD layers


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pa-grid-monitor-map-build/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def nearby_places(lat: float, lon: float, miles: float = 1.0) -> list[dict]:
    """Schools, hospitals, nursing homes and child-care centers within `miles` of the point,
    nearest first."""
    found: dict[tuple[str, str], dict] = {}
    for layer, kind in PLACE_LAYERS.items():
        query = urllib.parse.urlencode(
            {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "outSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "distance": miles,
                "units": "esriSRUnit_StatuteMile",
                "where": "1=1",
                "outFields": "NAME",
                "returnGeometry": "true",
                "f": "json",
            }
        )
        data = _get_json(f"{PASDA}/{layer}/query?{query}")
        if "error" in data:
            raise RuntimeError(f"layer {layer}: {data['error'].get('message')}")
        for feat in data.get("features", []):
            geom = feat.get("geometry") or {}
            if "x" not in geom:
                continue
            name = str(feat["attributes"].get("NAME") or "").strip().title()
            if not name:
                continue
            dist = haversine_miles(lat, lon, geom["y"], geom["x"])
            found[(kind, name.lower())] = {"kind": kind, "name": name, "miles": round(dist, 2)}
    return sorted(found.values(), key=lambda p: p["miles"])


def power_plants() -> list[dict]:
    """Pennsylvania's power plants from HIFLD with their summer capacity in MW."""
    query = urllib.parse.urlencode(
        {
            "where": "STATE='PA'",
            "outFields": "NAME,PRIM_FUEL,STATUS,SUMMER_CAP,LATITUDE,LONGITUDE",
            "returnGeometry": "false",
            "resultRecordCount": 2000,
            "f": "json",
        }
    )
    data = _get_json(f"{PASDA}/{POWER_PLANT_LAYER}/query?{query}")
    plants = []
    for feat in data.get("features", []):
        a = feat["attributes"]
        try:
            lat, lon = float(a["LATITUDE"]), float(a["LONGITUDE"])
        except (TypeError, ValueError):
            continue
        try:
            mw = float(a.get("SUMMER_CAP"))
        except (TypeError, ValueError):
            mw = None
        plants.append(
            {
                "rawName": str(a.get("NAME") or ""),
                "name": str(a.get("NAME") or "").title(),
                "fuel": FUEL_LABELS.get(str(a.get("PRIM_FUEL")), "Other"),
                "mw": None if mw is None or mw <= 0 else round(mw),
                "status": str(a.get("STATUS") or ""),
                "lat": lat,
                "lon": lon,
            }
        )
    return plants


def operating_plants(plants: list[dict], min_mw: float = 100) -> list[dict]:
    """Plants listed as operating with at least `min_mw` of summer capacity."""
    return [p for p in plants if p["status"] == "OP" and (p["mw"] or 0) >= min_mw]


def nearest_plant(lat: float, lon: float, plants: list[dict]) -> dict | None:
    """The closest plant in `plants`, with its distance in miles."""
    best, best_d = None, None
    for p in plants:
        d = haversine_miles(lat, lon, p["lat"], p["lon"])
        if best_d is None or d < best_d:
            best, best_d = p, d
    if best is None:
        return None
    return {"name": best["name"], "fuel": best["fuel"], "mw": best["mw"], "miles": round(best_d, 1)}
