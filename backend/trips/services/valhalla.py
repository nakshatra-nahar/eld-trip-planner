"""Truck routing with Valhalla (FOSSGIS public server), failing over to OSRM.

``route_trip`` is the planner's single routing entry point. It routes both legs with
Valhalla's ``truck`` costing (truck-legal roads, truck speeds) and falls back to the
OSRM car route for the whole trip when any Valhalla call fails, times out or errors.

The public server rejects requests whose locations are more than 1,500 km apart in a
straight line (summed over the request). A longer leg is split at points on an
interstate/motorway taken from the OSRM route of the same trip; each chunk is routed
between ``break_through`` locations with the OSRM heading, and the chunks are stitched
back into one leg. Short hops are packed into as few requests as the limit allows, and
calls run one at a time with a small gap to respect the server's usage policy.

Each leg's ``LegProfile`` is built from the Valhalla shape: every maneuver's time is
spread over its shape segments in proportion to distance, then capped at 65 mph.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import accumulate, pairwise
from typing import Any
from urllib.parse import urlparse

import requests

from trips.hos.profile import LegProfile, LonLat, RouteStep

from .http import Deadline, session
from .places import haversine_miles, highway_ref
from .routing import RoutedLeg, RouteResult, fetch_route
from .units import METERS_PER_MILE, TRUCK_MAX_MPS

log = logging.getLogger(__name__)

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
PROVIDER = f"Valhalla truck ({urlparse(VALHALLA_URL).netloc})"
CALL_TIMEOUT_S = 12.0  # per request
CONNECT_TIMEOUT_S = 3.05
BUDGET_S = 15.0  # all Valhalla calls of one trip
FALLBACK_RESERVE_S = 8.0  # of the request budget, always left for the OSRM fallback
MIN_GAP_S = 0.25  # pause between consecutive calls (process-wide)

KM_PER_MILE = METERS_PER_MILE / 1000.0
MAX_REQUEST_KM = 1450.0  # server limit: 1,500 km straight-line, summed over a request
CHUNK_TARGET_KM = 1200.0  # road length per chunk when a leg is split
SPLIT_WINDOW_MI = 125.0  # how far a split may move from its ideal mile to reach an interstate
SPLIT_MARGIN_MI = 3.0  # keep splits this far inside an interstate step (away from interchanges)
SAME_POINT_MI = 0.05  # a leg this short (current == pickup) is not routed

# Valhalla maneuver type -> (Instruction.maneuver, Instruction.modifier), in OSRM's vocabulary.
# https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#trip-legs-and-maneuvers
_MANEUVERS: dict[int, tuple[str, str]] = {
    1: ("depart", ""), 2: ("depart", ""), 3: ("depart", ""),
    4: ("arrive", ""), 5: ("arrive", "right"), 6: ("arrive", "left"),
    7: ("new name", "straight"), 8: ("continue", "straight"),
    9: ("turn", "slight right"), 10: ("turn", "right"), 11: ("turn", "sharp right"),
    12: ("turn", "uturn"), 13: ("turn", "uturn"),
    14: ("turn", "sharp left"), 15: ("turn", "left"), 16: ("turn", "slight left"),
    17: ("on ramp", "straight"), 18: ("on ramp", "right"), 19: ("on ramp", "left"),
    20: ("off ramp", "right"), 21: ("off ramp", "left"),
    22: ("fork", "straight"), 23: ("fork", "right"), 24: ("fork", "left"),
    25: ("merge", ""), 37: ("merge", "slight right"), 38: ("merge", "slight left"),
    26: ("roundabout", ""), 27: ("exit roundabout", ""),
    28: ("notification", ""), 29: ("notification", ""),  # ferry enter / exit
}  # fmt: skip
_DEPART = {1, 2, 3}
_ARRIVE = {4, 5, 6}
_CONTINUE = 8
_ROUNDABOUT, _ROUNDABOUT_EXIT = 26, 27
_SAME_ROAD_TYPES = {7, 8}  # "becomes" / "continue": foldable when the road does not change


class TruckRouteError(Exception):
    """Valhalla could not route the trip (network, HTTP, error answer, malformed data)."""


@dataclass(frozen=True)
class Location:
    lon: float
    lat: float
    heading: float | None = None  # set on split points: travel direction on the motorway

    def to_json(self) -> dict[str, Any]:
        if self.heading is None:
            return {"lon": self.lon, "lat": self.lat, "type": "break"}
        # A pass-through point on the interstate: no U-turn, same carriageway as the OSRM route.
        return {
            "lon": self.lon,
            "lat": self.lat,
            "type": "break_through",
            "heading": round(self.heading) % 360,
            "heading_tolerance": 45,
            "search_filter": {"exclude_ramp": True},
        }


@dataclass
class _Hop:
    leg: int  # index of the trip leg this hop belongs to
    start: Location
    end: Location
    result: dict[str, Any] | None = None  # the Valhalla leg JSON, once routed


# ---------------------------------------------------------------- geometry helpers


def decode_polyline6(encoded: str) -> list[LonLat]:
    """Decode a Valhalla shape (Google polyline algorithm, precision 6) to (lon, lat) pairs."""
    coords: list[LonLat] = []
    index = lat = lon = 0
    n = len(encoded)
    while index < n:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lon / 1e6, lat / 1e6))
    return coords


def _miles(a: LonLat, b: LonLat) -> float:
    return haversine_miles(a[1], a[0], b[1], b[0])


def _bearing(a: LonLat, b: LonLat) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlon = math.radians(b[0] - a[0])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


_CARDINAL = re.compile(r"\s+(?:North|South|East|West|[NSEW])$")


def road_of(street_names: list[str] | None) -> str:
    """Road label for a maneuver: its first highway ref without the direction ("I 65 South"
    -> "I 65", as OSRM refs read), else its first name."""
    names = [n.strip() for n in street_names or [] if n and n.strip()]
    refs = [highway_ref(_CARDINAL.sub("", n)) for n in names]
    return next((r for r in refs if r), names[0] if names else "")


# ---------------------------------------------------------------- splitting long legs


def _is_motorway(step: dict[str, Any], road: str) -> bool:
    if road.startswith("I "):
        return True
    return any("motorway" in (i.get("classes") or []) for i in step.get("intersections") or [])


def split_points(osrm_leg: RoutedLeg, n_chunks: int) -> list[Location]:
    """``n_chunks - 1`` split points along an OSRM leg, each placed on an interstate or
    motorway near its ideal (evenly spaced) mile when one is within ``SPLIT_WINDOW_MI``."""
    profile = osrm_leg.profile
    spans: list[tuple[float, float]] = []
    for raw, step in zip(osrm_leg.steps, profile.steps, strict=False):
        if _is_motorway(raw, step.road):
            margin = min(SPLIT_MARGIN_MI, (step.end_mile - step.start_mile) / 4)
            spans.append((step.start_mile + margin, step.end_mile - margin))

    points: list[Location] = []
    for k in range(1, n_chunks):
        ideal = profile.total_miles * k / n_chunks
        mile = ideal
        if spans:
            best = min((min(max(ideal, lo), hi) for lo, hi in spans), key=lambda m: abs(m - ideal))
            if abs(best - ideal) <= SPLIT_WINDOW_MI:
                mile = best
        here = profile.coord_at_mile(mile)
        heading = _bearing(profile.coord_at_mile(max(mile - 0.2, 0.0)), profile.coord_at_mile(mile + 0.2))
        points.append(Location(round(here[0], 6), round(here[1], 6), heading))
    return points


def _chunks_needed(osrm_leg: RoutedLeg) -> int:
    return max(2, math.ceil(osrm_leg.distance_miles * KM_PER_MILE / CHUNK_TARGET_KM))


def _pack(hops: list[_Hop]) -> list[list[_Hop]]:
    """Group consecutive hops into requests whose straight-line length stays under the limit."""
    batches: list[list[_Hop]] = []
    total = math.inf
    for hop in hops:
        km = _miles((hop.start.lon, hop.start.lat), (hop.end.lon, hop.end.lat)) * KM_PER_MILE
        if km > MAX_REQUEST_KM:
            raise TruckRouteError(f"a {km:.0f} km chunk exceeds the request limit")
        if total + km > MAX_REQUEST_KM:
            batches.append([])
            total = 0.0
        batches[-1].append(hop)
        total += km
    return batches


# ---------------------------------------------------------------- HTTP


_call_lock = threading.Lock()
_last_call_end = 0.0


def _post(body: dict[str, Any], deadline: Deadline) -> dict[str, Any]:
    """One Valhalla request (serialised process-wide, ``MIN_GAP_S`` apart)."""
    global _last_call_end
    with _call_lock:
        wait = _last_call_end + MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        if deadline.expired:
            raise TruckRouteError("time budget exhausted")
        read = deadline.timeout(CALL_TIMEOUT_S)
        try:
            resp = session().post(VALHALLA_URL, json=body, timeout=(min(CONNECT_TIMEOUT_S, read), read))
        except requests.RequestException as exc:
            raise TruckRouteError(f"{exc.__class__.__name__}: {exc}") from exc
        finally:
            _last_call_end = time.monotonic()
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise TruckRouteError(f"HTTP {resp.status_code}: not JSON")
    if resp.status_code != 200 or "trip" not in data:
        raise TruckRouteError(f"HTTP {resp.status_code}: error {data.get('error_code')} {data.get('error')}")
    return data["trip"]


def request_body(locations: list[Location]) -> dict[str, Any]:
    return {
        "locations": [loc.to_json() for loc in locations],
        "costing": "truck",
        "units": "miles",
        "directions_options": {"units": "miles", "language": "en-US"},
    }


# ---------------------------------------------------------------- building legs


def _stitch(parts: list[dict[str, Any]]) -> tuple[list[LonLat], list[dict[str, Any]]]:
    """Join a leg's routed chunks into one shape and one maneuver list (global shape indices).

    At each seam the chunk's "arrive" is dropped and the next chunk's "depart" is folded into
    the maneuver before it (same road), or becomes a "continue" onto the new road.
    """
    coords: list[LonLat] = []
    maneuvers: list[dict[str, Any]] = []
    for part in parts:
        shape = decode_polyline6(part["shape"])
        if len(shape) < 2:
            raise ValueError("chunk shape has fewer than 2 points")
        offset = len(coords)
        if coords and _miles(coords[-1], shape[0]) < 0.01:
            offset -= 1  # the seam vertex is shared
            shape = shape[1:]
        coords.extend(shape)
        for i, raw in enumerate(part["maneuvers"]):
            m = {
                "type": int(raw["type"]),
                "instruction": str(raw.get("instruction") or ""),
                "street_names": list(raw.get("street_names") or []),
                "time": float(raw.get("time") or 0.0),
                "begin": offset + int(raw["begin_shape_index"]),
                "end": offset + int(raw["end_shape_index"]),
            }
            if i == 0 and maneuvers and m["type"] in _DEPART:
                if maneuvers[-1]["type"] in _ARRIVE:
                    maneuvers.pop()
                prev = maneuvers[-1]
                road = road_of(m["street_names"])
                if road == road_of(prev["street_names"]) or set(prev["street_names"]) & set(m["street_names"]):
                    prev["end"], prev["time"] = m["end"], prev["time"] + m["time"]
                    continue
                m.update(type=_CONTINUE, instruction=f"Continue on {road}." if road else "Continue.", begin=prev["end"])
            maneuvers.append(m)
    if not maneuvers or maneuvers[-1]["end"] >= len(coords) or maneuvers[0]["begin"] != 0:
        raise ValueError("maneuver shape indices do not cover the shape")
    return coords, maneuvers


def build_leg(parts: list[dict[str, Any]]) -> RoutedLeg:
    """A ``RoutedLeg`` from one trip leg's Valhalla chunk(s), with a truck-capped profile."""
    coords, maneuvers = _stitch(parts)
    seg_miles = [_miles(a, b) for a, b in pairwise(coords)]
    # Valhalla's leg lengths are authoritative; the haversine shape sum is within a hair of them.
    official = sum(float((part.get("summary") or {}).get("length") or 0.0) for part in parts)
    shape_total = sum(seg_miles)
    if official > 0 and shape_total > 0:
        seg_miles = [d * official / shape_total for d in seg_miles]

    seg_seconds = [0.0] * len(seg_miles)
    for m in maneuvers:
        span = range(m["begin"], m["end"])
        miles = sum(seg_miles[i] for i in span)
        for i in span:
            seg_seconds[i] = m["time"] * seg_miles[i] / miles if miles > 0 else 0.0
    seg_minutes = [
        max(secs, miles * METERS_PER_MILE / TRUCK_MAX_MPS) / 60.0
        for miles, secs in zip(seg_miles, seg_seconds, strict=True)
    ]

    cum_miles = [0.0, *accumulate(seg_miles)]
    steps = [
        RouteStep(cum_miles[m["begin"]], cum_miles[m["end"]], road_of(m["street_names"]))
        for m in maneuvers
        if m["end"] > m["begin"]
    ]
    profile = LegProfile(coords, seg_miles, seg_minutes, steps)
    return RoutedLeg(
        profile=profile,
        coords=coords,
        steps=[],
        distance_miles=profile.total_miles,
        duration_hours=profile.total_minutes / 60.0,
        maneuvers=maneuvers,
    )


