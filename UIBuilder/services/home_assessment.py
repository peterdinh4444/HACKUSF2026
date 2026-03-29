"""
Bundle geocode + dashboard + regional feeds into a single home risk payload for the UI.
"""
from __future__ import annotations

import re
from typing import Any

from services.geo_bundle_cache import get_or_build_dashboard_regional_pair
from services.geocode import nominatim_search
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

    fl511_preview: list[str] = []
    fhp_block = tr.get("sample_fhp_closures_in_bbox") or {}
    for row in (fhp_block.get("rows") or [])[:3]:
        if not isinstance(row, dict):
            continue
        loc = (row.get("LOCATION") or row.get("TYPEEVENT") or "").strip()
        if loc:
            cty = (row.get("COUNTY") or "").strip()
            fl511_preview.append(f"[FHP closure] {loc}" + (f" ({cty})" if cty else ""))
    sample_block = tr.get("sample_incidents_fl511_other") or {}
    for row in (sample_block.get("rows") or [])[:4]:
        if not isinstance(row, dict):
            continue
        title = (row.get("NAME") or row.get("DESCRIPT") or row.get("HIGHWAY") or "").strip()
        if title:
            cty = (row.get("COUNTY") or "").strip()
            fl511_preview.append(f"{title}" + (f" ({cty})" if cty else ""))

    card = {
        "threat_score": th.get("score"),
        "threat_tier": th.get("tier"),
        "threat_reasons": th.get("reasons") or [],
        "evacuation_source": ev.get("source"),
        "evacuation_level": ev.get("evac_level") or ev.get("evac_zone"),
        "evacuation_match_method": ev.get("match_method"),
        "evacuation_color": ev.get("evac_color"),
        "evacuation_gis": ev.get("gis"),
        "evacuation_note": ev.get("note"),
        "evacuation_detail": {
            "velocity_mph_band": ev.get("velocity_mph_band"),
            "tide_heights_ft": ev.get("tide_heights_ft"),
            "to_be_evacuated": ev.get("to_be_evacuated"),
            "county_zone_label": ev.get("county") or (ev.get("raw") or {}).get("COUNTY_ZON"),
            "statewide_zone_pop_est": ev.get("statewide_zone_pop_est"),
            "statewide_edit_date": ev.get("statewide_edit_date"),
            "statewide_region": ev.get("statewide_region"),
            "layer_last_update_epoch_ms": ev.get("layer_last_update_epoch_ms"),
        },
        "power_outage_polygons_in_bbox": pw.get("count_in_bbox"),
        "fl511_incident_layers_total": _fl511_total(tr),
        "fl511_headline_preview": fl511_preview,
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
        dashboard, regional = get_or_build_dashboard_regional_pair(lat, lon, verbose=False)
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

    dashboard, regional = get_or_build_dashboard_regional_pair(lat, lon, verbose=False)

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


def assess_coordinates(
    lat: float,
    lon: float,
    *,
    label: str | None = None,
    zip_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Same bundle as assess_address but for known coordinates (no geocoder).
    Optional zip_row if you already matched the metro database.
    """
    top: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "display_name": label or f"{lat:.4f}°, {lon:.4f}°",
        "address": {},
    }
    dashboard, regional = get_or_build_dashboard_regional_pair(lat, lon, verbose=False)
    risk = build_risk_card(dashboard, regional, zip_row)
    mz = None
    if zip_row and isinstance(zip_row.get("zip"), str):
        mz = zip_row["zip"]
    return {
        "query": None,
        "geocode": top,
        "matched_zip": mz,
        "zip_database_match": zip_row,
        "dashboard": dashboard,
        "tampa_bay_regional": regional,
        "risk_card": risk,
    }


def compact_home_assessment(full: dict[str, Any]) -> dict[str, Any]:
    """
    Slim JSON for /api/assessment/home?compact=1 — scores and summaries without full dashboard trees.
    """
    if full.get("error"):
        return full
    dash = full.get("dashboard") or {}
    met = dash.get("metrics") or {}
    th = dash.get("threat") or {}
    reg = full.get("tampa_bay_regional") or {}
    ev = reg.get("evacuation") or {}
    tn = reg.get("traffic_near_home") or {}
    zr = full.get("zip_database_match")
    zip_slim = None
    if isinstance(zr, dict):
        zip_slim = {
            k: zr.get(k)
            for k in ("zip", "city", "county", "lat", "lon", "storm_surge_exposure", "river_inland_flood_exposure")
            if zr.get(k) is not None
        }
    return {
        "query": full.get("query"),
        "geocode": full.get("geocode"),
        "matched_zip": full.get("matched_zip"),
        "zip_database_match": zip_slim,
        "risk_scores": {
            "model": th.get("model"),
            "score": th.get("score"),
            "tier": th.get("tier"),
            "tds_inner_sum_ws2": th.get("tds_inner_sum_ws2"),
            "zone_multiplier_Z": th.get("zone_multiplier_Z"),
            "zone_letter": th.get("zone_letter"),
            "zone_explanation": th.get("zone_explanation"),
            "subscores": th.get("subscores"),
            "components": th.get("components"),
            "reasons": th.get("reasons"),
            "disclaimer": th.get("disclaimer"),
        },
        "risk_card": full.get("risk_card"),
        "evacuation": {
            "source": ev.get("source"),
            "zone": ev.get("evac_level") or ev.get("evac_zone"),
            "match_method": ev.get("match_method"),
            "note": ev.get("note"),
        },
        "traffic_near": {
            "total_nearby": tn.get("total_nearby"),
            "radius_mi": tn.get("radius_mi_rounded"),
        },
        "conditions_snapshot": {
            "nws_alerts_active": (met.get("alerts") or {}).get("active_count"),
            "coastal_water_anomaly_ft": (met.get("coastal") or {}).get("water_level_anomaly_ft"),
            "rain_next_48h_in": (met.get("atmosphere_forecast") or {}).get("precip_in_next_48h"),
        },
    }
