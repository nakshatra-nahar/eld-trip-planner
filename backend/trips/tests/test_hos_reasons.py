"""Stop reasons: every non-driving event says which rule scheduled it.

Each test plans a hand-checked scenario (most are the ones in test_hos_scenarios.py, whose
event lists are verified there) and asserts the ``reason`` the plan sends for the stop the
scenario is about. ``reason`` is recorded where the planner decides (``DutyEvent.cause``)
and worded in ``logs``; test_hos_properties.py checks the recorded numbers against the
event list for random trips.
"""

from datetime import datetime

import pytest

from trips.hos import LegProfile, PlanOptions, build_plan

from .test_hos_scenarios import START, B, C, check, leg, legs, namer, st55


def plan_for(trip, cycle, options, start=START):
    return build_plan(trip, start, cycle, options, namer)


def reasons(plan, kind):
    """(start clock, reason) of each timeline event of ``kind``."""
    return [(ev["start"][11:], ev.get("reason")) for ev in plan["timeline"] if ev["kind"] == kind]


def test_every_stop_has_a_reason_and_driving_has_none():
    plan = plan_for(legs(0, 0, 700, 700), 0, PlanOptions(include_inspections=True))
    for ev in plan["timeline"]:
        if ev["kind"] == "drive":
            assert "reason" not in ev
        else:
            assert isinstance(ev["reason"], str) and ev["reason"].strip() == ev["reason"] != ""
    by_id = {ev["id"]: ev for ev in plan["timeline"]}
    assert [s["reason"] for s in plan["stops"]] == [by_id[s["id"]]["reason"] for s in plan["stops"]]


def test_eleven_hour_limit():
    """700 mi at 60 mph: the rest at mile 660 follows 11 h of driving (19:15, after the post-trip)."""
    plan = plan_for(legs(0, 0, 700, 700), 0, PlanOptions(include_inspections=True))
    assert reasons(plan, "rest") == [("19:15", "11-hour driving limit reached")]


def test_fourteen_hour_window():
    """Duty period opened at 06:00, so the window closes at 20:00, as the pickup ends; the
    rest follows the post-trip. The 150-min fuel stop at mile 960 is the 8-h break."""
    plan = plan_for(legs(1200, 600, 60, 60), 0, PlanOptions(include_inspections=True, fuel_stop_minutes=150))
    assert reasons(plan, "rest") == [("20:15", "14-hour duty window closes at 20:00")]
    assert reasons(plan, "fuel") == [(
        "14:30",
        "30-minute break due after 8 hours of driving, taken as a fuel stop: fuel is due in 40 mi "
        "(960 mi on this tank)",
    )]


def test_eight_hour_break():
    plan = plan_for(legs(0, 0, 660, 660), 0, PlanOptions(include_inspections=True))
    assert reasons(plan, "break") == [("15:30", "8 hours of driving without a 30-minute interruption")]


def test_fuel_interval():
    """1,980 mi: the fuel stop stays on the road at mile 1,000 (fueling at the rest would add a stop)."""
    plan = plan_for([leg(B, B, 0, 0), leg(B, C, 1980, 1485)], 0, PlanOptions(include_inspections=False))
    assert reasons(plan, "fuel") == [("06:00", "1,000-mile fuel interval (1,000 mi on this tank)")]


def test_fuel_interval_that_is_also_the_break():
    plan = plan_for([leg(B, B, 0, 0), leg(B, C, 1100, 528)], 0, PlanOptions(include_inspections=False))
    assert reasons(plan, "fuel") == [(
        "15:00",
        "1,000-mile fuel interval (1,000 mi on this tank); also serves as the 30-minute break due "
        "after 8 hours of driving",
    )]
    assert reasons(plan, "break") == []


def test_fuel_before_the_rest():
    """80 mph: the 11-h limit binds at mile 880; fuel would fall due 90 min into the next period."""
    plan = plan_for([leg(B, B, 0, 0), leg(B, C, 1500, 1125)], 0, PlanOptions(include_inspections=False))
    assert reasons(plan, "fuel") == [(
        "18:30",
        "Fueling before the rest: fuel is due in 120 mi, early in the next duty period "
        "(880 mi on this tank)",
    )]
    assert reasons(plan, "rest") == [("19:00", "11-hour driving limit reached")]


