"""Forward geocoding restricted to the US and Canada.

Photon (komoot) is the primary provider because it is fast and typo-tolerant, which
suits autocomplete. Nominatim is the fallback when Photon errors or finds nothing.
Results are normalised to ``GeocodeResult`` dicts (``label``, ``short_label``, ``lat``,
``lon``) and cached in memory.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from .cache import TTLCache
from .errors import UpstreamUnavailable
from .http import Deadline, session
from .places import nearest_place
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

# Internal flag on Photon results (settlement vs address/POI), removed by ``_dedupe``.
_IS_PLACE = "_is_place"


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
    return result


def _photon(q: str, limit: int, deadline: Deadline) -> list[dict[str, Any]]:
    resp = session().get(
        PHOTON_URL,
        params={"q": q, "limit": limit + 4, "bbox": NA_BBOX, "lang": "en"},
        timeout=deadline.timeout(TIMEOUT_S),
    )
    resp.raise_for_status()
    results = [r for r in (_photon_feature(f) for f in resp.json().get("features", [])) if r is not None]
    # Photon ranks POIs named after a city ("St. Louis Lambert International Airport") above the city
    # itself. A query without digits is almost always a city search, so float settlements to the top
    # (stable sort keeps Photon's order within each group).
    if not re.search(r"\d", q):
        results.sort(key=lambda r: not r[_IS_PLACE])
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
    if item.get("addresstype") in {"city", "town", "village", "hamlet", "municipality"} or (not street_line and not name):
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
    """Drop repeats of the same label within ~5 mi (Photon often returns a city's node and its boundary)."""
    kept: list[dict[str, Any]] = []
    for r in results:
        r.pop(_IS_PLACE, None)
        label = r["short_label"].lower()
        if not any(
            k["short_label"].lower() == label and abs(k["lat"] - r["lat"]) < 0.08 and abs(k["lon"] - r["lon"]) < 0.08
            for k in kept
        ):
            kept.append(r)
    return kept[:limit]


def geocode(q: str, limit: int = DEFAULT_LIMIT, deadline: Deadline | None = None) -> list[dict[str, Any]]:
    """Return up to ``limit`` US/CA matches for ``q``.

    Raises ``UpstreamUnavailable`` only when every provider failed; an empty list means
    the providers answered but found nothing.
    """
    q = _normalise_query(q)
    if len(q) < MIN_QUERY_LEN:
        return []
    key = (q.lower(), limit)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    deadline = deadline or Deadline(None)
    errors: list[str] = []
    results: list[dict[str, Any]] | None = None
    for name, provider in (("photon", _photon), ("nominatim", _nominatim)):
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
