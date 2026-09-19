"""Hours-of-service constants for a property-carrying driver on the 70-hour/8-day cycle.

All durations are integer minutes. Sources refer to the FMCSA "Interstate Truck
Driver's Guide to Hours of Service" (2022-04-28); see docs/SPEC.md.
"""

from __future__ import annotations

# Duty statuses (log-sheet rows 1-4).
OFF = "OFF"  # 1. Off duty
SB = "SB"  # 2. Sleeper berth
D = "D"  # 3. Driving
ON = "ON"  # 4. On duty (not driving)
STATUSES = (OFF, SB, D, ON)
ON_DUTY_STATUSES = frozenset({D, ON})


class Kind:
    """Event kinds (mirrors EventKind in frontend/src/types/api.ts)."""

    DRIVE = "drive"
    PRE_TRIP = "pre_trip"
    POST_TRIP = "post_trip"
    PICKUP = "pickup"
    DROPOFF = "dropoff"
    FUEL = "fuel"
    BREAK = "break"
    REST = "rest"
    RESTART = "restart"


MAX_DRIVING = 11 * 60  # 11 h driving per duty period (p.6)
DUTY_WINDOW = 14 * 60  # no driving after the 14th hour of the duty period (p.6)
BREAK_AFTER_DRIVING = 8 * 60  # 8 h cumulative driving needs a 30-min interruption (p.10)
BREAK_MINUTES = 30  # the qualifying interruption; logged OFF (p.10)
RESET_OFF = 10 * 60  # 10 consecutive hours off resets the 11/14-h clocks (p.6-7)
CYCLE_LIMIT = 70 * 60  # 70 h on duty in 8 days; no driving at or above it (p.10-11)
RESTART = 34 * 60  # 34 consecutive hours off resets the cycle to 0 (p.11)

# When the rest of the trip does not fit in the cycle, take the 34-h restart once the next
# duty period could drive less than this (or less than all the remaining driving).
MIN_USEFUL_DRIVING = 60
# A break or fuel stop is skipped in favour of ending the duty period when less driving
# than this could follow it.
MIN_DRIVE_AFTER_STOP = 15

FUEL_INTERVAL_MILES = 1000.0  # fuel at least every 1,000 miles (assessment brief)
# Fuel early, at a stop that is happening anyway, when fuel falls due within this many miles.
FUEL_EARLY_MILES = 75.0
PICKUP_MINUTES = 60  # brief: 1 h for pickup, logged ON (p.5: loading is on duty)
DROPOFF_MINUTES = 60  # brief: 1 h for drop-off, logged ON
PRE_TRIP_MINUTES = 30  # at the start of every duty period, when inspections are enabled
POST_TRIP_MINUTES = 15  # before each rest/restart that ends a duty period, and at trip end

TRUCK_SPEED_CAP_MPH = 65.0  # applied by the route service when building LegProfile minutes

MIN_LEG_MILES = 0.1  # legs shorter than this are not driven (e.g. current == pickup)
MILE_EPS = 1e-6  # tolerance for floating-point mile comparisons
