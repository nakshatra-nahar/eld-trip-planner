"""The independent auditor must catch violations, not just pass compliant plans.

Each case hand-builds a duty-event list that breaks exactly one rule and checks the
auditor names it. (The planner tests only show that it returns [] for good plans.)
"""

import copy
from datetime import datetime

import pytest

from trips.hos import LegProfile, PlanOptions, build_plan
from trips.hos import rules as R
from trips.hos.audit import audit_events, audit_plan
from trips.hos.planner import DutyEvent

P = (-90.0, 37.0)


def events(*spec, gap_before=None):
    """DutyEvents from (kind, minutes, miles) steps, back to back from minute 0.

    ``gap_before``: index of a step that starts one minute late (a hole in the log).
    """
    out, minute, mile = [], 0, 0.0
    for i, (kind, minutes, miles) in enumerate(spec):
        if i == gap_before:
            minute += 1
        status = {R.Kind.DRIVE: R.D, R.Kind.BREAK: R.OFF, R.Kind.REST: R.SB, R.Kind.RESTART: R.OFF}.get(kind, R.ON)
        out.append(DutyEvent(kind, status, minute, minute + minutes, mile, mile + miles, 1, P, P, mile, mile + miles))
        minute, mile = minute + minutes, mile + miles
    return out


PICKUP = (R.Kind.PICKUP, 60, 0.0)
DROPOFF = (R.Kind.DROPOFF, 60, 0.0)


def test_compliant_events_pass():
    assert audit_events(events(PICKUP, ("drive", 300, 300.0), DROPOFF), 0) == []


@pytest.mark.parametrize(
    ("steps", "cycle", "gap_before", "keyword"),
    [
        pytest.param(  # 330 + 331 = 661 min of driving in one duty period
            [PICKUP, ("drive", 330, 330.0), ("break", 30, 0.0), ("drive", 331, 331.0), DROPOFF],
            0, None, "(> 11 h)", id="11-hour driving limit",
        ),
        pytest.param(  # the last drive ends at minute 930 of the window
            [PICKUP, ("drive", 300, 300.0), ("break", 30, 0.0), ("fuel", 480, 0.0), ("drive", 60, 60.0), DROPOFF],
            0, None, "(> 14 h)", id="14-hour window",
        ),
        pytest.param(  # 481 min of driving with no 30-min interruption
            [PICKUP, ("drive", 481, 481.0), DROPOFF],
            0, None, "without a 30-min break", id="30-minute break",
        ),
        pytest.param(  # 1,001 mi without a fuel stop
            [PICKUP, ("drive", 400, 1001.0), DROPOFF],
            0, None, "since fuel (> 1,000)", id="fuel every 1,000 mi",
        ),
        pytest.param(  # 69 h used + 1 h pickup: any driving goes past 70 h
            [PICKUP, ("drive", 10, 10.0), DROPOFF],
            69, None, "(> 70 h)", id="70-hour cycle",
        ),
        pytest.param(  # the drive starts one minute after the pickup ends
            [PICKUP, ("drive", 300, 300.0), DROPOFF],
            0, 1, "gap/overlap", id="time gap",
        ),
    ],
)
def test_auditor_catches_each_violation(steps, cycle, gap_before, keyword):
    problems = audit_events(events(*steps, gap_before=gap_before), cycle)
    assert problems, "the auditor missed the violation"
    assert any(keyword in p for p in problems), problems


def test_restart_resets_the_cycle():
    """The same drive at 69 h is legal after a 34-hour restart."""
    steps = [(R.Kind.RESTART, R.RESTART, 0.0), PICKUP, ("drive", 10, 10.0), DROPOFF]
    assert audit_events(events(*steps), 69) == []


def test_audit_plan_catches_tampered_totals():
    trip = [LegProfile.straight(P, P, 0, 0), LegProfile.straight((-95, 37), (-90, 37), 600, 600)]
    plan = build_plan(trip, datetime(2026, 9, 21, 6, 0), 0, PlanOptions(), lambda lat, lon, road=None: "X")
    assert audit_plan(plan) == []

    tampered = copy.deepcopy(plan)
    tampered["daily_logs"][0]["totals"][R.D] += 0.25
    problems = audit_plan(tampered)
    assert any("totals sum to 24.25" in p for p in problems), problems
    assert any(f"{R.D} total" in p for p in problems), problems
