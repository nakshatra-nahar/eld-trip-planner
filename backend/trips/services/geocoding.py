"""Forward geocoding restricted to the US and Canada.

Photon (komoot) is the primary provider because it is fast and typo-tolerant, which
suits autocomplete. Nominatim is the fallback when Photon errors or finds nothing, for
one-shot lookups only: its usage policy forbids autocomplete and allows 1 request/s.
Results are normalised to ``GeocodeResult`` dicts (``label``, ``short_label``, ``lat``,
``lon``) and cached in memory.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import requests

from .cache import TTLCache
from .errors import UpstreamUnavailable
from .http import Deadline, session
from .places import get_index, haversine_miles, nearest_place
from .regions import country_for_abbrev, region_abbrev, region_name

log = logging.getLogger(__name__)

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NA_BBOX = "-170,15,-50,72"  # lon_min, lat_min, lon_max, lat_max: all of US + CA
COUNTRIES = {"US", "CA"}
TIMEOUT_S = 8.0
DEFAULT_LIMIT = 6
MIN_QUERY_LEN = 2

_cache: TTLCache[list[dict[str, Any]]] = TTLCache(maxsize=2048, ttl=24 * 3600)

# Photon "type" values that denote a settlement rather than an address or POI.
_SETTLEMENT_TYPES = {"city", "town", "village", "hamlet", "locality", "district"}
# The subset that is a city or town proper (not a county, neighbourhood or locality).
_TOWN_TYPES = {"city", "town", "village", "hamlet"}

# Internal keys on Photon results, removed by ``_dedupe``: place vs address/POI, the
# place's state/province abbreviation, its name, and whether it is a city or town.
_IS_PLACE = "_is_place"
_ABBREV = "_abbrev"
_NAME = "_name"
_IS_TOWN = "_is_town"
_SAME_PLACE_MILES = 15.0  # a dataset place with the same name this close is the same place
_DUPLICATE_MILES = 22.0  # ~35 km: a city's node and its county/boundary often share a label

# Abbreviations spelled out before matching names: "St. Louis" == "Saint Louis".
_WORD_ALIASES = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}


def _join(*parts: str | None) -> str:
    """Join non-empty parts with ", ", dropping consecutive duplicates."""
    out: list[str] = []
    for p in parts:
        p = (p or "").strip()
        if p and (not out or out[-1].lower() != p.lower()):
            out.append(p)
    return ", ".join(out)


def _result(label: str, short_label: str, lat: float, lon: float) -> dict[str, Any]:
    return {"label": label, "short_label": short_label, "lat": round(lat, 6), "lon": round(lon, 6)}


def _normalise_query(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip()


def normalise_name(name: str) -> str:
    """Matching key for place names: "St. Louis" and "Saint-Louis" -> "saint louis"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", " ", plain).split()
    return " ".join(_WORD_ALIASES.get(w, w) for w in words)


# ---------------------------------------------------------------- Photon


def _photon_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if (props.get("countrycode") or "").upper() not in COUNTRIES or len(coords) != 2:
        return None
    kind = props.get("type")
    if kind in {"country"}:
        return None
    abbrev = region_abbrev(props.get("state"))
    state_full = region_name(abbrev) if abbrev else (props.get("state") or "")
    country = props.get("country") or country_for_abbrev(abbrev)
    name = props.get("name") or ""
    street_line = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    city = props.get("city") or props.get("town") or props.get("village") or ""

    if kind == "state":
        short = name or state_full
        city_part = ""
    elif props.get("osm_key") == "place" or (kind in _SETTLEMENT_TYPES and not city):
        short = _join(name, abbrev)
        city_part = ""
    else:
        # Address, street or POI: lead with the most specific bit, then the town.
        city_part = city or props.get("district") or props.get("locality") or props.get("county") or ""
        # A POI named after its town (e.g. "Joliet" station) is identified by its address.
        if name in (street_line, city_part):
            name = ""
        lead = name or street_line
        short = _join(lead, city_part, abbrev)

    label = _join(
        name if name != street_line else "",
        street_line,
        city_part if city_part != name else "",
        state_full if state_full != name else "",
        country,
    )
    result = _result(label or short, short or label, float(coords[1]), float(coords[0]))
    result[_IS_PLACE] = kind == "state" or props.get("osm_key") == "place"
    result[_ABBREV] = abbrev
    result[_NAME] = props.get("name") or ""
    result[_IS_TOWN] = props.get("osm_key") == "place" and kind in _TOWN_TYPES
    return result


def _population(r: dict[str, Any]) -> int:
    """Population of a town result: the largest same-named place in the offline dataset
    within a few miles (Photon has no population), else 0. GeoNames adds "City" to some
    names that OpenStreetMap leaves off ("New York City" is OSM's "New York")."""
    key = normalise_name(r[_NAME])
    names = {key, f"{key} city"}
    nearby = get_index().within(r["lat"], r["lon"], _SAME_PLACE_MILES)
    return max((p.population for p, _ in nearby if normalise_name(p.name) in names), default=0)


