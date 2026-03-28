#!/usr/bin/env python3
"""Generate data/tampa_metro_zips.csv with planning metadata (heuristics, not parcel-level)."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "tampa_metro_zips.csv"
OUT = ROOT / "data" / "tampa_metro_zips.csv"

HILLS_URL = "https://www.hcfl.gov/residents/public-safety/emergency-management/find-evacuation-information"
PIN_URL = "https://www.pinellascounty.org/emergency/knowyourzone.htm"
PAS_URL = "https://www.pascocountyfl.net/342/Emergency-Management"
FL511 = "https://www.fl511.com"
SWFWMD = "https://www.swfwmd.state.fl.us/resources/data-maps/hydrologic-data"

HIGH_SURGE = {
    "Apollo Beach",
    "Ruskin",
    "Sun City Center",
    "Gibsonton",
    "Hudson",
    "New Port Richey",
    "Port Richey",
    "Trinity",
    "Clearwater",
    "Dunedin",
    "Tarpon Springs",
    "St. Petersburg",
}
BRIDGE_CORRIDOR = {
    "33607",
    "33609",
    "33615",
    "33634",
    "33635",
    "33755",
    "33756",
    "33759",
    "33760",
    "33761",
    "33762",
    "33763",
    "33764",
    "33765",
    "34652",
    "34653",
    "34654",
    "34668",
}


def surge_tier(city: str, county: str, lat: float, lon: float) -> str:
    if city in HIGH_SURGE or county == "Pinellas":
        return "high"
    if county == "Pasco" and city in ("Hudson", "New Port Richey", "Port Richey", "Trinity"):
        return "high"
    if city in ("Apollo Beach", "Ruskin", "Sun City Center", "Gibsonton"):
        return "high"
    if county == "Hillsborough" and lat < 27.88 and lon < -82.42:
        return "high"
    if county == "Hillsborough" and lon < -82.52:
        return "moderate"
    if county == "Pasco" and lon < -82.65:
        return "moderate"
    return "low"


def river_tier(city: str, county: str, lat: float) -> str:
    if city in ("Lithia", "Thonotosassa", "Dover", "Zephyrhills", "Dade City", "Lacoochee"):
        return "high"
    if city in ("Riverview", "Plant City", "Wesley Chapel", "Land O Lakes"):
        return "moderate"
    if county == "Pinellas":
        return "low"
    return "moderate"


def coastal_class(city: str, county: str, lat: float, lon: float) -> str:
    if county == "Pinellas":
        return "peninsula_barrier_mix"
    if city in ("Apollo Beach", "Ruskin", "Gibsonton", "Hudson", "New Port Richey", "Port Richey"):
        return "open_bay_or_gulf_fringe"
    if county == "Hillsborough" and lon < -82.52:
        return "bay_shore"
    if county == "Pasco" and lon < -82.65:
        return "gulf_coastal"
    return "inland"


def fdot_note(z: str, city: str, county: str) -> str:
    if z in BRIDGE_CORRIDOR:
        return "FDOT 511: monitor Howard Frankland / Gandy / Courtney Campbell / bay crossings — use FL511 ArcGIS + app."
    if county == "Pinellas":
        return "Pinellas: multiple causeways; bridge wind closures common — check FL511 before evacuating."
    return "Regional: check FL511 for closures; I-4 / I-75 corridors often used for inland evac."


def county_urls(county: str) -> tuple[str, str]:
    if county == "Hillsborough":
        return HILLS_URL, "Hillsborough EM / HEAT"
    if county == "Pinellas":
        return PIN_URL, "Pinellas Know Your Zone"
    return PAS_URL, "Pasco Emergency Management"


def main() -> None:
    rows_in = []
    seen_zip: set[str] = set()
    with SRC.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        fieldnames = list(r.fieldnames or [])
        for row in r:
            zz = row["zip"].strip().zfill(5)
            if zz in seen_zip:
                continue
            seen_zip.add(zz)
            rows_in.append(row)

    out_fields = [
        "zip",
        "city",
        "county",
        "lat",
        "lon",
        "storm_surge_exposure",
        "river_inland_flood_exposure",
        "coastal_character",
        "fdot_bridge_evac_note",
        "county_emergency_url",
        "county_emergency_label",
        "swfwmd_data_portal_url",
        "fl511_url",
        "zip_planning_notes",
    ]

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for row in rows_in:
            z = row["zip"].strip().zfill(5)
            lat = float(row["lat"])
            lon = float(row["lon"])
            city = row["city"].strip()
            county = row["county"].strip()
            cu, cl = county_urls(county)
            st = surge_tier(city, county, lat, lon)
            rt = river_tier(city, county, lat)
            cc = coastal_class(city, county, lat, lon)
            notes = (
                f"Heuristic ZIP profile (not parcel-level): surge exposure {st}; river/pluvial signal {rt}. "
                f"Always confirm evacuation level with official GIS (HEAT / Know Your Zone) for your exact address."
            )
            w.writerow(
                {
                    "zip": z,
                    "city": city,
                    "county": county,
                    "lat": lat,
                    "lon": lon,
                    "storm_surge_exposure": st,
                    "river_inland_flood_exposure": rt,
                    "coastal_character": cc,
                    "fdot_bridge_evac_note": fdot_note(z, city, county),
                    "county_emergency_url": cu,
                    "county_emergency_label": cl,
                    "swfwmd_data_portal_url": SWFWMD,
                    "fl511_url": FL511,
                    "zip_planning_notes": notes,
                }
            )

    print("Wrote", len(rows_in), "rows to", OUT)


if __name__ == "__main__":
    main()
