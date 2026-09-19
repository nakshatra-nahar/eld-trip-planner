"""Hand-calculated HOS scenarios.

Every expected event list below was worked out by hand from the rules in docs/SPEC.md
(integer minutes from the trip start). Legs are straight, constant-speed profiles so the
arithmetic is easy to follow: at 60 mph one minute is one mile.
"""

from datetime import datetime

import pytest

from trips.hos import LegProfile, PlanOptions, build_plan, plan_events
from trips.hos.audit import audit_events, audit_plan

A = (-88.0, 41.5)  # current location (lon, lat)
B = (-87.6, 41.9)  # pickup
C = (-80.0, 40.4)  # drop-off
START = datetime(2026, 9, 21, 6, 0)


def leg(start, end, miles, minutes):
    return LegProfile.straight(start, end, miles, minutes)


def legs(leg0_miles, leg0_minutes, leg1_miles, leg1_minutes):
    return [leg(A, B, leg0_miles, leg0_minutes), leg(B, C, leg1_miles, leg1_minutes)]


def namer(lat, lon, road=None):
    return f"{road} near {lat:.3f},{lon:.3f}" if road else f"{lat:.3f},{lon:.3f}"


def shape(events):
    return [(e.kind, e.start, e.end) for e in events]


def check(trip_legs, cycle, options, expected, start=START):
    events = plan_events(trip_legs, cycle, options)
    assert shape(events) == expected
    assert audit_events(events, cycle) == []
    plan = build_plan(trip_legs, start, cycle, options, namer)
    assert audit_plan(plan) == []
    return events, plan


def test_short_trip_same_day():
    """50 mi to pickup, 200 mi to drop-off; everything fits in one duty period and one day."""
    events, plan = check(
        legs(50, 60, 200, 240), 10, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 90), ("pickup", 90, 150),
            ("drive", 150, 390), ("dropoff", 390, 450), ("post_trip", 450, 465),
        ],
        start=datetime(2026, 9, 21, 8, 0),
    )
    assert [e.status for e in events] == ["ON", "D", "ON", "D", "ON", "ON"]
    assert events[1].end_mile == pytest.approx(50)
    assert events[3].start_mile == pytest.approx(50) and events[3].end_mile == pytest.approx(250)

    (log,) = plan["daily_logs"]
    assert log["date"] == "2026-09-21"
    assert log["segments"] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 480},
        {"status": "ON", "start_minute": 480, "end_minute": 510},
        {"status": "D", "start_minute": 510, "end_minute": 570},
        {"status": "ON", "start_minute": 570, "end_minute": 630},
        {"status": "D", "start_minute": 630, "end_minute": 870},
        {"status": "ON", "start_minute": 870, "end_minute": 945},
        {"status": "OFF", "start_minute": 945, "end_minute": 1440},
    ]
    assert log["totals"] == {"OFF": 16.25, "SB": 0.0, "D": 5.0, "ON": 2.75}
    assert log["total_miles"] == 250.0
    assert log["on_duty_hours"] == 7.75
    assert log["cycle_hours_used"] == 17.75  # 10 + 7.75
    assert log["cycle_hours_available"] == 52.25
    assert [r["note"] for r in log["remarks"]] == [
        "Pre-trip inspection", "Pickup", "Drop-off", "Post-trip inspection",
    ]
    s = plan["summary"]
    assert (s["start_time"], s["end_time"]) == ("2026-09-21T08:00", "2026-09-21T15:45")
    assert s["total_miles"] == 250.0 and s["num_days"] == 1
    assert plan["warnings"] == []


def test_exactly_eleven_hours_of_driving():
    """660 mi at 60 mph = 11 h of driving: one 30-min break at 8 h, no 10-h rest needed."""
    check(
        legs(0, 0, 660, 660), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 570), ("break", 570, 600),
            ("drive", 600, 780), ("dropoff", 780, 840), ("post_trip", 840, 855),
        ],
    )


