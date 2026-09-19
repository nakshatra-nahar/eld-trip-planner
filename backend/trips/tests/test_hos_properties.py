"""Property-based tests: HOS invariants over many random trips.

The rule checks come from ``trips.hos.audit``, which re-derives every clock from the
event list alone. The tests here add route-level, log-level and "no premature stop"
properties on top.
"""

from datetime import datetime, timedelta
from itertools import pairwise

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from trips.hos import LegProfile, PlanOptions, build_plan, plan_events
from trips.hos import rules as R
from trips.hos.audit import audit_events, audit_plan

K = R.Kind


def namer(lat, lon, road=None):
    return f"{road or 'here'} {lat:.2f},{lon:.2f}"


@st.composite
def straight_legs(draw, max_miles=3500.0):
    miles = draw(st.one_of(st.just(0.0), st.floats(0, 0.3), st.floats(0, max_miles)))
    mph = draw(st.floats(20, 75))
    start = (draw(st.floats(-120, -70)), draw(st.floats(26, 48)))
    end = (start[0] + draw(st.floats(-5, 5)), start[1] + draw(st.floats(-5, 5)))
    return LegProfile.straight(start, end, miles, miles / mph * 60, n=draw(st.integers(2, 60)))


@st.composite
def multi_segment_legs(draw, max_miles=3500.0):
    """Polylines whose segments have different lengths and speeds (city, highway, ...)."""
    n = draw(st.integers(1, 25))
    seg_miles = draw(st.lists(st.floats(0, max_miles / n), min_size=n, max_size=n))
    speeds = draw(st.lists(st.floats(15, 75), min_size=n, max_size=n))
    lon, lat = draw(st.floats(-120, -70)), draw(st.floats(26, 48))
    coords = [(lon, lat)]
    for _ in range(n):
        lon += draw(st.floats(-1, 1))
        lat += draw(st.floats(-1, 1))
        coords.append((lon, lat))
    seg_minutes = [m / v * 60 for m, v in zip(seg_miles, speeds)]
    return LegProfile(coords, seg_miles, seg_minutes)


legs_st = st.one_of(straight_legs(), multi_segment_legs())
cycle_st = st.one_of(st.sampled_from([0.0, 60.0, 65.0, 69.0, 69.5, 70.0]), st.floats(0, 70))
start_st = st.datetimes(datetime(2026, 1, 1), datetime(2027, 12, 31)).map(
    lambda d: d.replace(second=0, microsecond=0)
)
options_st = st.builds(
    PlanOptions,
    include_inspections=st.booleans(),
    rest_status=st.sampled_from(["SB", "OFF"]),
    fuel_stop_minutes=st.one_of(st.just(30), st.integers(1, 180)),
)


def expected_route_miles(legs):
    return sum(leg.total_miles for leg in legs if leg.total_miles >= R.MIN_LEG_MILES)


def assert_no_premature_stops(events, cycle_hours, options):
    """Breaks, rests and restarts are only taken when a limit (nearly) binds."""
    window_start = None
    drive_in_period = drive_since_break = nondriving_run = 0
    cycle = cycle_hours * 60
    # Cycle minutes below which a restart is never needed: the next period can still do its
    # unavoidable on-duty work (pre-trip, pickup, a due fuel stop, post-trip) and drive 1 h.
    restart_floor = R.CYCLE_LIMIT - (
        R.MIN_USEFUL_DRIVING + R.PRE_TRIP_MINUTES + R.POST_TRIP_MINUTES + R.PICKUP_MINUTES + options.fuel_stop_minutes
    )
    early = R.MIN_DRIVE_AFTER_STOP + max(R.BREAK_MINUTES, options.fuel_stop_minutes)
    for i, ev in enumerate(events):
        if ev.kind == K.BREAK:
            assert drive_since_break == R.BREAK_AFTER_DRIVING, (i, ev)
        if ev.kind in (K.REST, K.RESTART) and window_start is not None:
            # Measure where the period's driving stopped: before its post-trip and any fuel stop.
            j = i
            while j > 0 and events[j - 1].kind in (K.POST_TRIP, K.FUEL):
                j -= 1
            at = events[j].start
            elapsed = at - window_start
            assert (
                drive_in_period >= R.MAX_DRIVING - R.MIN_DRIVE_AFTER_STOP
                or elapsed >= R.DUTY_WINDOW - early
                or cycle > restart_floor
            ), (i, ev, drive_in_period, elapsed, cycle)
        if ev.kind == K.RESTART:
            assert cycle > restart_floor, (i, ev, cycle)
            # The recap never passes 70 h before a restart (only the final drop-off and
            # post-trip may, which is legal on-duty not-driving time).
            assert cycle <= R.CYCLE_LIMIT + 1e-6, (i, ev, cycle)
            # A 10-h rest is never followed by a restart without any driving in between.
            prev_rest = next((e for e in reversed(events[:i]) if e.kind in (K.REST, K.RESTART, K.DRIVE)), None)
            assert prev_rest is None or prev_rest.kind == K.DRIVE, (i, ev)
        # advance clocks
        if ev.status in R.ON_DUTY_STATUSES:
            if window_start is None:
                window_start = ev.start
            cycle += ev.duration
        if ev.status == R.D:
            drive_in_period += ev.duration
            drive_since_break += ev.duration
            nondriving_run = 0
        else:
            nondriving_run += ev.duration
            if nondriving_run >= R.BREAK_MINUTES:
                drive_since_break = 0
        if ev.kind in (K.REST, K.RESTART):
            window_start, drive_in_period, drive_since_break = None, 0, 0
            if ev.kind == K.RESTART:
                cycle = 0
    # Past 70 h only after the last driving minute.
    last_drive = max((i for i, ev in enumerate(events) if ev.kind == K.DRIVE), default=-1)
    cycle = cycle_hours * 60
    for i, ev in enumerate(events):
        cycle = 0 if ev.kind == K.RESTART else cycle + (ev.duration if ev.is_on_duty else 0)
        if i < last_drive:
            assert cycle <= R.CYCLE_LIMIT + 1e-6, (i, ev, cycle)


