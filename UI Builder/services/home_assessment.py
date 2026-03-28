"""
Bundle geocode + dashboard + regional feeds into a single home risk payload for the UI.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from services.apis import aggregate_dashboard
from services.geocode import nominatim_search
from services.regional_tampa import regional_lookup
from services.tampa_db import get_by_zip


def _fl511_total(traffic: dict[str, Any]) -> int:
    layers = traffic.get("layers") or {}
    t = 0
    for v in layers.values():
        c = v.get("count")
        if isinstance(c, int):
            t += c
    return t


def build_risk_card(
    dashboard: dict[str, Any],
    regional: dict[str, Any],
    zip_row: dict[str, Any] | None,
) -> dict[str, Any]:
    th = dashboard.get("threat") or {}
    ev = regional.get("evacuation") or {}
    pw = regional.get("power_outages") or {}
    tr = regional.get("traffic_fl511") or {}
    rivers = regional.get("rivers_usgs_extended") or {}
    sites = (rivers.get("parsed") or {}).get("sites") or {}

    river_bits = []
    for sid, info in list(sites.items())[:6]:
        latest = (info.get("latest") or {})
        gh = latest.get("gage_height_ft")
        q = latest.get("discharge_cfs")
        river_bits.append(f"{sid}: gage {gh} ft, {q} cfs" if gh or q else f"{sid}: (no recent value)")

    card = {
        "threat_score": th.get("score"),
        "threat_tier": th.get("tier"),
        "threat_reasons": th.get("reasons") or [],
        "evacuation_source": ev.get("source"),
        "evacuation_level": ev.get("evac_level") or ev.get("evac_zone"),
        "evacuation_detail": {
            "velocity_mph_band": ev.get("velocity_mph_band"),
            "tide_heights_ft": ev.get("tide_heights_ft"),
            "to_be_evacuated": ev.get("to_be_evacuated"),
            "county_zone_label": ev.get("county") or ev.get("raw", {}).get("COUNTY_ZON"),
        },
        "power_outage_polygons_in_bbox": pw.get("count_in_bbox"),
        "fl511_incident_layers_total": _fl511_total(tr),
        "usgs_river_snapshot": river_bits,
        "zip_reference": (
            {
                "storm_surge_exposure": zip_row.get("storm_surge_exposure"),
                "river_inland_flood_exposure": zip_row.get("river_inland_flood_exposure"),
                "coastal_character": zip_row.get("coastal_character"),
                "fdot_note": zip_row.get("fdot_bridge_evac_note"),
                "county_emergency_url": zip_row.get("county_emergency_url"),
                "planning_notes": zip_row.get("zip_planning_notes"),
            }
            if zip_row
            else None
        ),
    }
    return card


def assess_address(address: str, save_nickname: str | None = None) -> dict[str, Any]:
    address = (address or "").strip()
    if len(address) < 4:
        return {"error": "address too short"}

    zip_only = re.match(r"^\s*(\d{5})(-\d{4})?\s*$", address)
    if zip_only:
        z = zip_only.group(1)
        zip_row = get_by_zip(z)
        if not zip_row:
            return {"error": "ZIP not in Tampa metro database", "matched_zip": z}
        lat, lon = float(zip_row["lat"]), float(zip_row["lon"])
        top = {
            "lat": lat,
            "lon": lon,
            "display_name": f"{zip_row.get('city')}, {zip_row.get('county')} {z} (centroid)",
            "address": {"postcode": z, "city": zip_row.get("city"), "county": zip_row.get("county")},
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_d = pool.submit(aggregate_dashboard, lat, lon, False)
            f_r = pool.submit(regional_lookup, lat, lon)
            dashboard = f_d.result()
            regional = f_r.result()
        risk = build_risk_card(dashboard, regional, zip_row)
        return {
            "query": address,
            "geocode": top,
            "matched_zip": z,
            "zip_database_match": zip_row,
            "dashboard": dashboard,
            "tampa_bay_regional": regional,
            "risk_card": risk,
        }

    geo = nominatim_search(address, limit=1)
    if geo.get("error"):
        return {"error": geo["error"], "nominatim": geo}
    results = geo.get("results") or []
    if not results:
        return {"error": "no geocode results", "nominatim": geo}
    top = results[0]
    lat, lon = top["lat"], top["lon"]
    addr = top.get("address") or {}
    raw_z = ""
    if isinstance(addr, dict) and addr.get("postcode") is not None:
        raw_z = str(addr["postcode"]).strip().split("-")[0].replace(" ", "")
    z = None
    if raw_z.isdigit() and len(raw_z) <= 5:
        z = raw_z.zfill(5)[:5]
    if z and len(z) != 5:
        z = None
    zip_row = get_by_zip(z) if z else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_d = pool.submit(aggregate_dashboard, lat, lon, False)
        f_r = pool.submit(regional_lookup, lat, lon)
        dashboard = f_d.result()
        regional = f_r.result()

    risk = build_risk_card(dashboard, regional, zip_row)
    return {
        "query": address,
        "geocode": top,
        "matched_zip": z,
        "zip_database_match": zip_row,
        "dashboard": dashboard,
        "tampa_bay_regional": regional,
        "risk_card": risk,
    }
