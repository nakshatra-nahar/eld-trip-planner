"""Polyline simplification for display (Douglas-Peucker with a global point budget)."""

from __future__ import annotations

import heapq
import math

LonLat = tuple[float, float]


def _perp_dist(p: LonLat, a: LonLat, b: LonLat, kx: float) -> float:
    """Distance from p to segment ab in a local equirectangular plane (degrees of latitude)."""
    px, py = p[0] * kx, p[1]
    ax, ay = a[0] * kx, a[1]
    bx, by = b[0] * kx, b[1]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dp_significance(points: list[LonLat]) -> list[float]:
    """Douglas-Peucker significance of every vertex.

    ``sig[i]`` is the largest tolerance at which DP would still keep vertex ``i``
    (clamped to its parent's value so the ranking is hierarchical). Keeping every
    vertex with ``sig > eps`` reproduces DP at tolerance ``eps``; keeping the top-K
    gives the best K-point DP approximation. Endpoints are ``inf``.
    """
    n = len(points)
    sig = [0.0] * n
    if n == 0:
        return sig
    sig[0] = sig[-1] = math.inf
    if n < 3:
        return sig
    mean_lat = sum(p[1] for p in points) / n
    kx = math.cos(math.radians(mean_lat))
    stack: list[tuple[int, int, float]] = [(0, n - 1, math.inf)]
    while stack:
        i, j, parent = stack.pop()
        if j - i < 2:
            continue
        a, b = points[i], points[j]
        best_k, best_d = i + 1, -1.0
        for k in range(i + 1, j):
            d = _perp_dist(points[k], a, b, kx)
            if d > best_d:
                best_k, best_d = k, d
        s = min(best_d, parent)
        sig[best_k] = s
        stack.append((i, best_k, s))
        stack.append((best_k, j, s))
    return sig


def simplify_many(lines: list[list[LonLat]], max_points: int) -> list[list[LonLat]]:
    """Simplify several polylines together so their combined size is <= ``max_points``.

    The budget is shared by geometric error, not split evenly, so a winding city
    approach keeps detail while a straight interstate collapses to a few points.
    Every line keeps its two endpoints.
    """
    total = sum(len(line) for line in lines)
    if total <= max_points:
        return [list(line) for line in lines]
    ranked: list[tuple[float, int, int]] = []
    for li, line in enumerate(lines):
        for idx, s in enumerate(dp_significance(line)):
            ranked.append((s, li, idx))
    budget = max(max_points, 2 * len(lines))
    keep = heapq.nlargest(budget, ranked)  # endpoints (inf) always survive
    chosen: list[list[int]] = [[] for _ in lines]
    for _, li, idx in keep:
        chosen[li].append(idx)
    return [[lines[li][i] for i in sorted(idxs)] for li, idxs in enumerate(chosen)]


def round_coords(line: list[LonLat], ndigits: int = 5) -> list[list[float]]:
    """JSON-ready ``[lon, lat]`` pairs (~1 m precision)."""
    return [[round(lon, ndigits), round(lat, ndigits)] for lon, lat in line]
