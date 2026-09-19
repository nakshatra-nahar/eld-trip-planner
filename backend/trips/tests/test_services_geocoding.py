"""Photon/Nominatim geocoding (mocked), label shaping, caching and offline reverse."""

from __future__ import annotations

import pytest
import requests

from trips.services import geocoding
from trips.services.errors import UpstreamUnavailable


def photon_feature(props, lon, lat):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


PHOTON = {
    "type": "FeatureCollection",
    "features": [
        photon_feature({"osm_key": "place", "osm_value": "city", "type": "city", "name": "Joliet",
                        "county": "Will County", "state": "Illinois", "country": "United States",
                        "countrycode": "US"}, -88.084, 41.526),
        photon_feature({"osm_key": "railway", "osm_value": "station", "type": "house", "housenumber": "90",
                        "name": "Joliet", "street": "East Jefferson Street", "city": "Joliet", "state": "IL",
                        "country": "United States", "countrycode": "US"}, -88.079, 41.5245),
        photon_feature({"osm_key": "place", "type": "city", "name": "Joliette", "state": "Quebec",
                        "country": "Canada", "countrycode": "CA"}, -73.44, 46.02),
        photon_feature({"osm_key": "place", "type": "city", "name": "Joliet", "state": "Jalisco",
                        "country": "Mexico", "countrycode": "MX"}, -103.3, 20.6),
        photon_feature({"osm_key": "office", "type": "house", "housenumber": "350", "name": "Empire State Building",
                        "street": "5th Avenue", "city": "New York", "state": "NY", "country": "United States",
                        "countrycode": "US"}, -73.9857, 40.7484),
        photon_feature({"osm_key": "highway", "type": "street", "name": "Main Street", "city": "Springfield",
                        "state": "Illinois", "country": "United States", "countrycode": "US"}, -89.65, 39.8),
        photon_feature({"osm_key": "place", "type": "state", "name": "Texas", "country": "United States",
                        "countrycode": "US"}, -99.0, 31.0),
    ],
}

NOMINATIM = [
    {"lat": "39.6687744", "lon": "-77.7193693", "addresstype": "place", "name": "",
     "display_name": "1600, Pennsylvania Avenue, Fountainhead, Washington County, Maryland, 21742, United States",
     "address": {"house_number": "1600", "road": "Pennsylvania Avenue", "village": "Fountainhead-Orchard Hills",
                 "state": "Maryland", "ISO3166-2-lvl4": "US-MD", "country_code": "us"}},
    {"lat": "45.5", "lon": "-73.56", "addresstype": "city", "name": "Montréal",
     "display_name": "Montréal, Québec, Canada",
     "address": {"city": "Montréal", "state": "Québec", "ISO3166-2-lvl4": "CA-QC", "country_code": "ca"}},
]


@pytest.fixture(autouse=True)
def _clear_cache():
    geocoding.clear_cache()
    yield
    geocoding.clear_cache()


@pytest.fixture
def use(monkeypatch, fake_session):
    def install(*results):
        fake = fake_session(*results)
        monkeypatch.setattr(geocoding, "session", lambda: fake)
        return fake

    return install


def test_photon_results_are_shaped_and_filtered(use, fake_response):
    fake = use(fake_response(200, PHOTON))
    results = geocoding.geocode("joliet", limit=10)
    # Settlements first (a digit-free query is a city search), then addresses/POIs, each in Photon order.
    assert [r["short_label"] for r in results] == [
        "Joliet, IL",
        "Joliette, QC",
        "Texas",
        "90 East Jefferson Street, Joliet, IL",
        "Empire State Building, New York, NY",
        "Main Street, Springfield, IL",
    ]
    assert results[0] == {"label": "Joliet, Illinois, United States", "short_label": "Joliet, IL", "lat": 41.526, "lon": -88.084}
    assert results[3]["label"] == "90 East Jefferson Street, Joliet, Illinois, United States"
    assert results[4]["label"] == "Empire State Building, 350 5th Avenue, New York, United States"
    params = fake.calls[0]["params"]
    assert params["bbox"] == "-170,15,-50,72" and params["q"] == "joliet"
    assert fake.calls[0]["url"] == "https://photon.komoot.io/api/"


def test_results_are_cached(use, fake_response):
    fake = use(fake_response(200, PHOTON))
    first = geocoding.geocode("Joliet  ")
    second = geocoding.geocode("joliet")
    assert first == second and len(fake.calls) == 1


def test_falls_back_to_nominatim_on_error(use, fake_response):
    fake = use(requests.ConnectionError("photon down"), fake_response(200, NOMINATIM))
    results = geocoding.geocode("1600 Pennsylvania Ave")
    assert results[0]["short_label"] == "1600 Pennsylvania Avenue, Fountainhead-Orchard Hills, MD"
    assert results[0]["label"].startswith("1600, Pennsylvania Avenue")
    assert results[1]["short_label"] == "Montréal, QC"
    assert "nominatim.openstreetmap.org" in fake.calls[1]["url"]
    assert fake.calls[1]["params"]["countrycodes"] == "us,ca"


def test_falls_back_to_nominatim_when_photon_finds_nothing(use, fake_response):
    use(fake_response(200, {"features": []}), fake_response(200, NOMINATIM))
    assert len(geocoding.geocode("something obscure")) == 2


def test_empty_when_both_answer_nothing(use, fake_response):
    use(fake_response(200, {"features": []}), fake_response(200, []))
    assert geocoding.geocode("zzzzqqq") == []


def test_raises_when_every_provider_fails(use, fake_response):
    use(fake_response(503), requests.Timeout("slow"))
    with pytest.raises(UpstreamUnavailable):
        geocoding.geocode("Chicago")


def test_short_query_skips_network(use):
    use()  # any request would fail the test
    assert geocoding.geocode(" a ") == []


def test_city_outranks_namesake_poi_and_near_duplicates_collapse(use, fake_response):
    airport = photon_feature({"osm_key": "aeroway", "type": "house", "name": "St. Louis Lambert International Airport",
                              "city": "St. Louis", "state": "Missouri", "country": "United States",
                              "countrycode": "US"}, -90.37, 38.75)
    city = photon_feature({"osm_key": "place", "type": "city", "name": "Saint Louis", "state": "Missouri",
                           "country": "United States", "countrycode": "US"}, -90.19, 38.625)
    city_again = photon_feature({"osm_key": "place", "type": "city", "name": "Saint Louis", "state": "Missouri",
                                 "country": "United States", "countrycode": "US"}, -90.21, 38.61)
    use(fake_response(200, {"type": "FeatureCollection", "features": [airport, city, city_again]}))
    labels = [r["short_label"] for r in geocoding.geocode("St. Louis")]
    assert labels == ["Saint Louis, MO", "St. Louis Lambert International Airport, St. Louis, MO"]


def test_address_query_keeps_provider_order(use, fake_response):
    use(fake_response(200, PHOTON))
    assert geocoding.geocode("90 joliet", limit=2)[1]["short_label"] == "90 East Jefferson Street, Joliet, IL"


def test_geocode_one(use, fake_response):
    use(fake_response(200, PHOTON))
    assert geocoding.geocode_one("joliet")["short_label"] == "Joliet, IL"


def test_reverse_is_offline():
    result = geocoding.reverse(41.8781, -87.6298)
    assert result == {"label": "Chicago, Illinois, United States", "short_label": "Chicago, IL", "lat": 41.8781, "lon": -87.6298}
    assert geocoding.reverse(43.65, -79.38)["label"] == "Toronto, Ontario, Canada"
    assert geocoding.reverse(51.5, -0.12) is None  # London: outside US/CA
