"""Offline nearest-place index and the engine's place namer."""

from __future__ import annotations

import zoneinfo

import pytest

from trips.services import places
from trips.services.places import (
    Place,
    PlaceIndex,
    highway_ref,
    nearest_place,
    place_namer,
    timezone_at,
)


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (41.8781, -87.6298, "Chicago, IL"),
        (41.5250, -88.0817, "Joliet, IL"),
        (38.6270, -90.1994, "St. Louis, MO"),
        (32.7767, -96.7970, "Dallas, TX"),
        (43.6532, -79.3832, "Toronto, ON"),
        (49.2827, -123.1207, "Vancouver, BC"),
        (45.5017, -73.5673, "Montréal, QC"),
    ],
)
def test_real_dataset_city_labels(lat, lon, expected):
    assert place_namer(lat, lon) == expected


def test_dataset_is_us_and_canada_only_and_reasonably_sized():
    index = places.get_index()
    assert 15_000 < index.size < 60_000
    admins = {p.admin for cell in index._cells.values() for p in cell}
    assert {"IL", "TX", "DC", "ON", "QC", "BC", "AK", "HI"} <= admins
    assert all(len(a) == 2 and a.isupper() for a in admins)


def test_nearest_place_returns_distance():
    name, admin, dist = nearest_place(41.8781, -87.6298)
    assert (name, admin) == ("Chicago", "IL")
    assert dist < 5


def test_far_away_point_returns_none_or_far():
    # Middle of the Atlantic: nothing within the search radius.
    assert nearest_place(30.0, -40.0) is None


def test_population_preference_and_plain_nearest():
    index = PlaceIndex(
        [
            Place("Hamlet", "IL", 41.00, -88.00, 600),
            Place("Big City", "IL", 41.10, -88.00, 500_000),  # ~6.9 mi away
            Place("Far Metro", "IL", 42.00, -88.00, 2_000_000),  # ~69 mi away: outside preferred radius
        ]
    )
    best, _ = index.nearest(41.001, -88.0)
    assert best.name == "Big City"
    best, dist = index.nearest(41.001, -88.0, prefer_populous=False)
    assert best.name == "Hamlet" and dist < 0.1


def test_population_preference_stays_in_nearest_state():
    # A stop just inside Oklahoma must not borrow a much bigger Missouri city over the line.
    index = PlaceIndex(
        [
            Place("Quapaw", "OK", 36.95, -94.79, 900),
            Place("Commerce", "OK", 36.93, -94.87, 2_500),
            Place("Big Metro", "MO", 37.08, -94.51, 5_000_000),
        ]
    )
    best, _ = index.nearest(36.96, -94.75)
    assert best.admin == "OK"


def test_grid_search_crosses_cells():
    # The only place is several cells away; ring search must still find it.
    index = PlaceIndex([Place("Lonely", "NV", 39.5, -116.5, 700)])
    best, dist = index.nearest(41.9, -119.9)
    assert best.name == "Lonely"
    assert 200 < dist < 300


@pytest.mark.parametrize(
    ("road", "expected"),
    [
        ("I 80", "I 80"),
        ("I 55; US 40", "I 55"),
        ("US 30", "US 30"),
        ("IL 59", "IL 59"),
        ("ON 401", "ON 401"),
        ("Main Street", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_highway_ref(road, expected):
    assert highway_ref(road) == expected


def test_place_namer_highway_prefix():
    assert place_namer(41.5250, -88.0817, "I 80") == "I 80 near Joliet, IL"
    assert place_namer(41.5250, -88.0817, "Jefferson Street") == "Joliet, IL"


@pytest.mark.parametrize(
    ("lat", "lon", "zone"),
    [
        (41.8781, -87.6298, "America/Chicago"),  # Chicago
        (39.7684, -86.1581, "America/Indiana/Indianapolis"),  # Indianapolis
        (33.4484, -112.0740, "America/Phoenix"),  # Phoenix: no DST
        (34.9022, -110.1582, "America/Phoenix"),  # Holbrook, AZ
        (40.7128, -74.0060, "America/New_York"),
        (47.6062, -122.3321, "America/Los_Angeles"),  # Seattle
        (39.7392, -104.9903, "America/Denver"),
        (43.6532, -79.3832, "America/Toronto"),
        (21.3069, -157.8583, "Pacific/Honolulu"),
    ],
)
def test_timezone_at_nearest_place(lat, lon, zone):
    assert timezone_at(lat, lon) == zone


def test_timezone_far_from_any_place_falls_back_to_utc():
    assert timezone_at(30.0, -40.0) == "UTC"


def test_every_dataset_place_has_a_known_time_zone():
    zones = {p.tz for cell in places.get_index()._cells.values() for p in cell}
    assert zones <= zoneinfo.available_timezones()


def test_within_radius():
    index = PlaceIndex([Place("Near", "IL", 41.0, -88.0, 1), Place("Far", "IL", 41.5, -88.0, 1)])
    assert [p.name for p, _ in index.within(41.05, -88.0, 10)] == ["Near"]
    assert {p.name for p, _ in index.within(41.05, -88.0, 40)} == {"Near", "Far"}
