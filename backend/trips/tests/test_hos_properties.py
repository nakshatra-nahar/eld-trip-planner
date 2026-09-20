"""Property-based tests: HOS invariants over many random trips.

The rule checks come from ``trips.hos.audit``, which re-derives every clock from the
event list alone. The tests here add route-level, log-level and "no premature stop"
properties on top.
"""

from datetime import datetime, timedelta
from itertools import pairwise
from math import ceil, floor

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from trips.hos import LegProfile, PlanOptions, build_plan, plan_events
from trips.hos import rules as R
from trips.hos.audit import audit_events, audit_plan
from trips.hos.planner import Rule, _Planner, build_leg_drives

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


def rest_of_trip_estimate(events, i, options):
    """A generous estimate of the on-duty minutes the trip needs after event ``i`` up to its
    last driving minute (no cheaper than the planner's own conservative estimate)."""
    later = events[i + 1 :]
    drive = sum(e.duration for e in later if e.kind == K.DRIVE)
    miles = sum(e.miles for e in later if e.kind == K.DRIVE)
    periods = ceil(drive / R.MAX_DRIVING) + 1
    inspections = periods * (R.PRE_TRIP_MINUTES + R.POST_TRIP_MINUTES) if options.include_inspections else 0
    pickup = R.PICKUP_MINUTES if any(e.kind == K.PICKUP for e in later) else 0
    fuel = (floor(miles / R.FUEL_INTERVAL_MILES) + 2) * options.fuel_stop_minutes
    return drive + inspections + pickup + fuel


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
            # Due now, or soon and taken with a fuel stop too short to count as the break.
            with_fuel = i > 0 and events[i - 1].kind == K.FUEL and options.fuel_stop_minutes < R.BREAK_MINUTES
            assert drive_since_break == R.BREAK_AFTER_DRIVING or (
                with_fuel and drive_since_break >= R.BREAK_AFTER_DRIVING - R.BREAK_EARLY_MINUTES
            ), (i, ev, drive_since_break)
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
            # Needed now, or optional: the rest of the trip does not fit in the cycle left.
            assert cycle > restart_floor or cycle + rest_of_trip_estimate(events, i, options) > R.CYCLE_LIMIT, (
                i, ev, cycle,
            )
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


def assert_fuel_only_when_needed(events, drives, options):
    """Fuel stops are only taken when (nearly) 1,000 mi have been driven since the last one;
    an early stop combines fueling with a stop that was happening anyway, or is taken at a
    rest because the next duty period would need it within its first hours of driving."""
    horizon = R.FUEL_BEFORE_REST_DRIVING if options.fuel_stop_minutes >= R.BREAK_MINUTES else R.MAX_DRIVING
    since = 0.0
    for i, ev in enumerate(events):
        if ev.kind == K.FUEL:
            if since < R.FUEL_INTERVAL_MILES - R.FUEL_EARLY_MILES - 5:
                near = {e.kind for e in events[max(0, i - 2) : i + 3]}
                assert near & {K.REST, K.RESTART}, (i, since)
                ahead, left = 0.0, horizon
                for e in events[i + 1 :]:
                    if e.kind == K.DRIVE and left > 0:
                        take = min(left, e.duration)
                        drive = drives[e.leg_index]
                        ahead += drive.leg_mile(e.progress_start + take) - drive.leg_mile(e.progress_start)
                        left -= take
                assert since + ahead >= R.FUEL_INTERVAL_MILES - 1e-6, (i, since, ahead)
            since = 0.0
        elif ev.kind == K.DRIVE:
            since += ev.miles


RULES_BY_KIND = {
    K.REST: {Rule.DRIVE_LIMIT, Rule.DUTY_WINDOW, Rule.LIMIT_BEFORE_STOP},
    K.RESTART: {Rule.CYCLE, Rule.CYCLE_BEFORE_STOP, Rule.EARLY_RESTART},
    K.BREAK: {Rule.BREAK, Rule.BREAK_WITH_FUEL},
    K.FUEL: {Rule.FUEL_INTERVAL, Rule.FUEL_SOON, Rule.FUEL_AHEAD},
    K.PICKUP: {Rule.PICKUP},
    K.DROPOFF: {Rule.DROPOFF},
    K.PRE_TRIP: {Rule.PRE_TRIP},
    K.POST_TRIP: {Rule.POST_TRIP, Rule.POST_TRIP_END},
}


