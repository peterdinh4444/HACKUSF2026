"""
Public data sources for Tampa Bay flood / storm context — fetch + aggregate.
"""
from __future__ import annotations

import os
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import requests

from services.aggregate import (
    build_detailed_report,
    build_metrics,
    coops_wind_summary,
    compute_threat_score_v2,
    merge_metric_extensions,
    parse_ndbc_met_txt,
    parse_usgs_iv_json,
)

HTTP_HEADERS = {
    "User-Agent": "HurricaneHub/0.1 (HACKUSF educational prototype; contact: local-dev)",
    "Accept": "application/json",
}

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_FLOOD = "https://flood-api.open-meteo.com/v1/flood"
NHC_CURRENT = "https://www.nhc.noaa.gov/CurrentStorms.json"
OPENFEMA_DECLARATIONS = "https://www.fema.gov/api/open/v1/FemaWebDisasterDeclarations"
NWPS_BASE = "https://api.water.noaa.gov/nwps/v1"
USGS_EPQS = "https://epqs.nationalmap.gov/v1/json"
NOAA_COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NWS_API = "https://api.weather.gov"
USGS_IV = "https://waterservices.usgs.gov/nwis/iv/"

DEFAULT_LAT = 27.9506
DEFAULT_LON = -82.4572
NOAA_STATION_TAMPA = "8726607"
# Tampa Bay — NDBC met (wave height, SST); wind often MM at this buoy
NDBC_STATION_TAMPA_BAY = "42099"
# Hillsborough River @ Tampa; Sweetwater Creek — inland flood context
USGS_SITES_TAMPA = ("02304500", "02306647")


def _get(url: str, params: dict | None = None, headers: dict | None = None) -> tuple[Any, int | None]:
    try:
        r = requests.get(url, params=params, headers=headers or HTTP_HEADERS, timeout=25)
        ct = r.headers.get("content-type", "")
        if "json" in ct.lower():
            return r.json(), r.status_code
        return r.text, r.status_code
    except requests.RequestException as e:
        return ({"error": str(e)}, None)


def _get_text(url: str, params: dict | None = None, headers: dict | None = None) -> tuple[str, int | None]:
    try:
        r = requests.get(url, params=params, headers=headers or HTTP_HEADERS, timeout=25)
        return r.text, r.status_code
    except requests.RequestException as e:
        return (str(e), None)


