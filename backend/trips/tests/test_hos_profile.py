"""LegProfile interpolation helpers."""

import pytest

from trips.hos import LegProfile, RouteStep


def make_profile():
    # Three segments: 10 mi in 10 min, 20 mi in 40 min, 30 mi in 30 min.
    coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 2.0), (4.0, 2.0)]
    steps = [RouteStep(0, 10, "Main St"), RouteStep(10, 30, "I 80"), RouteStep(30, 60, "")]
    return LegProfile(coords, [10, 20, 30], [10, 40, 30], steps)


def test_totals():
    p = make_profile()
    assert p.total_miles == 60
    assert p.total_minutes == 80


@pytest.mark.parametrize(
    ("minute", "mile"),
    [(-5, 0), (0, 0), (5, 5), (10, 10), (30, 20), (50, 30), (65, 45), (80, 60), (999, 60)],
)
def test_mile_at_minute(minute, mile):
    assert make_profile().mile_at_minute(minute) == pytest.approx(mile)


@pytest.mark.parametrize(("mile", "minute"), [(0, 0), (5, 5), (20, 30), (45, 65), (60, 80), (70, 80)])
def test_minute_at_mile(mile, minute):
    assert make_profile().minute_at_mile(mile) == pytest.approx(minute)


def test_minute_mile_roundtrip():
    p = make_profile()
    for tenth in range(601):
        mile = tenth / 10
        assert p.mile_at_minute(p.minute_at_mile(mile)) == pytest.approx(mile)


def test_coord_at_mile():
    p = make_profile()
    assert p.coord_at_mile(0) == (0.0, 0.0)
    assert p.coord_at_mile(5) == pytest.approx((0.5, 0.0))
    assert p.coord_at_mile(20) == pytest.approx((1.0, 1.0))
    assert p.coord_at_mile(60) == (4.0, 2.0)
    assert p.coord_at_mile(1e9) == (4.0, 2.0)


def test_road_at_mile():
    p = make_profile()
    assert p.road_at_mile(3) == "Main St"
    assert p.road_at_mile(10) == "I 80"
    assert p.road_at_mile(29.9) == "I 80"
    assert p.road_at_mile(45) == ""
    assert p.road_at_mile(15) == "I 80"
    assert LegProfile.straight((0, 0), (1, 1), 10, 10).road_at_mile(5) == ""


def test_zero_duration_segment_is_monotone():
    # A zero-minute segment (a jump in miles) must not break monotonicity.
    p = LegProfile([(0, 0), (1, 0), (2, 0), (3, 0)], [10, 5, 10], [10, 0, 10])
    minutes = [i / 4 for i in range(81)]
    miles = [p.mile_at_minute(m) for m in minutes]
    assert miles == sorted(miles)
    assert p.mile_at_minute(10) == pytest.approx(15)  # the far side of the jump


def test_straight_profile():
    p = LegProfile.straight((-90.0, 40.0), (-80.0, 42.0), 600, 540, n=7)
    assert len(p.coords) == 7
    assert p.total_miles == pytest.approx(600)
    assert p.total_minutes == pytest.approx(540)
    assert p.coord_at_mile(300) == pytest.approx((-85.0, 41.0))
    assert p.mile_at_minute(270) == pytest.approx(300)


def test_zero_length_leg():
    p = LegProfile.straight((-90.0, 40.0), (-90.0, 40.0), 0, 0)
    assert p.total_miles == 0
    assert p.mile_at_minute(10) == 0
    assert p.minute_at_mile(10) == 0
    assert p.coord_at_mile(0) == (-90.0, 40.0)


@pytest.mark.parametrize(
    "args",
    [
        ([(0, 0)], [], []),
        ([(0, 0), (1, 1)], [1, 2], [1]),
        ([(0, 0), (1, 1)], [-1], [1]),
        ([(0, 0), (1, 1)], [1], [float("nan")]),
    ],
)
def test_invalid_profiles_rejected(args):
    with pytest.raises(ValueError):
        LegProfile(*args)
