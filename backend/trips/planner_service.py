"""Orchestrates one trip plan: geocode -> route -> HOS engine -> ``PlanResponse`` dict.

The view hands over already-validated input (see ``PlanRequestSerializer``); every
failure surfaces as a ``ServiceError`` subclass carrying its ApiError code/status.

The engine works in naive home-terminal time (the current location's zone), which the log
sheets keep, per FMCSA. This layer adds each place's IANA zone and the local wall-clock
times of every event and stop, for the itinerary.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from trips import hos
from trips.services.errors import GeocodeFailed, UnsupportedRegion
from trips.services.geocoding import geocode_one, reverse
from trips.services.geometry import round_coords, simplify_many
from trips.services.http import Deadline
from trips.services.instructions import build_instructions
from trips.services.places import place_namer, timezone_at
from trips.services.routing import RoutedLeg, RouteResult
from trips.services.valhalla import build_instructions as build_truck_instructions
from trips.services.valhalla import route_trip

log = logging.getLogger(__name__)

ROLES = ("current", "pickup", "dropoff")
FIELDS = {role: f"{role}_location" for role in ROLES}
MAX_DISPLAY_POINTS = 1500
SNAP_WARNING_MILES = 2.0
ZERO_LEG_MILES = 0.1
DEFAULT_BUDGET_S = 25.0
TIME_FORMAT = "%Y-%m-%dT%H:%M"


def _resolve_location(role: str, loc: dict[str, Any], deadline: Deadline) -> dict[str, Any]:
    """Turn a ``LocationInput`` into a ``ResolvedLocation`` (label, lat, lon)."""
    label = (loc.get("label") or "").strip()
    if loc.get("lat") is not None and loc.get("lon") is not None:
        lat, lon = float(loc["lat"]), float(loc["lon"])
        if reverse(lat, lon) is None:  # no US/CA place within REVERSE_MAX_MILES
            raise UnsupportedRegion(
                "Locations must be in the United States or Canada.",
                details={FIELDS[role]: ["This point is outside the United States and Canada."]},
            )
        return {"label": label or place_namer(lat, lon, None), "lat": round(lat, 6), "lon": round(lon, 6)}

    query = loc["query"]
    hit = geocode_one(query, deadline=deadline)
    if hit is None:
        raise GeocodeFailed(
            f'Could not find the {role} location "{query}". Try a city and state, e.g. "Joliet, IL".',
            details={FIELDS[role]: [f'No US or Canadian match for "{query}".']},
        )
    return {"label": label or hit["short_label"], "lat": hit["lat"], "lon": hit["lon"]}


def _resolve_all(data: dict[str, Any], deadline: Deadline) -> dict[str, dict[str, Any]]:
    """Resolve the three locations, geocoding free-text ones concurrently."""
    needs_network = [r for r in ROLES if data[FIELDS[r]].get("lat") is None]
    if len(needs_network) <= 1:
        return {r: _resolve_location(r, data[FIELDS[r]], deadline) for r in ROLES}
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="geocode") as pool:
        futures = {r: pool.submit(_resolve_location, r, data[FIELDS[r]], deadline) for r in ROLES}
        return {r: futures[r].result() for r in ROLES}


def _instructions(leg: RoutedLeg, arrive_label: str) -> list[dict[str, Any]]:
    if leg.distance_miles < ZERO_LEG_MILES:  # (near) zero-length leg: nothing to follow
        return []
    if leg.maneuvers is not None:
        return build_truck_instructions(leg, arrive_label)
    return build_instructions(leg.steps, arrive_label=arrive_label, total_minutes=leg.duration_hours * 60)


def _route_payload(route: RouteResult, resolved: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build ``RouteInfo``: simplified geometries, per-leg stats and instructions."""
    simplified = simplify_many([leg.coords for leg in route.legs], MAX_DISPLAY_POINTS)
    full: list = []
    for i, line in enumerate(simplified):
        full.extend(line if i == 0 else line[1:])  # legs share their waypoint vertex

    legs = []
    for i, (leg, line) in enumerate(zip(route.legs, simplified, strict=True)):
        to_role = ROLES[i + 1]
        arrive = f"{to_role} ({resolved[to_role]['label']})"
        legs.append(
            {
                "from_role": ROLES[i],
                "to_role": to_role,
                "distance_miles": round(leg.distance_miles, 1),
                "duration_hours": round(leg.duration_hours, 2),
                "geometry": round_coords(line),
                "instructions": _instructions(leg, arrive),
            }
        )
    return {
        "distance_miles": round(sum(leg.distance_miles for leg in route.legs), 1),
        "duration_hours": round(sum(leg.duration_hours for leg in route.legs), 2),
        "geometry": round_coords(full),
        "legs": legs,
        "provider": route.provider,
        "truck_routing": route.truck_routing,
    }