def catalog_endpoints() -> list[dict[str, Any]]:
    """Public endpoints aggregated by this service (reference for developers)."""
    sites = ",".join(USGS_SITES_TAMPA)
    return [
        {
            "name": "NOAA CO-OPS (water level, wind, air pressure, predictions)",
            "use": "Tide gauge water level MLLW; same station wind (6-min); barometric pressure",
            "base": NOAA_COOPS,
            "example_water_level": f"{NOAA_COOPS}?begin_date=YYYYMMDD&end_date=YYYYMMDD&station={NOAA_STATION_TAMPA}&product=water_level&datum=MLLW&units=english&time_zone=lst_ldt&format=json&application=HurricaneHub",
            "example_wind": f"{NOAA_COOPS}?begin_date=YYYYMMDD&end_date=YYYYMMDD&station={NOAA_STATION_TAMPA}&product=wind&interval=6&units=english&time_zone=lst_ldt&format=json&application=HurricaneHub",
            "station_default": NOAA_STATION_TAMPA,
        },
        {
            "name": "NWS API (grid forecasts + alerts)",
            "use": "Hourly grid for POP/wind; active alerts for lat/lon",
            "base": NWS_API,
            "points": f"{NWS_API}/points/{DEFAULT_LAT},{DEFAULT_LON}",
            "alerts": f"{NWS_API}/alerts/active?point={DEFAULT_LAT},{DEFAULT_LON}",
            "notes": "Must send a descriptive User-Agent.",
        },
        {
            "name": "USGS EPQS (National Map elevation)",
            "use": "Terrain height at a point (flood exposure / surge stacking)",
            "base": USGS_EPQS,
            "example": f"{USGS_EPQS}?x={DEFAULT_LON}&y={DEFAULT_LAT}&units=Feet",
        },
        {
            "name": "USGS NWIS Instantaneous Values",
            "use": "River gage height (ft) + discharge (cfs) — Hillsborough / Sweetwater near Tampa",
            "base": USGS_IV,
            "example": f"{USGS_IV}?format=json&sites={sites}&parameterCd=00065,00060&siteStatus=all",
            "sites": list(USGS_SITES_TAMPA),
        },
        {
            "name": "NDBC (buoy / coastal met)",
            "use": "Significant wave height, sea temp, wind when sensors report",
            "base": "https://www.ndbc.noaa.gov/data/realtime2/",
            "example": f"https://www.ndbc.noaa.gov/data/realtime2/{NDBC_STATION_TAMPA_BAY}.txt",
            "station_default": NDBC_STATION_TAMPA_BAY,
        },
        {
            "name": "Open-Meteo (forecast)",
            "use": "Hourly precip sum, wind gusts — no API key",
            "base": OPEN_METEO,
            "example": f"{OPEN_METEO}?latitude={DEFAULT_LAT}&longitude={DEFAULT_LON}&hourly=precipitation,wind_gusts_10m&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=3",
        },
        {
            "name": "Mapbox Geocoding (optional)",
            "use": "Address → lat/lon for neighborhoods",
            "base": "https://api.mapbox.com/geocoding/v5/mapbox.places/",
            "env": "MAPBOX_ACCESS_TOKEN",
        },
        {
            "name": "NHC CurrentStorms.json",
            "use": "Active Atlantic/Eastern Pacific tropical cyclones (same feed as nhc.noaa.gov)",
            "base": "https://www.nhc.noaa.gov/",
            "example": NHC_CURRENT,
        },
        {
            "name": "Open-Meteo Flood API (GloFAS v4)",
            "use": "Simulated river discharge (~5 km); complements USGS gauges",
            "base": OPEN_METEO_FLOOD,
            "example": f"{OPEN_METEO_FLOOD}?latitude={DEFAULT_LAT}&longitude={DEFAULT_LON}&daily=river_discharge&forecast_days=7&past_days=7",
        },
        {
            "name": "OpenFEMA — Disaster Declarations",
            "use": "Historical FEMA declarations by state (context, not real-time hazard)",
            "base": OPENFEMA_DECLARATIONS,
            "example": f"{OPENFEMA_DECLARATIONS}?$filter=stateCode%20eq%20'FL'&$top=5&$orderby=declarationDate%20desc",
        },
        {
            "name": "NWS ASOS/AWOS latest observation",
            "use": "Ground-truth wind, visibility, pressure (e.g. KTPA for Tampa Intl)",
            "base": f"{NWS_API}/stations/KTPA/observations/latest",
        },
        {
            "name": "NOAA NWPS (National Water Prediction Service)",
            "use": "Official river forecasts + flood categories (replaces legacy AHPS API for many sites)",
            "base": f"{NWPS_BASE}/docs/",
            "example_gauge": f"{NWPS_BASE}/gauges/{{lid}}/stageflow",
            "notes": "Use gauge LID from water.noaa.gov map; requests may be slow — optional client-side.",
        },
        {
            "name": "Hillsborough County — Evacuation Zone (ArcGIS)",
            "use": "Official EVAC_LEVEL A–E polygons for HEAT / Know Your Zone",
            "example": "https://services1.arcgis.com/IbNXlmt2RVVRCZ6M/arcgis/rest/services/EvacuationZone/FeatureServer/0/query (point-in-polygon)",
        },
        {
            "name": "Florida EOC — Evacuation Zones (multi-county)",
            "use": "Pinellas, Pasco, and other counties — same layer used by state EOC apps",
            "example": "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Evacuation_Zones_20230608/FeatureServer/12/query",
        },
        {
            "name": "FDOT — Road Closures / FL511 (ArcGIS)",
            "use": "FHP closures + FL511 crashes, congestion, construction, incidents",
            "base": "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Road_Closures/FeatureServer",
        },
        {
            "name": "FDOT — Florida Power Outages View (ArcGIS)",
            "use": "Aggregated outage polygons (useful regional ‘lights out’ context)",
            "example": "https://services.arcgis.com/3wFbqsFPLeKqOlIK/ArcGIS/rest/services/Florida_Power_Outages_View/FeatureServer/0/query",
        },
    ]


