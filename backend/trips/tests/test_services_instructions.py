"""Instruction generator: every maneuver type/modifier, roundabouts, ramps, collapsing."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from trips.services.instructions import build_instructions, compass, instruction_text, ordinal, way_name

FIXTURES = Path(__file__).parent / "fixtures"


def step(type_, modifier=None, name="", ref=None, distance=100.0, duration=10.0, **extra):
    maneuver = {"type": type_, "location": [-88.0, 41.5], "bearing_after": 90}
    if modifier is not None:
        maneuver["modifier"] = modifier
    maneuver.update(extra.pop("maneuver", {}))
    s = {"maneuver": maneuver, "name": name, "distance": distance, "duration": duration}
    if ref is not None:
        s["ref"] = ref
    s.update(extra)
    return s


@pytest.mark.parametrize(
    ("s", "expected"),
    [
        (step("depart", name="Main Street", maneuver={"bearing_after": 0}), "Head north on Main Street"),
        (step("depart", maneuver={"bearing_after": 225}), "Head southwest"),
        (step("arrive", "right"), "Arrive at your destination, on the right"),
        (step("arrive"), "Arrive at your destination"),
        (step("turn", "left", name="Elm St"), "Turn left onto Elm St"),
        (step("turn", "sharp right", name="Elm St"), "Turn sharp right onto Elm St"),
        (step("turn", "slight left"), "Turn slight left"),
        (step("turn", "straight", name="Elm St"), "Go straight onto Elm St"),
        (step("turn", "uturn"), "Make a U-turn"),
        (step("new name", "straight", name="Oak Ave"), "Continue onto Oak Ave"),
        (step("new name", "slight right", name="Oak Ave"), "Bear right onto Oak Ave"),
        (step("continue", "straight", name="Oak Ave"), "Continue on Oak Ave"),
        (step("continue", "left", name="Oak Ave"), "Continue left onto Oak Ave"),
        (step("continue", "uturn", name="Oak Ave"), "Make a U-turn onto Oak Ave"),
        (step("continue"), "Continue straight"),
        (step("merge", "slight left", name="Stevenson Expressway", ref="I 55"), "Merge left onto Stevenson Expressway (I 55)"),
        (step("merge", "straight", ref="I 80"), "Merge onto I 80"),
        (step("on ramp", "right", destinations="I 80 West: Des Moines"), "Take the ramp on the right toward I 80 West: Des Moines"),
        (step("on ramp", "slight left", ref="I 294"), "Take the ramp on the left onto I 294"),
        (step("on ramp"), "Take the ramp"),
        (step("ramp", "right", ref="I 294"), "Take the ramp on the right onto I 294"),
        (step("off ramp", "slight right", exits="40A", destinations="Stadium, 9th Street, Tucker Boulevard"),
         "Take exit 40A on the right toward Stadium, 9th Street"),
        (step("off ramp", "right", name="Exit Road"), "Take the exit on the right onto Exit Road"),
        (step("fork", "slight right", ref="I 55", destinations="I 55 South: Saint Louis, Springfield, Peoria"),
         "Keep right at the fork toward I 55 South: Saint Louis, Springfield"),
        (step("fork", "slight left", name="Jack Buck Memorial Highway"), "Keep left at the fork onto Jack Buck Memorial Highway"),
        (step("fork", "straight"), "Keep straight at the fork"),
        (step("end of road", "left", name="Browder Street"), "Turn left at the end of the road onto Browder Street"),
        (step("end of road", "right"), "Turn right at the end of the road"),
        (step("use lane", "left", name="I 90"), "Keep left to stay on I 90"),
        (step("use lane", "straight", name="I 90"), "Continue straight on I 90"),
        (step("roundabout", "right", name="Range Line Road", maneuver={"exit": 3}),
         "Enter the roundabout and take the third exit onto Range Line Road"),
        (step("roundabout", "right"), "Enter the roundabout and exit"),
        (step("rotary", "right", name="Main St", rotary_name="Dupont Circle", maneuver={"exit": 2}),
         "Enter Dupont Circle and take the second exit onto Main St"),
        (step("rotary", "left", maneuver={"exit": 12}), "Enter the traffic circle and take the 12th exit"),
        (step("roundabout turn", "left", name="Pine St"), "At the roundabout, turn left onto Pine St"),
        (step("roundabout turn", "right", maneuver={"exit": 1}), "At the roundabout, take the first exit"),
        (step("exit roundabout", "right", name="Pine St"), "Exit the roundabout onto Pine St"),
        (step("exit rotary", "right"), "Exit the traffic circle"),
        (step("notification", "straight", name="I 80"), "Continue on I 80"),
        (step("some future type", "left", name="X"), "Turn left onto X"),
    ],
)
def test_instruction_text(s, expected):
    assert instruction_text(s) == expected


def test_arrive_with_waypoint_label():
    assert instruction_text(step("arrive", "left"), "pickup (St. Louis, MO)") == "Arrive at pickup (St. Louis, MO), on the left"


def test_helpers():
    assert [compass(b) for b in (0, 44, 46, 90, 181, 359, None)] == ["north", "northeast", "northeast", "east", "south", "north", ""]
    assert [ordinal(n) for n in (1, 3, 10, 11, 12, 13, 21, 22, 103)] == [
        "first", "third", "tenth", "11th", "12th", "13th", "21st", "22nd", "103rd"]
    assert way_name({"name": "Main Street", "ref": "US 30"}) == "Main Street (US 30)"
    assert way_name({"name": "", "ref": "I 55; I 64"}) == "I 55 / I 64"
    assert way_name({"name": "I 55", "ref": "I 55"}) == "I 55"


def test_collapses_name_changes_on_same_ref_and_keeps_distance():
    steps = [
        step("depart", name="A St", distance=100),
        step("merge", "slight left", name="Stevenson Expy", ref="I 55", distance=1000),
        step("new name", "straight", name="Adlai Stevenson Expy", ref="I 55", distance=5000),
        step("new name", "straight", name="", ref="I 55", distance=3000),
        step("new name", "straight", name="Route 66", ref="US 66", distance=2000),  # different road: kept
        step("use lane", "straight", name="Route 66", ref="US 66", distance=500),
        step("arrive", "right", distance=0),
    ]
    out = build_instructions(steps)
    assert [i["maneuver"] for i in out] == ["depart", "merge", "new name", "arrive"]
    assert out[1]["distance_miles"] == pytest.approx(9000 / 1609.344, abs=0.01)
    assert out[2]["text"] == "Continue onto Route 66 (US 66)"
    assert out[2]["distance_miles"] == pytest.approx(2500 / 1609.344, abs=0.01)
    total = sum(i["distance_miles"] for i in out)
    assert total == pytest.approx(11600 / 1609.344, abs=0.02)


def test_roundabout_exit_is_folded_and_names_the_exit_road():
    steps = [
        step("depart", name="A St"),
        step("roundabout", "right", name="A St", distance=40, maneuver={"exit": 2}),
        step("exit roundabout", "right", name="B Ave", distance=300, maneuver={"exit": 2}),
        step("arrive"),
    ]
    out = build_instructions(steps)
    assert [i["text"] for i in out] == [
        "Head east on A St",
        "Enter the roundabout and take the second exit onto B Ave",
        "Arrive at your destination",
    ]
    assert out[1]["road"] == "B Ave"
    assert out[1]["distance_miles"] == pytest.approx(340 / 1609.344, abs=0.01)


def test_turns_are_never_collapsed():
    steps = [step("depart"), step("turn", "left", name="X", distance=5), step("turn", "right", name="X", distance=5), step("arrive")]
    assert len(build_instructions(steps)) == 4


def test_truck_duration_cap_applies():
    # 100 miles in 60 minutes (100 mph) must take 100/65 h = ~92.3 min for a truck.
    out = build_instructions([step("depart", distance=160934.4, duration=3600)])
    assert out[0]["duration_minutes"] == pytest.approx(92.3, abs=0.1)


def test_instruction_contract_keys_and_real_fixtures():
    keys = {"text", "maneuver", "modifier", "road", "distance_miles", "duration_minutes", "location"}
    for name in ("osrm_carmel_roundabouts.json", "osrm_chicago_stlouis_dallas.json.gz"):
        path = FIXTURES / name
        data = json.loads((gzip.open(path) if name.endswith(".gz") else open(path)).read())
        for leg in data["routes"][0]["legs"]:
            out = build_instructions(leg["steps"], "dropoff")
            assert out[0]["maneuver"] == "depart" and out[-1]["maneuver"] == "arrive"
            assert len(out) <= len(leg["steps"])
            assert sum(i["distance_miles"] for i in out) == pytest.approx(leg["distance"] / 1609.344, abs=0.1)
            for ins in out:
                assert set(ins) == keys
                assert ins["text"] and not ins["text"].endswith(" ")
                assert len(ins["location"]) == 2
    # Roundabout exits in the Carmel fixture all fold into their "Enter the roundabout" lines.
    carmel = json.loads((FIXTURES / "osrm_carmel_roundabouts.json").read_text())
    texts = [i["text"] for leg in carmel["routes"][0]["legs"] for i in build_instructions(leg["steps"])]
    assert not any(t.startswith("Exit the roundabout") for t in texts)
    assert "Enter the roundabout and take the third exit onto South Richland Avenue" in texts
