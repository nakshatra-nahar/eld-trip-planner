"""Duty-status simulation: turns two route legs into a legal sequence of duty events.

Time is simulated in integer minutes from the trip start. Each leg's driving time is
rounded once to whole minutes (``LegDrive.minutes``); a driving chunk of ``k`` minutes
then covers the profile distance between progress ``p`` and ``p + k`` proportionally,
so miles are exact at every leg end and no rounding drift accumulates.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, inf

from . import rules as R
from .profile import LegProfile, LonLat

# Guards float noise when converting a fractional progress to whole minutes.
_MINUTE_EPS = 1e-9


@dataclass
class PlanOptions:
    include_inspections: bool = False  # off by default, as in the API (the brief does not list them)
    rest_status: str = R.SB  # "SB" | "OFF"; 34-h restarts are always OFF
    fuel_stop_minutes: int = 30

    def __post_init__(self) -> None:
        if self.rest_status not in (R.SB, R.OFF):
            raise ValueError(f"rest_status must be 'SB' or 'OFF', got {self.rest_status!r}")
        if int(self.fuel_stop_minutes) != self.fuel_stop_minutes or self.fuel_stop_minutes < 1:
            raise ValueError("fuel_stop_minutes must be a whole number >= 1")
        self.fuel_stop_minutes = int(self.fuel_stop_minutes)
        self.include_inspections = bool(self.include_inspections)


@dataclass(frozen=True)
class DutyEvent:
    """One contiguous activity. Minutes are from the trip start; miles are cumulative trip miles."""

    kind: str
    status: str
    start: int
    end: int
    start_mile: float
    end_mile: float
    leg_index: int  # 0 = current->pickup, 1 = pickup->dropoff
    start_coord: LonLat  # (lon, lat)
    end_coord: LonLat
    start_leg_mile: float  # leg-relative miles of the position leg (see LegDrive)
    end_leg_mile: float
    # Driving events only: integer progress (minutes into the leg's driving time).
    progress_start: int = 0
    progress_end: int = 0

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def miles(self) -> float:
        return self.end_mile - self.start_mile

    @property
    def is_on_duty(self) -> bool:
        return self.status in R.ON_DUTY_STATUSES


@dataclass(frozen=True)
class LegDrive:
    """A leg plus its integer driving time and its offset in cumulative trip miles."""

    leg: LegProfile
    offset: float  # trip mile at the start of this leg
    minutes: int  # whole driving minutes; 0 when the leg is too short to drive

    @property
    def driven_miles(self) -> float:
        return self.leg.total_miles if self.minutes else 0.0

    def leg_mile(self, progress: float) -> float:
        """Leg mile after ``progress`` of this leg's ``minutes`` of driving."""
        if self.minutes <= 0:
            return 0.0
        if progress >= self.minutes:
            return self.leg.total_miles
        leg = self.leg
        if leg.total_minutes > 0:
            return leg.mile_at_minute(progress * leg.total_minutes / self.minutes)
        return leg.total_miles * progress / self.minutes

    def progress_at_leg_mile(self, mile: float) -> float:
        """Fractional progress (minutes) at which leg mile ``mile`` is reached."""
        leg = self.leg
        if self.minutes <= 0 or leg.total_miles <= 0:
            return 0.0
        if leg.total_minutes > 0:
            return leg.minute_at_mile(mile) * self.minutes / leg.total_minutes
        return min(mile, leg.total_miles) / leg.total_miles * self.minutes


def leg_drive_minutes(leg: LegProfile) -> int:
    """Whole driving minutes for a leg: nearest minute, at least 1, 0 if skipped."""
    if leg.total_miles < R.MIN_LEG_MILES:
        return 0
    return max(1, floor(leg.total_minutes + 0.5))


def build_leg_drives(legs: list[LegProfile]) -> list[LegDrive]:
    if len(legs) != 2:
        raise ValueError(f"expected exactly 2 legs (current->pickup, pickup->dropoff), got {len(legs)}")
    drives: list[LegDrive] = []
    offset = 0.0
    for leg in legs:
        drive = LegDrive(leg, offset, leg_drive_minutes(leg))
        drives.append(drive)
        offset += drive.driven_miles
    return drives