def fetch_noaa_water_level(station: str = NOAA_STATION_TAMPA, days: int = 3) -> dict[str, Any]:
    end = date.today()
    begin = end - timedelta(days=max(1, min(days, 30)))
    params = {
        "begin_date": begin.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "station": station,
        "product": "water_level",
        "datum": "MLLW",
        "units": "english",
        "time_zone": "lst_ldt",
        "format": "json",
        "application": "HurricaneHub",
    }
    data, status = _get(NOAA_COOPS, params=params)
    out: dict[str, Any] = {"source": "NOAA CO-OPS", "station": station, "status": status, "raw": data}
    if isinstance(data, dict) and data.get("data"):
        vals = []
        for row in data["data"]:
            if row.get("v") in (None, "", "-"):
                continue
            try:
                vals.append(float(row["v"]))
            except (TypeError, ValueError):
                continue
        if vals:
            out["summary"] = {
                "latest_ft": round(vals[-1], 3),
                "mean_ft": round(statistics.mean(vals), 3),
                "min_ft": round(min(vals), 3),
                "max_ft": round(max(vals), 3),
                "samples": len(vals),
            }
    return out


def fetch_noaa_wind(station: str = NOAA_STATION_TAMPA) -> dict[str, Any]:
    end = date.today()
    begin = end - timedelta(days=2)
    params = {
        "begin_date": begin.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "station": station,
        "product": "wind",
        "interval": "6",
        "units": "english",
        "time_zone": "lst_ldt",
        "format": "json",
        "application": "HurricaneHub",
    }
    data, status = _get(NOAA_COOPS, params=params)
    out: dict[str, Any] = {"source": "NOAA CO-OPS wind", "station": station, "status": status, "raw": data}
    out["summary"] = coops_wind_summary({"raw": data})
    return out


def fetch_nws_context(lat: float, lon: float) -> dict[str, Any]:
    points, st = _get(f"{NWS_API}/points/{lat},{lon}")
    out: dict[str, Any] = {"source": "NWS", "status": st, "points": points if isinstance(points, dict) else {"raw": points}}
    if not isinstance(points, dict) or "properties" not in points:
        return out
    props = points["properties"]
    forecast_url = props.get("forecast")
    hourly_url = props.get("forecastHourly")
    alerts_url = f"{NWS_API}/alerts/active?point={lat},{lon}"
    fc, _ = _get(forecast_url) if forecast_url else ({}, None)
    hr, _ = _get(hourly_url) if hourly_url else ({}, None)
    al, _ = _get(alerts_url)
    out["forecast"] = fc if isinstance(fc, dict) else {}
    out["hourly"] = hr if isinstance(hr, dict) else {}
    out["alerts"] = al if isinstance(al, dict) else {}
    out["grid_id"] = props.get("gridId")
    out["office"] = props.get("cwa")
    return out


def fetch_usgs_elevation(lat: float, lon: float) -> dict[str, Any]:
    params = {"x": lon, "y": lat, "units": "Feet"}
    data, status = _get(USGS_EPQS, params=params)
    elev = None
    if isinstance(data, dict) and data.get("value") is not None:
        try:
            elev = float(data["value"])
        except (TypeError, ValueError):
            pass
    return {"source": "USGS EPQS", "status": status, "latitude": lat, "longitude": lon, "elevation_ft": elev, "raw": data}


def fetch_usgs_tampa_rivers() -> dict[str, Any]:
    params = {
        "format": "json",
        "sites": ",".join(USGS_SITES_TAMPA),
        "parameterCd": "00065,00060",
        "siteStatus": "all",
    }
    data, status = _get(USGS_IV, params=params)
    parsed = parse_usgs_iv_json(data) if isinstance(data, dict) else {"sites": {}}
    return {
        "source": "USGS NWIS iv",
        "status": status,
        "parsed": parsed,
        "raw": data,
    }