def check_trip(legs, cycle, start, options):
    events = plan_events(legs, cycle, options)

    # HOS rules, contiguity, pickup/drop-off exactly 60 min ON.
    assert audit_events(events, cycle) == []
    assert_no_premature_stops(events, cycle, options)

    # Driven miles equal the (drivable) route miles.
    driven = sum(ev.miles for ev in events if ev.kind == K.DRIVE)
    assert abs(driven - expected_route_miles(legs)) < 1e-6
    assert all(ev.miles >= -1e-9 for ev in events)

    # Fuel stops are only taken when (nearly) 1,000 mi have been driven since the last one;
    # an early stop combines fueling with a stop that was happening anyway.
    since = 0.0
    for ev in events:
        if ev.kind == K.FUEL:
            assert since >= R.FUEL_INTERVAL_MILES - R.FUEL_EARLY_MILES - 5, since
            since = 0.0
        elif ev.kind == K.DRIVE:
            since += ev.miles

    plan = build_plan(legs, start, cycle, options, namer)
    assert audit_plan(plan) == []

    timeline, logs, summary = plan["timeline"], plan["daily_logs"], plan["summary"]
    assert len(timeline) == len(events)
    for a, b in pairwise(timeline):
        assert a["end"] == b["start"]
    assert timeline[0]["start"] == start.strftime("%Y-%m-%dT%H:%M")
    end = start + timedelta(minutes=events[-1].end)
    assert summary["end_time"] == end.strftime("%Y-%m-%dT%H:%M")
    assert summary["total_miles"] == round(driven, 1)
    assert len(plan["stops"]) == sum(ev.kind != K.DRIVE for ev in events)
    assert summary["num_fuel_stops"] == sum(ev.kind == K.FUEL for ev in events)
    assert summary["num_restarts"] == sum(ev.kind == K.RESTART for ev in events)

    # One sheet per calendar day from the start date to the end date.
    last_day = (end - timedelta(minutes=1)).date()
    assert logs[0]["date"] == start.date().isoformat()
    assert logs[-1]["date"] == last_day.isoformat()
    assert len(logs) == (last_day - start.date()).days + 1
    for stop in plan["stops"]:
        assert 1 <= stop["day_number"] <= len(logs)
    for log in logs:
        assert 0 <= log["cycle_hours_available"] <= 70
        assert abs(log["on_duty_hours"] - (log["totals"]["D"] + log["totals"]["ON"])) < 1e-9
    driving_hours = sum(log["totals"]["D"] for log in logs)
    assert abs(driving_hours - summary["total_driving_hours"]) <= 0.01 * len(logs) + 1e-9
    return events, plan


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(leg0=legs_st, leg1=legs_st, cycle=cycle_st, start=start_st, options=options_st)
def test_random_trips_obey_every_invariant(leg0, leg1, cycle, start, options):
    check_trip([leg0, leg1], cycle, start, options)


@settings(max_examples=100, deadline=None)
@given(
    miles=st.floats(2000, 3500),
    cycle=st.floats(40, 70),
    start=start_st,
    options=options_st,
)
def test_long_trips_with_high_cycle(miles, cycle, start, options):
    """Long leg 1 with a heavily used cycle: exercises restarts across several midnights."""
    legs = [
        LegProfile.straight((-90, 40), (-89, 40), 30, 40),
        LegProfile.straight((-89, 40), (-75, 41), miles, miles / 55 * 60),
    ]
    _, plan = check_trip(legs, cycle, start, options)
    assert plan["summary"]["num_restarts"] >= 1


@settings(max_examples=150, deadline=None)
@given(
    leg1_minutes=st.integers(1, 2000),
    cycle=st.sampled_from([0.0, 69.5, 70.0]),
    start_minute=st.integers(0, 1439),
    options=options_st,
)
def test_trip_ends_on_or_near_midnight(leg1_minutes, cycle, start_minute, options):
    """Integer-minute legs at 60 mph, all start minutes: day boundaries land everywhere."""
    legs = [
        LegProfile.straight((-90, 40), (-90, 40), 0, 0),
        LegProfile.straight((-90, 40), (-80, 40), leg1_minutes, leg1_minutes),
    ]
    start = datetime(2026, 9, 21) + timedelta(minutes=start_minute)
    check_trip(legs, cycle, start, options)
