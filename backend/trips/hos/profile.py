"""Distance/time profile of one route leg, with interpolation helpers.

A ``LegProfile`` is built from OSRM's per-segment annotations: N coordinates and
N-1 segment distances (miles) and durations (minutes, already truck-adjusted).
Miles and minutes are leg-relative and grow monotonically along the polyline.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from math import isfinite

LonLat = tuple[float, float]


@dataclass(frozen=True)
class RouteStep:
    """One OSRM step within a leg, in leg-relative miles."""

    start_mile: float
    end_mile: float
    road: str  # step "ref" if present (e.g. "I 80"), else "name", else ""


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Piecewise-linear interpolation of ``ys`` over non-decreasing ``xs`` (clamped).

    On a zero-width interval (a repeated x) the furthest ``y`` wins, so the result is
    monotone in ``x`` when ``ys`` is.
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x)  # xs[i-1] <= x < xs[i]
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = ys[i - 1], ys[i]
    if x1 <= x0:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _validate_series(name: str, values: list[float], expected_len: int) -> None:
    if len(values) != expected_len:
        raise ValueError(f"{name} must have {expected_len} entries, got {len(values)}")
    for v in values:
        if not isfinite(v) or v < 0:
            raise ValueError(f"{name} entries must be finite and >= 0, got {v!r}")


class LegProfile:
    """Cumulative miles/minutes along a leg polyline."""

    __slots__ = ("_step_starts", "coords", "cum_miles", "cum_minutes", "steps")

    def __init__(
        self,
        coords: list[LonLat],
        seg_miles: list[float],
        seg_minutes: list[float],
        steps: list[RouteStep] | None = None,
    ) -> None:
        if len(coords) < 2:
            raise ValueError("a leg profile needs at least 2 coordinates")
        _validate_series("seg_miles", seg_miles, len(coords) - 1)
        _validate_series("seg_minutes", seg_minutes, len(coords) - 1)

        self.coords: list[LonLat] = [(float(lon), float(lat)) for lon, lat in coords]
        self.cum_miles: list[float] = [0.0, *accumulate(float(m) for m in seg_miles)]
        self.cum_minutes: list[float] = [0.0, *accumulate(float(m) for m in seg_minutes)]
        self.steps: list[RouteStep] = sorted(steps or [], key=lambda s: s.start_mile)
        self._step_starts: list[float] = [s.start_mile for s in self.steps]

    @property
    def total_miles(self) -> float:
        return self.cum_miles[-1]

    @property
    def total_minutes(self) -> float:
        return self.cum_minutes[-1]

    def mile_at_minute(self, minute: float) -> float:
        """Leg mile reached after ``minute`` minutes of driving (clamped to the leg)."""
        return _interp(self.cum_minutes, self.cum_miles, minute)

    def minute_at_mile(self, mile: float) -> float:
        """Driving minutes needed to reach leg mile ``mile`` (clamped to the leg)."""
        return _interp(self.cum_miles, self.cum_minutes, mile)

    def coord_at_mile(self, mile: float) -> LonLat:
        """(lon, lat) at leg mile ``mile``, interpolated along the polyline."""
        cm = self.cum_miles
        if mile <= 0 or cm[-1] <= 0:
            return self.coords[0]
        if mile >= cm[-1]:
            return self.coords[-1]
        i = bisect_right(cm, mile)
        m0, m1 = cm[i - 1], cm[i]
        (lon0, lat0), (lon1, lat1) = self.coords[i - 1], self.coords[i]
        if m1 <= m0:
            return (lon1, lat1)
        f = (mile - m0) / (m1 - m0)
        return (lon0 + (lon1 - lon0) * f, lat0 + (lat1 - lat0) * f)

    def road_at_mile(self, mile: float) -> str:
        """Road name/ref of the OSRM step covering ``mile``; "" if unknown."""
        if not self.steps:
            return ""
        i = bisect_right(self._step_starts, mile) - 1
        i = max(i, 0)
        return self.steps[i].road or ""

    # Alias used by the SPEC's prose ("step_at_mile returns the road name/ref").
    step_at_mile = road_at_mile

    @classmethod
    def straight(
        cls,
        start: LonLat,
        end: LonLat,
        miles: float,
        minutes: float,
        n: int = 50,
    ) -> LegProfile:
        """A straight, constant-speed leg of ``n`` points (tests and zero-length legs)."""
        n = max(2, int(n))
        (lon0, lat0), (lon1, lat1) = start, end
        coords = [
            (lon0 + (lon1 - lon0) * k / (n - 1), lat0 + (lat1 - lat0) * k / (n - 1))
            for k in range(n)
        ]
        segs = n - 1
        return cls(coords, [miles / segs] * segs, [minutes / segs] * segs)

    def __repr__(self) -> str:
        return (
            f"LegProfile(points={len(self.coords)}, miles={self.total_miles:.3f}, "
            f"minutes={self.total_minutes:.3f})"
        )
