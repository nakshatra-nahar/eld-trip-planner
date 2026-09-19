"""OSRM parsing into LegProfiles (live-captured fixtures) and host failover."""

from __future__ import annotations

import pytest
import requests

from trips.hos.profile import LegProfile
from trips.services import routing
from trips.services.errors import RouteNotFound, UpstreamUnavailable
from trips.services.http import Deadline
from trips.services.routing import parse_route
from trips.services.units import METERS_PER_MILE

WAYPOINTS = [(-87.6298, 41.8781), (-90.1994, 38.6270), (-96.7970, 32.7767)]


@pytest.fixture
def chicago_dallas(load_fixture):
    return load_fixture("osrm_chicago_stlouis_dallas.json.gz")


def test_parse_route_builds_two_leg_profiles(chicago_dallas):
    result = parse_route(chicago_dallas, "OSRM (test)")
    assert result.provider == "OSRM (test)"
    assert len(result.legs) == 2
    for leg, raw in zip(result.legs, chicago_dallas["routes"][0]["legs"]):
        assert isinstance(leg.profile, LegProfile)
        assert leg.distance_miles == pytest.approx(raw["distance"] / METERS_PER_MILE, rel=1e-4)
        assert len(leg.profile.coords) == len(raw["annotation"]["distance"]) + 1
        # Truck-adjusted time is never faster than OSRM's car time.
        assert leg.profile.total_minutes >= raw["duration"] / 60 - 1e-6
    # Chicago -> St. Louis ~297 mi, St. Louis -> Dallas ~629 mi.
    assert result.legs[0].distance_miles == pytest.approx(296.6, abs=1)
    assert result.legs[1].distance_miles == pytest.approx(629.1, abs=1)
    # Legs meet at the pickup and follow the route polyline end to end.
    geometry = chicago_dallas["routes"][0]["geometry"]["coordinates"]
    assert result.legs[0].coords[0] == tuple(geometry[0])
    assert result.legs[0].coords[-1] == result.legs[1].coords[0]
    assert result.legs[1].coords[-1] == tuple(geometry[-1])


def test_truck_speed_cap_per_segment(chicago_dallas):
    result = parse_route(chicago_dallas)
    raw = chicago_dallas["routes"][0]["legs"][1]["annotation"]
    for i, (d, t) in enumerate(zip(raw["distance"], raw["duration"])):
        seg_min = result.legs[1].profile.cum_minutes[i + 1] - result.legs[1].profile.cum_minutes[i]
        mph = (d / METERS_PER_MILE) / (seg_min / 60) if seg_min > 0 else 0
        assert mph <= 65.0 + 1e-6
        assert seg_min >= t / 60 - 1e-9  # never faster than the car profile
    # Average of the whole leg is below the cap too.
    leg = result.legs[1]
    assert leg.distance_miles / leg.duration_hours <= 65.0


def test_route_steps_give_road_refs(chicago_dallas):
    profile = parse_route(chicago_dallas).legs[0].profile
    assert profile.steps[-1].end_mile == pytest.approx(profile.total_miles, rel=1e-6)
    assert profile.road_at_mile(100.0) == "I 55"
    assert profile.road_at_mile(0.01) == "South Federal Street"


def test_zero_length_first_leg(load_fixture):
    result = parse_route(load_fixture("osrm_joliet_same_pickup.json"))
    assert result.legs[0].distance_miles == pytest.approx(0.0, abs=0.01)
    assert len(result.legs[0].profile.coords) >= 2
    assert result.legs[1].distance_miles > 15


def test_parse_route_rejects_inconsistent_geometry(chicago_dallas):
    broken = {**chicago_dallas, "routes": [{**chicago_dallas["routes"][0], "geometry": {"coordinates": [[0, 0], [1, 1]]}}]}
    with pytest.raises(ValueError):
        parse_route(broken)


@pytest.fixture
def use(monkeypatch, fake_session):
    """Install a FakeSession replaying ``results`` into the routing module."""

    def install(*results):
        fake = fake_session(*results)
        monkeypatch.setattr(routing, "session", lambda: fake)
        return fake

    return install


def test_fetch_route_success_sends_expected_request(use, fake_response, chicago_dallas):
    fake = use(fake_response(200, chicago_dallas))
    result = routing.fetch_route(WAYPOINTS)
    assert result.provider == "OSRM (router.project-osrm.org)"
    call = fake.calls[0]
    assert call["url"] == (
        "https://router.project-osrm.org/route/v1/driving/"
        "-87.629800,41.878100;-90.199400,38.627000;-96.797000,32.776700"
    )
    assert call["params"] == {"overview": "full", "geometries": "geojson", "steps": "true", "annotations": "distance,duration"}
    assert call["timeout"] == (routing.CONNECT_TIMEOUT_S, 15.0)


def test_fetch_route_retries_then_fails_over(use, fake_response, chicago_dallas):
    fake = use(requests.ConnectionError("reset"), fake_response(503), fake_response(200, chicago_dallas))
    result = routing.fetch_route(WAYPOINTS)
    assert result.provider == "OSRM (routing.openstreetmap.de)"
    assert [c["url"].split("/route/")[0] for c in fake.calls] == [
        "https://router.project-osrm.org",
        "https://router.project-osrm.org",
        "https://routing.openstreetmap.de/routed-car",
    ]


def test_fetch_route_timeout_fails_over_without_retry(use, fake_response, chicago_dallas):
    """A hung primary must not eat the whole budget: one timeout moves on to the mirror."""
    fake = use(requests.ReadTimeout("hung"), fake_response(200, chicago_dallas))
    result = routing.fetch_route(WAYPOINTS, Deadline(25))
    assert result.provider == "OSRM (routing.openstreetmap.de)"
    assert [c["url"].split("/route/")[0] for c in fake.calls] == [
        "https://router.project-osrm.org",
        "https://routing.openstreetmap.de/routed-car",
    ]
    # The primary's read timeout leaves at least half the budget for the mirror.
    connect, read = fake.calls[0]["timeout"]
    assert connect == routing.CONNECT_TIMEOUT_S and read <= 12.5


def test_fetch_route_all_hosts_down(use):
    use(*[requests.ConnectionError("down")] * 4)
    with pytest.raises(UpstreamUnavailable) as err:
        routing.fetch_route(WAYPOINTS)
    assert err.value.status == 502 and err.value.code == "upstream_unavailable"


def test_fetch_route_malformed_json_fails_over(use, fake_response, chicago_dallas):
    fake = use(fake_response(200, None), fake_response(502), fake_response(200, chicago_dallas))
    assert routing.fetch_route(WAYPOINTS).provider == "OSRM (routing.openstreetmap.de)"
    assert len(fake.calls) == 3


@pytest.mark.parametrize("code", ["NoRoute", "NoSegment"])
def test_fetch_route_no_route_is_final(use, fake_response, code):
    fake = use(fake_response(400, {"code": code, "message": "Impossible route between points"}))
    with pytest.raises(RouteNotFound) as err:
        routing.fetch_route(WAYPOINTS)
    assert err.value.status == 422 and err.value.code == "route_not_found"
    assert len(fake.calls) == 1  # no pointless failover