class _Planner:
    """Mutable HOS state machine; see the "Algorithm" section of docs/SPEC.md."""

    def __init__(
        self,
        drives: list[LegDrive],
        cycle_used_minutes: float,
        opts: PlanOptions,
        prior_off_minutes: int = 0,
        restart_at: int | None = None,
    ) -> None:
        self.drives = drives
        self.opts = opts
        self.events: list[DutyEvent] = []
        # Off-duty minutes just before the trip; a restart at minute 0 counts them.
        self.prior_off = prior_off_minutes
        # Optional restarts (see _optional_restart): how many were offered, and which to take.
        self.restart_options = 0
        self.restart_at = restart_at

        self.t = 0
        self.window_start: int | None = None
        self.drive_in_period = 0
        self.drive_since_break = 0
        self.nondriving_run = 0
        self.cycle = cycle_used_minutes
        self.miles_since_fuel = 0.0  # tank is full at the current location

        # Where the truck is: a position leg and integer progress along it.
        self.pos_leg = 0
        self.progress = 0
        # Which leg events are attributed to (the pickup still belongs to leg 0).
        self.event_leg = 0

    # ----- position helpers -------------------------------------------------

    def _position(self) -> tuple[float, float, LonLat]:
        drive = self.drives[self.pos_leg]
        leg_mile = drive.leg_mile(self.progress)
        return drive.offset + leg_mile, leg_mile, drive.leg.coord_at_mile(leg_mile)

    def _driving_remaining(self) -> int:
        current = self.drives[self.pos_leg]
        later = sum(d.minutes for d in self.drives[self.pos_leg + 1 :])
        return max(0, current.minutes - self.progress) + later

    def _miles_remaining(self) -> float:
        current = self.drives[self.pos_leg]
        later = sum(d.driven_miles for d in self.drives[self.pos_leg + 1 :])
        return max(0.0, current.driven_miles - current.leg_mile(self.progress)) + later

    def _miles_ahead(self, minutes: int) -> float:
        """Miles covered by the next ``minutes`` of driving from here (to the trip end at most)."""
        miles, leg, progress = 0.0, self.pos_leg, self.progress
        while minutes > 0 and leg < len(self.drives):
            drive = self.drives[leg]
            take = min(minutes, max(0, drive.minutes - progress))
            miles += drive.leg_mile(progress + take) - drive.leg_mile(progress)
            minutes -= take
            leg, progress = leg + 1, 0
        return miles

    # ----- event recording ----------------------------------------------------

    def _stationary(self, kind: str, status: str, minutes: int) -> None:
        """Record a non-driving event at the current position."""
        trip_mile, leg_mile, coord = self._position()
        start = self.t
        self.t += minutes
        self.events.append(
            DutyEvent(kind, status, start, self.t, trip_mile, trip_mile, self.event_leg,
                      coord, coord, leg_mile, leg_mile)
        )
        if status in R.ON_DUTY_STATUSES:
            self.cycle += minutes
        self.nondriving_run += minutes
        if self.nondriving_run >= R.BREAK_MINUTES:
            self.drive_since_break = 0  # any >= 30 consecutive non-driving minutes qualifies

    def _drive(self, minutes: int) -> None:
        drive = self.drives[self.pos_leg]
        p0, p1 = self.progress, self.progress + minutes
        m0, m1 = drive.leg_mile(p0), drive.leg_mile(p1)
        start = self.t
        self.t += minutes
        self.events.append(
            DutyEvent(R.Kind.DRIVE, R.D, start, self.t, drive.offset + m0, drive.offset + m1,
                      self.event_leg, drive.leg.coord_at_mile(m0), drive.leg.coord_at_mile(m1),
                      m0, m1, p0, p1)
        )
        self.progress = p1
        self.drive_in_period += minutes
        self.drive_since_break += minutes
        self.cycle += minutes
        self.nondriving_run = 0
        self.miles_since_fuel += m1 - m0

    # ----- duty-period transitions -------------------------------------------

    def _ensure_duty_period(self) -> None:
        """Open a duty period (restarting first if the cycle cannot support it).

        At the trip start the restart may also be optional (see ``_optional_restart``); it
        counts the off-duty time before the start, so it is shorter than 34 h.
        """
        if self.window_start is not None:
            return
        at_start = not self.events
        if self._needs_restart() or (at_start and self._optional_restart()):
            self._stationary(R.Kind.RESTART, R.OFF, R.RESTART - (self.prior_off if at_start else 0))
            self._reset_after_off(restart=True)
        self.window_start = self.t
        if self.opts.include_inspections:
            self._stationary(R.Kind.PRE_TRIP, R.ON, R.PRE_TRIP_MINUTES)
        fuel = self.opts.fuel_stop_minutes
        if self._fuel_before_rest() and self._cycle_allows(fuel) and not self._restart_before_stop(fuel):
            self._fuel()  # not fueled before the rest (no cycle room then): fuel before driving off

    def _end_duty_period(self, restart: bool | None = None) -> None:
        """Post-trip inspection, then a 10-h rest or a 34-h restart (chosen here when None).

        Fuel that the next duty period would soon need is taken first, at the same stop.
        """
        if self._fuel_before_rest() and self._cycle_allows(self.opts.fuel_stop_minutes):
            self._fuel()
        if restart is None:
            restart = self._needs_restart() or self._optional_restart()
        if self.opts.include_inspections and self.window_start is not None:
            self._stationary(R.Kind.POST_TRIP, R.ON, R.POST_TRIP_MINUTES)
        if restart:
            self._stationary(R.Kind.RESTART, R.OFF, R.RESTART)
        else:
            self._stationary(R.Kind.REST, self.opts.rest_status, R.RESET_OFF)
        self._reset_after_off(restart)

    def _reset_after_off(self, restart: bool) -> None:
        self.window_start = None
        self.drive_in_period = 0
        self.drive_since_break = 0
        if restart:
            self.cycle = 0.0

    # ----- 70-hour cycle planning -----------------------------------------------

    def _post_trip_reserve(self) -> int:
        """On-duty minutes a period still owes before it can end (its post-trip inspection)."""
        return R.POST_TRIP_MINUTES if self.opts.include_inspections and self.window_start is not None else 0

    def _cycle_allows(self, minutes: int) -> bool:
        """Whether ``minutes`` more on duty leave room for the period's post-trip within 70 h."""
        return self.cycle + minutes + self._post_trip_reserve() <= R.CYCLE_LIMIT + _MINUTE_EPS

    def _work_needed(self, drive: int, opening: bool) -> float:
        """Upper-bound estimate of the on-duty minutes left before the last driving minute.

        Only driving must end within 70 h; the drop-off and final post-trip that follow it
        are on duty (not driving), which is allowed after 70 h (FMCSA p.10).
        ``opening``: whether the current duty period is about to end (a new one opens next).
        """
        insp = self.opts.include_inspections
        if opening:
            periods = ceil(drive / R.MAX_DRIVING)
            pre_trips, post_trips = periods, periods - 1
        else:
            now = min(R.MAX_DRIVING - self.drive_in_period, R.DUTY_WINDOW - (self.t - (self.window_start or self.t)))
            later = ceil(max(0, drive - max(now, 0)) / R.MAX_DRIVING)
            pre_trips = post_trips = later
        fuel_stops = floor((self.miles_since_fuel + self._miles_remaining()) / R.FUEL_INTERVAL_MILES)
        return (
            drive
            + (pre_trips * R.PRE_TRIP_MINUTES + post_trips * R.POST_TRIP_MINUTES if insp else 0)
            + (R.PICKUP_MINUTES if self.event_leg == 0 and self.drives[1].minutes > 0 else 0)
            + fuel_stops * self.opts.fuel_stop_minutes
        )

    def _needs_restart(self) -> bool:
        """Whether the next duty period should be preceded by a 34-hour restart, not a 10-h rest.

        Called when a period ends (its post-trip is counted here) or is about to open. No
        restart while the rest of the trip's driving fits in the cycle. Otherwise restart
        once the next period could not drive a useful stretch (``MIN_USEFUL_DRIVING``, or all
        the remaining driving if less) after its unavoidable on-duty work. Because a period
        that ends with a rest reopens with the same answer, a rest is never followed by a
        restart straight away.
        """
        drive = self._driving_remaining()
        if drive <= 0:
            return False
        cycle = self.cycle + self._post_trip_reserve()
        if cycle + self._work_needed(drive, opening=True) <= R.CYCLE_LIMIT + _MINUTE_EPS:
            return False
        insp = self.opts.include_inspections
        lead = (R.PRE_TRIP_MINUTES + R.POST_TRIP_MINUTES) if insp else 0
        if self.event_leg == 0 and self.pos_leg == 1:  # parked at the pickup
            lead += R.PICKUP_MINUTES
        if self._fuel_room(self.drives[self.pos_leg]) < 1:
            lead += self.opts.fuel_stop_minutes
        room = R.CYCLE_LIMIT - cycle - lead
        return room < min(drive, R.MIN_USEFUL_DRIVING)

    def _optional_restart(self) -> bool:
        """Whether to take a 34-h restart now although a 10-h rest (or, at the trip start,
        no rest) would still be legal.

        Offered when the rest of the trip does not fit in the cycle left but fits in a fresh
        one; then restarting early can save the rest that would otherwise precede the
        restart. The planner cannot tell locally whether it pays off (the 14-h windows and
        stop placement decide), so ``plan_drives`` plans the trip once per offered option and
        keeps the earliest arrival. Offers are numbered in order; ``restart_at`` picks one.
        A trip that needs more than a fresh cycle keeps the greedy plan (restarting early
        would not save a restart).
        """
        drive = self._driving_remaining()
        if drive <= 0:
            return False
        work = self._work_needed(drive, opening=True)
        if work > R.CYCLE_LIMIT + _MINUTE_EPS:
            return False
        if self.cycle + self._post_trip_reserve() + work <= R.CYCLE_LIMIT + _MINUTE_EPS:
            return False
        index = self.restart_options
        self.restart_options += 1
        return index == self.restart_at

    def _restart_before_stop(self, minutes: int) -> bool:
        """Whether an on-duty stop of ``minutes`` would leave no cycle room to drive on.

        If so, the restart is taken before the stop, so the recap never passes 70 h mid-trip.
        """
        drive = self._driving_remaining()
        if drive <= 0 or self.window_start is None:
            return False
        after = self.cycle + minutes
        if after + self._work_needed(drive, opening=False) <= R.CYCLE_LIMIT + _MINUTE_EPS:
            return False
        return floor(R.CYCLE_LIMIT - self._post_trip_reserve() - after + _MINUTE_EPS) < 1

    # ----- driving loop ---------------------------------------------------------

    def _fuel_room(self, drive: LegDrive) -> float:
        """Whole minutes that can be driven before exceeding the fuel interval (inf if none)."""
        remaining = R.FUEL_INTERVAL_MILES - self.miles_since_fuel
        here = drive.leg_mile(self.progress)
        if drive.leg.total_miles - here <= remaining + R.MILE_EPS:
            return inf  # the leg ends before the tank does
        target = drive.progress_at_leg_mile(here + max(remaining, 0.0))
        room = floor(target - self.progress + _MINUTE_EPS)
        if room < 1 and self.miles_since_fuel <= R.MILE_EPS:
            return 1  # degenerate (>1,000 mi per minute) profile: always make progress
        return max(room, 0)

    def _fuel_soon(self) -> bool:
        """Fuel will be due within ``FUEL_EARLY_MILES`` and the trip goes past that point."""
        left = R.FUEL_INTERVAL_MILES - self.miles_since_fuel
        return left < R.FUEL_EARLY_MILES and self._miles_remaining() > left + R.MILE_EPS

    def _fuel_before_rest(self) -> bool:
        """Fuel at a rest or restart stop rather than early in the next duty period.

        True when fuel is due soon (``_fuel_soon``), or within the first
        ``FUEL_BEFORE_REST_DRIVING`` of the next period's driving (all of it when a fuel stop
        is too short to count as the 30-min break), provided fueling now adds no fuel stop to
        the trip. A later stop is left in place: it can double as, or remove the need for,
        the 8-h break.
        """
        if self._fuel_soon():
            return True
        left = R.FUEL_INTERVAL_MILES - self.miles_since_fuel
        remaining = self._miles_remaining()
        if remaining <= left + R.MILE_EPS:
            return False  # the tank reaches the drop-off
        horizon = R.FUEL_BEFORE_REST_DRIVING if self.opts.fuel_stop_minutes >= R.BREAK_MINUTES else R.MAX_DRIVING
        if self._miles_ahead(horizon) < left - R.MILE_EPS:
            return False
        return 1 + _fuel_stops_needed(0.0, remaining) <= _fuel_stops_needed(self.miles_since_fuel, remaining)

    def _drive_leg(self, leg_index: int) -> None:
        self.pos_leg, self.progress = leg_index, 0
        drive = self.drives[leg_index]
        while self.progress < drive.minutes:
            self._drive_step(drive)

    def _drive_step(self, drive: LegDrive) -> None:
        """One iteration of the priority loop; either records a stop or a driving chunk."""
        if self.window_start is None:
            self._ensure_duty_period()
            return

        cycle_room = floor(R.CYCLE_LIMIT - self.cycle + _MINUTE_EPS)
        if self.cycle + self._work_needed(self._driving_remaining(), opening=False) > R.CYCLE_LIMIT + _MINUTE_EPS:
            # A restart will interrupt the trip: stop driving early enough that the
            # post-trip before it still ends within 70 h.
            cycle_room = floor(R.CYCLE_LIMIT - self._post_trip_reserve() - self.cycle + _MINUTE_EPS)
        elapsed = self.t - self.window_start
        leg_left = drive.minutes - self.progress

        # 1. 70-hour cycle exhausted: 34-hour restart.
        if cycle_room < 1:
            self._end_duty_period(restart=True)
            return
        # 2. 11-hour driving or 14-hour window exhausted: 10-hour rest.
        if self.drive_in_period >= R.MAX_DRIVING or elapsed >= R.DUTY_WINDOW:
            self._end_duty_period()
            return

        fuel_room = self._fuel_room(drive)
        fuel_due = fuel_room < 1
        fuel = self.opts.fuel_stop_minutes

        # 3. 8 hours of driving since the last 30-min interruption.
        if self.drive_since_break >= R.BREAK_AFTER_DRIVING:
            fuel_now = fuel_due or self._fuel_soon()
            fuel_is_break = fuel_now and fuel >= R.BREAK_MINUTES  # a >= 30-min fuel stop is the break
            stop = fuel if fuel_is_break else R.BREAK_MINUTES + (fuel if fuel_now else 0)
            after = min(
                R.MAX_DRIVING - self.drive_in_period,
                R.DUTY_WINDOW - elapsed - stop,
                cycle_room - (fuel if fuel_now else 0),  # fueling is on duty
            )
            if after < R.MIN_DRIVE_AFTER_STOP and after < leg_left:
                # Too little driving would follow the stop: end the period instead.
                self._end_duty_period()
                return
            if fuel_now:
                self._fuel_stop()  # a short one is followed by the break at the same place
            if not fuel_is_break and self.window_start is not None:
                self._stationary(R.Kind.BREAK, R.OFF, R.BREAK_MINUTES)
            return
        # 4. Fuel interval reached.
        if fuel_due:
            after = min(R.MAX_DRIVING - self.drive_in_period, R.DUTY_WINDOW - elapsed - fuel, cycle_room - fuel)
            if after < R.MIN_DRIVE_AFTER_STOP and after < leg_left:
                self._end_duty_period()  # fuel, post-trip and rest at the same stop
                return
            self._fuel_stop()
            if fuel < R.BREAK_MINUTES and self.window_start is not None and self._break_due_soon(self.window_start):
                self._stationary(R.Kind.BREAK, R.OFF, R.BREAK_MINUTES)  # rather than a stop soon after
            return
        # 5. Drive until the first limit binds.
        chunk = min(
            R.MAX_DRIVING - self.drive_in_period,
            R.DUTY_WINDOW - elapsed,
            R.BREAK_AFTER_DRIVING - self.drive_since_break,
            cycle_room,
            fuel_room,
            leg_left,
        )
        self._drive(max(1, int(chunk)))

    def _break_due_soon(self, window_start: int) -> bool:
        """The 8-h break falls due within ``BREAK_EARLY_MINUTES`` of driving that this duty
        period will still do."""
        until = R.BREAK_AFTER_DRIVING - self.drive_since_break
        ahead = min(
            R.MAX_DRIVING - self.drive_in_period,
            R.DUTY_WINDOW - (self.t - window_start) - R.BREAK_MINUTES,
            self._driving_remaining(),
        )
        return until <= R.BREAK_EARLY_MINUTES and ahead > until

    def _fuel_stop(self) -> None:
        """Fuel now, unless that would strand the cycle: then restart first (fuel comes after)."""
        if self._restart_before_stop(self.opts.fuel_stop_minutes):
            self._end_duty_period(restart=True)
        else:
            self._fuel()

    def _fuel(self) -> None:
        self._stationary(R.Kind.FUEL, R.ON, self.opts.fuel_stop_minutes)
        self.miles_since_fuel = 0.0

    # ----- whole trip -------------------------------------------------------------

    def run(self) -> list[DutyEvent]:
        leg0, leg1 = self.drives
        if leg0.minutes > 0:
            self._drive_leg(0)
        # At the pickup: position is the start of leg 1, events still belong to leg 0.
        self.pos_leg, self.progress = 1, 0
        self._ensure_duty_period()
        if self._restart_before_stop(R.PICKUP_MINUTES):
            self._end_duty_period(restart=True)
            self._ensure_duty_period()
        if self._fuel_soon() and not self._restart_before_stop(R.PICKUP_MINUTES + self.opts.fuel_stop_minutes):
            self._fuel()  # fuel at the shipper rather than a few miles down the road
        self._stationary(R.Kind.PICKUP, R.ON, R.PICKUP_MINUTES)

        self.event_leg = 1
        if leg1.minutes > 0:
            self._drive_leg(1)
        self.pos_leg, self.progress = 1, leg1.minutes
        self._ensure_duty_period()
        self._stationary(R.Kind.DROPOFF, R.ON, R.DROPOFF_MINUTES)
        if self.opts.include_inspections:
            self._stationary(R.Kind.POST_TRIP, R.ON, R.POST_TRIP_MINUTES)
        return _merge_adjacent_drives(self.events)