def test_short_fuel_stop_followed_by_the_break():
    """15-min fuel stops: fuel due at 430 min of driving, the break 50 min later, both taken together."""
    opts = PlanOptions(include_inspections=False, fuel_stop_minutes=15)
    plan = plan_for([leg(B, B, 0, 0), leg(B, C, 1300, 559)], 0, opts)
    assert reasons(plan, "fuel") == [("14:10", "1,000-mile fuel interval (1,000 mi on this tank)")]
    assert reasons(plan, "break") == [
        ("14:25", "Taken at the fuel stop: the 30-minute break would be due after 50m more driving"),
    ]


def test_fuel_right_after_a_restart():
    """10 h used, 3,050 mi at 55 mph: the cycle runs out with fuel nearly due and no room to fuel
    before the restart, so the truck fuels after the pre-trip, before driving off."""
    trip = [st55((-95, 37), (-95, 37), 0), st55((-95, 37), (-80, 37), 3050)]
    plan = plan_for(trip, 10, PlanOptions(include_inspections=True))
    assert reasons(plan, "restart") == [("11:30", "70-hour/8-day cycle used up (70h); 34 consecutive hours off resets it")]
    assert reasons(plan, "fuel")[-1] == (
        "22:00", "Fuel is due in 15 mi (985 mi on this tank): fueling before driving off",
    )


def test_cycle_restart():
    plan = plan_for(legs(0, 0, 840, 840), 65, PlanOptions(include_inspections=True))
    assert reasons(plan, "restart") == [("11:00", "70-hour/8-day cycle used up (70h); 34 consecutive hours off resets it")]


def test_opening_restart_credits_the_time_off_since_midnight():
    plan = plan_for(legs(0, 0, 100, 120), 70, PlanOptions(include_inspections=True), start=datetime(2026, 9, 21, 8, 0))
    assert reasons(plan, "restart") == [(
        "08:00",
        "70-hour/8-day cycle used up (70h); 34 consecutive hours off resets it "
        "(credited with 8h off duty since midnight)",
    )]
    # A midnight start has nothing to credit.
    plan = plan_for(legs(0, 0, 100, 120), 70, PlanOptions(include_inspections=True), start=datetime(2026, 9, 21))
    assert reasons(plan, "restart") == [("00:00", "70-hour/8-day cycle used up (70h); 34 consecutive hours off resets it")]


def test_opening_restart_when_the_cycle_is_nearly_used_up():
    """69 h used: pre-trip, pickup and post-trip alone would pass 70 h before any driving."""
    plan = plan_for(legs(0, 0, 100, 120), 69, PlanOptions(include_inspections=True))
    assert reasons(plan, "restart") == [(
        "06:00",
        "70-hour/8-day cycle nearly used up (69h of 70h); 34 consecutive hours off resets it "
        "(credited with 6h off duty since midnight)",
    )]


def test_optional_restart_at_the_start():
    """65 h used, 600 mi: restarting first arrives earlier than driving 3.25 h and restarting then."""
    plan = plan_for(legs(0, 0, 600, 600), 65, PlanOptions(include_inspections=True))
    assert reasons(plan, "restart") == [(
        "06:00",
        "Only 5h left in the 70-hour cycle and the trip needs more: restarting before driving "
        "arrives earliest (credited with 6h off duty since midnight)",
    )]


def test_early_restart_replacing_a_rest():
    """LA -> Phoenix -> New York, 30 h used: the first 10-h rest (11 h of driving) becomes the restart."""
    LA, PHX, NYC = (-118.24, 34.05), (-112.07, 33.45), (-74.0, 40.71)
    trip = [st55(LA, PHX, 373), st55(PHX, NYC, 2411)]
    plan = plan_for(trip, 30, PlanOptions(include_inspections=True), start=datetime(2026, 9, 21, 8, 0))
    # 30 h + 30 min pre-trip + 11 h driving + 1 h pickup + 15 min post-trip = 42h 45m used.
    assert reasons(plan, "restart") == [(
        "20:45",
        "Taken here instead of a 10-hour rest (11-hour driving limit reached) to reset the 70-hour "
        "cycle: the rest of the trip needs more than the 27h 15m left",
    )]


