"""Independent HOS compliance checks for a planned trip.

The auditor re-derives every clock from the event list alone (it does not reuse the
planner's state), so it can catch planner bugs. It returns human-readable violations;
an empty list means the plan is compliant. Used by the test suite and available to the
API layer as a self-check.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from . import rules as R
from .planner import DutyEvent

_EPS = 1e-6


def audit_events(
    events: Sequence[DutyEvent], cycle_used_hours: float, prior_off_duty_minutes: int = 0
) -> list[str]:
    """Check contiguity and every HOS rule the planner must respect.

    ``prior_off_duty_minutes``: off-duty time right before the first event, which counts
    toward a 34-h restart that opens the trip.
    """
    problems: list[str] = []
    if not events:
        return ["no events"]
    if events[0].start != 0:
        problems.append(f"first event starts at {events[0].start}, not 0")
    for prev, ev in pairwise(events):
        if prev.end != ev.start:
            problems.append(f"gap/overlap between {prev.kind}@{prev.end} and {ev.kind}@{ev.start}")
        if abs(prev.end_mile - ev.start_mile) > _EPS:
            problems.append(f"mile jump {prev.end_mile} -> {ev.start_mile} at minute {ev.start}")
    for ev in events:
        if ev.duration <= 0:
            problems.append(f"{ev.kind}@{ev.start} has non-positive duration {ev.duration}")
        if ev.kind != R.Kind.DRIVE and abs(ev.miles) > _EPS:
            problems.append(f"non-driving {ev.kind}@{ev.start} moves {ev.miles} mi")
        if ev.kind == R.Kind.DRIVE and ev.status != R.D:
            problems.append(f"drive@{ev.start} has status {ev.status}")

    for kind in (R.Kind.PICKUP, R.Kind.DROPOFF):
        matching = [ev for ev in events if ev.kind == kind]
        if len(matching) != 1:
            problems.append(f"expected exactly one {kind}, found {len(matching)}")
        for ev in matching:
            if ev.duration != 60 or ev.status != R.ON:
                problems.append(f"{kind} must be 60 min ON, got {ev.duration} min {ev.status}")
    order = [ev.kind for ev in events if ev.kind in (R.Kind.PICKUP, R.Kind.DROPOFF)]
    if order != [R.Kind.PICKUP, R.Kind.DROPOFF]:
        problems.append(f"pickup must precede drop-off, got {order}")

    # Clocks. The driver starts rested, so no window is open at minute 0.
    window_start: int | None = None
    drive_in_period = 0
    drive_since_break = 0
    off_run = prior_off_duty_minutes  # consecutive OFF/SB minutes
    nondriving_run = 0  # consecutive non-driving minutes, any status
    cycle = cycle_used_hours * 60.0
    miles_since_fuel = 0.0

    for ev in events:
        dur = ev.duration
        if ev.status in (R.OFF, R.SB):
            off_run += dur
            if off_run >= R.RESET_OFF:
                window_start, drive_in_period, drive_since_break = None, 0, 0
            if off_run >= R.RESTART:
                cycle = 0.0
        else:
            off_run = 0
            if window_start is None:
                window_start = ev.start  # the 14 hours start with any work

        if ev.status != R.D:
            nondriving_run += dur
            if nondriving_run >= R.BREAK_MINUTES:
                drive_since_break = 0
        else:
            nondriving_run = 0
            assert window_start is not None
            drive_in_period += dur
            drive_since_break += dur
            where = f"drive {ev.start}-{ev.end}"
            if drive_in_period > R.MAX_DRIVING:
                problems.append(f"{where}: {drive_in_period} min driving in the duty period (> 11 h)")
            if ev.end - window_start > R.DUTY_WINDOW:
                problems.append(f"{where}: ends {ev.end - window_start} min into the window (> 14 h)")
            if drive_since_break > R.BREAK_AFTER_DRIVING:
                problems.append(f"{where}: {drive_since_break} min driving without a 30-min break (> 8 h)")
            if cycle + dur > R.CYCLE_LIMIT + _EPS:
                problems.append(f"{where}: cycle reaches {(cycle + dur) / 60:.3f} h (> 70 h)")

        if ev.status in R.ON_DUTY_STATUSES:
            cycle += dur
        if ev.kind == R.Kind.FUEL:
            miles_since_fuel = 0.0
        elif ev.kind == R.Kind.DRIVE:
            miles_since_fuel += ev.miles
            if miles_since_fuel > R.FUEL_INTERVAL_MILES + _EPS:
                problems.append(f"drive {ev.start}-{ev.end}: {miles_since_fuel:.3f} mi since fuel (> 1,000)")
    return problems


def audit_plan(plan: dict) -> list[str]:
    """Check the JSON plan's daily logs: full-day coverage, exact totals, miles."""
    problems: list[str] = []
    logs = plan["daily_logs"]
    summary = plan["summary"]
    if len(logs) != summary["num_days"]:
        problems.append(f"{len(logs)} sheets but summary.num_days = {summary['num_days']}")
    miles_units = 0
    for i, log in enumerate(logs):
        tag = f"sheet {log['date']}"
        if log["day_number"] != i + 1:
            problems.append(f"{tag}: day_number {log['day_number']} != {i + 1}")
        segs = log["segments"]
        if not segs or segs[0]["start_minute"] != 0 or segs[-1]["end_minute"] != 1440:
            problems.append(f"{tag}: segments do not span 0-1440")
        minutes = dict.fromkeys(R.STATUSES, 0)
        for a, b in pairwise(segs):
            if a["end_minute"] != b["start_minute"]:
                problems.append(f"{tag}: segment gap at {a['end_minute']}")
            if a["status"] == b["status"]:
                problems.append(f"{tag}: unmerged {a['status']} segments at {a['end_minute']}")
        for s in segs:
            if s["end_minute"] <= s["start_minute"]:
                problems.append(f"{tag}: empty segment {s}")
            minutes[s["status"]] += s["end_minute"] - s["start_minute"]
        total_hundredths = sum(round(v * 100) for v in log["totals"].values())
        if total_hundredths != 2400:
            problems.append(f"{tag}: totals sum to {total_hundredths / 100}")
        for status, mins in minutes.items():
            if abs(log["totals"][status] - mins / 60) > 0.01 + _EPS:
                problems.append(f"{tag}: {status} total {log['totals'][status]} vs {mins / 60:.4f} h")
        for r in log["remarks"]:
            if not 0 <= r["start_minute"] < r["end_minute"] <= 1440:
                problems.append(f"{tag}: remark out of range {r}")
        miles_units += round(log["total_miles"] * 10)
    if miles_units != round(summary["total_miles"] * 10):
        problems.append(f"per-day miles sum to {miles_units / 10}, route total {summary['total_miles']}")
    return problems