def fetch_ndbc_buoy(station_id: str = NDBC_STATION_TAMPA_BAY) -> dict[str, Any]:
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    text, status = _get_text(url)
    parsed = parse_ndbc_met_txt(text) if status == 200 else {}
    return {"source": "NDBC", "station": station_id, "status": status, "parsed": parsed}


def fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation,wind_gusts_10m,wind_speed_10m",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "forecast_days": 3,
        "timezone": "America/New_York",
    }
    data, status = _get(OPEN_METEO, params=params)
    out: dict[str, Any] = {"source": "Open-Meteo", "status": status, "raw": data}
    if not isinstance(data, dict) or not data.get("hourly"):
        return out
    h = data["hourly"]
    prec = h.get("precipitation") or []
    gust = h.get("wind_gusts_10m") or []
    n24 = min(24, len(prec), len(gust))
    n48 = min(48, len(prec), len(gust))
    p24 = [float(prec[i] or 0) for i in range(n24)]
    p48 = [float(prec[i] or 0) for i in range(n48)]
    g24 = [float(gust[i] or 0) for i in range(n24)]
    g48 = [float(gust[i] or 0) for i in range(n48)]
    out["summary"] = {
        "precip_in_next24h_sum": round(sum(p24), 3),
        "precip_in_next48h_sum": round(sum(p48), 3),
        "max_wind_gust_mph_24h": round(max(g24) if g24 else 0, 1),
        "max_wind_gust_mph_48h": round(max(g48) if g48 else 0, 1),
    }
    return out


def fetch_open_meteo_flood(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "forecast_days": 7,
        "past_days": 7,
    }
    data, status = _get(OPEN_METEO_FLOOD, params=params)
    out: dict[str, Any] = {"source": "Open-Meteo Flood", "status": status, "raw": data}
    if not isinstance(data, dict):
        return out
    daily = data.get("daily") or {}
    dis = daily.get("river_discharge") or []
    vals: list[float] = []
    for x in dis:
        try:
            if x is not None:
                vals.append(float(x))
        except (TypeError, ValueError):
            continue
    if not vals:
        return out
    out["summary"] = {
        "glofas_river_discharge_m3s_latest": round(vals[-1], 3),
        "glofas_river_discharge_m3s_max_7d": round(max(vals), 3),
        "glofas_river_discharge_m3s_min_7d": round(min(vals), 3),
        "glofas_grid_elevation_m": data.get("elevation"),
    }
    return out


def fetch_nhc_current_storms() -> dict[str, Any]:
    data, status = _get(NHC_CURRENT)
    out: dict[str, Any] = {"source": "NHC", "status": status, "raw": data}
    storms: list[Any] = []
    if isinstance(data, dict):
        storms = data.get("activeStorms") or []
    names: list[str] = []
    for s in storms:
        if isinstance(s, dict):
            nm = s.get("name") or s.get("stormName") or s.get("id")
            if nm:
                names.append(str(nm))
    out["summary"] = {
        "nhc_active_storms": len(storms),
        "nhc_named_storms": len(storms),
        "storm_names": names[:12],
        "summary_line": (
            f"{len(storms)} active system(s) in NHC CurrentStorms feed: {', '.join(names[:4])}"
            if storms
            else "No active systems in NHC CurrentStorms.json"
        ),
    }
    return out


def fetch_openfema_fl_recent(top: int = 5) -> dict[str, Any]:
    params = {"$filter": "stateCode eq 'FL'", "$top": str(top), "$orderby": "declarationDate desc"}
    data, status = _get(OPENFEMA_DECLARATIONS, params=params)
    out: dict[str, Any] = {"source": "OpenFEMA", "status": status, "raw": data}
    if not isinstance(data, dict):
        return out
    rows = data.get("FemaWebDisasterDeclarations") or []
    majors: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (r.get("declarationType") or "").strip() == "Major Disaster":
            nm = (r.get("disasterName") or "").strip()
            dt = (r.get("declarationDate") or "")[:10]
            it = (r.get("incidentType") or "").strip()
            majors.append(f"{nm} ({dt}, {it})")
    out["summary"] = {
        "recent_fl_major_disasters": majors[:5],
        "records_returned": len(rows),
    }
    return out