def _fuel_stops_needed(miles_since_fuel: float, miles: float) -> int:
    """Fewest fuel stops to drive ``miles`` more with ``miles_since_fuel`` already on the tank."""
    return max(0, ceil((miles_since_fuel + miles - R.MILE_EPS) / R.FUEL_INTERVAL_MILES) - 1)


def _merge_adjacent_drives(events: list[DutyEvent]) -> list[DutyEvent]:
    """Defensive: join back-to-back driving chunks on the same leg into one event."""
    merged: list[DutyEvent] = []
    for ev in events:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.kind == ev.kind == R.Kind.DRIVE
            and prev.leg_index == ev.leg_index
            and prev.end == ev.start
        ):
            merged[-1] = DutyEvent(
                R.Kind.DRIVE, R.D, prev.start, ev.end, prev.start_mile, ev.end_mile, ev.leg_index,
                prev.start_coord, ev.end_coord, prev.start_leg_mile, ev.end_leg_mile,
                prev.progress_start, ev.progress_end,
            )
        else:
            merged.append(ev)
    return merged


def _validate_cycle(cycle_used_hours: float) -> float:
    hours = float(cycle_used_hours)
    if not (0.0 <= hours <= R.CYCLE_LIMIT / 60):
        raise ValueError(f"cycle_used_hours must be within 0-70, got {cycle_used_hours!r}")
    return hours * 60.0


