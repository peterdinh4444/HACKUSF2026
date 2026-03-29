"""
Tampa Bay regional infrastructure: FDOT ArcGIS (FL511), county evacuation GIS,
statewide power outage view, extended USGS gauges.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Point buffer around the assessed home for “nearby” FDOT / FL511 features (~7.5 mi)
TRAFFIC_NEAR_RADIUS_M_DEFAULT = 12_000

FDOT_TRAFFIC_LAYERS: tuple[tuple[int, str, str], ...] = (
    (0, "fhp_closures", "FHP — road / lane closure"),
    (1, "fhp_crashes", "FHP — crash"),
    (2, "fhp_brush_fires", "FHP — brush fire"),
    (3, "fhp_other_incidents", "FHP — other incident"),
    (4, "fl511_crashes", "FL511 — crash"),
    (5, "fl511_congestion", "FL511 — congestion"),
    (6, "fl511_construction", "FL511 — construction"),
    (7, "fl511_other", "FL511 — other"),
)
FHP_TRAFFIC_FIELDS = "LOCATION,COUNTY,TYPEEVENT,REMARKS,DATESTR,TIMESTR,URGENCY"
FL511_TRAFFIC_FIELDS = "NAME,DESCRIPT,COUNTY,HIGHWAY,SEVERITY,TYPE,UPDATED"

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


def arcgis_point_query(
    base_query_url: str,
    lat: float,
    lon: float,
    *,
    distance_m: float | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    if distance_m is not None and distance_m > 0:
        params["distance"] = str(int(distance_m))
        params["units"] = "esriSRUnit_Meter"
    data, status = _ag_get(base_query_url, params)
    return {"status": status, "data": data}


def _arcgis_error(data: Any) -> str | None:
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)
        return str(err)
    return None


def _feature_area_sqft(attrs: dict[str, Any]) -> float:
    """Prefer Hillsborough Shape__Area (sq ft); else statewide Shape__Area (deg²) — still comparable within one query."""
    for key in ("Shape__Area", "Shape_STAr", "Shape_Ar_1"):
        v = attrs.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return float("inf")


def _pick_tightest_feature(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not features:
        return None
    if len(features) == 1:
        return features[0]
    scored = sorted(
        features,
        key=lambda f: _feature_area_sqft(f.get("attributes") or {}),
    )
    return scored[0]


def evacuation_for_point(lat: float, lon: float) -> dict[str, Any]:
    """
    Prefer Hillsborough official layer; else statewide FL EOC zones.
    Uses a small-radius buffer if the geocoded point sits just outside polygon boundaries.
    """
    hb_meta: dict[str, Any] = {"url": HILLSBOROUGH_EVAC, "attempts": []}
    st_meta: dict[str, Any] = {"url": FL_EVAC_ZONES, "attempts": []}

    def run_hillsborough(distance_m: float | None, label: str) -> list[dict[str, Any]] | None:
        q = arcgis_point_query(HILLSBOROUGH_EVAC, lat, lon, distance_m=distance_m)
        data = q.get("data")
        hb_meta["attempts"].append(
            {
                "mode": label,
                "http_status": q.get("status"),
                "arcgis_error": _arcgis_error(data),
                "feature_count": len((data or {}).get("features") or []) if isinstance(data, dict) else 0,
            }
        )
        if not isinstance(data, dict):
            return None
        feats = data.get("features")
        return feats if isinstance(feats, list) else None

    feats = run_hillsborough(None, "intersect") or []
    match_method = "intersect"
    if not feats:
        feats = run_hillsborough(100, "buffer_100m") or []
        match_method = "buffer_100m"
    if not feats:
        feats = run_hillsborough(250, "buffer_250m") or []
        match_method = "buffer_250m"

    picked = _pick_tightest_feature(feats)
    if picked:
        attr = picked.get("attributes") or {}
        return {
            "source": "hillsborough_county_evacuation_zone",
            "match_method": match_method,
            "evac_level": attr.get("EVAC_LEVEL"),
            "velocity_mph_band": attr.get("VELOCITY"),
            "tide_heights_ft": attr.get("TIDE_HTS"),
            "evac_color": attr.get("EVAC_COLOR"),
            "to_be_evacuated": attr.get("TO_BE_EVAC"),
            "layer_last_update_epoch_ms": attr.get("LASTUPDATE"),
            "raw": attr,
            "gis": {"hillsborough": hb_meta, "statewide": st_meta},
        }

    def run_statewide(distance_m: float | None, label: str) -> list[dict[str, Any]] | None:
        q = arcgis_point_query(FL_EVAC_ZONES, lat, lon, distance_m=distance_m)
        data = q.get("data")
        st_meta["attempts"].append(
            {
                "mode": label,
                "http_status": q.get("status"),
                "arcgis_error": _arcgis_error(data),
                "feature_count": len((data or {}).get("features") or []) if isinstance(data, dict) else 0,
            }
        )
        if not isinstance(data, dict):
            return None
        feats2 = data.get("features")
        return feats2 if isinstance(feats2, list) else None

    sfeats = run_statewide(None, "intersect") or []
    st_method = "intersect"
    if not sfeats:
        sfeats = run_statewide(100, "buffer_100m") or []
        st_method = "buffer_100m"
    if not sfeats:
        sfeats = run_statewide(250, "buffer_250m") or []
        st_method = "buffer_250m"

    picked2 = _pick_tightest_feature(sfeats)
    if picked2:
        attr = picked2.get("attributes") or {}
        return {
            "source": "florida_eoc_evacuation_zones_layer",
            "match_method": st_method,
            "county": attr.get("County_Nam") or attr.get("COUNTY_ZON"),
            "evac_zone": attr.get("EZone") or attr.get("COUNTY_ZON"),
            "statewide_zone_pop_est": attr.get("EST_ZONE_P") or attr.get("SUM_POP_20"),
            "statewide_edit_date": attr.get("Edit_Date"),
            "statewide_region": attr.get("Region"),
            "raw": attr,
            "gis": {"hillsborough": hb_meta, "statewide": st_meta},
        }

    return {
        "source": None,
        "match_method": None,
        "note": "No evacuation polygon matched within 250 m of this point — try the official county map or move the pin slightly.",
        "gis": {"hillsborough": hb_meta, "statewide": st_meta},
    }


def _bbox_envelope() -> str:
    xmin, ymin, xmax, ymax = TAMPA_BAY_VIEWBOX
    return f"{xmin},{ymin},{xmax},{ymax}"


def _slim_traffic_fhp(attrs: dict[str, Any], layer_key: str, layer_label: str) -> dict[str, Any]:
    loc = (attrs.get("LOCATION") or attrs.get("TYPEEVENT") or "").strip()
    cty = (attrs.get("COUNTY") or "").strip()
    rem = (attrs.get("REMARKS") or "").strip()
    ds = (attrs.get("DATESTR") or "").strip()
    ts = (attrs.get("TIMESTR") or "").strip()
    when = f"{ds} {ts}".strip() or "—"
    urg = (attrs.get("URGENCY") or "").strip()
    title = loc or layer_label
    detail_bits = [x for x in (rem, urg) if x]
    return {
        "layer_key": layer_key,
        "category": layer_label,
        "title": title,
        "road_or_highway": loc or "—",
        "county": cty or "—",
        "when": when,
        "detail": " · ".join(detail_bits) if detail_bits else "—",
        "threat_tags": [layer_label.split("—")[-1].strip().lower()],
    }


def _slim_traffic_fl511(attrs: dict[str, Any], layer_key: str, layer_label: str) -> dict[str, Any]:
    name = (attrs.get("NAME") or attrs.get("DESCRIPT") or "").strip()
    hw = (attrs.get("HIGHWAY") or "").strip()
    cty = (attrs.get("COUNTY") or "").strip()
    sev = (attrs.get("SEVERITY") or "").strip()
    typ = (attrs.get("TYPE") or "").strip()
    upd = attrs.get("UPDATED")
    when = str(upd).strip() if upd not in (None, "") else "—"
    title = name or hw or layer_label
    detail_bits = [x for x in (sev, typ) if x]
    tags = []
    if "crash" in layer_key:
        tags.append("crash")
    if "closure" in layer_key or "congestion" in layer_key:
        tags.append(layer_key.replace("fl511_", "").replace("_", " "))
    return {
        "layer_key": layer_key,
        "category": layer_label,
        "title": title,
        "road_or_highway": hw or "—",
        "county": cty or "—",
        "when": when,
        "detail": " · ".join(detail_bits) if detail_bits else "—",
        "threat_tags": tags or [layer_label.split("—")[-1].strip().lower()],
    }


def _query_traffic_near_layer(
    layer_id: int,
    layer_key: str,
    layer_label: str,
    lat: float,
    lon: float,
    radius_m: int,
    max_features: int,
) -> dict[str, Any]:
    fields = FHP_TRAFFIC_FIELDS if layer_id < 4 else FL511_TRAFFIC_FIELDS
    url = f"{FDOT_ROAD_CLOSURES}/{layer_id}/query"
    params: dict[str, Any] = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": str(int(radius_m)),
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "where": "1=1",
        "outFields": fields,
        "returnGeometry": "false",
        "resultRecordCount": str(max(1, min(max_features, 25))),
        "f": "json",
    }
    data, status = _ag_get(url, params)
    slim: list[dict[str, Any]] = []
    err = _arcgis_error(data)
    if isinstance(data, dict) and not err:
        for f in (data.get("features") or [])[:max_features]:
            attrs = f.get("attributes") if isinstance(f, dict) else None
            if not isinstance(attrs, dict):
                continue
            if layer_id < 4:
                slim.append(_slim_traffic_fhp(attrs, layer_key, layer_label))
            else:
                slim.append(_slim_traffic_fl511(attrs, layer_key, layer_label))
    return {
        "layer_id": layer_id,
        "layer_key": layer_key,
        "http_status": status,
        "arcgis_error": err,
        "items": slim,
    }


def traffic_near_point(
    lat: float,
    lon: float,
    *,
    radius_m: int = TRAFFIC_NEAR_RADIUS_M_DEFAULT,
    per_layer_max: int = 10,
) -> dict[str, Any]:
    """
    FDOT / FL511 features within a meter radius of the home pin (not the whole Tampa bbox).
    Prioritize scanning official closures and crashes for evacuation awareness.
    """
    radius_m = max(500, min(int(radius_m), 50_000))
    per_layer_max = max(1, min(per_layer_max, 25))
    totals: dict[str, int] = {}
    by_layer: dict[str, list[dict[str, Any]]] = {}
    highways: set[str] = set()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {
            pool.submit(
                _query_traffic_near_layer,
                lid,
                key,
                label,
                lat,
                lon,
                radius_m,
                per_layer_max,
            ): key
            for lid, key, label in FDOT_TRAFFIC_LAYERS
        }
        for fut in as_completed(futs):
            block = fut.result()
            key = block["layer_key"]
            items = block.get("items") or []
            by_layer[key] = items
            totals[key] = len(items)
            for it in items:
                rw = (it.get("road_or_highway") or "").strip()
                if rw and rw != "—" and len(rw) > 2:
                    highways.add(rw)

    priority = [k for _, k, _ in FDOT_TRAFFIC_LAYERS]
    flat: list[dict[str, Any]] = []
    for k in priority:
        flat.extend(by_layer.get(k) or [])

    return {
        "source": "FDOT ArcGIS Road_Closures (point buffer)",
        "radius_m": radius_m,
        "radius_mi_rounded": round(radius_m / 1609.34, 1),
        "totals_by_layer": totals,
        "total_nearby": sum(totals.values()),
        "highways_or_roads_mentioned": sorted(highways)[:24],
        "by_layer": by_layer,
        "incidents_chronological": flat[:40],
        "disclaimer": "Live GIS snapshot near your pin — verify on FL511 and county EM before you drive.",
    }


def fl511_tampa_bay_summary() -> dict[str, Any]:
    """
    FDOT Road_Closures FeatureServer — all public layers (FHP + FL511).
    Layer ids: 0 FHP closures, 1 FHP crashes, 2 FHP brush fires, 3 FHP other;
    4–7 FL511 crashes / congestion / construction / other.
    For evacuation routing, layer 0 (official closures) is the highest-signal feed.
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
    layer_pairs = [
        (0, "fhp_closures"),
        (1, "fhp_crashes"),
        (2, "fhp_brush_fires"),
        (3, "fhp_other_incidents"),
        (4, "fl511_crashes"),
        (5, "fl511_congestion"),
        (6, "fl511_construction"),
        (7, "fl511_other"),
    ]
    out: dict[str, Any] = {
        "source": "FDOT ArcGIS Road_Closures",
        "feature_server": FDOT_ROAD_CLOSURES,
        "bbox": TAMPA_BAY_VIEWBOX,
        "layers": {},
    }
    for idx, label in layer_pairs:
        url = f"{FDOT_ROAD_CLOSURES}/{idx}/query"
        params = dict(common)
        params["where"] = "1=1"
        params["returnCountOnly"] = "true"
        data, st = _ag_get(url, params)
        cnt = None
        if isinstance(data, dict) and "count" in data:
            cnt = data.get("count")
        out["layers"][label] = {"layer_id": idx, "status": st, "count": cnt}
    # FHP road/lane closures — strongest signal for “can I use this evac route?”
    sp0 = dict(common)
    sp0["where"] = "1=1"
    sp0["outFields"] = "LOCATION,COUNTY,TYPEEVENT,REMARKS,DATESTR,TIMESTR"
    sp0["resultRecordCount"] = "5"
    sp0["outSR"] = "4326"
    d0, st0 = _ag_get(f"{FDOT_ROAD_CLOSURES}/0/query", sp0)
    f0 = (d0 or {}).get("features") if isinstance(d0, dict) else []
    rows0 = [(f.get("attributes") or {}) for f in f0]
    out["sample_fhp_closures_in_bbox"] = {"status": st0, "count": len(rows0), "rows": rows0}
    # FL511 “other” incidents — human-readable traffic events
    sp = dict(common)
    sp["where"] = "1=1"
    sp["outFields"] = "NAME,DESCRIPT,COUNTY,HIGHWAY,SEVERITY,TYPE,UPDATED"
    sp["resultRecordCount"] = "5"
    sp["outSR"] = "4326"
    data, st = _ag_get(f"{FDOT_ROAD_CLOSURES}/7/query", sp)
    feats = (data or {}).get("features") if isinstance(data, dict) else []
    samples = [(f.get("attributes") or {}) for f in feats]
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
        "traffic_near_home": traffic_near_point(lat, lon),
        "power_outages": fl_power_outages_tampa_bay(),
        "rivers_usgs_extended": _fetch_usgs_iv_sites(USGS_TAMPA_EXTENDED),
        "references": {
            "swfwmd_edp": "https://www.swfwmd.state.fl.us/resources/data-maps/hydrologic-data (Environmental Data Portal — station downloads)",
            "waze_ccp": "https://www.waze.com/wazeforcities (Connected Citizens Program — requires partnership)",
            "teco_outage_portal": "https://account.tecoenergy.com/Outage/Outagemap (consumer map; may differ from public GIS feeds)",
        },
    }
