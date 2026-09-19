"""planner_service orchestration, with the network mocked.

Every test runs the real HOS engine. The orchestration test wraps ``hos.build_plan`` in a
call-through spy to pin down this layer's own job (resolve -> route -> call the engine
correctly -> assemble ``PlanResponse``); another checks the full contract end to end.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trips import hos, planner_service
from trips.serializers import PlanRequestSerializer
from trips.services import routing
from trips.services.errors import GeocodeFailed, RouteNotFound, UnsupportedRegion

from .test_services_valhalla import replay_route

# Key sets of the api.ts interfaces (the JSON contract).
PLAN_RESPONSE = {"input", "route", "timeline", "stops", "daily_logs", "summary", "assumptions", "warnings"}
PLAN_INPUT = {"current_location", "pickup_location", "dropoff_location", "current_cycle_used_hours", "start_time", "options",
              "home_timezone", "home_tz_abbr"}
RESOLVED = {"label", "lat", "lon"}
OPTIONS = {"include_inspections", "rest_status", "fuel_stop_minutes"}
ROUTE_INFO = {"distance_miles", "duration_hours", "geometry", "legs", "provider", "truck_routing"}
ROUTE_LEG = {"from_role", "to_role", "distance_miles", "duration_hours", "geometry", "instructions"}
INSTRUCTION = {"text", "maneuver", "modifier", "road", "distance_miles", "duration_minutes", "location"}
PLACE_REF = {"lat", "lon", "name", "city", "tz"}  # + optional "road"
TIMELINE_EVENT = {"id", "kind", "status", "label", "start", "end", "duration_hours", "miles", "start_mile",
                  "end_mile", "leg_index", "start_location", "end_location", "local_start", "local_end",
                  "start_tz_abbr", "end_tz_abbr"}
STOP = {"id", "kind", "status", "label", "start", "end", "duration_hours", "mile_marker", "day_number", "location",
        "local_start", "local_end", "local_tz_abbr"}
DAILY_LOG = {"date", "day_number", "total_miles", "segments", "totals", "remarks", "on_duty_hours",
             "cycle_hours_used", "cycle_hours_available", "from_location", "to_location"}
LOG_SEGMENT = {"status", "start_minute", "end_minute"}
LOG_REMARK = {"start_minute", "end_minute", "status", "location", "city", "note"}  # + optional "road"
SUMMARY = {"total_miles", "total_driving_hours", "total_on_duty_hours", "trip_duration_hours", "start_time",
           "end_time", "num_days", "num_fuel_stops", "num_breaks", "num_rests", "num_restarts",
           "cycle_hours_used_at_end", "cycle_hours_available_at_end"}


def assert_plan_response_contract(body: dict) -> None:
    """Structural check of a PlanResponse against frontend/src/types/api.ts."""
    assert set(body) == PLAN_RESPONSE
    assert set(body["input"]) == PLAN_INPUT
    for key in ("current_location", "pickup_location", "dropoff_location"):
        assert set(body["input"][key]) == RESOLVED
    assert set(body["input"]["options"]) == OPTIONS
    route = body["route"]
    assert set(route) == ROUTE_INFO and len(route["legs"]) == 2
    assert isinstance(route["truck_routing"], bool)
    ZoneInfo(body["input"]["home_timezone"])  # a valid IANA zone
    assert [(leg["from_role"], leg["to_role"]) for leg in route["legs"]] == [("current", "pickup"), ("pickup", "dropoff")]
    for leg in route["legs"]:
        assert set(leg) == ROUTE_LEG
        assert all(len(p) == 2 for p in leg["geometry"])
        for ins in leg["instructions"]:
            assert set(ins) == INSTRUCTION
    for ev in body["timeline"]:
        assert set(ev) == TIMELINE_EVENT
        assert set(ev["start_location"]) - {"road"} == PLACE_REF == set(ev["end_location"]) - {"road"}
    for stop in body["stops"]:
        assert set(stop) == STOP and stop["kind"] != "drive"
        assert set(stop["location"]) - {"road"} == PLACE_REF
    for log in body["daily_logs"]:
        assert set(log) == DAILY_LOG
        assert set(log["totals"]) == {"OFF", "SB", "D", "ON"}
        assert all(set(s) == LOG_SEGMENT for s in log["segments"])
        assert all(set(r) - {"road"} == LOG_REMARK for r in log["remarks"])
    assert set(body["summary"]) == SUMMARY
    assert all(isinstance(s, str) for s in body["assumptions"] + body["warnings"])


def validated(**overrides) -> dict:
    payload = {
        "current_location": {"lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL"},
        "pickup_location": {"lat": 38.6270, "lon": -90.1994},
        "dropoff_location": {"query": "Dallas, TX"},
        "current_cycle_used_hours": 12.5,
        "start_time": "2026-09-21T08:00",
    }
    payload.update(overrides)
    s = PlanRequestSerializer(data=payload)
    s.is_valid(raise_exception=True)
    return s.validated_data


DALLAS = {"label": "Dallas, Texas, United States", "short_label": "Dallas, TX", "lat": 32.7767, "lon": -96.797}
CAR_FALLBACK_WARNING = (
    "Truck routing was unavailable, so this route follows the car road network (OSRM) with a 65 mph cap; "
    "check it for truck restrictions."
)


@pytest.fixture
def offline(monkeypatch, load_fixture):
    """Mock geocoding and OSRM; record what the planner asked for."""
    calls: dict = {"geocode": [], "route": []}

    def fake_geocode_one(q, deadline=None):
        calls["geocode"].append(q)
        return DALLAS if "dallas" in q.lower() else None

    def fake_route_trip(waypoints, deadline=None):
        calls["route"].append(waypoints)
        return routing.parse_route(load_fixture("osrm_chicago_stlouis_dallas.json.gz"), "OSRM (test)")

    monkeypatch.setattr(planner_service, "geocode_one", fake_geocode_one)
    monkeypatch.setattr(planner_service, "route_trip", fake_route_trip)
    return calls


def test_orchestration_calls_engine_correctly(monkeypatch, offline):
    seen: dict = {}
    real_build_plan = hos.build_plan

    def spy_build_plan(legs, start_time, cycle_used_hours, options, place_namer):
        seen.update(legs=legs, start_time=start_time, cycle=cycle_used_hours, options=options, namer=place_namer)
        seen["plan"] = real_build_plan(legs, start_time, cycle_used_hours, options, place_namer)
        return seen["plan"]

    monkeypatch.setattr(hos, "build_plan", spy_build_plan)
    body = planner_service.plan_trip(validated(options={"rest_status": "OFF", "include_inspections": True}))

    # Engine got two truck-adjusted profiles and the parsed inputs.
    assert [round(p.total_miles) for p in seen["legs"]] == [297, 629]
    assert seen["start_time"] == datetime(2026, 9, 21, 8, 0)
    assert seen["cycle"] == 12.5
    assert (seen["options"].include_inspections, seen["options"].rest_status, seen["options"].fuel_stop_minutes) == (True, "OFF", 30)
    assert seen["namer"](41.525, -88.0817, "I 80") == "I 80 near Joliet, IL"

    # Only the free-text location was geocoded; OSRM got (lon, lat) waypoints in order.
    assert offline["geocode"] == ["Dallas, TX"]
    assert offline["route"] == [[(-87.6298, 41.8781), (-90.1994, 38.627), (-96.797, 32.7767)]]

    assert body["input"] == {
        "current_location": {"label": "Chicago, IL", "lat": 41.8781, "lon": -87.6298},
        "pickup_location": {"label": "St. Louis, MO", "lat": 38.627, "lon": -90.1994},
        "dropoff_location": {"label": "Dallas, TX", "lat": 32.7767, "lon": -96.797},
        "current_cycle_used_hours": 12.5,
        "start_time": "2026-09-21T08:00",
        "options": {"include_inspections": True, "rest_status": "OFF", "fuel_stop_minutes": 30},
        "home_timezone": "America/Chicago",
        "home_tz_abbr": "CDT",
    }
    route = body["route"]
    assert route["provider"] == "OSRM (test)" and route["truck_routing"] is False
    assert route["distance_miles"] == pytest.approx(925.7, abs=0.2)
    assert route["duration_hours"] == pytest.approx(sum(p.total_minutes for p in seen["legs"]) / 60, abs=0.01)
    assert len(route["geometry"]) <= planner_service.MAX_DISPLAY_POINTS
    assert route["geometry"][0] == route["legs"][0]["geometry"][0]
    assert route["geometry"][-1] == route["legs"][1]["geometry"][-1]
    assert route["legs"][0]["instructions"][-1]["text"] == "Arrive at pickup (St. Louis, MO)"
    # Engine output is passed through (timeline/stops gain local times); routing warnings go first.
    for key in ("timeline", "stops", "daily_logs", "summary", "assumptions"):
        assert body[key] == seen["plan"][key]
    assert body["warnings"] == [CAR_FALLBACK_WARNING, *seen["plan"]["warnings"]]


def test_unknown_query_raises_geocode_failed(offline):
    with pytest.raises(GeocodeFailed) as err:
        planner_service.plan_trip(validated(pickup_location={"query": "Nowhere-ville 123"}))
    assert err.value.status == 422
    assert "pickup_location" in err.value.details


def test_route_errors_propagate(monkeypatch, offline):
    def no_route(waypoints, deadline=None):
        raise RouteNotFound("No drivable route was found between these locations.")

    monkeypatch.setattr(planner_service, "route_trip", no_route)
    with pytest.raises(RouteNotFound):
        planner_service.plan_trip(validated())


def test_zero_length_first_leg_warning(monkeypatch, load_fixture):
    monkeypatch.setattr(
        planner_service, "route_trip",
        lambda waypoints, deadline=None: routing.parse_route(load_fixture("osrm_joliet_same_pickup.json"), "OSRM (test)"),
    )
    body = planner_service.plan_trip(
        validated(
            current_location={"lat": 41.525, "lon": -88.0817},
            pickup_location={"lat": 41.525, "lon": -88.0817},
            dropoff_location={"lat": 41.7508, "lon": -88.1479},
        )
    )
    assert body["warnings"][:2] == [CAR_FALLBACK_WARNING, "Current location is at the pickup, so there is no driving before pickup."]
    assert body["timeline"][0]["kind"] != "drive" or body["timeline"][0]["leg_index"] == 1
    assert body["route"]["legs"][0]["distance_miles"] == 0.0


def test_real_engine_end_to_end_contract(offline):
    body = planner_service.plan_trip(validated(current_cycle_used_hours=20))
    assert_plan_response_contract(body)
    summary = body["summary"]
    assert summary["total_miles"] == pytest.approx(body["route"]["distance_miles"], abs=0.2)
    assert summary["start_time"] == "2026-09-21T08:00"
    assert summary["num_days"] == len(body["daily_logs"]) >= 2
    assert {s["kind"] for s in body["stops"]} >= {"pickup", "dropoff", "rest"}
    pickup = next(s for s in body["stops"] if s["kind"] == "pickup")
    assert pickup["location"]["name"] == "St. Louis, MO"
    for log in body["daily_logs"]:
        assert log["segments"][0]["start_minute"] == 0 and log["segments"][-1]["end_minute"] == 1440
        assert sum(log["totals"].values()) == pytest.approx(24.0, abs=0.01)


@pytest.mark.parametrize("where", [(20.6597, -103.3496), (48.857, 2.352)])
def test_coordinates_outside_us_ca_are_rejected(offline, where):
    lat, lon = where
    with pytest.raises(UnsupportedRegion) as err:
        planner_service.plan_trip(validated(pickup_location={"lat": lat, "lon": lon}))
    assert (err.value.status, err.value.code) == (422, "unsupported_region")
    assert "pickup_location" in err.value.details


# ---------------------------------------------------------------- truck routing + local times


@pytest.fixture
def truck_route(monkeypatch, load_fixture, fake_response):
    """Route through ``planner_service`` with a captured Valhalla trip replayed offline."""

    def install(name):
        result, _ = replay_route(monkeypatch, load_fixture, fake_response, name)
        monkeypatch.setattr(planner_service, "route_trip", lambda waypoints, deadline=None: result)
        return result

    return install


def _plan_between(waypoints, **overrides):
    roles = ("current_location", "pickup_location", "dropoff_location")
    locations = {role: {"lat": lat, "lon": lon} for role, (lon, lat) in zip(roles, waypoints)}
    return planner_service.plan_trip(validated(**locations, **overrides))


def test_truck_route_end_to_end(truck_route):
    route = truck_route("route_indy_louisville_atlanta.json.gz")
    body = _plan_between([(-86.158, 39.768), (-85.7585, 38.2527), (-84.388, 33.749)])
    assert_plan_response_contract(body)
    assert body["route"]["provider"] == "Valhalla truck (valhalla1.openstreetmap.de)"
    assert body["route"]["truck_routing"] is True
    assert CAR_FALLBACK_WARNING not in body["warnings"]
    loaded = body["route"]["legs"][1]
    assert loaded["distance_miles"] == pytest.approx(route.legs[1].distance_miles, abs=0.1)
    assert loaded["instructions"][-1]["text"].startswith("Arrive at dropoff (Atlanta, GA)")
    assert {"I 65", "I 24", "I 75"} <= {i["road"] for i in loaded["instructions"]}


def test_local_times_across_time_zones(truck_route):
    """LA -> Phoenix -> New York starting 08:00 PDT: logs stay on Pacific time, stops show local time."""
    truck_route("route_la_phoenix_nyc.json.gz")
    body = _plan_between([(-118.2437, 34.0522), (-112.074, 33.4484), (-74.006, 40.7128)], current_cycle_used_hours=30)
    assert_plan_response_contract(body)
    assert (body["input"]["home_timezone"], body["input"]["home_tz_abbr"]) == ("America/Los_Angeles", "PDT")

    stops = {s["kind"]: s for s in body["stops"]}
    pickup, dropoff = stops["pickup"], stops["dropoff"]
    assert pickup["location"]["tz"] == "America/Phoenix"
    # Arizona stays on MST (UTC-7), which equals PDT in September.
    assert (pickup["local_start"], pickup["local_tz_abbr"]) == (pickup["start"], "MST")
    assert dropoff["location"]["tz"] == "America/New_York" and dropoff["local_tz_abbr"] == "EDT"
    three_hours_later = datetime.strptime(dropoff["end"], planner_service.TIME_FORMAT) + timedelta(hours=3)
    assert dropoff["local_end"] == three_hours_later.strftime(planner_service.TIME_FORMAT)

    first, last = body["timeline"][0], body["timeline"][-1]
    assert (first["local_start"], first["start_tz_abbr"]) == (first["start"], "PDT")
    assert last["end_tz_abbr"] == "EDT"
    zones = {e[end]["tz"] for e in body["timeline"] for end in ("start_location", "end_location")}
    assert {"America/Los_Angeles", "America/Phoenix", "America/Chicago", "America/New_York"} <= zones
    # Log sheets are untouched: still home-terminal (Pacific) time. Remarks name the interstate.
    assert body["daily_logs"][0]["date"] == "2026-09-21"
    remark_roads = {r.get("road") for log in body["daily_logs"] for r in log["remarks"]}
    assert remark_roads & {"I 40", "I 44", "I 70", "I 80"}


@pytest.mark.parametrize(
    ("home_time", "zone", "expected"),
    [
        ("2026-03-08T01:30", "America/New_York", ("2026-03-08T03:30", "EDT")),  # spring forward
        ("2026-11-01T00:30", "America/New_York", ("2026-11-01T01:30", "EDT")),
        ("2026-07-01T12:00", "America/Phoenix", ("2026-07-01T10:00", "MST")),
        ("2026-07-01T12:00", "America/Chicago", ("2026-07-01T12:00", "CDT")),
    ],
)
def test_local_time_conversion(home_time, zone, expected):
    assert planner_service._local(home_time, ZoneInfo("America/Chicago"), ZoneInfo(zone)) == expected


# ---------------------------------------------------------------- warnings and assumptions


def test_truck_detour_warning_replaces_the_fallback_text(monkeypatch, load_fixture):
    car = routing.parse_route(load_fixture("osrm_chicago_stlouis_dallas.json.gz"), "OSRM (test)")
    detoured = dataclasses.replace(car, detour_miles=390.7)
    monkeypatch.setattr(planner_service, "geocode_one", lambda q, deadline=None: DALLAS)
    monkeypatch.setattr(planner_service, "route_trip", lambda waypoints, deadline=None: detoured)
    body = planner_service.plan_trip(validated())
    miles = f"{sum(leg.distance_miles for leg in car.legs):,.0f}"
    assert body["warnings"][0] == (
        "Truck routing detoured 391 mi (e.g. around a border crossing OpenStreetMap marks truck-restricted), "
        f"so this route follows the car road network ({miles} mi) with a 65 mph cap; check it for truck restrictions."
    )
    assert CAR_FALLBACK_WARNING not in body["warnings"]


def test_canadian_location_notes_us_hos_rules(offline):
    body = planner_service.plan_trip(validated(current_location={"lat": 43.6532, "lon": -79.3832}))  # Toronto, ON
    assert any("in Canada" in w and "US FMCSA rules" in w for w in body["warnings"]), body["warnings"]
    us_only = planner_service.plan_trip(validated())
    assert not any("in Canada" in w for w in us_only["warnings"])


def test_trip_across_fall_back_warns_about_the_clock(offline):
    body = planner_service.plan_trip(validated(start_time="2026-10-31T22:00"))
    assert "This trip crosses a daylight-saving change on Nov 1; times after it are shown on the pre-change clock." in body["warnings"]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2027-03-13T20:00", "2027-03-14T22:00", "Mar 14"),  # spring forward
        ("2026-10-30T08:00", "2026-11-02T08:00", "Nov 1"),  # fall back, multi-day
        ("2026-09-21T08:00", "2026-09-25T08:00", None),
        ("2027-03-14T03:00", "2027-03-15T08:00", None),  # starts after the change
    ],
)
def test_dst_warning(start, end, expected):
    fmt = planner_service.TIME_FORMAT
    out = planner_service._dst_warning(datetime.strptime(start, fmt), datetime.strptime(end, fmt), ZoneInfo("America/New_York"))
    assert out == ([] if expected is None else [
        f"This trip crosses a daylight-saving change on {expected}; times after it are shown on the pre-change clock."
    ])


def test_inspections_are_off_by_default_and_the_assumptions_say_so(offline):
    body = planner_service.plan_trip(validated())
    assert body["input"]["options"]["include_inspections"] is False
    assert not {"pre_trip", "post_trip"} & {e["kind"] for e in body["timeline"]}
    assert any(a.startswith("No pre-/post-trip inspection time is added") for a in body["assumptions"])
    assert any("US FMCSA rules" in a for a in body["assumptions"])

    with_insp = planner_service.plan_trip(validated(options={"include_inspections": True}))
    assert {"pre_trip", "post_trip"} <= {e["kind"] for e in with_insp["timeline"]}
    assert any(a.startswith("A 30-minute pre-trip inspection") for a in with_insp["assumptions"])
