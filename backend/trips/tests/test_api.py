"""HTTP layer: routing, validation errors in the ApiError shape, error-code mapping."""

from __future__ import annotations

import json

import pytest

from trips import planner_service
from trips.services import geocoding
from trips.services.errors import GeocodeFailed, RouteNotFound, UpstreamUnavailable

PLAN_URL = "/api/trips/plan/"

VALID = {
    "current_location": {"lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL"},
    "pickup_location": {"query": "St. Louis, MO"},
    "dropoff_location": {"lat": 32.7767, "lon": -96.797},
    "current_cycle_used_hours": 10,
    "start_time": "2026-09-21T08:00",
    "options": {"include_inspections": False},
}


def post(client, body, url=PLAN_URL):
    data = body if isinstance(body, str) else json.dumps(body)
    return client.post(url, data=data, content_type="application/json")


def assert_api_error(resp, status, code):
    assert resp.status_code == status, resp.content
    assert resp["Content-Type"].startswith("application/json")
    body = resp.json()
    assert body["code"] == code
    assert isinstance(body["error"], str) and body["error"]
    assert set(body) <= {"error", "code", "details"}
    if "details" in body:
        assert all(isinstance(v, list) and all(isinstance(m, str) for m in v) for v in body["details"].values())
    return body


@pytest.fixture
def fake_planner(monkeypatch):
    seen = {}

    def fake(data, budget_s):
        seen.update(data=data, budget_s=budget_s)
        return {"ok": True}

    monkeypatch.setattr(planner_service, "plan_trip", fake)
    return seen


# ---------------------------------------------------------------- health / routing


@pytest.mark.parametrize("url", ["/api/health/", "/api/health"])
def test_health(client, url):
    resp = client.get(url)
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


def test_unknown_url_is_json_404(client):
    assert_api_error(client.get("/api/nope/"), 404, "not_found")


def test_wrong_method(client):
    assert_api_error(client.get(PLAN_URL), 405, "method_not_allowed")


def test_cors_allows_vite_dev_server(client):
    resp = client.get("/api/health/", HTTP_ORIGIN="http://localhost:5173")
    assert resp["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in client.get("/api/health/", HTTP_ORIGIN="https://evil.example")


# ---------------------------------------------------------------- plan: success path


def test_plan_passes_validated_data_to_service(client, fake_planner, settings):
    settings.PLAN_TIME_BUDGET_SECONDS = 12
    for url in (PLAN_URL, "/api/trips/plan"):
        resp = post(client, VALID, url)
        assert resp.status_code == 200 and resp.json() == {"ok": True}
    data = fake_planner["data"]
    assert fake_planner["budget_s"] == 12
    assert data["start_time"].isoformat() == "2026-09-21T08:00:00"
    assert data["options"] == {"include_inspections": False, "rest_status": "SB", "fuel_stop_minutes": 30}
    assert data["pickup_location"]["query"] == "St. Louis, MO"


@pytest.mark.parametrize("options", [None, {}])
def test_plan_options_default(client, fake_planner, options):
    body = {**VALID}
    if options is None:
        body.pop("options")
    else:
        body["options"] = options
    assert post(client, body).status_code == 200
    assert fake_planner["data"]["options"] == {"include_inspections": False, "rest_status": "SB", "fuel_stop_minutes": 30}


@pytest.mark.parametrize("cycle", [0, 70, 69.75, "35"])
def test_plan_accepts_cycle_bounds(client, fake_planner, cycle):
    assert post(client, {**VALID, "current_cycle_used_hours": cycle}).status_code == 200


# ---------------------------------------------------------------- plan: validation errors


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"current_cycle_used_hours": 70.5}, "current_cycle_used_hours"),
        ({"current_cycle_used_hours": -1}, "current_cycle_used_hours"),
        ({"current_cycle_used_hours": "lots"}, "current_cycle_used_hours"),
        ({"current_cycle_used_hours": None}, "current_cycle_used_hours"),
        ({"start_time": "21/09/2026 08:00"}, "start_time"),
        ({"start_time": "2026-02-30T08:00"}, "start_time"),
        ({"start_time": ""}, "start_time"),
        ({"start_time": "9999-12-31T23:00"}, "start_time"),
        ({"start_time": "1850-01-01T08:00"}, "start_time"),
        ({"current_cycle_used_hours": True}, "current_cycle_used_hours"),
        ({"pickup_location": {"lat": True, "lon": -87}}, "pickup_location.lat"),
        ({"pickup_location": {}}, "pickup_location"),
        ({"pickup_location": {"query": "   "}}, "pickup_location"),
        ({"pickup_location": {"lat": 41.0}}, "pickup_location"),
        ({"pickup_location": {"lat": 95, "lon": -87}}, "pickup_location.lat"),
        ({"dropoff_location": {"lat": 41, "lon": -200}}, "dropoff_location.lon"),
        ({"dropoff_location": "Dallas"}, "dropoff_location"),
        ({"options": {"rest_status": "D"}}, "options.rest_status"),
        ({"options": {"fuel_stop_minutes": 0}}, "options.fuel_stop_minutes"),
        ({"options": {"include_inspections": "maybe"}}, "options.include_inspections"),
    ],
)
def test_plan_validation_errors(client, fake_planner, patch, field):
    body = assert_api_error(post(client, {**VALID, **patch}), 400, "validation_error")
    assert field in body["details"], body
    assert "data" not in fake_planner  # never reached the service


def test_plan_missing_everything(client, fake_planner):
    body = assert_api_error(post(client, {}), 400, "validation_error")
    assert set(body["details"]) == {
        "current_location", "pickup_location", "dropoff_location", "current_cycle_used_hours", "start_time"}