def _still_leg(point: LonLat) -> RoutedLeg:
    """A zero-length leg (current == pickup), like OSRM's degenerate leg."""
    profile = LegProfile([point, point], [0.0], [0.0])
    return RoutedLeg(profile, [point, point], [], 0.0, 0.0, maneuvers=[])


# ---------------------------------------------------------------- public API


def fetch_truck_route(waypoints: list[LonLat], deadline: Deadline, osrm: Callable[[], RouteResult]) -> RouteResult:
    """Route the trip with Valhalla's truck costing. Raises ``TruckRouteError`` on any failure.

    ``osrm()`` returns the OSRM route of the same waypoints; it is only called when a leg
    is too long for one Valhalla request and needs split points.
    """
    stops = [Location(round(lon, 6), round(lat, 6)) for lon, lat in waypoints]
    hops: list[_Hop] = []
    for i, (a, b) in enumerate(pairwise(stops)):
        crow_km = _miles((a.lon, a.lat), (b.lon, b.lat)) * KM_PER_MILE
        if crow_km < SAME_POINT_MI * KM_PER_MILE:
            continue
        points = [a, b]
        if crow_km > MAX_REQUEST_KM:
            osrm_leg = osrm().legs[i]
            points = [a, *split_points(osrm_leg, _chunks_needed(osrm_leg)), b]
        hops.extend(_Hop(i, s, e) for s, e in pairwise(points))

    batches = _pack(hops)
    log.debug("Valhalla: %d hop(s) in %d request(s)", len(hops), len(batches))
    for batch in batches:
        trip = _post(request_body([batch[0].start, *(h.end for h in batch)]), deadline)
        legs = trip.get("legs") or []
        if trip.get("status") not in (0, None) or len(legs) != len(batch):
            raise TruckRouteError(f"unexpected answer: status {trip.get('status')}, {len(legs)} legs for {len(batch)}")
        for hop, leg in zip(batch, legs, strict=True):
            hop.result = leg

    routed: list[RoutedLeg] = []
    for i in range(len(waypoints) - 1):
        parts = [h.result for h in hops if h.leg == i and h.result is not None]
        try:
            routed.append(build_leg(parts) if parts else _still_leg(waypoints[i + 1]))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise TruckRouteError(f"malformed route: {exc}") from exc
    snap = [_miles(waypoints[0], routed[0].coords[0])]
    snap += [_miles(waypoints[i + 1], leg.coords[-1]) for i, leg in enumerate(routed)]
    return RouteResult(legs=routed, provider=PROVIDER, snap_miles=snap, truck_routing=True)