def test_eleven_hour_limit_forces_rest():
    """700 mi: 11 h of driving ends at mile 660; post-trip, 10 h in the sleeper, then 40 more minutes."""
    events, plan = check(
        legs(0, 0, 700, 700), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 570), ("break", 570, 600),
            ("drive", 600, 780), ("post_trip", 780, 795), ("rest", 795, 1395),
            ("pre_trip", 1395, 1425), ("drive", 1425, 1465), ("dropoff", 1465, 1525),
            ("post_trip", 1525, 1540),
        ],
    )
    rest = events[6]
    assert rest.status == "SB" and rest.start_mile == pytest.approx(660)
    assert plan["timeline"][6]["label"] == "10-hour rest (sleeper berth)"
    # 06:00 + 795 min = 19:15; the rest runs to 05:15 the next day.
    assert [d["date"] for d in plan["daily_logs"]] == ["2026-09-21", "2026-09-22"]
    day2 = plan["daily_logs"][1]
    assert day2["remarks"][0]["note"] == "10-hour rest (cont.)"
    assert day2["remarks"][0]["start_minute"] == 0 and day2["remarks"][0]["end_minute"] == 315


def test_rest_status_off_duty():
    events, plan = check(
        legs(0, 0, 700, 700), 0, PlanOptions(rest_status="OFF", include_inspections=False),
        [
            ("pickup", 0, 60), ("drive", 60, 540), ("break", 540, 570), ("drive", 570, 750),
            ("rest", 750, 1350), ("drive", 1350, 1390), ("dropoff", 1390, 1450),
        ],
    )
    assert events[4].status == "OFF"
    assert plan["timeline"][4]["label"] == "10-hour rest (off duty)"


def test_fourteen_hour_window_limits_driving():
    """With a 150-min fuel stop the 14-h window, not the 11-h limit, ends the first period.

    Leg 0 is a fast synthetic 1,200 mi in 600 min (2 mi/min), so the window runs out
    during the pickup: pickup is still allowed (on duty, not driving), driving is not.
    """
    opts = PlanOptions(fuel_stop_minutes=150)
    events, _ = check(
        legs(1200, 600, 60, 60), 0, opts,
        [
            ("pre_trip", 0, 30), ("drive", 30, 510), ("break", 510, 540), ("drive", 540, 560),
            ("fuel", 560, 710), ("drive", 710, 810), ("pickup", 810, 870),
            ("post_trip", 870, 885), ("rest", 885, 1485), ("pre_trip", 1485, 1515),
            ("drive", 1515, 1575), ("dropoff", 1575, 1635), ("post_trip", 1635, 1650),
        ],
    )
    fuel = events[4]
    assert fuel.start_mile == pytest.approx(1000)
    drive_minutes = sum(e.duration for e in events[:7] if e.kind == "drive")
    assert drive_minutes == 600  # < 11 h: the 14-h window is what forced the rest


def test_restart_when_cycle_runs_out():
    """Cycle 65 h: 3.5 h of driving hits 70 h, so a 34-h restart splits the trip over 3 days."""
    events, plan = check(
        legs(0, 0, 600, 600), 65, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 300), ("post_trip", 300, 315),
            ("restart", 315, 2355), ("pre_trip", 2355, 2385), ("drive", 2385, 2775),
            ("dropoff", 2775, 2835), ("post_trip", 2835, 2850),
        ],
    )
    assert events[2].end_mile == pytest.approx(210)
    assert events[4].status == "OFF"
    logs = plan["daily_logs"]
    assert [d["date"] for d in logs] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert [d["total_miles"] for d in logs] == [210.0, 135.0, 255.0]
    # Day 1 ends mid-restart (70.25 h used); days 2-3 count only time after the restart.
    assert [d["cycle_hours_used"] for d in logs] == [70.25, 2.75, 8.25]
    assert [d["cycle_hours_available"] for d in logs] == [0.0, 67.25, 61.75]
    # The restart runs 11:15 on day 1 to 21:15 on day 2.
    assert logs[1]["segments"][:2] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 1275},
        {"status": "ON", "start_minute": 1275, "end_minute": 1305},
    ]
    assert logs[1]["remarks"][0]["note"] == "34-hour restart (cont.)"
    s = plan["summary"]
    assert s["num_restarts"] == 1
    assert s["cycle_hours_used_at_end"] == 8.25
    assert plan["warnings"] == ["34-hour restart required: cycle hours exhausted on day 1."]


