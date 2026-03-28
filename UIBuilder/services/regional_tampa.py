"""
Tampa Bay regional infrastructure: FDOT ArcGIS (FL511), county evacuation GIS,
statewide power outage view, extended USGS gauges.
"""
from __future__ import annotations

from typing import Any

import requests

from services.aggregate import parse_usgs_iv_json

HTTP_HEADERS = {
    "User-Agent": "HurricaneHub/0.1 (HACKUSF educational prototype; contact: local-dev)",
    "Accept": "application/json",
}
USGS_IV = "https://waterservices.usgs.gov/nwis/iv/"

# ArcGIS REST — verified public FeatureServers
HILLSBOROUGH_EVAC = (
    "https://services1.arcgis.com/IbNXlmt2RVVRCZ6M/arcgis/rest/services/EvacuationZone/FeatureServer/0/query"
)
FL_EVAC_ZONES = (
    "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Evacuation_Zones_20230608/FeatureServer/12/query"
)
FDOT_ROAD_CLOSURES = "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Road_Closures/FeatureServer"
FL_POWER_OUTAGES = (
    "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Florida_Power_Outages_View/FeatureServer/0/query"
)

# Tampa Bay rough bounding box (lon_min, lat_min, lon_max, lat_max) for regional filters
TAMPA_BAY_VIEWBOX = (-82.9, 27.5, -82.1, 28.2)

# USGS: Hillsborough River, Sweetwater, Tampa Bypass Canal @ S-162, below S-161
USGS_TAMPA_EXTENDED = ("02304500", "02306647", "02301778", "02301771")


def _ag_get(url: str, params: dict[str, Any]) -> tuple[Any, int | None]:
    try:
        r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=25)
        if "json" in (r.headers.get("content-type") or "").lower():
            return r.json(), r.status_code
        return r.text, r.status_code
    except requests.RequestException as e:
        return {"error": str(e)}, None


def arcgis_point_query(base_query_url: str, lat: float, lon: float) -> dict[str, Any]:
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    data, status = _ag_get(base_query_url, params)
    return {"status": status, "data": data}


def evacuation_for_point(lat: float, lon: float) -> dict[str, Any]:
    """Prefer Hillsborough County official layer; else statewide FL EOC zones (Pinellas/Pasco/etc.)."""
    h = arcgis_point_query(HILLSBOROUGH_EVAC, lat, lon)
    feats = (h.get("data") or {}).get("features") if isinstance(h.get("data"), dict) else None
    if feats:
        attr = feats[0].get("attributes") or {}
        return {
            "source": "hillsborough_county_evacuation_zone",
            "evac_level": attr.get("EVAC_LEVEL"),
            "velocity_mph_band": attr.get("VELOCITY"),
            "tide_heights_ft": attr.get("TIDE_HTS"),
            "evac_color": attr.get("EVAC_COLOR"),
            "to_be_evacuated": attr.get("TO_BE_EVAC"),
            "raw": attr,
        }
    s = arcgis_point_query(FL_EVAC_ZONES, lat, lon)
    feats2 = (s.get("data") or {}).get("features") if isinstance(s.get("data"), dict) else None
    if feats2:
        attr = feats2[0].get("attributes") or {}
        return {
            "source": "florida_eoc_evacuation_zones_layer",
            "county": attr.get("County_Nam") or attr.get("COUNTY_ZON"),
            "evac_zone": attr.get("EZone") or attr.get("COUNTY_ZON"),
            "raw": attr,
        }
    return {"source": None, "note": "No evacuation polygon matched at this coordinate."}


def _bbox_envelope() -> str:
    xmin, ymin, xmax, ymax = TAMPA_BAY_VIEWBOX
    return f"{xmin},{ymin},{xmax},{ymax}"