class OsrmRoute:
    """The trip's OSRM route, fetched at most once (for split points or the fallback)."""

    def __init__(self, waypoints: list[LonLat], deadline: Deadline):
        self._waypoints, self._deadline = waypoints, deadline
        self._route: RouteResult | None = None

    def __call__(self) -> RouteResult:
        if self._route is None:
            self._route = fetch_route(self._waypoints, deadline=self._deadline)
        return self._route


def route_trip(waypoints: list[LonLat], deadline: Deadline | None = None) -> RouteResult:
    """Truck route through ``waypoints`` [(lon, lat), ...]; the OSRM car route if Valhalla fails.

    OSRM's own errors (``RouteNotFound``, ``UpstreamUnavailable``) propagate unchanged.
    """
    deadline = deadline or Deadline(None)
    osrm = OsrmRoute(waypoints, deadline)
    remaining = deadline.remaining()
    budget = BUDGET_S if remaining is None else min(BUDGET_S, remaining - FALLBACK_RESERVE_S)
    if budget > 1.0:
        started = time.monotonic()
        try:
            route = fetch_truck_route(waypoints, Deadline(budget), osrm)
            log.info("Valhalla truck route in %.2fs", time.monotonic() - started)
            return route
        except TruckRouteError as exc:
            log.warning("Valhalla failed after %.2fs, falling back to OSRM: %s", time.monotonic() - started, exc)
    return osrm()


