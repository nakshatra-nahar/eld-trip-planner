"""Unit constants shared by the routing and instruction services."""

from __future__ import annotations

from trips.hos.rules import TRUCK_SPEED_CAP_MPH

METERS_PER_MILE = 1609.344
TRUCK_MAX_MPS = TRUCK_SPEED_CAP_MPH * METERS_PER_MILE / 3600.0  # the truck speed cap, in m/s
