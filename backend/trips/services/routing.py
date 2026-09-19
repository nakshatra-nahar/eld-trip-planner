"""OSRM routing client with host failover, turned into HOS ``LegProfile``s.

One request with three waypoints (current -> pickup -> dropoff) yields two legs.
Each leg's per-segment annotations become a ``LegProfile`` whose segment minutes are
truck-adjusted: every segment takes ``max(osrm_seconds, distance / 65 mph)``, since
OSRM's car profile happily assumes 75+ mph on rural interstates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from trips.hos.profile import LegProfile, RouteStep

from .errors import RouteNotFound, UpstreamUnavailable
from .http import Deadline, session

log = logging.getLogger(__name__)

OSRM_HOSTS = (
    "https://router.project-osrm.org",
    "https://routing.openstreetmap.de/routed-car",
)
TIMEOUT_S = 15.0
ATTEMPTS_PER_HOST = 2  # 1 retry
METERS_PER_MILE = 1609.344
TRUCK_SPEED_CAP_MPH = 65.0
TRUCK_MAX_MPS = TRUCK_SPEED_CAP_MPH * METERS_PER_MILE / 3600.0

# OSRM "code" values meaning "your input has no route" (not a server problem).
_NO_ROUTE_CODES = {"NoRoute", "NoSegment", "NoMatch", "NoTrips", "InvalidValue", "InvalidQuery", "TooBig"}

LonLat = tuple[float, float]


@dataclass
class RoutedLeg:
    profile: LegProfile
    coords: list[LonLat]  # full-resolution leg polyline (lon, lat)
    steps: list[dict[str, Any]]  # raw OSRM steps, for instructions
    distance_miles: float
    duration_hours: float  # truck-adjusted driving time


@dataclass
class RouteResult:
    legs: list[RoutedLeg]
    provider: str  # e.g. "OSRM (router.project-osrm.org)"
    snap_miles: list[float] = field(default_factory=list)  # input -> snapped waypoint distance


def _truck_minutes(dist_m: float, dur_s: float) -> float:
    return max(dur_s, dist_m / TRUCK_MAX_MPS) / 60.0


def _step_road(step: dict[str, Any]) -> str:
    ref = (step.get("ref") or "").split(";")[0].strip()
    return ref or (step.get("name") or "").strip()


def _leg_steps(steps: list[dict[str, Any]], total_miles: float) -> list[RouteStep]:
    """Leg-relative ``RouteStep``s, scaled so step miles agree with the annotation total."""
    raw = [float(s.get("distance") or 0.0) / METERS_PER_MILE for s in steps]
    scale = total_miles / sum(raw) if sum(raw) > 0 else 0.0
    out: list[RouteStep] = []
    mile = 0.0
    for step, miles in zip(steps, raw):
        end = mile + miles * scale
        out.append(RouteStep(start_mile=mile, end_mile=end, road=_step_road(step)))
        mile = end
    return out


def parse_route(data: dict[str, Any], provider: str = "OSRM") -> RouteResult:
    """Convert an OSRM ``/route`` JSON body (code "Ok") into a ``RouteResult``.

    Raises ``RouteNotFound`` for "no route" answers and ``ValueError`` if the payload is
    malformed (callers treat that as an upstream failure).
    """
    code = data.get("code")
    if code != "Ok":
        raise RouteNotFound(_no_route_message(code, data.get("message")))
    routes = data.get("routes") or []
    if not routes:
        raise RouteNotFound("No drivable route was found between these locations.")
    route = routes[0]
    geometry: list[list[float]] = route["geometry"]["coordinates"]
    legs_json = route["legs"]

    # With overview=full, the route polyline is the concatenation of the legs'
    # annotation nodes, consecutive legs sharing their waypoint vertex.
    counts = [len(leg["annotation"]["distance"]) + 1 for leg in legs_json]
    if len(geometry) != sum(counts) - (len(counts) - 1):
        raise ValueError(f"geometry has {len(geometry)} points; annotations imply {sum(counts) - len(counts) + 1}")

    legs: list[RoutedLeg] = []
    offset = 0
    for leg, n in zip(legs_json, counts):
        coords = [(float(c[0]), float(c[1])) for c in geometry[offset : offset + n]]
        offset += n - 1
        dist_m = [float(d) for d in leg["annotation"]["distance"]]
        dur_s = [float(d) for d in leg["annotation"]["duration"]]
        if len(dur_s) != len(dist_m):
            raise ValueError("annotation distance/duration length mismatch")
        # Annotations omit OSRM's turn/signal penalties, which the leg total includes;
        # spread that gap over the segments so the truck is never faster than OSRM.
        gap_scale = float(leg.get("duration") or 0.0) / sum(dur_s) if sum(dur_s) > 0 else 1.0
        dur_s = [t * max(gap_scale, 1.0) for t in dur_s]
        seg_miles = [d / METERS_PER_MILE for d in dist_m]
        seg_minutes = [_truck_minutes(d, t) for d, t in zip(dist_m, dur_s)]
        if len(coords) < 2:  # degenerate zero-length leg (current == pickup)
            coords = coords * 2 if coords else [(0.0, 0.0), (0.0, 0.0)]
            seg_miles, seg_minutes = [0.0], [0.0]
        steps = leg.get("steps") or []
        profile = LegProfile(coords, seg_miles, seg_minutes, _leg_steps(steps, sum(seg_miles)))
        legs.append(
            RoutedLeg(
                profile=profile,
                coords=coords,
                steps=steps,
                distance_miles=profile.total_miles,
                duration_hours=profile.total_minutes / 60.0,
            )
        )
    snap = [float(w.get("distance") or 0.0) / METERS_PER_MILE for w in data.get("waypoints") or []]
    return RouteResult(legs=legs, provider=provider, snap_miles=snap)


def _no_route_message(code: str | None, message: str | None) -> str:
    if code == "NoSegment":
        return "One of the locations is too far from any drivable road."
    if code in ("NoRoute", None):
        return "No drivable route was found between these locations."
    return f"The routing service could not route this trip ({code}: {message or 'no details'})."


def route_url(host: str, waypoints: list[LonLat]) -> str:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in waypoints)
    return f"{host}/route/v1/driving/{coords}"


ROUTE_PARAMS = {
    "overview": "full",
    "geometries": "geojson",
    "steps": "true",
    "annotations": "distance,duration",
}


def fetch_route(waypoints: list[LonLat], deadline: Deadline | None = None) -> RouteResult:
    """Route through ``waypoints`` [(lon, lat), ...], trying each OSRM host in turn."""
    deadline = deadline or Deadline(None)
    failures: list[str] = []
    for host in OSRM_HOSTS:
        provider = f"OSRM ({urlparse(host).netloc})"
        for attempt in range(ATTEMPTS_PER_HOST):
            if deadline.expired:
                raise UpstreamUnavailable("Routing timed out. Please try again.")
            try:
                resp = session().get(route_url(host, waypoints), params=ROUTE_PARAMS, timeout=deadline.timeout(TIMEOUT_S))
            except requests.RequestException as exc:
                failures.append(f"{provider}: {exc.__class__.__name__}")
                log.warning("OSRM %s attempt %d failed: %s", host, attempt + 1, exc)
                continue
            # OSRM reports "no route" as HTTP 400 with a JSON code; that is final.
            if resp.status_code in (200, 400):
                try:
                    data = resp.json()
                except ValueError:
                    data = None
                if isinstance(data, dict) and data.get("code") in _NO_ROUTE_CODES:
                    raise RouteNotFound(_no_route_message(data.get("code"), data.get("message")))
                if resp.status_code == 200 and isinstance(data, dict):
                    try:
                        return parse_route(data, provider)
                    except (ValueError, KeyError, TypeError, IndexError) as exc:
                        failures.append(f"{provider}: malformed response")
                        log.warning("OSRM %s returned a malformed route: %s", host, exc)
                        break  # a malformed answer will not fix itself on retry
            failures.append(f"{provider}: HTTP {resp.status_code}")
            log.warning("OSRM %s attempt %d: HTTP %s", host, attempt + 1, resp.status_code)
    raise UpstreamUnavailable(
        "The routing service is unavailable right now. Please try again in a minute.",
        details={"upstream": failures} if failures else None,
    )
