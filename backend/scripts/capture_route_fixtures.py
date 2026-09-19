#!/usr/bin/env python3
"""Record real OSRM + Valhalla exchanges as offline test fixtures.

Runs ``valhalla.route_trip`` for each trip below against the live services and saves
every request/response pair to ``trips/tests/fixtures/route_<name>.json.gz``:

    {"waypoints": [[lon, lat], ...],
     "osrm": <OSRM /route JSON or null>,          # only fetched for legs that need split points
     "valhalla": [{"request": {...}, "response": {...}}, ...]}

OSRM step geometries and intersection details other than ``classes`` are dropped to keep
the files small; nothing the parsers read is removed.

Usage (from ``backend/``):  uv run python scripts/capture_route_fixtures.py [name ...]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from trips.services import routing, valhalla  # noqa: E402
from trips.services.http import Deadline, session  # noqa: E402

FIXTURES = BACKEND_DIR / "trips" / "tests" / "fixtures"

TRIPS: dict[str, list[tuple[float, float]]] = {
    # Two short legs packed into one Valhalla request.
    "indy_louisville_atlanta": [(-86.158, 39.768), (-85.7585, 38.2527), (-84.388, 33.749)],
    # A 2,500-mile loaded leg split into chunks at interstate points from the OSRM route.
    "la_phoenix_nyc": [(-118.2437, 34.0522), (-112.074, 33.4484), (-74.006, 40.7128)],
}


def _slim_osrm(data: dict[str, Any]) -> dict[str, Any]:
    for route in data.get("routes", []):
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                step.pop("geometry", None)
                step["intersections"] = [
                    {"classes": i["classes"]} if i.get("classes") else {} for i in step.get("intersections", [])
                ]
    return data


class Recorder:
    """Wraps the real session and records OSRM GETs and Valhalla POSTs."""

    def __init__(self) -> None:
        self.osrm: dict[str, Any] | None = None
        self.valhalla: list[dict[str, Any]] = []

    def get(self, url: str, params: dict | None = None, timeout: Any = None):
        resp = session().get(url, params=params, timeout=timeout)
        self.osrm = resp.json()
        return resp

    def post(self, url: str, json: dict | None = None, timeout: Any = None):
        resp = session().post(url, json=json, timeout=timeout)
        self.valhalla.append({"request": json, "response": resp.json()})
        return resp


def capture(name: str) -> None:
    recorder = Recorder()
    routing.session = valhalla.session = lambda: recorder
    waypoints = TRIPS[name]
    result = valhalla.route_trip(waypoints, Deadline(60))
    if not result.truck_routing:
        raise SystemExit(f"{name}: Valhalla failed; not saving an OSRM-only fixture")
    payload = {
        "waypoints": waypoints,
        "osrm": _slim_osrm(recorder.osrm) if recorder.osrm else None,
        "valhalla": recorder.valhalla,
    }
    path = FIXTURES / f"route_{name}.json.gz"
    with open(path, "wb") as out, gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(json.dumps(payload, separators=(",", ":")).encode())
    miles = [round(leg.distance_miles, 1) for leg in result.legs]
    print(f"{name}: {len(recorder.valhalla)} Valhalla call(s), legs {miles} mi -> {path.name}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", metavar="name", help=f"trips to capture (default: {', '.join(TRIPS)})")
    names = parser.parse_args().names or list(TRIPS)
    unknown = set(names) - set(TRIPS)
    if unknown:
        parser.error(f"unknown trip(s): {', '.join(sorted(unknown))}")
    for name in names:
        capture(name)


if __name__ == "__main__":
    main()