def _rank_places(q: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order a city search. Places come first; among them, those in a state named in the
    query ("Dallas, GA"), then cities/towns whose name starts with the query ("St. Lou" ->
    Saint Louis, MO before the JeffVanderLou neighbourhood), then larger towns first ("Chic"
    -> Chicago before Chico). Addresses and POIs keep Photon's order after the places."""
    head, sep, tail = q.partition(",")
    wanted = region_abbrev(tail.strip()) if sep else ""
    prefix = normalise_name(head)

    def key(item: tuple[int, dict[str, Any]]) -> tuple:
        i, r = item
        if not r[_IS_PLACE]:
            return (1, 0, 0, 0, i)
        is_match = r[_IS_TOWN] and normalise_name(r[_NAME]).startswith(prefix)
        population = _population(r) if r[_IS_TOWN] else 0
        return (0, bool(wanted) and r[_ABBREV] != wanted, not is_match, -population, i)

    return [r for _, r in sorted(enumerate(results), key=key)]


def _photon(q: str, limit: int, deadline: Deadline) -> list[dict[str, Any]]:
    resp = session().get(
        PHOTON_URL,
        params={"q": q, "limit": limit + 4, "bbox": NA_BBOX, "lang": "en"},
        timeout=deadline.timeout(TIMEOUT_S),
    )
    resp.raise_for_status()
    results = [r for r in (_photon_feature(f) for f in resp.json().get("features", [])) if r is not None]
    # Photon ranks POIs named after a city ("St. Louis Lambert International Airport") above the city
    # itself, and small towns above big cities ("Chic" -> Chico, CA first). A query without digits is
    # almost always a city search, so re-rank it.
    if not re.search(r"\d", q):
        results = _rank_places(q, results)
    return results


# ---------------------------------------------------------------- Nominatim


def _nominatim_item(item: dict[str, Any]) -> dict[str, Any] | None:
    addr = item.get("address") or {}
    if (addr.get("country_code") or "").upper() not in COUNTRIES:
        return None
    iso = addr.get("ISO3166-2-lvl4") or ""
    abbrev = iso.split("-", 1)[1] if "-" in iso else region_abbrev(addr.get("state"))
    city = next(
        (addr[k] for k in ("city", "town", "village", "hamlet", "municipality", "suburb") if addr.get(k)),
        "",
    )
    street_line = " ".join(p for p in (addr.get("house_number"), addr.get("road")) if p)
    name = item.get("name") or ""
    settlement = item.get("addresstype") in {"city", "town", "village", "hamlet", "municipality"}
    if settlement or (not street_line and not name):
        short = _join(name or city, abbrev)
    elif item.get("addresstype") == "state":
        short = name or addr.get("state", "")
    else:
        short = _join(name if name and name != street_line else street_line, city, abbrev)
    label = item.get("display_name") or short
    return _result(label, short, float(item["lat"]), float(item["lon"]))


def _nominatim(q: str, limit: int, deadline: Deadline) -> list[dict[str, Any]]:
    resp = session().get(
        NOMINATIM_URL,
        params={"q": q, "format": "jsonv2", "countrycodes": "us,ca", "addressdetails": 1, "limit": limit},
        timeout=deadline.timeout(TIMEOUT_S),
    )
    resp.raise_for_status()
    return [r for r in (_nominatim_item(i) for i in resp.json()) if r is not None]


# ---------------------------------------------------------------- public API


def _dedupe(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Drop repeats of the same label within ~35 km: Photon often returns a city's node plus
    its boundary or its namesake county ("Los Angeles, CA" twice)."""
    kept: list[dict[str, Any]] = []
    for r in results:
        for internal in (_IS_PLACE, _ABBREV, _NAME, _IS_TOWN):
            r.pop(internal, None)
        label = r["short_label"].lower()
        if not any(
            k["short_label"].lower() == label
            and haversine_miles(k["lat"], k["lon"], r["lat"], r["lon"]) <= _DUPLICATE_MILES
            for k in kept
        ):
            kept.append(r)
    return kept[:limit]


def geocode(
    q: str, limit: int = DEFAULT_LIMIT, deadline: Deadline | None = None, allow_fallback: bool = True
) -> list[dict[str, Any]]:
    """Return up to ``limit`` US/CA matches for ``q``.

    ``allow_fallback=False`` (autocomplete) uses Photon only. Raises ``UpstreamUnavailable``
    only when every provider tried failed; an empty list means they answered but found nothing.
    """
    q = _normalise_query(q)
    if len(q) < MIN_QUERY_LEN:
        return []
    key = (q.lower(), limit, allow_fallback)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    deadline = deadline or Deadline(None)
    errors: list[str] = []
    results: list[dict[str, Any]] | None = None
    providers = [("photon", _photon), ("nominatim", _nominatim)][: 2 if allow_fallback else 1]
    for name, provider in providers:
        if deadline.expired:
            break
        try:
            found = _dedupe(provider(q, limit, deadline), limit)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            log.warning("geocoder %s failed for %r: %s", name, q, exc)
            errors.append(name)
            continue
        results = found
        if found:
            break  # otherwise fall through to the next provider

    if results is None:
        raise UpstreamUnavailable(f"Geocoding service unavailable ({', '.join(errors) or 'timeout'}).")
    if results or not errors:  # never cache a "not found" caused by a failing provider
        _cache.set(key, results)
    return results


def geocode_one(q: str, deadline: Deadline | None = None) -> dict[str, Any] | None:
    results = geocode(q, limit=1, deadline=deadline)
    return results[0] if results else None


REVERSE_MAX_MILES = 150.0


def reverse(lat: float, lon: float) -> dict[str, Any] | None:
    """Offline reverse geocode: the nearest US/CA place, keeping the caller's coordinates."""
    found = nearest_place(lat, lon)
    if found is None:
        return None
    name, abbrev, dist = found
    if dist > REVERSE_MAX_MILES:
        return None
    return _result(_join(name, region_name(abbrev), country_for_abbrev(abbrev)), f"{name}, {abbrev}", lat, lon)


def clear_cache() -> None:
    _cache.clear()
