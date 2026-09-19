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
from trips.hos.planner import _Planner, build_leg_drives

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


def since_midnight(start):
    return start.hour * 60 + start.minute


def check(trip_legs, cycle, options, expected, start=START):
    """Events as ``build_plan`` plans them for ``start`` (off duty since midnight before it)."""
    prior = since_midnight(start)
    events = plan_events(trip_legs, cycle, options, prior_off_duty_minutes=prior)
    assert shape(events) == expected
    assert audit_events(events, cycle, prior) == []
    plan = build_plan(trip_legs, start, cycle, options, namer)
    assert audit_plan(plan) == []
    return events, plan


def test_short_trip_same_day():
    """50 mi to pickup, 200 mi to drop-off; everything fits in one duty period and one day."""
    events, plan = check(
        legs(50, 60, 200, 240), 10, PlanOptions(include_inspections=True),
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
        legs(0, 0, 660, 660), 0, PlanOptions(include_inspections=True),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 570), ("break", 570, 600),
            ("drive", 600, 780), ("dropoff", 780, 840), ("post_trip", 840, 855),
        ],
    )


def test_eleven_hour_limit_forces_rest():
    """700 mi: 11 h of driving ends at mile 660; post-trip, 10 h in the sleeper, then 40 more minutes."""
    events, plan = check(
        legs(0, 0, 700, 700), 0, PlanOptions(include_inspections=True),
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
    opts = PlanOptions(include_inspections=True, fuel_stop_minutes=150)
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
    """Cycle 65 h, 840 mi: 3.25 h of driving uses the cycle up to its last 15 min, which the
    post-trip takes; a 34-h restart then splits the trip over 3 days.

    Restarting at the start instead (06:00, so 28 h long) would leave 14 h of driving after
    it, which needs a 10-h rest: arrival at minute 3,360 rather than 3,120. So the planner
    keeps the greedy plan. (Until the restart-placement search, this test used 600 mi; that
    trip now restarts at the start, see test_restart_at_the_start_when_it_arrives_earlier.)
    """
    events, plan = check(
        legs(0, 0, 840, 840), 65, PlanOptions(include_inspections=True),
        [
            ("pre_trip", 0, 30), ("pickup", 30, 90), ("drive", 90, 285), ("post_trip", 285, 300),
            ("restart", 300, 2340), ("pre_trip", 2340, 2370), ("drive", 2370, 2850),
            ("break", 2850, 2880), ("drive", 2880, 3045), ("dropoff", 3045, 3105), ("post_trip", 3105, 3120),
        ],
    )
    assert events[2].end_mile == pytest.approx(195)
    assert events[4].status == "OFF"
    logs = plan["daily_logs"]
    assert [d["date"] for d in logs] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert [d["total_miles"] for d in logs] == [195.0, 150.0, 495.0]
    # Day 1 ends mid-restart at exactly 70 h; days 2-3 count only time after the restart.
    assert [d["cycle_hours_used"] for d in logs] == [70.0, 3.0, 12.5]
    assert [d["cycle_hours_available"] for d in logs] == [0.0, 67.0, 57.5]
    # The restart runs 11:00 on day 1 to 21:00 on day 2.
    assert logs[1]["segments"][:2] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 1260},
        {"status": "ON", "start_minute": 1260, "end_minute": 1290},
    ]
    assert logs[1]["remarks"][0]["note"] == "34-hour restart (cont.)"
    s = plan["summary"]
    assert s["num_restarts"] == 1
    assert s["cycle_hours_used_at_end"] == 12.5
    assert plan["warnings"] == [
        "34-hour restart required on day 1: the 70-hour cycle is used up and driving remains "
        "(assumes none of the hours already used roll off during the trip)."
    ]