def _quant_to_mph(qv: dict[str, Any] | None) -> float | None:
    if not isinstance(qv, dict) or qv.get("value") is None:
        return None
    try:
        v = float(qv["value"])
    except (TypeError, ValueError):
        return None
    uc = str(qv.get("unitCode") or "")
    if "km_h" in uc:
        return round(v * 0.621371, 1)
    if "m_s" in uc or "m/s" in uc:
        return round(v * 2.23694, 1)
    if "knot" in uc.lower():
        return round(v * 1.15078, 1)
    return round(v, 1)


def fetch_nws_airport_obs(station_id: str = "KTPA") -> dict[str, Any]:
    data, status = _get(f"{NWS_API}/stations/{station_id}/observations/latest")
    out: dict[str, Any] = {
        "source": "NWS observations",
        "station_id": station_id,
        "status": status,
        "raw": data,
    }
    if not isinstance(data, dict):
        return out
    props = data.get("properties") or {}
    vis_mi = None
    vis = props.get("visibility")
    if isinstance(vis, dict) and vis.get("value") is not None:
        try:
            vis_mi = round(float(vis["value"]) / 1609.34, 2)
        except (TypeError, ValueError):
            pass
    pres_mb = None
    bp = props.get("barometricPressure")
    if isinstance(bp, dict) and bp.get("value") is not None:
        try:
            pres_mb = round(float(bp["value"]) / 100.0, 1)
        except (TypeError, ValueError):
            pass
    wdir = None
    wd = props.get("windDirection")
    if isinstance(wd, dict) and wd.get("value") is not None:
        try:
            wdir = float(wd["value"])
        except (TypeError, ValueError):
            wdir = None
    out["summary"] = {
        "station_id": station_id,
        "station_name": props.get("stationName"),
        "obs_time": props.get("timestamp"),
        "text_description": props.get("textDescription"),
        "wind_mph": _quant_to_mph(props.get("windSpeed")),
        "wind_gust_mph": _quant_to_mph(props.get("windGust")),
        "wind_dir_deg": wdir,
        "visibility_mi": vis_mi,
        "pressure_mb": pres_mb,
    }
    return out


def mapbox_forward_geocode(query: str, limit: int = 3) -> dict[str, Any]:
    token = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
    if not token:
        return {"source": "Mapbox", "skipped": True, "reason": "MAPBOX_ACCESS_TOKEN not set"}
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(query)}.json"
    params = {"access_token": token, "limit": limit, "proximity": f"{DEFAULT_LON},{DEFAULT_LAT}"}
    data, status = _get(url, params=params, headers={"User-Agent": HTTP_HEADERS["User-Agent"]})
    return {"source": "Mapbox", "status": status, "raw": data}