def assert_causes_match_events(events, cycle_hours, prior, options):
    """Each stop's recorded cause (the source of its ``reason``) agrees with the clocks
    re-derived from the event list: the reasons state what actually bound."""
    window_start = None
    period_drive = drive_since_break = nondriving_run = 0
    last_drive_end = 0
    cycle = cycle_hours * 60
    since_fuel = 0.0
    horizon = R.FUEL_BEFORE_REST_DRIVING if options.fuel_stop_minutes >= R.BREAK_MINUTES else R.MAX_DRIVING

    def check_rest_cause(c, ev):
        if c.rule == Rule.DRIVE_LIMIT:
            assert period_drive == R.MAX_DRIVING, (ev, period_drive)
        elif c.rule == Rule.DUTY_WINDOW:
            assert period_drive < R.MAX_DRIVING and window_start is not None, ev
            assert c.at == window_start + R.DUTY_WINDOW and last_drive_end <= c.at <= ev.start, (ev, c)
        else:
            assert c.rule == Rule.LIMIT_BEFORE_STOP and c.left < R.MIN_DRIVE_AFTER_STOP, (ev, c)
            assert c.stop in ("break", "fuel", "fuel_break"), c
            if c.limit == "drive":
                assert c.left == R.MAX_DRIVING - period_drive, (ev, c, period_drive)
            elif c.limit == "window":
                assert window_start is not None and c.at == window_start + R.DUTY_WINDOW, (ev, c)
            else:
                assert c.limit == "cycle", c

    for i, ev in enumerate(events):
        c = ev.cause
        nxt = next((e for e in events[i + 1 :] if e.kind != K.POST_TRIP), None)
        if ev.kind == K.DRIVE:
            assert c is None, ev
        else:
            assert c is not None and c.rule in RULES_BY_KIND[ev.kind], (i, ev)
        if ev.kind == K.REST:
            check_rest_cause(c, ev)
        if ev.kind == K.RESTART:
            assert abs(c.cycle - cycle) < 1e-6, (i, c, cycle)
            assert c.credit == (R.RESTART - ev.duration if ev.start == 0 else 0), (i, ev, c)
            assert c.credit == 0 or c.credit == prior, (i, c, prior)
            if c.rule == Rule.EARLY_RESTART:
                assert (c.instead_of is None) == (ev.start == 0), (i, c)
                if c.instead_of is not None:
                    check_rest_cause(c.instead_of, ev)
            if c.rule == Rule.CYCLE_BEFORE_STOP:
                assert c.stop in ("pickup", "fuel"), c
                if c.stop == "pickup":
                    assert nxt is not None and any(e.kind == K.PICKUP for e in events[i + 1 : i + 4]), (i, c)
        if ev.kind == K.BREAK:
            if c.rule == Rule.BREAK:
                assert drive_since_break == R.BREAK_AFTER_DRIVING, (i, drive_since_break)
            else:
                assert events[i - 1].kind == K.FUEL, i
                assert c.left == R.BREAK_AFTER_DRIVING - drive_since_break <= R.BREAK_EARLY_MINUTES, (i, c)
        if ev.kind == K.FUEL:
            assert abs(c.fuel_miles - since_fuel) < 1e-6, (i, c, since_fuel)
            if c.rule == Rule.FUEL_INTERVAL:
                assert since_fuel > R.FUEL_INTERVAL_MILES - 5, (i, since_fuel)
            elif c.rule == Rule.FUEL_SOON:
                assert R.FUEL_INTERVAL_MILES - since_fuel < R.FUEL_EARLY_MILES + 1e-6, (i, since_fuel)
            else:
                assert c.left == horizon and c.stop in ("rest", "restart", "duty_start"), (i, c)
            if c.stop in ("rest", "restart"):
                assert nxt is not None and nxt.kind == c.stop, (i, c, nxt)
            elif c.stop == "pickup":
                assert nxt is not None and nxt.kind == K.PICKUP, (i, c, nxt)
            elif c.stop == "duty_start":
                assert events[i - 1].kind in (K.PRE_TRIP, K.REST, K.RESTART), (i, events[i - 1])
            if c.as_break:
                assert options.fuel_stop_minutes >= R.BREAK_MINUTES and c.stop == "break", (i, c)
                assert drive_since_break == R.BREAK_AFTER_DRIVING, (i, drive_since_break)
            elif c.stop == "break":
                assert nxt is not None and nxt.kind in (K.BREAK, K.REST, K.RESTART), (i, c, nxt)
        if ev.kind == K.POST_TRIP:
            assert (c.rule == Rule.POST_TRIP_END) == (i == len(events) - 1), (i, c)
        # advance clocks
        if ev.status in R.ON_DUTY_STATUSES:
            if window_start is None:
                window_start = ev.start
            cycle += ev.duration
        if ev.status == R.D:
            period_drive += ev.duration
            drive_since_break += ev.duration
            nondriving_run = 0
            since_fuel += ev.miles
            last_drive_end = ev.end
        else:
            nondriving_run += ev.duration
            if nondriving_run >= R.BREAK_MINUTES:
                drive_since_break = 0
        if ev.kind == K.FUEL:
            since_fuel = 0.0
        if ev.kind in (K.REST, K.RESTART):
            window_start, period_drive, drive_since_break = None, 0, 0
            if ev.kind == K.RESTART:
                cycle = 0


