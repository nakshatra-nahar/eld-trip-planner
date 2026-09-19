"""Live smoke test against the real OSRM + Photon services.

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
    assert body["input"]["pickup_location"]["label"].endswith("MO")
    assert body["summary"]["num_days"] >= 2
