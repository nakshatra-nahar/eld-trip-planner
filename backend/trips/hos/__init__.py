"""Pure-Python hours-of-service (HOS) trip planner. No Django or network imports.

Public interface (see docs/SPEC.md, "Engine public interface"):
``build_plan``, ``plan_events``, ``PlanOptions``, ``LegProfile``, ``RouteStep``, ``PlaceNamer``.
"""

from .logs import PlaceNamer, build_plan
from .planner import DutyEvent, PlanOptions, plan_events
from .profile import LegProfile, RouteStep

__all__ = [
    "DutyEvent",
    "LegProfile",
    "PlaceNamer",
    "PlanOptions",
    "RouteStep",
    "build_plan",
    "plan_events",
]