def _routing_warnings(route: RouteResult) -> list[str]:
    warnings = []
    if not route.truck_routing:
        warnings.append(
            "Truck routing was unavailable, so this route follows the car road network (OSRM) with a 65 mph cap; "
            "check it for truck restrictions."
        )
    for role, miles in zip(ROLES, route.snap_miles, strict=False):  # snap_miles may be empty
        if miles >= SNAP_WARNING_MILES:
            warnings.append(
                f"The {role} location is {miles:.1f} mi from the nearest drivable road; the route starts/ends there."
            )
    if route.legs and route.legs[0].distance_miles < ZERO_LEG_MILES:
        warnings.append("Current location is at the pickup, so there is no driving before pickup.")
    if len(route.legs) > 1 and route.legs[1].distance_miles < ZERO_LEG_MILES:
        warnings.append("Pickup and dropoff are at the same place, so the loaded leg has no driving.")
    return warnings


def _local(value: str, home: ZoneInfo, zone: ZoneInfo) -> tuple[str, str]:
    """Home-terminal wall time -> (wall time, zone abbreviation) in ``zone``."""
    local = datetime.strptime(value, TIME_FORMAT).replace(tzinfo=home).astimezone(zone)
    return local.strftime(TIME_FORMAT), local.tzname() or ""


def _add_local_times(plan: dict[str, Any], home: ZoneInfo) -> None:
    """Add ``tz`` to every place ref, and each event's and stop's local wall-clock times."""

    def zone_of(place: dict[str, Any]) -> ZoneInfo:
        place["tz"] = timezone_at(place["lat"], place["lon"])
        return ZoneInfo(place["tz"])

    for event in plan["timeline"]:
        start_zone, end_zone = zone_of(event["start_location"]), zone_of(event["end_location"])
        event["local_start"], event["start_tz_abbr"] = _local(event["start"], home, start_zone)
        event["local_end"], event["end_tz_abbr"] = _local(event["end"], home, end_zone)
    for stop in plan["stops"]:
        zone = zone_of(stop["location"])
        stop["local_start"], stop["local_tz_abbr"] = _local(stop["start"], home, zone)
        stop["local_end"], _ = _local(stop["end"], home, zone)


def plan_trip(data: dict[str, Any], budget_s: float = DEFAULT_BUDGET_S) -> dict[str, Any]:
    """Plan a trip from validated ``PlanRequestSerializer`` data; returns a ``PlanResponse`` dict."""
    started = time.monotonic()
    deadline = Deadline(budget_s)
    options: dict[str, Any] = data["options"]
    start_time: datetime = data["start_time"]
    cycle_used = float(data["current_cycle_used_hours"])

    resolved = _resolve_all(data, deadline)
    waypoints = [(resolved[r]["lon"], resolved[r]["lat"]) for r in ROLES]
    route = route_trip(waypoints, deadline=deadline)
    t_route = time.monotonic()

    plan = hos.build_plan(
        [leg.profile for leg in route.legs],
        start_time,
        cycle_used,
        hos.PlanOptions(
            include_inspections=options["include_inspections"],
            rest_status=options["rest_status"],
            fuel_stop_minutes=options["fuel_stop_minutes"],
        ),
        place_namer,
    )
    t_plan = time.monotonic()
    home_tz = timezone_at(resolved["current"]["lat"], resolved["current"]["lon"])
    home = ZoneInfo(home_tz)
    _add_local_times(plan, home)

    response = {
        "input": {
            "current_location": resolved["current"],
            "pickup_location": resolved["pickup"],
            "dropoff_location": resolved["dropoff"],
            "current_cycle_used_hours": round(cycle_used, 2),
            "start_time": start_time.strftime(TIME_FORMAT),
            "options": {
                "include_inspections": options["include_inspections"],
                "rest_status": options["rest_status"],
                "fuel_stop_minutes": options["fuel_stop_minutes"],
            },
            "home_timezone": home_tz,
            "home_tz_abbr": start_time.replace(tzinfo=home).tzname() or "",
        },
        "route": _route_payload(route, resolved),
        "timeline": plan["timeline"],
        "stops": plan["stops"],
        "daily_logs": plan["daily_logs"],
        "summary": plan["summary"],
        "assumptions": list(plan.get("assumptions") or []),
        "warnings": _routing_warnings(route) + list(plan.get("warnings") or []),
    }
    log.info(
        "planned %.0f mi trip via %s in %.2fs (geocode+route %.2fs, engine %.2fs, assemble %.2fs)",
        response["route"]["distance_miles"],
        route.provider,
        time.monotonic() - started,
        t_route - started,
        t_plan - t_route,
        time.monotonic() - t_plan,
    )
    return response