def test_restart_at_the_start_when_it_arrives_earlier():
    """Cycle 65 h, 600 mi, 06:00 start. Greedy: 3.25 h of driving, then the restart
    (arrival at minute 2,850). Restarting first counts the 6 h off since midnight (28 h),
    and all 10 h of driving then fit in one duty period: arrival at minute 2,475."""
    _, plan = check(
        legs(0, 0, 600, 600), 65, PlanOptions(include_inspections=True),
        [
            ("restart", 0, 1680), ("pre_trip", 1680, 1710), ("pickup", 1710, 1770),
            ("drive", 1770, 2250), ("break", 2250, 2280), ("drive", 2280, 2400),
            ("dropoff", 2400, 2460), ("post_trip", 2460, 2475),
        ],
    )
    greedy = _Planner(build_leg_drives(legs(0, 0, 600, 600)), 65 * 60, PlanOptions(include_inspections=True), 360).run()
    assert kinds(greedy)[:5] == ["pre_trip", "pickup", "drive", "post_trip", "restart"]
    assert greedy[-1].end == 2850
    assert plan["summary"]["end_time"] == "2026-09-22T23:15"
    assert plan["warnings"] == [
        "34-hour restart required before driving: only 5h of the 70-hour cycle is available at the "
        "start and the trip needs more; it counts the 6h off duty since midnight, so it lasts 28h "
        "(assumes none of the hours already used roll off during the trip)."
    ]


@pytest.mark.parametrize("cycle", [70, 69.5, 69.99])
def test_cycle_nearly_or_fully_used_at_start(cycle):
    """Less than 1 h of cycle left: restart before opening the first duty period. The 6 h
    off duty since midnight count toward it, so it lasts 28 h (to 10:00 on day 2)."""
    _, plan = check(
        legs(0, 0, 100, 120), cycle, PlanOptions(include_inspections=True),
        [
            ("restart", 0, 1680), ("pre_trip", 1680, 1710), ("pickup", 1710, 1770),
            ("drive", 1770, 1890), ("dropoff", 1890, 1950), ("post_trip", 1950, 1965),
        ],
    )
    assert plan["summary"]["cycle_hours_used_at_end"] == 4.75
    assert plan["warnings"][0].startswith("34-hour restart required before driving")
    assert plan["daily_logs"][0]["segments"] == [{"status": "OFF", "start_minute": 0, "end_minute": 1440}]


def test_cycle_69_restarts_before_working():
    """69 h used: pre-trip, pickup and post-trip alone would pass 70 h before any driving,
    so the restart comes first rather than after an hour of work (recap stays <= 70)."""
    _, plan = check(
        legs(0, 0, 100, 120), 69, PlanOptions(include_inspections=True),
        [
            ("restart", 0, 1680), ("pre_trip", 1680, 1710), ("pickup", 1710, 1770),
            ("drive", 1770, 1890), ("dropoff", 1890, 1950), ("post_trip", 1950, 1965),
        ],
    )
    assert [d["cycle_hours_used"] for d in plan["daily_logs"]] == [69.0, 4.75]


