"""Hand-calculated HOS scenarios.

Every expected event list below was worked out by hand from the rules in docs/SPEC.md
(integer minutes from the trip start). Legs are straight, constant-speed profiles so the
arithmetic is easy to follow: at 60 mph one minute is one mile.
"""

from datetime import datetime
from itertools import pairwise

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

    Leg 0 is a fast synthetic 1,200 mi in 600 min (2 mi/min). The 8-h break falls due at
    mile 960, 40 mi before the tank limit, so the (>= 30-min) fuel stop is taken there and
    also counts as the break. The window then closes as the pickup ends: pickup is still
    allowed (on duty, not driving), driving is not.
    """
    opts = PlanOptions(fuel_stop_minutes=150)
    events, _ = check(
        legs(1200, 600, 60, 60), 0, opts,
        [
            ("pre_trip", 0, 30), ("drive", 30, 510), ("fuel", 510, 660), ("drive", 660, 780),
            ("pickup", 780, 840), ("post_trip", 840, 855), ("rest", 855, 1455), ("pre_trip", 1455, 1485),
            ("drive", 1485, 1545), ("dropoff", 1545, 1605), ("post_trip", 1605, 1620),
        ],
    )
    fuel = events[2]
    assert fuel.start_mile == pytest.approx(960)
    assert not [e for e in events if e.kind == "break"]
    drive_minutes = sum(e.duration for e in events[:5] if e.kind == "drive")
    assert drive_minutes == 600  # < 11 h: the 14-h window is what forced the rest


def test_restart_when_cycle_runs_out():
    """Cycle 65 h: 3.25 h of driving uses the cycle up to its last 15 min, which the post-trip
    takes; a 34-h restart then splits the trip over 3 days."""
    events, plan = check(
        legs(0, 0, 600, 600), 65, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 285), ("post_trip", 285, 300),
            ("restart", 300, 2340), ("pre_trip", 2340, 2370), ("drive", 2370, 2775),
            ("dropoff", 2775, 2835), ("post_trip", 2835, 2850),
        ],
    )
    assert events[2].end_mile == pytest.approx(195)
    assert events[4].status == "OFF"
    logs = plan["daily_logs"]
    assert [d["date"] for d in logs] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert [d["total_miles"] for d in logs] == [195.0, 150.0, 255.0]
    # Day 1 ends mid-restart at exactly 70 h; days 2-3 count only time after the restart.
    assert [d["cycle_hours_used"] for d in logs] == [70.0, 3.0, 8.5]
    assert [d["cycle_hours_available"] for d in logs] == [0.0, 67.0, 61.5]
    # The restart runs 11:00 on day 1 to 21:00 on day 2.
    assert logs[1]["segments"][:2] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 1260},
        {"status": "ON", "start_minute": 1260, "end_minute": 1290},
    ]
    assert logs[1]["remarks"][0]["note"] == "34-hour restart (cont.)"
    s = plan["summary"]
    assert s["num_restarts"] == 1
    assert s["cycle_hours_used_at_end"] == 8.5
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


def test_cycle_69_restarts_before_working():
    """69 h used: pre-trip, pickup and post-trip alone would pass 70 h before any driving,
    so the restart comes first rather than after an hour of work (recap stays <= 70)."""
    _, plan = check(
        legs(0, 0, 100, 120), 69, PlanOptions(),
        [
            ("restart", 0, 2040), ("pre_trip", 2040, 2070), ("pickup", 2070, 2130),
            ("drive", 2130, 2250), ("dropoff", 2250, 2310), ("post_trip", 2310, 2325),
        ],
    )
    assert [d["cycle_hours_used"] for d in plan["daily_logs"]] == [69.0, 4.75]


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
    """Leg 0 is exactly 1,000 mi: no fuel stop on the road; the truck fuels at the shipper."""
    events, _ = check(
        legs(1000, 1000, 100, 100), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 510), ("break", 510, 540), ("drive", 540, 720),
            ("post_trip", 720, 735), ("rest", 735, 1335), ("pre_trip", 1335, 1365),
            ("drive", 1365, 1705), ("fuel", 1705, 1735), ("pickup", 1735, 1795),
            ("drive", 1795, 1895), ("dropoff", 1895, 1955), ("post_trip", 1955, 1970),
        ],
    )
    assert events[8].start_mile == pytest.approx(1000) and events[8].leg_index == 0


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
    """100 mi to pickup + 2,400 mi at 60 mph: three 10-h rests, two fuel stops, four sheets.

    The second fuel stop falls due 20 mi after the day-3 rest, so it is taken at that stop.
    """
    events, plan = check(
        legs(100, 100, 2400, 2400), 0, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 130), ("pickup", 130, 190),
            ("drive", 190, 670), ("break", 670, 700), ("drive", 700, 780),
            ("post_trip", 780, 795), ("rest", 795, 1395),
            ("pre_trip", 1395, 1425), ("drive", 1425, 1765), ("fuel", 1765, 1795),
            ("drive", 1795, 2115), ("post_trip", 2115, 2130), ("rest", 2130, 2730),
            ("pre_trip", 2730, 2760), ("drive", 2760, 3240), ("break", 3240, 3270),
            ("drive", 3270, 3450), ("fuel", 3450, 3480), ("post_trip", 3480, 3495), ("rest", 3495, 4095),
            ("pre_trip", 4095, 4125), ("drive", 4125, 4605), ("break", 4605, 4635), ("drive", 4635, 4675),
            ("dropoff", 4675, 4735), ("post_trip", 4735, 4750),
        ],
    )
    fuel_miles = [e.start_mile for e in events if e.kind == "fuel"]
    assert fuel_miles == pytest.approx([1000, 1980])
    s = plan["summary"]
    assert s["total_miles"] == 2500.0
    assert s["total_driving_hours"] == 41.67  # 2,500 min
    assert s["total_on_duty_hours"] == 47.67  # + 4 pre, 4 post, pickup, drop-off, 2 fuel = 360 min
    assert s["end_time"] == "2026-09-24T13:10"
    assert (s["num_days"], s["num_fuel_stops"], s["num_breaks"], s["num_rests"], s["num_restarts"]) == (4, 2, 3, 3, 0)
    assert [d["cycle_hours_used"] for d in plan["daily_logs"]] == [12.75, 25.0, 37.25, 47.67]
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


# ----- cycle-planning regressions (rest vs restart, recap <= 70 h, stop placement) -----


def straight(miles, mph=60.0):
    return LegProfile.straight((-95, 37), (-90, 37), miles, miles / mph * 60)


def kinds(events):
    return [e.kind for e in events]


def test_rest_suffices_when_remaining_drive_fits_in_cycle():
    """57.5 h used: after 11 h of driving 20 min remain and 30 min of cycle; a 10-h rest is
    enough (the drop-off may run past 70 h), not a 34-h restart."""
    _, plan = check(
        [straight(180), straight(500)], 57.5, PlanOptions(include_inspections=False),
        [
            ("drive", 0, 180), ("pickup", 180, 240), ("drive", 240, 720), ("rest", 720, 1320),
            ("drive", 1320, 1340), ("dropoff", 1340, 1400),
        ],
    )
    assert plan["summary"]["cycle_hours_used_at_end"] == 70.83
    assert any("after 70 h" in w for w in plan["warnings"])


def test_no_rest_immediately_followed_by_restart():
    """56.3 h used with inspections: the post-trip is counted before choosing rest vs restart."""
    events = plan_events([straight(180), straight(500)], 56.3, PlanOptions())
    assert "restart" not in kinds(events)
    assert shape(events)[-5:] == [
        ("rest", 765, 1365), ("pre_trip", 1365, 1395), ("drive", 1395, 1415),
        ("dropoff", 1415, 1475), ("post_trip", 1475, 1490),
    ]
    assert audit_events(events, 56.3) == []


def test_restart_before_pickup_keeps_recap_within_70():
    """66 h used: the pickup would push the cycle past 70 h with driving still ahead, so the
    restart comes first and no sheet shows more than 70 h."""
    trip = [LegProfile.straight((-90, 40), (-89, 40), 165, 180), LegProfile.straight((-89, 40), (-80, 40), 300, 327)]
    _, plan = check(
        trip, 66, PlanOptions(),
        [
            ("pre_trip", 0, 30), ("drive", 30, 210), ("post_trip", 210, 225), ("restart", 225, 2265),
            ("pre_trip", 2265, 2295), ("pickup", 2295, 2355), ("drive", 2355, 2682),
            ("dropoff", 2682, 2742), ("post_trip", 2742, 2757),
        ],
    )
    assert max(d["cycle_hours_used"] for d in plan["daily_logs"]) <= 70


def test_no_break_when_little_driving_would_follow():
    """The 8-h break is skipped when the 14-h window or cycle would allow < 15 min after it."""
    events = plan_events([straight(1644, 47.3), straight(1830, 47.3)], 61.3, PlanOptions())
    assert audit_events(events, 61.3) == []
    assert "break" in kinds(events)
    for ev, nxt, after in zip(events, events[1:], events[2:], strict=False):
        if ev.kind == "break" and nxt.kind == "drive" and nxt.duration < 15:
            assert after.kind in ("pickup", "dropoff"), (ev, nxt, after)  # short only to reach the stop


def test_fuel_taken_at_the_rest_stop_when_nearly_due():
    """Fuel due 2 mi after the 11-h limit: fuel, post-trip and rest happen at one stop."""
    events = plan_events([straight(1306.6, 55), straight(2448.2, 55)], 46.94, PlanOptions(fuel_stop_minutes=15))
    for a, b in pairwise(events):
        if a.kind == "fuel" and b.kind == "drive":
            assert b.duration >= 15
    assert audit_events(events, 46.94) == []


def test_fuel_stop_replaces_a_break_when_nearly_due():
    events = plan_events(
        [straight(616.9, 47.3), straight(3350, 47.3)], 39.35,
        PlanOptions(include_inspections=False, fuel_stop_minutes=45),
    )
    first_fuel = next(i for i, e in enumerate(events) if e.kind == "fuel")
    assert events[first_fuel - 1].kind == "drive" and events[first_fuel - 2].kind != "break"
    assert audit_events(events, 39.35) == []


def test_trip_start_remark_without_inspections():
    """With inspections off the OFF -> D change at the trip start still gets a location remark."""
    trip = [straight(100), straight(700)]
    plan = build_plan(trip, datetime(2026, 1, 5, 23, 59), 20, PlanOptions(include_inspections=False), namer)
    (first,) = plan["daily_logs"][0]["remarks"]
    assert (first["start_minute"], first["end_minute"], first["status"]) == (1439, 1440, "D")
    assert first["note"] == "Start of trip / on duty"
