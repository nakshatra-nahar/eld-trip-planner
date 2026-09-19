"""Valhalla truck routing: parsing live-captured fixtures, chunking long legs, instructions, OSRM failover."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

import pytest
import requests

from trips.services import routing, valhalla
from trips.services.errors import RouteNotFound
from trips.services.http import Deadline
from trips.services.places import haversine_miles

SHORT = "route_indy_louisville_atlanta.json.gz"  # 2 legs, 1 Valhalla request
LONG = "route_la_phoenix_nyc.json.gz"  # 2,500-mile leg: OSRM split points + 4 Valhalla requests
CHICAGO_DALLAS = [(-87.6298, 41.8781), (-90.1994, 38.6270), (-96.7970, 32.7767)]

# Instruction.maneuver values the frontend knows (OSRM's vocabulary, see api.ts).
OSRM_MANEUVERS = {"depart", "arrive", "turn", "new name", "continue", "merge", "on ramp", "off ramp", "fork",
                  "end of road", "use lane", "roundabout", "rotary", "roundabout turn", "exit roundabout",
                  "exit rotary", "notification"}


class ReplaySession:
    """Replays a captured trip: OSRM GETs return the recorded route, Valhalla POSTs must send
    exactly the recorded request bodies and get the recorded responses back."""

    def __init__(self, fixture: dict[str, Any], response_cls, osrm: dict[str, Any] | None = None):
        self.response_cls = response_cls
        self.osrm = osrm if osrm is not None else fixture.get("osrm")
        self.exchanges = list(fixture["valhalla"])
        self.gets: list[str] = []
        self.posts: list[dict[str, Any]] = []

    def get(self, url, params=None, timeout=None):
        self.gets.append(url)
        if self.osrm is None:
            raise AssertionError(f"unexpected OSRM request to {url}")
        return self.response_cls(200, self.osrm)

    def post(self, url, json=None, timeout=None):
        assert url == valhalla.VALHALLA_URL
        read = timeout[1]
        assert 0 < read <= valhalla.CALL_TIMEOUT_S
        self.posts.append(json)
        if not self.exchanges:
            raise AssertionError("unexpected Valhalla request")
        exchange = self.exchanges.pop(0)
        assert json == exchange["request"]
        return self.response_cls(200, exchange["response"])


def replay_route(monkeypatch, load_fixture, response_cls, name: str) -> tuple[routing.RouteResult, ReplaySession]:
    """Run ``route_trip`` on a captured trip, offline. Also used by the planner tests."""
    fixture = load_fixture(name)
    fake = ReplaySession(fixture, response_cls)
    monkeypatch.setattr(valhalla, "session", lambda: fake)
    monkeypatch.setattr(routing, "session", lambda: fake)
    monkeypatch.setattr(valhalla, "MIN_GAP_S", 0.0)
    result = valhalla.route_trip([tuple(w) for w in fixture["waypoints"]], Deadline(25))
    assert not fake.exchanges, "not every recorded Valhalla call was made"
    return result, fake


@pytest.fixture(autouse=True)
def _no_gap(monkeypatch):
    monkeypatch.setattr(valhalla, "MIN_GAP_S", 0.0)


@pytest.fixture
def replay(monkeypatch, load_fixture, fake_response):
    return lambda name: replay_route(monkeypatch, load_fixture, fake_response, name)


def _main_roads(leg: routing.RoutedLeg, n: int = 4) -> list[str]:
    miles: Counter[str] = Counter()
    for step in leg.profile.steps:
        miles[step.road] += step.end_mile - step.start_mile
    return [road for road, _ in miles.most_common(n)]


# ---------------------------------------------------------------- helpers


def test_decode_polyline6():
    # Google's reference polyline, read at precision 6 (so every value is 10x smaller).
    coords = valhalla.decode_polyline6("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert coords == pytest.approx([(-12.02, 3.85), (-12.095, 4.07), (-12.6453, 4.3252)])


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["I 65 South"], "I 65"),
        (["Dwight D Eisenhower Highway", "I 70"], "I 70"),
        (["US 36", "SR 37", "State Route 37 East"], "US 36"),
        (["Main Street"], "Main Street"),
        (["North Street"], "North Street"),
        ([], ""),
        (None, ""),
    ],
)
def test_road_of_prefers_highway_refs(names, expected):
    assert valhalla.road_of(names) == expected


def test_break_and_break_through_locations():
    assert valhalla.Location(-90.0, 38.0).to_json() == {"lon": -90.0, "lat": 38.0, "type": "break"}
    split = valhalla.Location(-90.0, 38.0, heading=359.7).to_json()
    assert split["type"] == "break_through" and split["heading"] == 0
    assert split["search_filter"] == {"exclude_ramp": True}


# ---------------------------------------------------------------- short trip (one request)


def test_short_trip_is_one_valhalla_request(replay, load_fixture):
    result, fake = replay(SHORT)
    assert fake.gets == []  # no OSRM call when no leg needs splitting
    assert [loc["type"] for loc in fake.posts[0]["locations"]] == ["break", "break", "break"]
    assert fake.posts[0]["costing"] == "truck" and fake.posts[0]["units"] == "miles"
    assert result.provider == "Valhalla truck (valhalla1.openstreetmap.de)"
    assert result.truck_routing is True

    raw_legs = load_fixture(SHORT)["valhalla"][0]["response"]["trip"]["legs"]
    for leg, raw in zip(result.legs, raw_legs):
        assert leg.distance_miles == pytest.approx(raw["summary"]["length"], rel=1e-6)
        # Valhalla's truck time (its maneuver times add up to the summary within rounding), capped at 65 mph.
        assert leg.profile.total_minutes >= raw["summary"]["time"] / 60 - 0.01
        assert leg.distance_miles / leg.duration_hours <= 65.0
        assert leg.steps == [] and leg.maneuvers is not None
    assert result.legs[0].coords[-1] == pytest.approx(result.legs[1].coords[0], abs=1e-5)  # legs meet at pickup
    assert all(miles < 0.5 for miles in result.snap_miles) and len(result.snap_miles) == 3


def test_truck_speed_cap_per_segment(replay):
    result, _ = replay(SHORT)
    profile = result.legs[1].profile
    for i in range(len(profile.coords) - 1):
        miles = profile.cum_miles[i + 1] - profile.cum_miles[i]
        minutes = profile.cum_minutes[i + 1] - profile.cum_minutes[i]
        assert miles <= 65.0 * minutes / 60 + 1e-9


def test_route_steps_give_interstate_refs(replay):
    result, _ = replay(SHORT)
    to_louisville, to_atlanta = result.legs
    assert to_louisville.profile.road_at_mile(60) == "I 65"
    assert _main_roads(to_atlanta, 3) == ["I 65", "I 24", "I 75"]
    assert to_atlanta.profile.steps[-1].end_mile == pytest.approx(to_atlanta.profile.total_miles)


def test_instructions_follow_contract(replay):
    result, _ = replay(SHORT)
    leg = result.legs[1]
    ins = valhalla.build_instructions(leg, "dropoff (Atlanta, GA)")
    assert ins[0]["maneuver"] == "depart" and ins[0]["location"] == [round(c, 6) for c in leg.coords[0]]
    assert ins[-1]["maneuver"] == "arrive" and ins[-1]["text"].startswith("Arrive at dropoff (Atlanta, GA)")
    assert {i["maneuver"] for i in ins} <= OSRM_MANEUVERS
    assert all(i["text"] and not i["text"].endswith(".") for i in ins)
    assert sum(i["distance_miles"] for i in ins) == pytest.approx(leg.distance_miles, abs=0.1)
    assert sum(i["duration_minutes"] for i in ins) == pytest.approx(leg.duration_hours * 60, abs=1)
    exit_to_i65 = next(i for i in ins if i["road"] == "I 65")
    assert exit_to_i65["maneuver"] in {"fork", "on ramp", "merge", "off ramp"}
    assert "I 65" in exit_to_i65["text"]


def test_maneuver_types_map_to_osrm_vocabulary():
    assert valhalla._MANEUVERS[10] == ("turn", "right")
    assert valhalla._MANEUVERS[16] == ("turn", "slight left")
    assert valhalla._MANEUVERS[19] == ("on ramp", "left")
    assert valhalla._MANEUVERS[20] == ("off ramp", "right")
    assert valhalla._MANEUVERS[24] == ("fork", "left")
    assert valhalla._MANEUVERS[26] == ("roundabout", "")
    assert valhalla._MANEUVERS[6] == ("arrive", "left")
    assert {m for m, _ in valhalla._MANEUVERS.values()} <= OSRM_MANEUVERS


def _leg_with(maneuvers: list[dict[str, Any]], n_coords: int) -> routing.RoutedLeg:
    shape = [(-90.0 + i * 0.01, 38.0) for i in range(n_coords)]
    parts = [{"shape": _encode(shape), "maneuvers": maneuvers}]
    return valhalla.build_leg(parts)


def _encode(coords: list[tuple[float, float]]) -> str:
    """Polyline6 encoder (test helper, the inverse of decode_polyline6)."""
    out, prev = [], (0, 0)
    for lon, lat in coords:
        point = (round(lat * 1e6), round(lon * 1e6))
        for value, last in zip(point, prev):
            v = value - last
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev = point
    return "".join(out)


def _man(type_: int, begin: int, end: int, names=(), text="", time=60.0) -> dict[str, Any]:
    return {"type": type_, "instruction": text, "street_names": list(names), "time": time, "length": 0.0,
            "begin_shape_index": begin, "end_shape_index": end}


def test_roundabout_exit_and_same_road_continue_fold():
    leg = _leg_with(
        [
            _man(1, 0, 1, ["Main Street"], "Drive east on Main Street."),
            _man(26, 1, 2, [], "Enter the roundabout and take the 2nd exit onto US 40."),
            _man(27, 2, 3, ["US 40"], "Exit the roundabout onto US 40."),
            _man(8, 3, 4, ["US 40 West"], "Continue on US 40 West."),
            _man(15, 4, 5, ["Oak Street"], "Turn left onto Oak Street. Continue on Oak Street."),
            _man(4, 5, 5, [], "You have arrived at your destination."),
        ],
        6,
    )
    ins = valhalla.build_instructions(leg)
    assert [(i["maneuver"], i["modifier"], i["road"]) for i in ins] == [
        ("depart", "", "Main Street"),
        ("roundabout", "", "US 40"),  # takes the road of its exit
        ("turn", "left", "Oak Street"),
        ("arrive", "", ""),
    ]
    # The exit and the "continue" on the same road fold into the roundabout line.
    assert ins[1]["distance_miles"] == pytest.approx(3 * ins[0]["distance_miles"], abs=0.01)
    assert ins[1]["duration_minutes"] == pytest.approx(3.0)
    assert ins[2]["text"] == "Turn left onto Oak Street, then continue on Oak Street"
    assert ins[3]["text"] == "Arrive at your destination"


def test_time_is_spread_by_distance_and_capped():
    # Maneuver 1 covers two segments (1 mi each is ~0.54 mi at this latitude) with 30 min of
    # travel: slower than the cap, so its time is split evenly. Maneuver 2 claims 1 second: capped.
    leg = _leg_with([_man(1, 0, 2, ["A"], time=1800.0), _man(8, 2, 3, ["B"], time=1.0), _man(4, 3, 3)], 4)
    seg = [b - a for a, b in pairwise(leg.profile.cum_minutes)]
    miles = [b - a for a, b in pairwise(leg.profile.cum_miles)]
    assert seg[0] == pytest.approx(15.0) and seg[1] == pytest.approx(15.0)
    assert seg[2] == pytest.approx(miles[2] / 65.0 * 60)


# ---------------------------------------------------------------- long trip (chunked)


def test_long_leg_is_chunked_at_interstate_points(replay, load_fixture):
    result, fake = replay(LONG)
    assert len(fake.gets) == 1  # one OSRM route for the split points
    assert len(fake.posts) == 4
    assert result.truck_routing is True and result.provider.startswith("Valhalla truck")
    for body in fake.posts:
        locs = body["locations"]
        crow_km = sum(haversine_miles(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in pairwise(locs)) * 1.609344
        assert crow_km <= valhalla.MAX_REQUEST_KM  # the server rejects > 1,500 km
    # LA -> Phoenix is packed with the first chunk; the split points pass through on I-40/I-44/I-70.
    splits = [loc for body in fake.posts for loc in body["locations"] if loc["type"] == "break_through"]
    assert len({(s["lon"], s["lat"]) for s in splits}) == 3
    assert all(45 <= s["heading"] <= 135 for s in splits)  # eastbound

    la_phx, phx_nyc = result.legs
    assert la_phx.distance_miles == pytest.approx(374.3, abs=1)
    chunks = [leg for body in load_fixture(LONG)["valhalla"] for leg in body["response"]["trip"]["legs"]][1:]
    assert phx_nyc.distance_miles == pytest.approx(sum(c["summary"]["length"] for c in chunks), rel=1e-6)
    assert {"I 40", "I 44", "I 70", "I 80"} <= set(_main_roads(phx_nyc, 6))


def test_stitched_leg_has_one_depart_and_contiguous_maneuvers(replay):
    result, _ = replay(LONG)
    leg = result.legs[1]
    types = [m["type"] for m in leg.maneuvers]
    assert sum(t in valhalla._DEPART for t in types) == 1 and types[0] in valhalla._DEPART
    assert sum(t in valhalla._ARRIVE for t in types) == 1 and types[-1] in valhalla._ARRIVE
    assert all(a["end"] == b["begin"] for a, b in pairwise(leg.maneuvers))
    assert leg.maneuvers[-1]["end"] == len(leg.coords) - 1
    # No jump at the seams: consecutive shape points stay close together.
    assert max(haversine_miles(a[1], a[0], b[1], b[0]) for a, b in pairwise(leg.coords)) < 5


def test_split_points_land_on_interstates(load_fixture):
    osrm = routing.parse_route(load_fixture(LONG)["osrm"])
    leg = osrm.legs[1]
    n = valhalla._chunks_needed(leg)
    assert n == 4  # ~3,880 km of road in chunks under 1,200 km
    points = valhalla.split_points(leg, n)
    assert len(points) == 3
    for k, point in enumerate(points, start=1):
        mile = min(range(len(leg.coords)), key=lambda i: abs(leg.coords[i][0] - point.lon) + abs(leg.coords[i][1] - point.lat))
        at = leg.profile.cum_miles[mile]
        assert leg.profile.road_at_mile(at).startswith("I ")
        assert abs(at - leg.distance_miles * k / n) <= valhalla.SPLIT_WINDOW_MI + 1


def test_split_points_fall_back_to_ideal_mile_without_interstates():
    straight = routing.RoutedLeg(
        profile=routing.LegProfile.straight((-100.0, 35.0), (-80.0, 35.0), 1100.0, 1000.0),
        coords=[], steps=[], distance_miles=1100.0, duration_hours=16.7,
    )
    points = valhalla.split_points(straight, 2)
    assert points[0].lon == pytest.approx(-90.0, abs=0.05) and points[0].heading == pytest.approx(90, abs=1)


# ---------------------------------------------------------------- failover to OSRM


class ScriptedSession:
    """Valhalla POSTs answer from a script; OSRM GETs return a fixed route."""

    def __init__(self, response_cls, osrm: Any, *posts: Any):
        self.response_cls, self.osrm, self.script = response_cls, osrm, list(posts)
        self.gets = 0
        self.posts = 0

    def get(self, url, params=None, timeout=None):
        self.gets += 1
        if isinstance(self.osrm, BaseException):
            raise self.osrm
        return self.osrm

    def post(self, url, json=None, timeout=None):
        self.posts += 1
        result = self.script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def scripted(monkeypatch, fake_response, load_fixture):
    def install(*posts, osrm=None):
        if osrm is None:
            osrm = fake_response(200, load_fixture("osrm_chicago_stlouis_dallas.json.gz"))
        fake = ScriptedSession(fake_response, osrm, *posts)
        monkeypatch.setattr(valhalla, "session", lambda: fake)
        monkeypatch.setattr(routing, "session", lambda: fake)
        return fake

    return install


@pytest.mark.parametrize(
    "failure",
    [
        requests.ReadTimeout("slow"),
        requests.ConnectionError("down"),
        "no_route",
        "http_500",
        "not_json",
        "missing_leg",
        "bad_shape",
    ],
)
def test_any_valhalla_failure_falls_back_to_osrm(scripted, fake_response, failure):
    responses = {
        "no_route": fake_response(400, {"error_code": 442, "error": "No path could be found for input"}),
        "http_500": fake_response(500, None),
        "not_json": fake_response(200, None),
        "missing_leg": fake_response(200, {"trip": {"status": 0, "legs": [{"shape": "", "maneuvers": []}]}}),
        "bad_shape": fake_response(200, {"trip": {"status": 0, "legs": [{"shape": "", "maneuvers": []}] * 2}}),
    }
    fake = scripted(responses.get(failure, failure))
    result = valhalla.route_trip(CHICAGO_DALLAS, Deadline(25))
    assert result.provider == "OSRM (router.project-osrm.org)"
    assert result.truck_routing is False
    assert (fake.posts, fake.gets) == (1, 1)


def test_osrm_errors_propagate_when_valhalla_fails(scripted, fake_response):
    scripted(
        fake_response(400, {"error_code": 442, "error": "No path could be found for input"}),
        osrm=fake_response(400, {"code": "NoRoute", "message": "Impossible route"}),
    )
    with pytest.raises(RouteNotFound):
        valhalla.route_trip(CHICAGO_DALLAS, Deadline(25))


def test_valhalla_is_skipped_when_the_budget_is_nearly_spent(scripted):
    fake = scripted()  # any Valhalla call would fail the test
    result = valhalla.route_trip(CHICAGO_DALLAS, Deadline(valhalla.FALLBACK_RESERVE_S + 0.5))
    assert result.truck_routing is False and fake.posts == 0


def test_call_timeout_is_capped_by_the_budget(monkeypatch, fake_response):
    seen = {}

    class Capture:
        def post(self, url, json=None, timeout=None):
            seen["timeout"] = timeout
            raise requests.ReadTimeout("slow")

    monkeypatch.setattr(valhalla, "session", lambda: Capture())
    with pytest.raises(valhalla.TruckRouteError):
        valhalla._post({}, Deadline(4.0))
    connect, read = seen["timeout"]
    assert read <= 4.0 and connect <= read


def test_same_point_leg_is_not_routed(monkeypatch, fake_response, load_fixture):
    """current == pickup: only the loaded leg goes to Valhalla; leg 0 is a zero-length leg."""
    short = load_fixture(SHORT)
    atl_leg = short["valhalla"][0]["response"]["trip"]["legs"][1]
    calls = []

    class OneLeg:
        def post(self, url, json=None, timeout=None):
            calls.append(json)
            return fake_response(200, {"trip": {"status": 0, "legs": [atl_leg]}})

    monkeypatch.setattr(valhalla, "session", lambda: OneLeg())
    louisville, atlanta = (-85.7585, 38.2527), (-84.388, 33.749)
    result = valhalla.route_trip([louisville, louisville, atlanta], Deadline(25))
    assert len(calls) == 1 and len(calls[0]["locations"]) == 2
    assert result.legs[0].distance_miles == 0.0 and result.legs[0].maneuvers == []
    assert result.legs[1].distance_miles == pytest.approx(atl_leg["summary"]["length"])
    assert result.truck_routing is True


def test_calls_are_spaced_apart(monkeypatch, fake_response, load_fixture):
    """Consecutive requests keep ``MIN_GAP_S`` between them (the public server's rate limit)."""
    monkeypatch.setattr(valhalla, "MIN_GAP_S", 0.2)
    sleeps: list[float] = []
    monkeypatch.setattr(valhalla.time, "sleep", sleeps.append)
    trip = load_fixture(SHORT)["valhalla"][0]["response"]

    class Instant:
        def post(self, url, json=None, timeout=None):
            return fake_response(200, trip)

    monkeypatch.setattr(valhalla, "session", lambda: Instant())
    valhalla._post({}, Deadline(10))
    valhalla._post({}, Deadline(10))
    assert len(sleeps) >= 1 and 0 < sleeps[-1] <= 0.2


# ---------------------------------------------------------------- live


@pytest.mark.live
def test_live_indianapolis_to_atlanta_uses_the_interstates():
    indy, atlanta = (-86.158, 39.768), (-84.388, 33.749)
    result = valhalla.route_trip([indy, indy, atlanta], Deadline(25))
    assert result.truck_routing, result.provider
    assert {"I 65", "I 24", "I 75"} <= set(_main_roads(result.legs[1], 4))
    assert 500 < result.legs[1].distance_miles < 600


@pytest.mark.live
def test_live_phoenix_to_holbrook_takes_i17_and_i40():
    phoenix, holbrook = (-112.074, 33.4484), (-110.1582, 34.9022)
    result = valhalla.route_trip([phoenix, phoenix, holbrook], Deadline(25))
    assert result.truck_routing, result.provider
    assert _main_roads(result.legs[1], 2) == ["I 17", "I 40"]


@pytest.mark.live
def test_live_coast_to_coast_is_chunked():
    result = valhalla.route_trip([(-118.2437, 34.0522), (-112.074, 33.4484), (-74.006, 40.7128)], Deadline(25))
    assert result.truck_routing, result.provider
    assert 2300 < result.legs[1].distance_miles < 2700
    assert result.legs[1].distance_miles / result.legs[1].duration_hours <= 65.0



def _chunk(lons: list[float], maneuvers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"shape": _encode([(lon, 38.0) for lon in lons]), "maneuvers": maneuvers}


def test_stitch_folds_the_seam_on_the_same_road():
    first = _chunk([-90.0, -89.9, -89.8], [_man(1, 0, 1, ["Main St"]), _man(8, 1, 2, ["I 70", "Mark Twain Expy"]),
                                            _man(4, 2, 2)])
    second = _chunk([-89.8, -89.7, -89.6], [_man(1, 0, 1, ["I 70 East"]), _man(20, 1, 2, ["Exit Rd"]), _man(4, 2, 2)])
    coords, maneuvers = valhalla._stitch([first, second])
    assert len(coords) == 5  # the seam vertex is shared
    assert [(m["type"], m["begin"], m["end"]) for m in maneuvers] == [(1, 0, 1), (8, 1, 3), (20, 3, 4), (4, 4, 4)]
    assert maneuvers[1]["time"] == 120.0  # the depart's time joins the I 70 maneuver


def test_stitch_turns_a_seam_onto_a_new_road_into_continue():
    first = _chunk([-90.0, -89.9], [_man(1, 0, 1, ["I 40"]), _man(4, 1, 1)])
    second = _chunk([-89.89, -89.8], [_man(1, 0, 1, ["I 44"]), _man(4, 1, 1)])  # ~0.5 mi gap: not shared
    coords, maneuvers = valhalla._stitch([first, second])
    assert len(coords) == 4
    assert [(m["type"], m["begin"], m["end"]) for m in maneuvers] == [(1, 0, 1), (8, 1, 3), (4, 3, 3)]
    assert maneuvers[1]["instruction"] == "Continue on I 44."