def _validate_prior_off(minutes: int) -> int:
    if int(minutes) != minutes or not (0 <= minutes < R.RESTART):
        raise ValueError(f"prior_off_duty_minutes must be a whole number within 0-{R.RESTART - 1}, got {minutes!r}")
    return int(minutes)


def plan_drives(
    drives: list[LegDrive],
    cycle_used_hours: float,
    options: PlanOptions | None = None,
    *,
    prior_off_duty_minutes: int = 0,
) -> list[DutyEvent]:
    """Plan over prepared ``LegDrive``s (shared with the log builder).

    Plans greedily, then once per optional restart the greedy plan passed (see
    ``_Planner._optional_restart``), and returns the earliest arrival (the greedy plan on a tie).
    """
    args = (drives, _validate_cycle(cycle_used_hours), options or PlanOptions(),
            _validate_prior_off(prior_off_duty_minutes))
    greedy = _Planner(*args)
    best = greedy.run()
    for index in range(greedy.restart_options):
        events = _Planner(*args, restart_at=index).run()
        if events[-1].end < best[-1].end:
            best = events
    return best


def plan_events(
    legs: list[LegProfile],
    cycle_used_hours: float,
    options: PlanOptions | None = None,
    *,
    prior_off_duty_minutes: int = 0,
) -> list[DutyEvent]:
    """Plan the trip: drive leg 0, pickup, drive leg 1, drop-off, post-trip.

    ``prior_off_duty_minutes``: off-duty time right before the start (``build_plan`` passes
    the minutes since local midnight); a restart needed at the start counts it toward 34 h.
    Returns contiguous events starting at minute 0.
    """
    return plan_drives(build_leg_drives(legs), cycle_used_hours, options,
                       prior_off_duty_minutes=prior_off_duty_minutes)