def check_trip(legs, cycle, start, options):
    prior = start.hour * 60 + start.minute  # build_plan: off duty since midnight
    events = plan_events(legs, cycle, options, prior_off_duty_minutes=prior)

    # HOS rules, contiguity, pickup/drop-off exactly 60 min ON.
    assert audit_events(events, cycle, prior) == []
    assert_no_premature_stops(events, cycle, options)
    assert_causes_match_events(events, cycle, prior, options)

    # The restart-placement search never arrives later than the greedy plan.
    greedy = _Planner(build_leg_drives(legs), cycle * 60, options, prior).run()
    assert events[-1].end <= greedy[-1].end

    # Driven miles equal the (drivable) route miles.
    driven = sum(ev.miles for ev in events if ev.kind == K.DRIVE)
    assert abs(driven - expected_route_miles(legs)) < 1e-6
    assert all(ev.miles >= -1e-9 for ev in events)

    assert_fuel_only_when_needed(events, build_leg_drives(legs), options)

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
    # Every stop says why it happens; driving does not.
    for item in timeline:
        assert ("reason" in item) == (item["kind"] != K.DRIVE), item
        assert item.get("reason", "x").strip() != ""
    by_id = {item["id"]: item for item in timeline}
    assert all(stop["reason"] == by_id[stop["id"]]["reason"] for stop in plan["stops"])
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
    # Flags (zero-length remarks): the first change from OFF and the final change back to it.
    flags = [(i, r) for i, log in enumerate(logs) for r in log["remarks"] if r["start_minute"] == r["end_minute"]]
    notes = [r["note"] for _, r in flags]
    first_on = events[0].status in R.ON_DUTY_STATUSES
    start_note = "Start of trip: " + ("driving" if events[0].status == R.D else "on duty")
    assert notes == ([start_note] if first_on else []) + ["End of trip: off duty"]
    if first_on:
        assert (flags[0][0], flags[0][1]["start_minute"]) == (0, start.hour * 60 + start.minute)
    last_on = max(i for i, ev in enumerate(events) if ev.status in R.ON_DUTY_STATUSES)
    off_at = datetime.fromisoformat(timeline[last_on]["end"])
    day, end_flag = flags[-1]
    sheet_start = datetime.fromisoformat(logs[day]["date"])
    assert sheet_start + timedelta(minutes=end_flag["start_minute"]) == off_at
    assert end_flag["location"] == timeline[last_on]["end_location"]["name"]
    for log in logs:
        keys = [(r["start_minute"], r["end_minute"]) for r in log["remarks"]]
        assert keys == sorted(keys)
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