@pytest.mark.parametrize("raw", ["{not json", '{"current_cycle_used_hours": NaN}', "[]"])
def test_plan_malformed_json(client, fake_planner, raw):
    assert_api_error(post(client, raw), 400, "validation_error")


def test_plan_body_too_large(client, fake_planner, settings):
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1000
    raw = '{"start_time": "' + "x" * 2000 + '"}'
    assert_api_error(post(client, raw), 413, "payload_too_large")


def test_plan_deeply_nested_json(client, fake_planner):
    assert_api_error(post(client, "[" * 100_000 + "]" * 100_000), 400, "validation_error")


def test_plan_rejects_non_json_content_type(client):
    resp = client.post(PLAN_URL, data="a=b", content_type="application/x-www-form-urlencoded")
    assert_api_error(resp, 415, "unsupported_media_type")


# ---------------------------------------------------------------- plan: service errors


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (GeocodeFailed("Could not find the pickup location.", details={"pickup_location": ["No match"]}), 422, "geocode_failed"),
        (RouteNotFound("No drivable route was found between these locations."), 422, "route_not_found"),
        (UpstreamUnavailable("The routing service is unavailable right now."), 502, "upstream_unavailable"),
    ],
)
def test_plan_service_errors(client, monkeypatch, exc, status, code):
    def boom(data, budget_s):
        raise exc

    monkeypatch.setattr(planner_service, "plan_trip", boom)
    body = assert_api_error(post(client, VALID), status, code)
    assert body["error"] == exc.message


def test_plan_unexpected_error_is_json_500(client, monkeypatch):
    def boom(data, budget_s):
        raise ZeroDivisionError("bug")

    monkeypatch.setattr(planner_service, "plan_trip", boom)
    assert_api_error(post(client, VALID), 500, "internal_error")


# ---------------------------------------------------------------- geocode / reverse


def test_geocode(client, monkeypatch):
    result = {"label": "Joliet, Illinois, United States", "short_label": "Joliet, IL", "lat": 41.5, "lon": -88.1}
    seen = {}

    def fake(q, limit=6, allow_fallback=True):
        seen["allow_fallback"] = allow_fallback
        return [result] if q == "joliet" else []

    monkeypatch.setattr(geocoding, "geocode", fake)
    resp = client.get("/api/geocode/", {"q": "  joliet "})
    assert resp.status_code == 200 and resp.json() == {"results": [result]}
    assert seen["allow_fallback"] is False  # autocomplete never hits Nominatim


def test_geocode_is_rate_limited(client, monkeypatch, settings):
    from django.core.cache import cache
    from rest_framework.settings import api_settings
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**api_settings.DEFAULT_THROTTLE_RATES, "geocode": "2/min"})
    monkeypatch.setattr(geocoding, "geocode", lambda q, limit=6, allow_fallback=True: [])
    codes = [client.get("/api/geocode/", {"q": "joliet"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    cache.clear()


def _limit_plans(monkeypatch, rate):
    from rest_framework.settings import api_settings
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**api_settings.DEFAULT_THROTTLE_RATES, "plan": rate})


def test_plan_is_rate_limited_with_api_error_and_retry_after(client, monkeypatch):
    _limit_plans(monkeypatch, "2/min")
    # Throttling runs before validation, so even rejected requests count toward the limit.
    codes = [post(client, {}).status_code for _ in range(2)]
    assert codes == [400, 400]
    resp = post(client, VALID)
    body = assert_api_error(resp, 429, "rate_limited")
    assert "Too many requests" in body["error"]
    assert int(resp["Retry-After"]) > 0
    # The message quotes exactly the header's number.
    assert body["error"].endswith(f"Try again in {resp['Retry-After']} s.")


def test_plan_rate_limit_is_per_client_ip(client, monkeypatch):
    _limit_plans(monkeypatch, "1/min")

    def plan_from(ip):
        return client.post(PLAN_URL, data="{}", content_type="application/json", HTTP_X_VERCEL_FORWARDED_FOR=ip)

    assert plan_from("203.0.113.7").status_code == 400
    assert plan_from("203.0.113.7").status_code == 429
    assert plan_from("198.51.100.23").status_code == 400  # another visitor is unaffected


def test_default_rates_cover_plan_and_geocode():
    from rest_framework.settings import api_settings

    assert set(api_settings.DEFAULT_THROTTLE_RATES) >= {"plan", "geocode"}


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "a"}, {"q": " a "}, {"q": "x" * 201}, {"q": "ok", "limit": 0}])
def test_geocode_validation(client, params):
    body = assert_api_error(client.get("/api/geocode/", params), 400, "validation_error")
    assert set(body["details"]) <= {"q", "limit"}


def test_geocode_upstream_down(client, monkeypatch):
    def down(q, limit=6, allow_fallback=True):
        raise UpstreamUnavailable("Geocoding service unavailable (photon, nominatim).")

    monkeypatch.setattr(geocoding, "geocode", down)
    assert_api_error(client.get("/api/geocode/", {"q": "Chicago"}), 502, "upstream_unavailable")


def test_reverse(client):
    resp = client.get("/api/reverse/", {"lat": "41.8781", "lon": "-87.6298"})
    assert resp.status_code == 200
    assert resp.json() == {"result": {"label": "Chicago, Illinois, United States", "short_label": "Chicago, IL",
                                      "lat": 41.8781, "lon": -87.6298}}
    assert client.get("/api/reverse/", {"lat": "48.85", "lon": "2.35"}).json() == {"result": None}


@pytest.mark.parametrize("params", [{}, {"lat": "41"}, {"lat": "abc", "lon": "1"}, {"lat": "91", "lon": "0"}, {"lat": "nan", "lon": "0"}])
def test_reverse_validation(client, params):
    assert_api_error(client.get("/api/reverse/", params), 400, "validation_error")
