"""Offline nearest-place lookup ("City, ST") for log-sheet remarks and stop labels,
plus each place's IANA time zone for local stop times.

The dataset (``trips/data/places.csv.gz``, built by ``scripts/build_places.py``) holds
~23k US/CA populated places. It is loaded lazily on first use and indexed into a
1-degree lat/lon grid; a lookup scans rings of cells around the query point, so it
never touches a network service (reverse-geocoding APIs are rate-limited).
"""

from __future__ import annotations

import csv
import gzip
import math
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "places.csv.gz"

EARTH_RADIUS_MI = 3958.8
CELL_DEG = 1.0
# Candidates within this radius compete on distance *and* size, so a stop 6 mi from
# Joliet (pop. 150k) is labelled "Joliet, IL" rather than a 600-person village 2 mi away.
# Only candidates in the nearest place's state/province compete, so a stop just inside
# Oklahoma is never labelled with the bigger town across the line ("Joplin, MO").
PREFERRED_RADIUS_MI = 25.0
POPULATION_WEIGHT_MI = 4.0  # miles of distance traded per 10x population
MAX_RING = 12  # cells; beyond ~800 mi we give up (query is far outside US/CA)

# Highway refs that read well in a remark: "I 80", "US 30", "IL 59", "TX 121", "ON 401",
# "Hwy 1", "CR 12", "Trans-Canada Highway" is a name, not a ref.
_HIGHWAY_REF = re.compile(
    r"^(I|US|SR|CR|Hwy|HWY|Highway|Route|RT|[A-Z]{2})[ -]?\d+[A-Z]?(?:\s?(?:Bus|Alt|Byp|Spur|Loop))?$"
)


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    admin: str  # state / province postal abbreviation
    lat: float
    lon: float
    population: int
    tz: str = ""  # IANA time zone, e.g. "America/Chicago"

    @property
    def label(self) -> str:
        return f"{self.name}, {self.admin}"


class PlaceIndex:
    def __init__(self, places: list[Place]):
        self._cells: dict[tuple[int, int], list[Place]] = {}
        for p in places:
            self._cells.setdefault(self._cell(p.lat, p.lon), []).append(p)
        self.size = len(places)

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / CELL_DEG), math.floor(lon / CELL_DEG))

    @classmethod
    def from_csv_gz(cls, path: Path) -> PlaceIndex:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            places = [
                Place(r["name"], r["admin"], float(r["lat"]), float(r["lon"]), int(r["population"] or 0), r["tz"])
                for r in csv.DictReader(fh)
            ]
        return cls(places)

    def _ring(self, cy: int, cx: int, r: int):
        """Yield the places in the square ring of cells at Chebyshev distance r."""
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dy), abs(dx)) == r:
                    yield from self._cells.get((cy + dy, cx + dx), ())

    def within(self, lat: float, lon: float, radius_mi: float) -> list[tuple[Place, float]]:
        """Every place within ``radius_mi`` of (lat, lon), as (place, distance_miles)."""
        cy, cx = self._cell(lat, lon)
        cell_mi = CELL_DEG * 69.0 * max(math.cos(math.radians(min(abs(lat) + CELL_DEG, 89.0))), 0.05)
        rings = min(MAX_RING, math.ceil(radius_mi / cell_mi))
        found = []
        for r in range(rings + 1):
            for p in self._ring(cy, cx, r):
                d = haversine_miles(lat, lon, p.lat, p.lon)
                if d <= radius_mi:
                    found.append((p, d))
        return found

    def nearest(self, lat: float, lon: float, prefer_populous: bool = True) -> tuple[Place, float] | None:
        """Return (place, distance_miles) for the best place near (lat, lon), or None."""
        cy, cx = self._cell(lat, lon)
        best: Place | None = None
        best_dist = math.inf
        candidates: list[tuple[Place, float]] = []
        # One cell is >= ~69 mi in latitude but narrower in longitude at high latitudes.
        cell_mi = CELL_DEG * 69.0 * max(math.cos(math.radians(min(abs(lat) + CELL_DEG, 89.0))), 0.05)
        for r in range(MAX_RING + 1):
            for p in self._ring(cy, cx, r):
                d = haversine_miles(lat, lon, p.lat, p.lon)
                if d < best_dist:
                    best, best_dist = p, d
                if d <= PREFERRED_RADIUS_MI:
                    candidates.append((p, d))
            # Everything outside ring r is at least r * cell_mi away.
            if best is not None and r * cell_mi >= max(best_dist, PREFERRED_RADIUS_MI):
                break
        if best is None:
            return None
        if prefer_populous and candidates:
            # The nearest place's admin is our proxy for the point's own state (no polygons offline).
            candidates = [c for c in candidates if c[0].admin == best.admin] or [(best, best_dist)]
            return min(candidates, key=lambda c: c[1] - POPULATION_WEIGHT_MI * math.log10(max(c[0].population, 1)))
        return best, best_dist


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(a)))


_index: PlaceIndex | None = None
_index_lock = threading.Lock()


def get_index() -> PlaceIndex:
    """Load the dataset once per process (thread-safe)."""
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = PlaceIndex.from_csv_gz(DATA_FILE)
    return _index


def nearest_place(lat: float, lon: float, prefer_populous: bool = True) -> tuple[str, str, float] | None:
    """Return (name, admin_abbrev, distance_miles) of the best nearby place, or None."""
    found = get_index().nearest(lat, lon, prefer_populous)
    if found is None:
        return None
    place, dist = found
    return place.name, place.admin, dist


FALLBACK_TZ = "UTC"  # only for points with no place within MAX_RING cells (far outside US/CA)


@lru_cache(maxsize=4096)
def _timezone_at(lat_r: float, lon_r: float) -> str:
    found = get_index().nearest(lat_r, lon_r, prefer_populous=False)
    return (found[0].tz if found else "") or FALLBACK_TZ


def timezone_at(lat: float, lon: float) -> str:
    """IANA time zone at (lat, lon): the zone of the nearest populated place."""
    return _timezone_at(round(lat, 2), round(lon, 2))


def highway_ref(road: str | None) -> str:
    """Return the first highway ref in an OSRM road string ("I 55; US 40" -> "I 55"), else ""."""
    if not road:
        return ""
    first = road.split(";")[0].split("/")[0].strip()
    return first if _HIGHWAY_REF.match(first) else ""


@lru_cache(maxsize=4096)
def _city_label(lat_r: float, lon_r: float) -> str:
    found = nearest_place(lat_r, lon_r)
    if found is None:
        return f"{lat_r:.3f}, {lon_r:.3f}"
    name, admin, _ = found
    return f"{name}, {admin}"


def place_namer(lat: float, lon: float, road: str | None = None) -> str:
    """Engine ``PlaceNamer``: "City, ST", or "I 80 near City, ST" when on a highway."""
    # Round to ~100 m so repeated lookups along a route hit the cache.
    city = _city_label(round(lat, 3), round(lon, 3))
    ref = highway_ref(road)
    return f"{ref} near {city}" if ref else city
