"""Place a project on the map from public data, with no key.

    python scripts/map/locate.py muni "Archbald|Lackawanna" "Upper Merion|Montgomery"
    python scripts/map/locate.py addr "900 Conshohocken Rd, Conshohocken, PA 19428"

`muni` returns the Census 2020 internal point of a township, borough or city (use these for
precision "municipality", which the map reports as "not measured"). A name starting with "="
must match exactly, because "Swatara" also matches "Lower Swatara". `addr` uses the Census
street-address geocoder (use these for precision "site"). Neither is a property line.
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
GAZ = CACHE / "2020_gaz_cousubs_42.txt"
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_gaz_cousubs_42.txt"
PA_GEO = HERE.parent.parent / "frontend" / "src" / "data" / "paGeo.ts"


def county_fips() -> dict[str, str]:
    text = PA_GEO.read_text(encoding="utf-8")
    pattern = r'"fips":\s*"(\d+)",\s*"name":\s*"([^"]+)"'
    return {m.group(2).lower(): m.group(1) for m in re.finditer(pattern, text)}


def load_gazetteer() -> list[dict]:
    if not GAZ.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        GAZ.write_bytes(urllib.request.urlopen(GAZ_URL, timeout=60).read())
    rows = []
    for line in GAZ.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        p = [x.strip() for x in line.split("\t")]
        if len(p) >= 11:
            rows.append({"geoid": p[1], "name": p[3], "lat": float(p[9]), "lon": float(p[10])})
    return rows


def municipality(name: str, county: str) -> list[dict]:
    fips = county_fips().get(county.lower())
    if not fips:
        raise SystemExit(f"unknown county {county!r}")
    exact = name.startswith("=")
    needle = name.lstrip("=").lower()
    return [
        r
        for r in load_gazetteer()
        if r["geoid"].startswith(fips)
        and (r["name"].lower() == needle if exact else needle in r["name"].lower())
    ]


def geocode(address: str) -> list[tuple[str, float, float]]:
    query = urllib.parse.urlencode(
        {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    )
    url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + query
    data = json.load(urllib.request.urlopen(url, timeout=30))
    return [
        (m["matchedAddress"], m["coordinates"]["y"], m["coordinates"]["x"])
        for m in data["result"]["addressMatches"]
    ]


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("muni", "addr"):
        raise SystemExit(__doc__)
    for arg in sys.argv[2:]:
        if sys.argv[1] == "muni":
            name, county = arg.split("|")
            print(arg, "->", municipality(name, county))
        else:
            print(arg, "->", geocode(arg))
