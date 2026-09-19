"""build_plan output must match the TypeScript contract in frontend/src/types/api.ts.

The interfaces are parsed from api.ts itself, so a change to the contract that the
engine does not follow fails here.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from trips.hos import LegProfile, PlanOptions, RouteStep, build_plan

API_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "types" / "api.ts"
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_api_ts() -> tuple[dict[str, dict[str, str]], dict[str, set[str]], dict[str, dict[str, str]]]:
    """Return ({interface: {field: ts_type}}, {union alias: {literal values}},
    {interface: {optional field: ts_type}})."""
    text = API_TS.read_text()
    interfaces, optionals = {}, {}
    for name, body in re.findall(r"export interface (\w+) \{(.*?)\n\}", text, re.DOTALL):
        fields, optional = {}, {}
        for line in body.splitlines():
            line = line.split("//")[0].strip()
            m = re.match(r"(\w+)(\??):\s*(.+)$", line)
            if m:
                (optional if m.group(2) else fields)[m.group(1)] = m.group(3).strip()
        interfaces[name] = fields
        optionals[name] = optional
    unions = {}
    for name, body in re.findall(r"export type (\w+) =((?:\s*\|?\s*'[^']*')+)", text):
        unions[name] = set(re.findall(r"'([^']*)'", body))
    return interfaces, unions, optionals


@pytest.fixture(scope="module")
def contract():
    if not API_TS.exists():
        pytest.skip("frontend/src/types/api.ts not available")
    return parse_api_ts()


def check_value(value, ts_type, contract, path):
    interfaces, unions, _ = contract
    ts_type = ts_type.strip()
    if ts_type.endswith("[]"):
        assert isinstance(value, list), path
        for i, item in enumerate(value):
            check_value(item, ts_type[:-2], contract, f"{path}[{i}]")
    elif ts_type == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (path, value)
    elif ts_type == "string":
        assert isinstance(value, str), (path, value)
    elif ts_type == "boolean":
        assert isinstance(value, bool), (path, value)
    elif ts_type in unions:
        assert value in unions[ts_type], (path, value)
    elif m := re.fullmatch(r"Exclude<(\w+),\s*'([^']*)'>", ts_type):
        assert value in unions[m.group(1)] - {m.group(2)}, (path, value)
    elif m := re.fullmatch(r"Record<(\w+),\s*(\w+)>", ts_type):
        assert isinstance(value, dict) and set(value) == unions[m.group(1)], (path, value)
        for k, v in value.items():
            check_value(v, m.group(2), contract, f"{path}.{k}")
    elif ts_type in interfaces:
        check_interface(value, ts_type, contract, path)
    else:
        raise AssertionError(f"{path}: unsupported TS type {ts_type!r} in test")


def check_interface(obj, name, contract, path=None):
    path = path or name
    fields, optional = contract[0][name], contract[2][name]
    assert isinstance(obj, dict), path
    assert set(fields) <= set(obj) <= set(fields) | set(optional), f"{path}: keys {sorted(obj)} vs {sorted(fields)}"
    for key, ts_type in {**fields, **optional}.items():
        if key in obj:
            check_value(obj[key], ts_type, contract, f"{path}.{key}")


def namer(lat, lon, road=None):
    base = f"Town {lat:.1f}, ST"
    return f"{road} near {base}" if road else base


@pytest.fixture(scope="module")
def plan():
    coords0 = [(-88.0 + i * 0.01, 41.5) for i in range(11)]
    leg0 = LegProfile(coords0, [5.0] * 10, [6.0] * 10, [RouteStep(0, 20, "Main St"), RouteStep(20, 50, "I 55")])
    coords1 = [(-87.9 + i * 0.129, 41.5 - i * 0.015) for i in range(101)]
    leg1 = LegProfile(coords1, [15.0] * 100, [15 / 58 * 60] * 100, [RouteStep(0, 1500, "I 80")])
    return build_plan([leg0, leg1], datetime(2026, 9, 21, 6, 0), 62.5, PlanOptions(), namer)


def test_plan_has_exactly_the_engine_keys(plan):
    assert set(plan) == {"timeline", "stops", "daily_logs", "summary", "assumptions", "warnings"}
    json.dumps(plan)  # JSON-ready: no datetimes, tuples-only-as-lists, etc.


def test_plan_matches_api_ts(plan, contract):
    assert plan["timeline"] and plan["stops"] and plan["daily_logs"]
    for i, ev in enumerate(plan["timeline"]):
        check_interface(ev, "TimelineEvent", contract, f"timeline[{i}]")
    for i, stop in enumerate(plan["stops"]):
        check_interface(stop, "Stop", contract, f"stops[{i}]")
    for i, log in enumerate(plan["daily_logs"]):
        check_interface(log, "DailyLog", contract, f"daily_logs[{i}]")
    check_interface(plan["summary"], "TripSummary", contract, "summary")
    assert all(isinstance(s, str) and s for s in plan["assumptions"])
    assert all(isinstance(s, str) and s for s in plan["warnings"])
    # This trip (62.5 h used) needs a restart, so there is at least one warning.
    assert plan["warnings"]
    # Sheets stay in home-terminal time; the API adds local times, so no "no conversion" claim.
    assert any("home-terminal time zone" in s for s in plan["assumptions"])
    assert not any("no time-zone conversion" in s for s in plan["assumptions"])


def test_formats_and_ids(plan):
    ids = [ev["id"] for ev in plan["timeline"]]
    assert ids == [f"e{i}" for i in range(1, len(ids) + 1)]
    by_id = {ev["id"]: ev for ev in plan["timeline"]}
    for ev in plan["timeline"]:
        assert TIME_RE.match(ev["start"]) and TIME_RE.match(ev["end"])
    for stop in plan["stops"]:
        src = by_id[stop["id"]]
        assert stop["kind"] == src["kind"] != "drive"
        assert stop["location"] == src["start_location"]
        assert stop["mile_marker"] == src["start_mile"]
    for log in plan["daily_logs"]:
        assert DATE_RE.match(log["date"])
    s = plan["summary"]
    assert TIME_RE.match(s["start_time"]) and TIME_RE.match(s["end_time"])


def test_rounding(plan):
    def decimals(x):
        return len(repr(float(x)).split(".")[1].rstrip("0"))

    for ev in plan["timeline"]:
        assert decimals(ev["duration_hours"]) <= 2
        for key in ("miles", "start_mile", "end_mile"):
            assert decimals(ev[key]) <= 1
    for log in plan["daily_logs"]:
        assert decimals(log["total_miles"]) <= 1
        assert all(decimals(v) <= 2 for v in log["totals"].values())


def test_place_names_use_road_refs_en_route(plan):
    by_kind = {}
    for ev in plan["timeline"]:
        by_kind.setdefault(ev["kind"], []).append(ev)
    # Trip endpoints are addresses: no road ref.
    assert not plan["timeline"][0]["start_location"]["name"].startswith("I ")
    assert not by_kind["pickup"][0]["start_location"]["name"].startswith("I ")
    assert not by_kind["dropoff"][0]["start_location"]["name"].startswith("I ")
    # En-route stops on leg 1 (a single "I 80" step) carry the road ref.
    en_route = [
        ev for kind in ("break", "rest", "restart", "fuel")
        for ev in by_kind.get(kind, []) if ev["leg_index"] == 1
    ]
    assert en_route
    for ev in en_route:
        assert ev["start_location"]["name"].startswith("I 80 near Town "), ev


def test_engine_is_pure_python():
    """trips/hos must not import Django, DRF, requests or any networking module."""
    forbidden = re.compile(r"^\s*(from|import)\s+(django|rest_framework|requests|urllib|http|socket)\b", re.MULTILINE)
    hos_dir = Path(__file__).resolve().parents[1] / "hos"
    for source in hos_dir.glob("*.py"):
        assert not forbidden.search(source.read_text()), source.name


def test_place_refs_carry_city_and_road(plan):
    """Every PlaceRef splits its name into city (+ road on a highway), consistently."""
    for ev in plan["timeline"]:
        for ref in (ev["start_location"], ev["end_location"]):
            assert ref["city"].startswith("Town ")
            expected = f"{ref['road']} near {ref['city']}" if "road" in ref else ref["city"]
            assert ref["name"] == expected
    for log in plan["daily_logs"]:
        for r in log["remarks"]:
            assert r["location"].endswith(r["city"])
