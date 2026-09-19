"""Live smoke tests against the real Valhalla, OSRM and Photon services.

Deselected by default (pytest.ini: -m "not live"). Run with:  uv run pytest -m live
"""

from __future__ import annotations

import pytest

from .test_services_planner import assert_plan_response_contract


@pytest.mark.live
def test_live_plan_chicago_to_dallas(client):
    resp = client.post(
        "/api/trips/plan/",
        data={
            "current_location": {"query": "Chicago, IL"},
            "pickup_location": {"query": "St. Louis, MO"},
            "dropoff_location": {"query": "Dallas, TX"},
            "current_cycle_used_hours": 20,
            "start_time": "2026-09-21T08:00",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert_plan_response_contract(body)
    assert 850 < body["route"]["distance_miles"] < 1000
    assert body["route"]["truck_routing"] is True, body["route"]["provider"]
    assert body["input"]["pickup_location"]["label"].endswith("MO")
    assert (body["input"]["home_timezone"], body["input"]["home_tz_abbr"]) == ("America/Chicago", "CDT")
    assert body["summary"]["num_days"] >= 2


@pytest.mark.live
@pytest.mark.parametrize(("q", "first"), [("St. Lou", "Saint Louis, MO"), ("Chic", "Chicago, IL")])
def test_live_autocomplete_ranking(client, q, first):
    resp = client.get("/api/geocode/", {"q": q})
    assert resp.status_code == 200, resp.content
    assert resp.json()["results"][0]["short_label"] == first
