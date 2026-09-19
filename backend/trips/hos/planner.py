"""Duty-status simulation: turns two route legs into a legal sequence of duty events.

Time is simulated in integer minutes from the trip start. Each leg's driving time is
rounded once to whole minutes (``LegDrive.minutes``); a driving chunk of ``k`` minutes
then covers the profile distance between progress ``p`` and ``p + k`` proportionally,
so miles are exact at every leg end and no rounding drift accumulates.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, inf

from . import rules as R
from .profile import LegProfile, LonLat

# Guards float noise when converting a fractional progress to whole minutes.
_MINUTE_EPS = 1e-9


@dataclass
class PlanOptions:
    include_inspections: bool = True
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

    def __init__(self, drives: list[LegDrive], cycle_used_minutes: float, opts: PlanOptions) -> None:
        self.drives = drives
        self.opts = opts
        self.events: list[DutyEvent] = []

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
        """Open a duty period (restarting first if the cycle is nearly spent)."""
        if self.window_start is not None:
            return
        if self.cycle > R.CYCLE_RESTART_THRESHOLD and self._driving_remaining() > 0:
            self._stationary(R.Kind.RESTART, R.OFF, R.RESTART)
            self._reset_after_off(restart=True)
        self.window_start = self.t
        if self.opts.include_inspections:
            self._stationary(R.Kind.PRE_TRIP, R.ON, R.PRE_TRIP_MINUTES)

    def _end_duty_period(self, restart: bool) -> None:
        """Post-trip inspection, then a 10-h rest or a 34-h restart."""
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

    def _needs_restart(self) -> bool:
        # A 10-h rest would be followed by a restart anyway (no roll-off), so go straight to 34 h.
        return self.cycle > R.CYCLE_RESTART_THRESHOLD

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
        elapsed = self.t - self.window_start

        # 1. 70-hour cycle exhausted: 34-hour restart.
        if cycle_room < 1:
            self._end_duty_period(restart=True)
            return
        # 2. 11-hour driving or 14-hour window exhausted: 10-hour rest.
        if self.drive_in_period >= R.MAX_DRIVING or elapsed >= R.DUTY_WINDOW:
            self._end_duty_period(restart=self._needs_restart())
            return

        fuel_room = self._fuel_room(drive)
        fuel_due = fuel_room < 1

        # 3. 8 hours of driving since the last 30-min interruption.
        if self.drive_since_break >= R.BREAK_AFTER_DRIVING:
            if fuel_due and self.opts.fuel_stop_minutes >= R.BREAK_MINUTES:
                self._fuel()  # a >= 30-min fuel stop satisfies the break
            elif R.DUTY_WINDOW - (elapsed + R.BREAK_MINUTES) < 1:
                # The window would close during the break: rest instead of a wasted break.
                self._end_duty_period(restart=self._needs_restart())
            else:
                self._stationary(R.Kind.BREAK, R.OFF, R.BREAK_MINUTES)
            return
        # 4. Fuel interval reached.
        if fuel_due:
            self._fuel()
            return
        # 5. Drive until the first limit binds.
        chunk = min(
            R.MAX_DRIVING - self.drive_in_period,
            R.DUTY_WINDOW - elapsed,
            R.BREAK_AFTER_DRIVING - self.drive_since_break,
            cycle_room,
            fuel_room,
            drive.minutes - self.progress,
        )
        self._drive(max(1, int(chunk)))

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


def plan_drives(
    drives: list[LegDrive], cycle_used_hours: float, options: PlanOptions | None = None
) -> list[DutyEvent]:
    """Plan over prepared ``LegDrive``s (shared with the log builder)."""
    return _Planner(drives, _validate_cycle(cycle_used_hours), options or PlanOptions()).run()


def plan_events(
    legs: list[LegProfile], cycle_used_hours: float, options: PlanOptions | None = None
) -> list[DutyEvent]:
    """Plan the trip: drive leg 0, pickup, drive leg 1, drop-off, post-trip.

    Returns contiguous events starting at minute 0.
    """
    return plan_drives(build_leg_drives(legs), cycle_used_hours, options)
