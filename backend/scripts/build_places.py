#!/usr/bin/env python3
"""Build the offline US + Canada nearest-place dataset used for log-sheet remarks.

Downloads GeoNames ``cities500.zip`` (all populated places with population >= 500)
and ``admin1CodesASCII.txt``, keeps US and CA rows, maps each row's admin1 code to a
postal abbreviation and writes ``trips/data/places.csv.gz`` with the columns:

    name,admin,lat,lon,population,tz

``tz`` is the GeoNames IANA time zone ("America/Chicago"), used for local stop times.

US admin1 codes already are postal abbreviations ("IL"); Canadian ones are numeric
("08") and are mapped via admin1CodesASCII ("CA.08" -> "Ontario") -> "ON".

Usage (from ``backend/``):  uv run python scripts/build_places.py [--dataset cities1000]
GeoNames data is CC BY 4.0 (https://www.geonames.org/).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import zipfile
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from trips.services.regions import region_abbrev  # noqa: E402

BASE_URL = "https://download.geonames.org/export/dump/"
OUTPUT = BACKEND_DIR / "trips" / "data" / "places.csv.gz"
USER_AGENT = "eld-trip-planner/1.0 (dataset build script)"
COUNTRIES = {"US", "CA"}
# Populated-place feature codes to keep. Drops PPLX (city sections / neighbourhoods),
# PPLH (historical) and PPLQ (abandoned), which make poor remark locations.
FEATURE_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLG", "PPLS", "PPLF", "PPLL", "PPLR"}


def download(name: str) -> bytes:
    url = BASE_URL + name
    print(f"Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    resp.raise_for_status()
    return resp.content


def canadian_admin1(admin1_text: str) -> dict[str, str]:
    """Map Canadian numeric admin1 codes ("08") to province abbreviations ("ON")."""
    mapping: dict[str, str] = {}
    for line in admin1_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].startswith("CA."):
            continue
        code = parts[0].split(".", 1)[1]
        abbrev = region_abbrev(parts[1]) or region_abbrev(parts[2])
        if abbrev:
            mapping[code] = abbrev
    return mapping


def build(dataset: str) -> list[tuple[str, str, float, float, int, str]]:
    ca_codes = canadian_admin1(download("admin1CodesASCII.txt").decode("utf-8"))
    archive = zipfile.ZipFile(io.BytesIO(download(f"{dataset}.zip")))
    rows: list[tuple[str, str, float, float, int, str]] = []
    with archive.open(f"{dataset}.txt") as fh:
        for raw in io.TextIOWrapper(fh, encoding="utf-8"):
            f = raw.rstrip("\n").split("\t")
            country, feature_code, admin1 = f[8], f[7], f[10]
            if country not in COUNTRIES or feature_code not in FEATURE_CODES:
                continue
            abbrev = admin1 if country == "US" else ca_codes.get(admin1, "")
            if not region_abbrev(abbrev):  # skips territories / unknown codes
                continue
            rows.append((f[1], abbrev, round(float(f[4]), 4), round(float(f[5]), 4), int(f[14] or 0), f[17]))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="cities500", choices=["cities500", "cities1000", "cities5000"])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    rows = build(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["name", "admin", "lat", "lon", "population", "tz"])
    writer.writerows(rows)
    # mtime=0 keeps the output byte-identical across rebuilds of the same data.
    with open(args.output, "wb") as out, gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    size_kb = args.output.stat().st_size / 1024
    print(f"Wrote {len(rows):,} places to {args.output} ({size_kb:,.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
