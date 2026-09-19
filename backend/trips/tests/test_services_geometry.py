"""Douglas-Peucker display simplification."""

from __future__ import annotations

import math

from trips.services.geometry import dp_significance, simplify_many


def test_straight_line_collapses_to_endpoints():
    line = [(float(i), 0.0) for i in range(100)]
    (out,) = simplify_many([line], 2)
    assert out == [line[0], line[-1]]


def test_keeps_the_corner():
    line = [(i / 10, 0.0) for i in range(11)] + [(1.0, i / 10) for i in range(1, 11)]
    (out,) = simplify_many([line], 3)
    assert out == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_significance_endpoints_infinite():
    sig = dp_significance([(0, 0), (1, 1), (2, 0)])
    assert math.isinf(sig[0]) and math.isinf(sig[-1]) and sig[1] > 0


def test_real_route_respects_budget_and_endpoints(load_fixture):
    data = load_fixture("osrm_chicago_stlouis_dallas.json.gz")
    geometry = [tuple(c) for c in data["routes"][0]["geometry"]["coordinates"]]
    split = len(data["routes"][0]["legs"][0]["annotation"]["distance"])
    legs = [geometry[: split + 1], geometry[split:]]
    out = simplify_many(legs, 1500)
    assert sum(len(line) for line in out) <= 1500
    for original, simple in zip(legs, out):
        assert simple[0] == original[0] and simple[-1] == original[-1]
        assert len(simple) >= 2


def test_small_input_untouched():
    lines = [[(0, 0), (1, 1)], [(1, 1), (2, 2), (3, 1)]]
    assert simplify_many(lines, 10) == lines