def test_restart_before_the_pickup():
    """66 h used: the pickup would leave no cycle to drive on, so the restart comes first."""
    trip = [LegProfile.straight((-90, 40), (-89, 40), 165, 180), LegProfile.straight((-89, 40), (-80, 40), 600, 600)]
    plan = plan_for(trip, 66, PlanOptions(include_inspections=True))
    # 66 h + 30 min pre-trip + 3 h driving + 15 min post-trip.
    assert reasons(plan, "restart") == [(
        "09:45",
        "70-hour/8-day cycle nearly used up (69h 45m of 70h): no driving time would be left after "
        "the pickup; 34 consecutive hours off resets it",
    )]


@pytest.mark.parametrize("inspections", [True, False])
def test_pickup_dropoff_and_inspections(inspections):
    plan = plan_for(legs(50, 60, 200, 240), 10, PlanOptions(include_inspections=inspections))
    assert [r for _, r in reasons(plan, "pickup")] == ["1 hour on duty for loading, per the trip assumptions"]
    assert [r for _, r in reasons(plan, "dropoff")] == ["1 hour on duty for unloading, per the trip assumptions"]
    pre, post = reasons(plan, "pre_trip"), reasons(plan, "post_trip")
    if inspections:
        assert [r for _, r in pre] == ["Starts every duty period: 30 minutes on duty (inspections are on)"]
        assert [r for _, r in post] == ["Ends the trip: 15 minutes on duty (inspections are on)"]
    else:
        assert pre == post == []


def test_post_trip_before_a_rest():
    plan = plan_for(legs(0, 0, 700, 700), 0, PlanOptions(include_inspections=True))
    assert [r for _, r in reasons(plan, "post_trip")] == [
        "Ends every duty period: 15 minutes on duty (inspections are on)",
        "Ends the trip: 15 minutes on duty (inspections are on)",
    ]


def test_rest_instead_of_a_break_that_little_driving_would_follow():
    """170 mi, pickup, then 800 mi at 60 mph: the break falls due after 10h 50m of driving in
    the period, so only 10 min could follow it; the rest comes first (17:50)."""
    _, plan = check(
        legs(170, 170, 800, 800), 0, PlanOptions(include_inspections=False),
        [
            ("drive", 0, 170), ("pickup", 170, 230), ("drive", 230, 710), ("rest", 710, 1310),
            ("drive", 1310, 1630), ("dropoff", 1630, 1690),
        ],
    )
    assert reasons(plan, "rest") == [
        ("17:50", "11-hour driving limit: only 10m of driving would be left after a 30-minute break"),
    ]


def test_limit_before_stop_wording():
    """Direct check of the wording for a rest that replaces a stop (engine cause -> sentence)."""
    from trips.hos.logs import _PlanBuilder
    from trips.hos.planner import Cause, Rule, build_leg_drives, plan_drives

    trip = legs(0, 0, 700, 700)
    drives = build_leg_drives(trip)
    events = plan_drives(drives, 0, PlanOptions(), prior_off_duty_minutes=360)
    builder = _PlanBuilder(drives, events, START, 0, PlanOptions(), namer)
    word = builder._rest_reason
    assert word(Cause(Rule.LIMIT_BEFORE_STOP, limit="drive", left=10, stop="break")) == (
        "11-hour driving limit: only 10m of driving would be left after a 30-minute break"
    )
    assert word(Cause(Rule.LIMIT_BEFORE_STOP, limit="window", left=0, stop="fuel", at=840)) == (
        "14-hour duty window closes at 20:00: no driving time would be left after a fuel stop"
    )
    assert word(Cause(Rule.LIMIT_BEFORE_STOP, limit="cycle", left=14, stop="fuel_break")) == (
        "70-hour cycle: only 14m of driving would be left after fueling and a 30-minute break"
    )