def _strip_raw(d: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky raw payloads for default JSON responses."""
    if not isinstance(d, dict):
        return d
    out = {k: v for k, v in d.items() if k != "raw"}
    for k, v in list(out.items()):
        if isinstance(v, dict):
            out[k] = _strip_raw(v)
    return out


def aggregate_dashboard(lat: float | None = None, lon: float | None = None, verbose: bool = False) -> dict[str, Any]:
    lat = lat if lat is not None else DEFAULT_LAT
    lon = lon if lon is not None else DEFAULT_LON

    with ThreadPoolExecutor(max_workers=12) as pool:
        f_epqs = pool.submit(fetch_usgs_elevation, lat, lon)
        f_rivers = pool.submit(fetch_usgs_tampa_rivers)
        f_wl = pool.submit(fetch_noaa_water_level)
        f_wind = pool.submit(fetch_noaa_wind)
        f_ndbc = pool.submit(fetch_ndbc_buoy)
        f_om = pool.submit(fetch_open_meteo, lat, lon)
        f_flood = pool.submit(fetch_open_meteo_flood, lat, lon)
        f_nhc = pool.submit(fetch_nhc_current_storms)
        f_fema = pool.submit(fetch_openfema_fl_recent)
        f_ktpa = pool.submit(fetch_nws_airport_obs, "KTPA")
        f_nws = pool.submit(fetch_nws_context, lat, lon)

        usgs_epqs = f_epqs.result()
        usgs_rivers = f_rivers.result()
        noaa_wl = f_wl.result()
        noaa_wind = f_wind.result()
        ndbc = f_ndbc.result()
        meteo = f_om.result()
        open_meteo_flood = f_flood.result()
        nhc = f_nhc.result()
        openfema = f_fema.result()
        nws_ktpa = f_ktpa.result()
        nws = f_nws.result()

    usgs_parsed = usgs_rivers.get("parsed") or {"sites": {}}
    wind_summ = noaa_wind.get("summary") or coops_wind_summary(noaa_wind)

    metrics = build_metrics(
        lat,
        lon,
        usgs_epqs,
        usgs_parsed,
        noaa_wl,
        wind_summ,
        ndbc,
        meteo,
        nws.get("hourly") or {},
        nws.get("alerts") or {},
    )
    merge_metric_extensions(
        metrics,
        open_meteo_flood=open_meteo_flood,
        nhc=nhc,
        openfema=openfema,
        nws_obs=nws_ktpa,
    )
    threat = compute_threat_score_v2(metrics)
    report = build_detailed_report(metrics, threat)

    sources = {
        "usgs_epqs": usgs_epqs,
        "usgs_rivers": usgs_rivers,
        "noaa_water_level": noaa_wl,
        "noaa_wind": noaa_wind,
        "ndbc": ndbc,
        "open_meteo": meteo,
        "open_meteo_flood": open_meteo_flood,
        "nhc_current_storms": nhc,
        "openfema_fl": openfema,
        "nws_ktpa_obs": nws_ktpa,
        "nws": nws,
    }

    result: dict[str, Any] = {
        "location": {"latitude": lat, "longitude": lon, "label": "Tampa Bay prototype viewport"},
        "metrics": metrics,
        "threat": threat,
        "detailed_report": report,
        "sources": sources if verbose else {k: _strip_raw(v) for k, v in sources.items()},
        "more_apis_reference": _more_apis_reference(),
    }

    if not verbose:
        for k in (
            "usgs_epqs",
            "usgs_rivers",
            "noaa_water_level",
            "noaa_wind",
            "ndbc",
            "open_meteo",
            "open_meteo_flood",
            "nhc_current_storms",
            "openfema_fl",
            "nws_ktpa_obs",
        ):
            if k in result["sources"] and isinstance(result["sources"][k], dict):
                result["sources"][k].pop("raw", None)
        nw = result["sources"].get("nws")
        if isinstance(nw, dict):
            feats = (nw.get("alerts") or {}).get("features") or []
            result["sources"]["nws"] = {
                "office": nw.get("office"),
                "grid_id": nw.get("grid_id"),
                "active_alert_count": len(feats),
                "alert_events_sample": [(f.get("properties") or {}).get("event") for f in feats[:5]],
                "_note": "Full NWS JSON available with ?verbose=1",
            }

    return result


def _more_apis_reference() -> dict[str, Any]:
    """Curated list of additional public feeds useful for a flood/hurricane report (not all wired in)."""
    return {
        "storm_surge_inundation_maps": "https://www.nhc.noaa.gov/nhc_inundation.shtml (GIS/KMZ; regional availability)",
        "spc_convective_outlooks": "https://www.spc.noaa.gov/products/ (text + geojson layers; hail/wind/tornado)",
        "goes_satellite_imagery": "https://www.star.nesdis.noaa.gov/GOES/ (band composites; no single JSON metric)",
        "mrms_radar_mosaics": "https://mrms.ncep.noaa.gov/data/ (GRIB2; third-party tile APIs exist)",
        "usgs_waterwatch": "https://waterwatch.usgs.gov/ (national maps; complements NWIS iv)",
        "fema_nfhl": "National Flood Hazard Layer via ArcGIS Online / fema.gov flood maps (not a simple lat/lon JSON)",
        "noaa_space_weather": "https://services.swpc.noaa.gov/json/ (GNSS/radio outages — indirect for comms resilience)",
        "openstreetmap_overpass": "https://wiki.openstreetmap.org/wiki/Overpass_API (infrastructure / shelter POIs)",
    }