# ---------------------------------------------------------------- instructions


def _instruction_text(m: dict[str, Any], arrive_label: str | None) -> str:
    if m["type"] in _ARRIVE:
        side = {5: ", on the right", 6: ", on the left"}.get(m["type"], "")
        return f"Arrive at {arrive_label or 'your destination'}{side}"
    # One line per maneuver, no trailing period (like the OSRM text):
    # "Turn left onto 5th Street. Continue on US 66." -> "Turn left onto 5th Street, then continue on US 66".
    return m["instruction"].strip().rstrip(".").replace(". Continue on ", ", then continue on ")


def build_instructions(leg: RoutedLeg, arrive_label: str | None = None) -> list[dict[str, Any]]:
    """``Instruction`` dicts (see frontend api.ts) from a Valhalla leg's maneuvers.

    Valhalla's English text is used as is (the final line names the stop). Distance and
    duration come from the leg profile, so they add up to the leg's truck-adjusted totals.
    A roundabout exit, and a "continue" that stays on the same road, fold into the line before.
    """
    cum_miles, cum_minutes = leg.profile.cum_miles, leg.profile.cum_minutes
    out: list[dict[str, Any]] = []
    for m in leg.maneuvers or []:
        maneuver, modifier = _MANEUVERS.get(m["type"], ("continue", ""))
        road = road_of(m["street_names"])
        prev = out[-1] if out else None
        foldable = m["type"] == _ROUNDABOUT_EXIT and prev is not None and prev["maneuver"] == "roundabout"
        foldable |= m["type"] in _SAME_ROAD_TYPES and prev is not None and bool(road) and road == prev["road"]
        if prev is not None and foldable:
            prev["_end"] = m["end"]
            prev["road"] = prev["road"] or road  # a roundabout line names the road it exits onto
            continue
        lon, lat = leg.coords[m["begin"]]
        out.append(
            {
                "text": _instruction_text(m, arrive_label),
                "maneuver": maneuver,
                "modifier": modifier,
                "road": road,
                "location": [round(lon, 6), round(lat, 6)],
                "_begin": m["begin"],
                "_end": m["end"],
            }
        )
    for ins in out:
        begin, end = ins.pop("_begin"), ins.pop("_end")
        ins["distance_miles"] = round(cum_miles[end] - cum_miles[begin], 2)
        ins["duration_minutes"] = round((cum_minutes[end] - cum_minutes[begin]), 1)
    return out