def fl511_tampa_bay_summary() -> dict[str, Any]:
    """
    Aggregate FDOT Road_Closures FeatureServer layers that carry FL511 traffic events.
    Layer index reference: 0=FHP closures, 4-511 crashes/congestion/construction/other.
    """
    env = _bbox_envelope()
    common = {
        "geometry": env,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "false",
        "f": "json",
    }
    layers = [0, 4, 5, 6, 7]
    names = ["fhp_closures", "fl511_crashes", "fl511_congestion", "fl511_construction", "fl511_other"]
    out: dict[str, Any] = {"source": "FDOT ArcGIS Road_Closures", "bbox": TAMPA_BAY_VIEWBOX, "layers": {}}
    for idx, label in zip(layers, names):
        url = f"{FDOT_ROAD_CLOSURES}/{idx}/query"
        params = dict(common)
        params["where"] = "1=1"
        params["returnCountOnly"] = "true"
        data, st = _ag_get(url, params)
        cnt = None
        if isinstance(data, dict) and "count" in data:
            cnt = data.get("count")
        out["layers"][label] = {"status": st, "count": cnt}
    # sample a few human-readable incidents from FL511 "other" if present
    sample_url = f"{FDOT_ROAD_CLOSURES}/7/query"
    sp = dict(common)
    sp["where"] = "1=1"
    sp["outFields"] = "NAME,DESCRIPT,COUNTY,HIGHWAY,SEVERITY,TYPE,UPDATED"
    sp["resultRecordCount"] = "5"
    sp["outSR"] = "4326"
    data, st = _ag_get(sample_url, sp)
    feats = (data or {}).get("features") if isinstance(data, dict) else []
    samples = []
    for f in feats:
        samples.append((f.get("attributes") or {}))
    out["sample_incidents_fl511_other"] = {"status": st, "count": len(samples), "rows": samples}
    return out


def fl_power_outages_tampa_bay() -> dict[str, Any]:
    env = _bbox_envelope()
    params = {
        "where": "1=1",
        "geometry": env,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    full, st = _ag_get(FL_POWER_OUTAGES, params)
    feats = (full or {}).get("features") if isinstance(full, dict) else []
    slim = []
    for f in feats[:25]:
        slim.append((f.get("attributes") or {}))
    params2 = dict(params)
    params2["returnCountOnly"] = "true"
    params2.pop("outFields", None)
    cnt_data, _ = _ag_get(FL_POWER_OUTAGES, params2)
    count = (cnt_data or {}).get("count") if isinstance(cnt_data, dict) else None
    return {
        "source": "Florida_Power_Outages_View (aggregated public outage polygons)",
        "status": st,
        "count_in_bbox": count,
        "features_in_bbox_returned": len(feats),
        "sample_attributes": slim,
    }


def _fetch_usgs_iv_sites(site_ids: tuple[str, ...]) -> dict[str, Any]:
    params = {
        "format": "json",
        "sites": ",".join(site_ids),
        "parameterCd": "00065,00060",
        "siteStatus": "all",
    }
    data, status = _ag_get(USGS_IV, params)
    parsed = parse_usgs_iv_json(data) if isinstance(data, dict) else {"sites": {}}
    return {"source": "USGS NWIS iv (Tampa-focused)", "status": status, "parsed": parsed, "raw": data}


def regional_lookup(lat: float, lon: float) -> dict[str, Any]:
    return {
        "evacuation": evacuation_for_point(lat, lon),
        "traffic_fl511": fl511_tampa_bay_summary(),
        "power_outages": fl_power_outages_tampa_bay(),
        "rivers_usgs_extended": _fetch_usgs_iv_sites(USGS_TAMPA_EXTENDED),
        "references": {
            "swfwmd_edp": "https://www.swfwmd.state.fl.us/resources/data-maps/hydrologic-data (Environmental Data Portal — station downloads)",
            "waze_ccp": "https://www.waze.com/wazeforcities (Connected Citizens Program — requires partnership)",
            "teco_outage_portal": "https://account.tecoenergy.com/Outage/Outagemap (consumer map; may differ from public GIS feeds)",
        },
    }