@pytest.mark.parametrize("cycle", [70, 69.5, 69.99])
def test_cycle_nearly_or_fully_used_at_start(cycle):
    """Less than 1 h of cycle left: restart before opening the first duty period."""
    _, plan = check(
        legs(0, 0, 100, 120), cycle, PlanOptions(),
        [
            ("restart", 0, 2040), ("pre_trip", 2040, 2070), ("pickup", 2070, 2130),
            ("drive", 2130, 2250), ("dropoff", 2250, 2310), ("post_trip", 2310, 2325),
        ],
    )
    assert plan["summary"]["cycle_hours_used_at_end"] == 4.75
    assert plan["warnings"][0].startswith("34-hour restart required before driving")
    assert plan["daily_logs"][0]["segments"] == [{"status": "OFF", "start_minute": 0, "end_minute": 1440}]


def test_cycle_69_works_then_restarts():
    """69 h is not above the 69-h threshold: pre-trip and pickup push it to 70.5, then restart."""
    check(
        legs(0, 0, 100, 120), 69, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("post_trip", 90, 105),
            ("restart", 105, 2145), ("pre_trip", 2145, 2175), ("drive", 2175, 2295),
            ("dropoff", 2295, 2355), ("post_trip", 2355, 2370),
        ],
    )


@pytest.mark.parametrize("leg0_miles", [0.0, 0.05])
def test_current_equals_pickup(leg0_miles):
    """A (near) zero-length first leg is not driven; the pickup happens right after the pre-trip."""
    trip_legs = [leg(B, B, leg0_miles, leg0_miles), leg(B, C, 120, 120)]
    events, plan = check(
        trip_legs, 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 210),
            ("dropoff", 210, 270), ("post_trip", 270, 285),
        ],
    )
    pickup = events[1]
    assert pickup.leg_index == 0 and pickup.start_coord == B and pickup.start_mile == 0
    assert all(e.leg_index == 1 for e in events[2:])
    assert plan["summary"]["total_miles"] == 120.0


def test_fuel_point_coincides_with_leg_end():
    """Leg 0 is exactly 1,000 mi: no fuel before the pickup, but fuel before driving on."""
    events, _ = check(
        legs(1000, 1000, 100, 100), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 510), ("break", 510, 540), ("drive", 540, 720),
            ("post_trip", 720, 735), ("rest", 735, 1335), ("pre_trip", 1335, 1365),
            ("drive", 1365, 1705), ("pickup", 1705, 1765), ("fuel", 1765, 1795),
            ("drive", 1795, 1895), ("dropoff", 1895, 1955), ("post_trip", 1955, 1970),
        ],
    )
    assert events[9].start_mile == pytest.approx(1000) and events[9].leg_index == 1


def test_trip_ending_exactly_at_midnight():
    """14:00 start + 10 h of activity ends at 24:00: one sheet, no OFF padding at the end."""
    _, plan = check(
        legs(0, 0, 480, 480), 0, PlanOptions(include_inspections=False),
        [("pickup", 0, 60), ("drive", 60, 540), ("dropoff", 540, 600)],
        start=datetime(2026, 9, 21, 14, 0),
    )
    (log,) = plan["daily_logs"]
    assert log["segments"] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 840},
        {"status": "ON", "start_minute": 840, "end_minute": 900},
        {"status": "D", "start_minute": 900, "end_minute": 1380},
        {"status": "ON", "start_minute": 1380, "end_minute": 1440},
    ]
    assert plan["summary"]["end_time"] == "2026-09-22T00:00"
    assert plan["summary"]["num_days"] == 1