@pytest.mark.parametrize("leg0_miles", [0.0, 0.05])
def test_current_equals_pickup(leg0_miles):
    """A (near) zero-length first leg is not driven; the pickup happens right after the pre-trip."""
    trip_legs = [leg(B, B, leg0_miles, leg0_miles), leg(B, C, 120, 120)]
    events, plan = check(
        trip_legs, 0, PlanOptions(include_inspections=True),
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
        legs(1000, 1000, 100, 100), 0, PlanOptions(include_inspections=True),
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
        legs(100, 100, 2400, 2400), 0, PlanOptions(include_inspections=True),
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
    for prior in (-1, 2040, 1.5):
        with pytest.raises(ValueError):
            plan_events(trip, 0, PlanOptions(include_inspections=True), prior_off_duty_minutes=prior)
    with pytest.raises(ValueError):
        plan_events(trip, 70.5, PlanOptions(include_inspections=True))
    with pytest.raises(ValueError):
        plan_events(trip, -1, PlanOptions(include_inspections=True))
    with pytest.raises(ValueError):
        plan_events(trip[:1], 0, PlanOptions(include_inspections=True))
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
    events = plan_events([straight(180), straight(500)], 56.3, PlanOptions(include_inspections=True))
    assert "restart" not in kinds(events)
    assert shape(events)[-5:] == [
        ("rest", 765, 1365), ("pre_trip", 1365, 1395), ("drive", 1395, 1415),
        ("dropoff", 1415, 1475), ("post_trip", 1475, 1490),
    ]
    assert audit_events(events, 56.3) == []


def test_restart_before_pickup_keeps_recap_within_70():
    """66 h used: the pickup would push the cycle past 70 h with driving still ahead, so the
    restart comes first and no sheet shows more than 70 h.

    Leg 1 is 10 h of driving (it was 327 min before the restart-placement search, when a
    restart at the start then arrived earlier): driving leg 0 before the restart lets leg 1
    fit in one duty period after it.
    """
    trip = [LegProfile.straight((-90, 40), (-89, 40), 165, 180), LegProfile.straight((-89, 40), (-80, 40), 600, 600)]
    _, plan = check(
        trip, 66, PlanOptions(include_inspections=True),
        [
            ("pre_trip", 0, 30), ("drive", 30, 210), ("post_trip", 210, 225), ("restart", 225, 2265),
            ("pre_trip", 2265, 2295), ("pickup", 2295, 2355), ("drive", 2355, 2835), ("break", 2835, 2865),
            ("drive", 2865, 2985), ("dropoff", 2985, 3045), ("post_trip", 3045, 3060),
        ],
    )
    assert max(d["cycle_hours_used"] for d in plan["daily_logs"]) <= 70


def test_no_break_when_little_driving_would_follow():
    """The 8-h break is skipped when the 14-h window or cycle would allow < 15 min after it."""
    events = plan_events([straight(1644, 47.3), straight(1830, 47.3)], 61.3, PlanOptions(include_inspections=True))
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


# ----- restart placement, time off before the start, fuel placement, warning texts -----


def st55(start, end, miles):
    return LegProfile.straight(start, end, miles, miles / 55 * 60)


def greedy_events(trip, cycle, options, prior=0):
    """The plan without the restart-placement search (every optional restart declined)."""
    return _Planner(build_leg_drives(trip), cycle * 60, options, prior).run()


def stops(events):
    return [(e.kind, e.start, e.end) for e in events if e.kind != "drive"]


def test_restart_replaces_a_rest_when_the_rest_of_the_trip_fits_a_fresh_cycle():
    """Grader repro: Los Angeles -> Phoenix (373 mi) -> New York (2,411 mi) at 55 mph, 30 h
    used, 08:00 start. Greedy: three 10-h rests, then 2.5 h of driving and a 34-h restart
    (near Marshall, IL). At the first rest ~51 h of on-duty work remain, more than the 27.25 h
    left but less than a fresh cycle, so the restart takes that rest's place: 11.25 h earlier.
    """
    LA, PHX, NYC = (-118.24, 34.05), (-112.07, 33.45), (-74.0, 40.71)
    trip = [st55(LA, PHX, 373), st55(PHX, NYC, 2411)]
    opts = PlanOptions(include_inspections=True)
    greedy = greedy_events(trip, 30, opts, prior=480)
    assert [k for k in kinds(greedy) if k in ("rest", "restart")] == ["rest", "rest", "rest", "restart", "rest"]
    restart = kinds(greedy).index("restart")
    assert kinds(greedy)[restart - 4 : restart] == ["rest", "pre_trip", "drive", "post_trip"]
    assert greedy[restart - 2].duration == 150  # 2.5 h of driving between the rest and the restart
    assert greedy[-1].end == 7987  # 133.12 h

    events = plan_events(trip, 30, opts, prior_off_duty_minutes=480)
    assert audit_events(events, 30, 480) == []
    assert [k for k in kinds(events) if k in ("rest", "restart")] == ["restart", "rest", "rest", "rest"]
    first = events[kinds(events).index("restart")]
    assert (first.start, first.start_mile) == (765, pytest.approx(604.9, abs=0.1))  # 11 h of driving
    assert events[-1].end == 7312  # 121.87 h
    assert greedy[-1].end - events[-1].end == 675
    plan = build_plan(trip, datetime(2026, 9, 21, 8, 0), 30, opts, namer)
    assert audit_plan(plan) == []
    assert plan["summary"]["end_time"] == "2026-09-26T09:52"


def test_no_optional_restart_when_the_rest_of_the_trip_exceeds_a_fresh_cycle():
    """50 h used, 4,500 mi at 60 mph: at the first rest ~64 h of driving (over 70 h of work)
    remain, more than a fresh cycle holds, so no early restart is offered; the restart waits
    until the cycle runs out."""
    trip = [straight(0), straight(4500)]
    planner = _Planner(build_leg_drives(trip), 50 * 60, PlanOptions(include_inspections=True))
    events = planner.run()
    assert planner.restart_options == 0
    assert [(e.kind, e.start) for e in events if e.kind in ("rest", "restart")][:2] == [("rest", 795), ("restart", 1830)]
    assert shape(plan_events(trip, 50, PlanOptions(include_inspections=True))) == shape(events)


def test_greedy_plan_kept_when_an_early_restart_does_not_arrive_sooner():
    """10 h used, 3,050 mi at 55 mph: early restarts are offered at five rests, but none
    arrives sooner than using up the cycle first, so the greedy plan is kept (also on a tie)."""
    trip = [st55((-95, 37), (-95, 37), 0), st55((-95, 37), (-80, 37), 3050)]
    drives, opts = build_leg_drives(trip), PlanOptions(include_inspections=True)
    planner = _Planner(drives, 10 * 60, opts)
    greedy = planner.run()
    assert planner.restart_options == 5
    for index in range(5):
        assert _Planner(drives, 10 * 60, opts, restart_at=index).run()[-1].end >= greedy[-1].end
    assert shape(plan_events(trip, 10, opts)) == shape(greedy)


def test_restart_at_the_start_counts_the_time_off_since_midnight():
    """70 h used, 08:00 start: the log shows the driver off duty since midnight, so the restart
    ends 34 h after midnight (10:00 on day 2), not 34 h after the start (18:00)."""
    trip = legs(0, 0, 100, 120)
    events, plan = check(
        trip, 70, PlanOptions(include_inspections=True),
        [
            ("restart", 0, 1560), ("pre_trip", 1560, 1590), ("pickup", 1590, 1650),
            ("drive", 1650, 1770), ("dropoff", 1770, 1830), ("post_trip", 1830, 1845),
        ],
        start=datetime(2026, 9, 21, 8, 0),
    )
    # Without the 8 h before the start the 26-h restart would not reset the cycle.
    assert any("cycle reaches" in p for p in audit_events(events, 70))
    restart = plan["timeline"][0]
    assert (restart["start"], restart["end"], restart["duration_hours"]) == ("2026-09-21T08:00", "2026-09-22T10:00", 26.0)
    day1, day2 = plan["daily_logs"]
    assert day1["segments"] == [{"status": "OFF", "start_minute": 0, "end_minute": 1440}]
    assert day2["segments"][:2] == [
        {"status": "OFF", "start_minute": 0, "end_minute": 600},
        {"status": "ON", "start_minute": 600, "end_minute": 690},
    ]
    assert [d["cycle_hours_used"] for d in plan["daily_logs"]] == [70.0, 4.75]
    assert plan["warnings"] == [
        "34-hour restart required before driving: the 70-hour cycle is already used up at the start; "
        "it counts the 8h off duty since midnight, so it lasts 26h "
        "(assumes none of the hours already used roll off during the trip)."
    ]
    # A midnight start has no time off to count.
    assert plan_events(trip, 70, PlanOptions(include_inspections=True))[0].duration == 2040


def test_fuel_before_the_rest_when_the_next_period_needs_it_early():
    """80 mph synthetic leg (4 mi / 3 min): the 11-h limit binds at mile 880, and fuel would
    fall due 90 min into the next period, so the truck fuels before the 10-h rest instead.
    The trip still needs one fuel stop either way."""
    check(
        [leg(B, B, 0, 0), leg(B, C, 1500, 1125)], 0, PlanOptions(include_inspections=False),
        [
            ("pickup", 0, 60), ("drive", 60, 540), ("break", 540, 570), ("drive", 570, 750),
            ("fuel", 750, 780), ("rest", 780, 1380), ("drive", 1380, 1845), ("dropoff", 1845, 1905),
        ],
    )


def test_fuel_stays_on_the_road_when_fueling_at_the_rest_adds_a_stop():
    """As above but 1,980 mi: fueling at mile 880 would need a second stop at 1,880; fueling
    at 1,000 reaches the drop-off. So the stop stays 90 min into the next period (where it
    also resets the 8-h break clock)."""
    events, _ = check(
        [leg(B, B, 0, 0), leg(B, C, 1980, 1485)], 0, PlanOptions(include_inspections=False),
        [
            ("pickup", 0, 60), ("drive", 60, 540), ("break", 540, 570), ("drive", 570, 750),
            ("rest", 750, 1350), ("drive", 1350, 1440), ("fuel", 1440, 1470), ("drive", 1470, 1950),
            ("break", 1950, 1980), ("drive", 1980, 2070), ("rest", 2070, 2670), ("drive", 2670, 2835),
            ("dropoff", 2835, 2895),
        ],
    )
    assert [e.start_mile for e in events if e.kind == "fuel"] == [pytest.approx(1000)]


def test_fuel_right_after_a_restart_when_the_cycle_left_no_room_before_it():
    """10 h used, 3,050 mi at 55 mph: the cycle runs out 13.75 mi before fuel is due, with no
    room to fuel before the restart. The truck fuels after the pre-trip, before driving off,
    instead of stopping again 15 min after the restart."""
    trip = [st55((-95, 37), (-95, 37), 0), st55((-95, 37), (-80, 37), 3050)]
    events = plan_events(trip, 10, PlanOptions(include_inspections=True))
    assert audit_events(events, 10) == []
    assert stops(events)[-6:] == [
        ("post_trip", 6075, 6090), ("restart", 6090, 8130), ("pre_trip", 8130, 8160),
        ("fuel", 8160, 8190), ("dropoff", 8262, 8322), ("post_trip", 8322, 8337),
    ]
    restart, fuel = events[kinds(events).index("restart")], events[kinds(events).index("restart") + 2]
    assert fuel.start_mile == restart.start_mile


def test_short_fuel_stop_and_break_taken_together():
    """With 15-min fuel stops (too short to be the 30-min break), a break that falls due at
    or soon after a fuel stop is taken right after it rather than on its own shortly after."""
    opts = PlanOptions(include_inspections=False, fuel_stop_minutes=15)
    # Fuel and break due together (125 mph, 1,000 mi in 480 min).
    check(
        [leg(B, B, 0, 0), leg(B, C, 1100, 528)], 0, opts,
        [("pickup", 0, 60), ("drive", 60, 540), ("fuel", 540, 555), ("break", 555, 585),
         ("drive", 585, 633), ("dropoff", 633, 693)],
    )
    # Fuel due 430 min in, the break 50 min later: both at the fuel stop.
    check(
        [leg(B, B, 0, 0), leg(B, C, 1300, 559)], 0, opts,
        [("pickup", 0, 60), ("drive", 60, 490), ("fuel", 490, 505), ("break", 505, 535),
         ("drive", 535, 664), ("dropoff", 664, 724)],
    )


def test_warning_durations_use_the_ui_format():
    from trips.hos.logs import _duration

    assert [_duration(m) for m in (0, 45, 600, 383, 4250)] == ["0m", "45m", "10h", "6h 23m", "70h 50m"]
    _, plan = check(
        [straight(180), straight(500)], 57.5, PlanOptions(include_inspections=False),
        [
            ("drive", 0, 180), ("pickup", 180, 240), ("drive", 240, 720), ("rest", 720, 1320),
            ("drive", 1320, 1340), ("dropoff", 1340, 1400),
        ],
        start=datetime(2026, 9, 21),
    )
    assert plan["warnings"] == [
        "The cycle ends at 70h 50m: driving finishes within 70 h, and the drop-off that follows is "
        "on duty (not driving), which is allowed after 70 h (FMCSA p.10)."
    ]


def test_no_roll_off_caveat_when_the_trip_alone_exceeds_the_cycle():
    """50 h used but the trip's own work passes 70 h: a restart is needed with or without
    roll-off, so its warning has no caveat."""
    plan = build_plan([straight(0), straight(4500)], datetime(2026, 9, 21), 50, PlanOptions(include_inspections=True), namer)
    assert plan["warnings"] == [
        "34-hour restart required on day 2: the 70-hour cycle is used up and driving remains."
    ]
