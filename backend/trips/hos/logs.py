"""Turns planned duty events into the JSON-ready plan (timeline, stops, daily logs, summary).

Output shapes match frontend/src/types/api.ts: ``TimelineEvent``, ``Stop``, ``DailyLog``
and ``TripSummary``. Hours are rounded to 2 dp and miles to 1 dp. Per-sheet totals and
per-day miles use largest-remainder rounding, so they add up exactly (24.00 h per sheet,
per-day miles summing to the trip miles).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import rules as R
from .planner import Cause, DutyEvent, LegDrive, PlanOptions, Rule, build_leg_drives, plan_drives
from .profile import LegProfile, LonLat

PlaceNamer = Callable[[float, float, "str | None"], str]  # (lat, lon, road) -> "City, ST"

MINUTES_PER_DAY = 24 * 60
_TIME_FMT = "%Y-%m-%dT%H:%M"
# A position closer than this to a leg end is the pickup/drop-off/start address itself.
_ENDPOINT_MILES = 0.05

_LABELS = {
    R.Kind.DRIVE: "Driving",
    R.Kind.PRE_TRIP: "Pre-trip inspection",
    R.Kind.POST_TRIP: "Post-trip inspection",
    R.Kind.PICKUP: "Pickup (loading)",
    R.Kind.DROPOFF: "Drop-off (unloading)",
    R.Kind.FUEL: "Fuel stop",
    R.Kind.BREAK: "30-minute break",
    R.Kind.RESTART: "34-hour restart",
}
_REST_LABELS = {R.SB: "10-hour rest (sleeper berth)", R.OFF: "10-hour rest (off duty)"}
_REMARK_NOTES = {
    R.Kind.PRE_TRIP: "Pre-trip inspection",
    R.Kind.POST_TRIP: "Post-trip inspection",
    R.Kind.PICKUP: "Pickup",
    R.Kind.DROPOFF: "Drop-off",
    R.Kind.FUEL: "Fuel",
    R.Kind.BREAK: "30-minute break",
    R.Kind.REST: "10-hour rest",
    R.Kind.RESTART: "34-hour restart",
}


def _road_part(name: str, city: str) -> str:
    """The road in a namer label: "I 44 near Joplin, MO" with city "Joplin, MO" -> "I 44"."""
    suffix = f" near {city}"
    return name[: -len(suffix)] if name != city and name.endswith(suffix) else ""


def _remark_place(ref: dict) -> dict:
    """``LogRemark`` location fields from a ``PlaceRef``."""
    out = {"location": ref["name"], "city": ref["city"]}
    if "road" in ref:
        out["road"] = ref["road"]
    return out


def _label(ev: DutyEvent) -> str:
    return _REST_LABELS[ev.status] if ev.kind == R.Kind.REST else _LABELS[ev.kind]


def _hours(minutes: float) -> float:
    return round(minutes / 60.0, 2)


def _duration(minutes: float) -> str:
    """Minutes as the UI writes durations: "0m", "45m", "10h", "6h 23m"."""
    total = max(0, round(minutes))
    h, m = divmod(total, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h" if m == 0 else f"{h}h {m:02d}m"


def _miles(miles: float) -> float:
    return round(miles, 1)


def _spoken(minutes: int) -> str:
    """A fixed duration in words: 60 -> "1 hour", 30 -> "30 minutes", 90 -> "1h 30m"."""
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} hour" + ("s" if h != 1 else "")
    return f"{m} minutes" if h == 0 else _duration(minutes)


_RESETS = "34 consecutive hours off resets it"
_AVOIDED_STOP = {
    "break": "a 30-minute break",
    "fuel": "a fuel stop",
    "fuel_break": "fueling and a 30-minute break",
    "pickup": "the pickup",
}
_FUEL_WHERE = {
    "break": "fueling at the 30-minute break",
    "rest": "fueling before the rest",
    "restart": "fueling before the restart",
    "pickup": "fueling at the pickup rather than just after it",
    "duty_start": "fueling before driving off",
}
_ALSO_BREAK = "also serves as the 30-minute break due after 8 hours of driving"


def _largest_remainder(raw_units: list[float], total_units: int) -> list[int]:
    """Round each value to an integer so the results sum exactly to ``total_units``."""
    floors = [int(v // 1) for v in raw_units]
    diff = total_units - sum(floors)
    order = sorted(range(len(raw_units)), key=lambda i: raw_units[i] - floors[i], reverse=True)
    if diff >= 0:
        for i in order[:diff]:
            floors[i] += 1
    else:  # float noise only; take from the smallest remainders that can afford it
        for i in reversed(order):
            if diff == 0:
                break
            if floors[i] > 0:
                floors[i] -= 1
                diff += 1
    return floors


@dataclass(frozen=True)
class _Piece:
    """Part of an event (or of the OFF padding) that falls on one calendar day."""

    day: int  # 0-based sheet index
    start: int  # minute of the sheet, 0..1440
    end: int
    status: str
    event: DutyEvent | None  # None for the padding before/after the trip


class _PlanBuilder:
    def __init__(
        self,
        drives: list[LegDrive],
        events: list[DutyEvent],
        start_time: datetime,
        cycle_used_hours: float,
        options: PlanOptions,
        place_namer: PlaceNamer,
    ) -> None:
        self.drives = drives
        self.events = events
        self.start = start_time.replace(second=0, microsecond=0, tzinfo=None)
        self.start_offset = self.start.hour * 60 + self.start.minute  # minutes after local midnight
        self.initial_cycle = float(cycle_used_hours) * 60.0
        self.options = options
        self._namer = place_namer
        self._names: dict[tuple[float, float, str | None], str] = {}
        self.ids = {id(ev): f"e{i}" for i, ev in enumerate(events, start=1)}

        self.end_minute = events[-1].end
        self.num_days = (self.start_offset + self.end_minute - 1) // MINUTES_PER_DAY + 1
        self.pieces = self._split_into_days()

    # ----- time and place helpers -------------------------------------------------

    def _clock(self, minute: int) -> str:
        return (self.start + timedelta(minutes=minute)).strftime(_TIME_FMT)

    def _day_of(self, minute: int) -> int:
        """0-based sheet index of trip minute ``minute`` (an instant at midnight starts the new day)."""
        return (self.start_offset + minute) // MINUTES_PER_DAY

    def _date(self, day: int) -> date:
        return self.start.date() + timedelta(days=day)

    def _name(self, coord: LonLat, road: str | None) -> str:
        lon, lat = coord
        key = (round(lat, 4), round(lon, 4), road or None)
        name = self._names.get(key)
        if name is None:
            name = self._namer(lat, lon, road or None)
            self._names[key] = name
        return name

    def _road(self, leg_index: int, leg_mile: float) -> str | None:
        """Road ref for an en-route position; None at the start/pickup/drop-off addresses."""
        leg = self.drives[leg_index].leg
        if leg_mile <= _ENDPOINT_MILES or leg_mile >= leg.total_miles - _ENDPOINT_MILES:
            return None
        return leg.road_at_mile(leg_mile) or None

    def _place_ref(self, coord: LonLat, leg_index: int, leg_mile: float) -> dict:
        """``PlaceRef``: the display ``name`` plus its parts, ``city`` and (on a highway) ``road``."""
        lon, lat = coord
        name = self._name(coord, self._road(leg_index, leg_mile))
        city = self._name(coord, None)
        ref = {"lat": round(lat, 5), "lon": round(lon, 5), "name": name, "city": city}
        road = _road_part(name, city)
        if road:
            ref["road"] = road
        return ref

    def _drive_state(self, ev: DutyEvent, minute: int) -> tuple[float, LonLat]:
        """(trip mile, coord) at trip minute ``minute`` inside driving event ``ev``."""
        drive = self.drives[ev.leg_index]
        leg_mile = drive.leg_mile(ev.progress_start + (minute - ev.start))
        return drive.offset + leg_mile, drive.leg.coord_at_mile(leg_mile)

    def _coord_at(self, ev: DutyEvent | None, minute: int) -> LonLat:
        if ev is None:  # padding: before the trip at the start, after it at the end
            return self.events[0].start_coord if minute <= 0 else self.events[-1].end_coord
        if ev.kind == R.Kind.DRIVE:
            return self._drive_state(ev, minute)[1]
        return ev.start_coord

    # ----- day splitting ----------------------------------------------------------------

    def _split_into_days(self) -> list[_Piece]:
        """Pad with OFF to whole days and cut every span at midnight."""
        spans: list[tuple[int, int, str, DutyEvent | None]] = []
        total = self.num_days * MINUTES_PER_DAY
        first = self.start_offset
        last = self.start_offset + self.end_minute
        if first > 0:
            spans.append((0, first, R.OFF, None))
        spans.extend((first + ev.start, first + ev.end, ev.status, ev) for ev in self.events)
        if last < total:
            spans.append((last, total, R.OFF, None))

        pieces: list[_Piece] = []
        for g0, g1, status, ev in spans:
            g = g0
            while g < g1:
                day = g // MINUTES_PER_DAY
                cut = min(g1, (day + 1) * MINUTES_PER_DAY)
                base = day * MINUTES_PER_DAY
                pieces.append(_Piece(day, g - base, cut - base, status, ev))
                g = cut
        return pieces

    def _trip_minute(self, piece: _Piece, sheet_minute: int) -> int:
        return piece.day * MINUTES_PER_DAY + sheet_minute - self.start_offset

    # ----- output sections -------------------------------------------------------------

    def timeline(self) -> list[dict]:
        out = []
        for ev in self.events:
            item = {
                "id": self.ids[id(ev)],
                "kind": ev.kind,
                "status": ev.status,
                "label": _label(ev),
                "start": self._clock(ev.start),
                "end": self._clock(ev.end),
                "duration_hours": _hours(ev.duration),
                "miles": _miles(ev.miles),
                "start_mile": _miles(ev.start_mile),
                "end_mile": _miles(ev.end_mile),
                "leg_index": ev.leg_index,
                "start_location": self._place_ref(ev.start_coord, ev.leg_index, self._pos_leg_mile(ev, True)),
                "end_location": self._place_ref(ev.end_coord, ev.leg_index, self._pos_leg_mile(ev, False)),
            }
            reason = self._reason(ev)
            if reason:
                item["reason"] = reason
            out.append(item)
        return out

    # ----- reasons ----------------------------------------------------------------------

    def _hhmm(self, minute: int) -> str:
        return self._clock(minute)[11:]

    def _cycle_state(self, cycle: float) -> str:
        if round(cycle) >= R.CYCLE_LIMIT:
            return f"70-hour/8-day cycle used up ({_duration(cycle)})"
        return f"70-hour/8-day cycle nearly used up ({_duration(cycle)} of 70h)"

    def _rest_reason(self, c: Cause) -> str:
        if c.rule == Rule.DRIVE_LIMIT:
            return "11-hour driving limit reached"
        if c.rule == Rule.DUTY_WINDOW:
            return f"14-hour duty window closes at {self._hhmm(c.at)}"
        if c.rule == Rule.LIMIT_BEFORE_STOP:
            limit = {
                "drive": "11-hour driving limit",
                "window": f"14-hour duty window closes at {self._hhmm(c.at)}",
                "cycle": "70-hour cycle",
            }[c.limit]
            left = f"only {_duration(c.left)} of driving" if c.left >= 1 else "no driving time"
            return f"{limit}: {left} would be left after {_AVOIDED_STOP[c.stop]}"
        raise ValueError(f"not a rest rule: {c.rule!r}")

    def _reason(self, ev: DutyEvent) -> str | None:
        """One short sentence on why a non-driving event happens (None for driving)."""
        c = ev.cause
        if c is None:
            return None
        credit = f" (credited with {_duration(c.credit)} off duty since midnight)" if c.credit else ""
        tank = f"{c.fuel_miles:,.0f} mi on this tank"
        match c.rule:
            case Rule.DRIVE_LIMIT | Rule.DUTY_WINDOW | Rule.LIMIT_BEFORE_STOP:
                return self._rest_reason(c)
            case Rule.CYCLE:
                return f"{self._cycle_state(c.cycle)}; {_RESETS}{credit}"
            case Rule.CYCLE_BEFORE_STOP:
                return (f"{self._cycle_state(c.cycle)}: no driving time would be left after "
                        f"{_AVOIDED_STOP[c.stop]}; {_RESETS}")
            case Rule.EARLY_RESTART if c.instead_of is not None:
                return (f"Taken here instead of a 10-hour rest ({self._rest_reason(c.instead_of)}) to reset "
                        f"the 70-hour cycle: the rest of the trip needs more than the "
                        f"{_duration(R.CYCLE_LIMIT - c.cycle)} left")
            case Rule.EARLY_RESTART:
                return (f"Only {_duration(R.CYCLE_LIMIT - c.cycle)} left in the 70-hour cycle and the trip "
                        f"needs more: restarting before driving arrives earliest{credit}")
            case Rule.BREAK:
                return "8 hours of driving without a 30-minute interruption"
            case Rule.BREAK_WITH_FUEL:
                return ("Taken at the fuel stop: the 30-minute break would be due after "
                        f"{_duration(c.left)} more driving")
            case Rule.FUEL_INTERVAL:
                interval = f"{R.FUEL_INTERVAL_MILES:,.0f}-mile fuel interval ({tank})"
                return f"{interval}; {_ALSO_BREAK}" if c.as_break else interval
            case Rule.FUEL_SOON:
                due_in = round(R.FUEL_INTERVAL_MILES - c.fuel_miles)
                due = (f"fuel is due in {due_in:,} mi ({tank})" if due_in >= 1
                       else f"{R.FUEL_INTERVAL_MILES:,.0f}-mile fuel interval ({tank})")
                if c.as_break:
                    return f"30-minute break due after 8 hours of driving, taken as a fuel stop: {due}"
                return f"{due[0].upper()}{due[1:]}: {_FUEL_WHERE[c.stop]}"
            case Rule.FUEL_AHEAD if c.stop == "duty_start":
                due_in = max(1, round(R.FUEL_INTERVAL_MILES - c.fuel_miles))
                return f"Fueling before driving off: fuel is due in {due_in:,} mi ({tank})"
            case Rule.FUEL_AHEAD:
                due_in = max(1, round(R.FUEL_INTERVAL_MILES - c.fuel_miles))
                return (f"Fueling before the {c.stop}: fuel is due in {due_in:,} mi, early in the next "
                        f"duty period ({tank})")
            case Rule.PICKUP:
                return f"{_spoken(R.PICKUP_MINUTES)} on duty for loading, per the trip assumptions"
            case Rule.DROPOFF:
                return f"{_spoken(R.DROPOFF_MINUTES)} on duty for unloading, per the trip assumptions"
            case Rule.PRE_TRIP:
                return f"Starts every duty period: {_spoken(R.PRE_TRIP_MINUTES)} on duty (inspections are on)"
            case Rule.POST_TRIP:
                return f"Ends every duty period: {_spoken(R.POST_TRIP_MINUTES)} on duty (inspections are on)"
            case Rule.POST_TRIP_END:
                return f"Ends the trip: {_spoken(R.POST_TRIP_MINUTES)} on duty (inspections are on)"
        raise ValueError(f"unknown rule {c.rule!r}")

    def _pos_leg_mile(self, ev: DutyEvent, start: bool) -> float:
        # The pickup is recorded on leg 0 but positioned at leg 1's start: an endpoint either way.
        if ev.kind == R.Kind.PICKUP:
            return 0.0
        return ev.start_leg_mile if start else ev.end_leg_mile

    def stops(self, timeline: list[dict]) -> list[dict]:
        out = []
        for ev, item in zip(self.events, timeline, strict=True):
            if ev.kind == R.Kind.DRIVE:
                continue
            stop = {
                "id": item["id"],
                "kind": ev.kind,
                "status": ev.status,
                "label": item["label"],
                "start": item["start"],
                "end": item["end"],
                "duration_hours": item["duration_hours"],
                "mile_marker": item["start_mile"],
                "day_number": self._day_of(ev.start) + 1,
                "location": item["start_location"],
            }
            if "reason" in item:
                stop["reason"] = item["reason"]
            out.append(stop)
        return out

    def daily_logs(self, timeline: list[dict], total_miles: float) -> list[dict]:
        by_day: list[list[_Piece]] = [[] for _ in range(self.num_days)]
        for p in self.pieces:
            by_day[p.day].append(p)
        names = {id(ev): item["start_location"] for ev, item in zip(self.events, timeline, strict=True)}

        raw_miles = [sum(self._piece_miles(p) for p in day) for day in by_day]
        tenths = _largest_remainder([m * 10 for m in raw_miles], round(total_miles * 10))

        logs = []
        cycle = self.initial_cycle
        for day, pieces in enumerate(by_day):
            # Cycle recap: on-duty time accumulates; a restart zeroes it once it completes.
            for p in pieces:
                if p.status in R.ON_DUTY_STATUSES:
                    cycle += p.end - p.start
                ev = p.event
                if ev is not None and ev.kind == R.Kind.RESTART and self._trip_minute(p, p.end) == ev.end:
                    cycle = 0.0
            logs.append(self._sheet(day, pieces, tenths[day] / 10, cycle, names))
        return logs

    def _piece_miles(self, p: _Piece) -> float:
        ev = p.event
        if ev is None or ev.kind != R.Kind.DRIVE:
            return 0.0
        m0 = self._drive_state(ev, self._trip_minute(p, p.start))[0]
        m1 = self._drive_state(ev, self._trip_minute(p, p.end))[0]
        return m1 - m0

    def _sheet(self, day: int, pieces: list[_Piece], miles: float, cycle: float, names: dict) -> dict:
        segments: list[dict] = []
        minutes: dict[str, int] = dict.fromkeys(R.STATUSES, 0)
        for p in pieces:
            minutes[p.status] += p.end - p.start
            if segments and segments[-1]["status"] == p.status:
                segments[-1]["end_minute"] = p.end
            else:
                segments.append({"status": p.status, "start_minute": p.start, "end_minute": p.end})

        hundredths = _largest_remainder([minutes[s] * 100 / 60 for s in R.STATUSES], 2400)
        totals = {s: h / 100 for s, h in zip(R.STATUSES, hundredths, strict=True)}

        remarks = []
        trip_start = self.start_offset - day * MINUTES_PER_DAY  # sheet minute of the trip start
        for p in pieces:
            ev = p.event
            if ev is not None and ev is self.events[0] and ev.kind == R.Kind.DRIVE and p.start == trip_start:
                # A change of duty status needs a location (FMCSA p.17); with inspections off
                # the trip opens OFF -> D with no pre-trip remark to carry it.
                remarks.append({
                    "start_minute": p.start,
                    "end_minute": min(p.start + 1, p.end),
                    "status": ev.status,
                    **_remark_place(names[id(ev)]),
                    "note": "Start of trip / on duty",
                })
            if ev is None or ev.kind == R.Kind.DRIVE:
                continue
            continued = self._trip_minute(p, p.start) > ev.start
            note = _REMARK_NOTES[ev.kind] + (" (cont.)" if continued else "")
            remarks.append({
                "start_minute": p.start,
                "end_minute": p.end,
                "status": ev.status,
                **_remark_place(names[id(ev)]),
                "note": note,
            })

        first, last = pieces[0], pieces[-1]
        used = _hours(cycle)
        return {
            "date": self._date(day).isoformat(),
            "day_number": day + 1,
            "total_miles": round(miles, 1),
            "segments": segments,
            "totals": totals,
            "remarks": remarks,
            "on_duty_hours": round(totals[R.D] + totals[R.ON], 2),
            "cycle_hours_used": used,
            "cycle_hours_available": max(0.0, round(R.CYCLE_LIMIT / 60 - used, 2)),
            "from_location": self._name(self._coord_at(first.event, self._trip_minute(first, first.start)), None),
            "to_location": self._name(self._coord_at(last.event, self._trip_minute(last, last.end)), None),
        }

    def summary(self, total_miles: float) -> dict:
        count = {k: 0 for k in (R.Kind.FUEL, R.Kind.BREAK, R.Kind.REST, R.Kind.RESTART)}
        driving = on_duty = 0
        cycle = self.initial_cycle
        for ev in self.events:
            if ev.kind in count:
                count[ev.kind] += 1
            if ev.status == R.D:
                driving += ev.duration
            if ev.is_on_duty:
                on_duty += ev.duration
                cycle += ev.duration
            if ev.kind == R.Kind.RESTART:
                cycle = 0.0
        used = _hours(cycle)
        return {
            "total_miles": total_miles,
            "total_driving_hours": _hours(driving),
            "total_on_duty_hours": _hours(on_duty),
            "trip_duration_hours": _hours(self.end_minute),
            "start_time": self._clock(0),
            "end_time": self._clock(self.end_minute),
            "num_days": self.num_days,
            "num_fuel_stops": count[R.Kind.FUEL],
            "num_breaks": count[R.Kind.BREAK],
            "num_rests": count[R.Kind.REST],
            "num_restarts": count[R.Kind.RESTART],
            "cycle_hours_used_at_end": used,
            "cycle_hours_available_at_end": max(0.0, round(R.CYCLE_LIMIT / 60 - used, 2)),
        }

    def assumptions(self) -> list[str]:
        opts = self.options
        rest = "sleeper berth" if opts.rest_status == R.SB else "off duty"
        items = [
            "Property-carrying driver on the 70-hour/8-day cycle; no adverse driving conditions.",
            (
                "Hours of service follow US FMCSA rules (70 h/8 days) for the whole trip, as the brief "
                "specifies; Canadian legs are not planned under Canada's own hours-of-service rules."
            ),
            "The driver starts the trip rested (at least 10 hours off), so the 11- and 14-hour clocks are fresh.",
            "The driver is off duty from midnight until the trip starts and from the trip end until midnight.",
            (
                "The fuel tank is full at the current location; fuel at least every 1,000 miles "
                f"({opts.fuel_stop_minutes} min on duty per stop)."
            ),
            "Pickup and drop-off take 1 hour each, logged on duty (not driving).",
            f"10-hour rests are logged as {rest}; 34-hour restarts are logged off duty.",
            "Current Cycle Used hours do not roll off during the trip (conservative: no per-day history is given).",
            "A 34-hour restart is taken when the rest of the trip's driving no longer fits in the 70-hour "
            "cycle, at the trip start or in place of the 10-hour rest that gives the earliest arrival; "
            "on-duty work after the last drive (drop-off, post-trip) may run past 70 h.",
            "A 34-hour restart at the trip start counts the off-duty time since midnight toward its 34 hours.",
            "Log sheets use the home-terminal time zone of the start location for the whole trip, "
            "even across time zones (FMCSA p.16); stops also show their local time.",
            "Log times use the home-terminal clock and do not shift for a daylight-saving change during the trip.",
            "Times are to the minute, as an ELD records them; the grid shows the paper form's 15-minute ticks.",
            "The driver resumes at the earliest legal moment after a 10-hour rest or 34-hour restart, "
            "so departures can fall overnight.",
            "A single driver: no split sleeper berth and no team driving.",
            f"Truck speed is capped at {R.TRUCK_SPEED_CAP_MPH:g} mph over each route segment.",
        ]
        # After the pickup/drop-off line.
        at = next(i for i, s in enumerate(items) if s.startswith("Pickup and drop-off")) + 1
        if opts.include_inspections:
            items.insert(at, "A 30-minute pre-trip inspection starts every duty period and a 15-minute "
                             "post-trip inspection ends it (on duty, not driving).")
        else:
            items.insert(at, "No pre-/post-trip inspection time is added: the brief lists only pickup, "
                             "drop-off and fueling as on-duty stops (inspections can be turned on).")
        return items

    def warnings(self) -> list[str]:
        out = []
        # With no hours carried in, would the trip's own work up to its last drive fit in 70 h?
        # If so, a restart is only needed because the used hours are assumed not to roll off.
        rolloff = " (assumes none of the hours already used roll off during the trip)"
        caveat = rolloff if self.initial_cycle > 0 and self._own_work_to_last_drive() <= R.CYCLE_LIMIT else ""
        cycle = self.initial_cycle
        for ev in self.events:
            if ev.kind == R.Kind.RESTART:
                room = R.CYCLE_LIMIT - cycle
                left = _duration(room)
                if ev.start == 0:
                    counted = (
                        f"; it counts the {_duration(R.RESTART - ev.duration)} off duty since midnight, "
                        f"so it lasts {_duration(ev.duration)}"
                        if ev.duration < R.RESTART else ""
                    )
                    why = (
                        f"only {left} of the 70-hour cycle is available at the start and the trip needs more"
                        if room >= 1 else "the 70-hour cycle is already used up at the start"
                    )
                    out.append(f"34-hour restart required before driving: {why}{counted}{caveat}.")
                else:
                    why = (
                        f"only {left} of the 70-hour cycle is left and the rest of the trip needs more"
                        if room >= 1 else "the 70-hour cycle is used up and driving remains"
                    )
                    out.append(f"34-hour restart required on day {self._day_of(ev.start) + 1}: {why}{caveat}.")
                cycle = 0.0
            elif ev.is_on_duty:
                cycle += ev.duration
        if cycle > R.CYCLE_LIMIT + 1e-6:
            after = (
                "drop-off and post-trip inspection that follow are"
                if self.options.include_inspections
                else "drop-off that follows is"
            )
            out.append(
                f"The cycle ends at {_duration(cycle)}: driving finishes within 70 h, and the {after} "
                "on duty (not driving), which is allowed after 70 h (FMCSA p.10)."
            )
        return out

    def _own_work_to_last_drive(self) -> int:
        """On-duty minutes of the trip itself, up to the end of its last driving event."""
        last = max((i for i, ev in enumerate(self.events) if ev.kind == R.Kind.DRIVE), default=-1)
        return sum(ev.duration for ev in self.events[: last + 1] if ev.is_on_duty)

    def build(self) -> dict:
        timeline = self.timeline()
        total_miles = _miles(sum(ev.miles for ev in self.events if ev.kind == R.Kind.DRIVE))
        return {
            "timeline": timeline,
            "stops": self.stops(timeline),
            "daily_logs": self.daily_logs(timeline, total_miles),
            "summary": self.summary(total_miles),
            "assumptions": self.assumptions(),
            "warnings": self.warnings(),
        }


def build_plan(
    legs: list[LegProfile],
    start_time: datetime,
    cycle_used_hours: float,
    options: PlanOptions | None,
    place_namer: PlaceNamer,
) -> dict:
    """Plan the trip and return JSON-ready ``timeline``, ``stops``, ``daily_logs``,
    ``summary``, ``assumptions`` and ``warnings`` (see frontend/src/types/api.ts)."""
    options = options or PlanOptions()
    drives = build_leg_drives(legs)
    # The driver is off duty from local midnight until the start (the sheets draw it so).
    since_midnight = start_time.hour * 60 + start_time.minute
    events = plan_drives(drives, cycle_used_hours, options, prior_off_duty_minutes=since_midnight)
    return _PlanBuilder(drives, events, start_time, cycle_used_hours, options, place_namer).build()