def test_driving_across_midnight_splits_miles():
    """A driving event from 22:00 to 02:00 puts 120 mi on day 1 and 120 mi on day 2."""
    _, plan = check(
        legs(0, 0, 240, 240), 0, PlanOptions(include_inspections=False),
        [("pickup", 0, 60), ("drive", 60, 300), ("dropoff", 300, 360)],
        start=datetime(2026, 9, 21, 21, 0),
    )
    assert [d["total_miles"] for d in plan["daily_logs"]] == [120.0, 120.0]
    assert plan["daily_logs"][1]["segments"][0] == {"status": "D", "start_minute": 0, "end_minute": 120}


def test_multi_day_2500_miles():
    """100 mi to pickup + 2,400 mi at 60 mph: three 10-h rests, two fuel stops, four sheets."""
    events, plan = check(
        legs(100, 100, 2400, 2400), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 130), ("pickup", 130, 190),
            ("drive", 190, 670), ("break", 670, 700), ("drive", 700, 780),
            ("post_trip", 780, 795), ("rest", 795, 1395),
            ("pre_trip", 1395, 1425), ("drive", 1425, 1765), ("fuel", 1765, 1795),
            ("drive", 1795, 2115), ("post_trip", 2115, 2130), ("rest", 2130, 2730),
            ("pre_trip", 2730, 2760), ("drive", 2760, 3240), ("break", 3240, 3270),
            ("drive", 3270, 3450), ("post_trip", 3450, 3465), ("rest", 3465, 4065),
            ("pre_trip", 4065, 4095), ("drive", 4095, 4115), ("fuel", 4115, 4145),
            ("drive", 4145, 4625), ("break", 4625, 4655), ("drive", 4655, 4675),
            ("dropoff", 4675, 4735), ("post_trip", 4735, 4750),
        ],
    )
    fuel_miles = [e.start_mile for e in events if e.kind == "fuel"]
    assert fuel_miles == pytest.approx([1000, 2000])
    s = plan["summary"]
    assert s["total_miles"] == 2500.0
    assert s["total_driving_hours"] == 41.67  # 2,500 min
    assert s["total_on_duty_hours"] == 47.67  # + 4 pre, 4 post, pickup, drop-off, 2 fuel = 360 min
    assert s["end_time"] == "2026-09-24T13:10"
    assert (s["num_days"], s["num_fuel_stops"], s["num_breaks"], s["num_rests"], s["num_restarts"]) == (4, 2, 3, 3, 0)
    assert [d["cycle_hours_used"] for d in plan["daily_logs"]] == [12.75, 25.0, 36.75, 47.67]
    assert sum(d["total_miles"] for d in plan["daily_logs"]) == pytest.approx(2500)


def test_fuel_stop_can_count_as_the_break():
    """When the 8-h break and the fuel stop fall due together, one 30-min fuel stop serves both."""
    # Leg 1 at 125 mph: after 480 min of driving the truck has covered exactly 1,000 mi.
    events, _ = check(
        [leg(B, B, 0, 0), leg(B, C, 1100, 528)], 0, PlanOptions(include_inspections=False),
        [("pickup", 0, 60), ("drive", 60, 540), ("fuel", 540, 570), ("drive", 570, 618), ("dropoff", 618, 678)],
    )
    assert not [e for e in events if e.kind == "break"]


def test_invalid_inputs():
    trip = legs(10, 10, 10, 10)
    with pytest.raises(ValueError):
        plan_events(trip, 70.5, PlanOptions())
    with pytest.raises(ValueError):
        plan_events(trip, -1, PlanOptions())
    with pytest.raises(ValueError):
        plan_events(trip[:1], 0, PlanOptions())
    with pytest.raises(ValueError):
        PlanOptions(rest_status="ON")
    with pytest.raises(ValueError):
        PlanOptions(fuel_stop_minutes=0)
