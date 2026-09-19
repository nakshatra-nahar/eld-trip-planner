"""US state and Canadian province names <-> postal abbreviations.

Pure data with no Django imports so ``scripts/build_places.py`` can reuse it.
"""

from __future__ import annotations

US_STATES: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

CA_PROVINCES: dict[str, str] = {
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB",
    "New Brunswick": "NB", "Newfoundland and Labrador": "NL",
    "Northwest Territories": "NT", "Nova Scotia": "NS", "Nunavut": "NU",
    "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
    "Saskatchewan": "SK", "Yukon": "YT",
}

# Accept a few common spelling variants (accents, older names).
_ALIASES: dict[str, str] = {
    "québec": "QC", "yukon territory": "YT", "newfoundland": "NL",
    "washington, d.c.": "DC", "washington d.c.": "DC",
}

_BY_NAME: dict[str, str] = {
    **{k.lower(): v for k, v in US_STATES.items()},
    **{k.lower(): v for k, v in CA_PROVINCES.items()},
    **_ALIASES,
}
_ABBREVS: frozenset[str] = frozenset(US_STATES.values()) | frozenset(CA_PROVINCES.values())
CA_ABBREVS: frozenset[str] = frozenset(CA_PROVINCES.values())


def region_abbrev(name: str | None) -> str:
    """Return the postal abbreviation for a state/province name (or abbreviation); "" if unknown."""
    if not name:
        return ""
    key = name.strip()
    if key.upper() in _ABBREVS:
        return key.upper()
    return _BY_NAME.get(key.lower(), "")


def country_for_abbrev(abbrev: str) -> str:
    return "Canada" if abbrev in CA_ABBREVS else "United States"


def region_name(abbrev: str) -> str:
    for table in (US_STATES, CA_PROVINCES):
        for name, code in table.items():
            if code == abbrev:
                return name
    return abbrev
