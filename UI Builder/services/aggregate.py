"""
Build unified metrics + threat score from raw source payloads.
"""
from __future__ import annotations

import statistics
from typing import Any


def parse_usgs_iv_json(data: Any) -> dict[str, Any]:
    """Latest instantaneous values per site/parameter from USGS WaterML JSON."""
    out: dict[str, Any] = {"sites": {}}
    if not isinstance(data, dict):
        return out
    val = data.get("value") or {}
    for ts in val.get("timeSeries") or []:
        name = ts.get("name") or ""
        parts = name.split(":")
        if len(parts) < 3:
            continue
        site_id = parts[1]
        param = parts[2]
        site_name = (ts.get("sourceInfo") or {}).get("siteName") or ""
        values = ts.get("values") or []
        if not values:
            continue
        vals = values[0].get("value") or []
        if not vals:
            continue
        last = vals[-1]
        raw_v = last.get("value")
        try:
            v = float(raw_v)
        except (TypeError, ValueError):
            continue
        if site_id not in out["sites"]:
            out["sites"][site_id] = {"name": site_name, "latest": {}}
        if param == "00065":
            out["sites"][site_id]["latest"]["gage_height_ft"] = round(v, 2)
        elif param == "00060":
            out["sites"][site_id]["latest"]["discharge_cfs"] = round(v, 2)
        out["sites"][site_id]["latest"]["obs_time"] = last.get("dateTime")
    return out


def parse_ndbc_met_txt(text: str) -> dict[str, Any]:
    """
    Parse NDBC standard meteorological .txt (realtime2).
    First non-comment line is typically the most recent observation.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return {}
    parts = lines[0].split()
    if len(parts) < 14:
        return {"parse_error": True, "line": lines[0][:120]}

    def fnum(i: int) -> float | None:
        if i >= len(parts):
            return None
        if parts[i] in ("MM", "99.00"):
            return None
        try:
            return float(parts[i])
        except ValueError:
            return None

    # YY MM DD hh mm WDIR WSPD GST WVHT ...
    wdir = fnum(5)
    wspd_ms = fnum(6)
    gst_ms = fnum(7)
    wvht_m = fnum(8)
    dpd_s = fnum(9)
    wtmp_c = fnum(13)

    wspd_mph = wspd_ms * 2.23694 if wspd_ms is not None else None
    gst_mph = gst_ms * 2.23694 if gst_ms is not None else None
    wvht_ft = wvht_m * 3.28084 if wvht_m is not None else None

    return {
        "observation_time_utc": " ".join(parts[0:5]),
        "wind_dir_deg": wdir,
        "wind_speed_mph": round(wspd_mph, 1) if wspd_mph is not None else None,
        "wind_gust_mph": round(gst_mph, 1) if gst_mph is not None else None,
        "sig_wave_height_ft": round(wvht_ft, 2) if wvht_ft is not None else None,
        "dominant_wave_period_s": dpd_s,
        "sea_water_temp_c": wtmp_c,
    }


def coops_wind_summary(wind_payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize NOAA CO-OPS wind JSON (knots in 's' and 'g' per English units)."""
    raw = wind_payload.get("raw")
    if not isinstance(raw, dict) or not raw.get("data"):
        return {}
    rows = raw["data"]
    speeds: list[float] = []
    gusts: list[float] = []
    for row in rows:
        try:
            if row.get("s") not in (None, ""):
                speeds.append(float(row["s"]))
            if row.get("g") not in (None, ""):
                gusts.append(float(row["g"]))
        except (TypeError, ValueError):
            continue
    if not speeds and not gusts:
        return {}
    # CO-OPS English: wind speed / gust typically in knots
    out: dict[str, Any] = {}
    if speeds:
        out["latest_wind_kt"] = round(speeds[-1], 2)
        out["mean_wind_kt"] = round(statistics.mean(speeds), 2)
        out["max_wind_kt"] = round(max(speeds), 2)
    if gusts:
        out["max_gust_kt"] = round(max(gusts), 2)
    return out


def nws_hourly_metrics(hourly_fc: dict[str, Any]) -> dict[str, Any]:
    props = hourly_fc.get("properties") or {}
    periods = props.get("periods") or []
    if not periods:
        return {}
    next24 = periods[:24]
    pops: list[float] = []
    wind_speeds: list[float] = []
    wind_gusts: list[float] = []
    for p in next24:
        pop = p.get("probabilityOfPrecipitation")
        if isinstance(pop, dict) and pop.get("value") is not None:
            try:
                pops.append(float(pop["value"]))
            except (TypeError, ValueError):
                pass
        ws = p.get("windSpeed")
        if isinstance(ws, str) and " to " in ws:
            try:
                a, b = ws.split(" to ")
                wind_speeds.append((float(a) + float(b)) / 2)
            except (ValueError, TypeError):
                pass
        elif isinstance(ws, (int, float)):
            wind_speeds.append(float(ws))
        wg = p.get("windGust")
        if isinstance(wg, (int, float)):
            wind_gusts.append(float(wg))
    m: dict[str, Any] = {}
    if pops:
        m["max_precip_probability_pct_24h"] = round(max(pops), 0)
        m["mean_precip_probability_pct_24h"] = round(statistics.mean(pops), 1)
    if wind_speeds:
        m["mean_sustained_wind_mph_24h"] = round(statistics.mean(wind_speeds), 1)
        m["max_sustained_wind_mph_24h"] = round(max(wind_speeds), 1)
    if wind_gusts:
        m["max_wind_gust_mph_24h_nws"] = round(max(wind_gusts), 1)
    return m


FLOOD_EVENT_KEYWORDS = (
    "flood",
    "flash flood",
    "coastal flood",
    "lakeshore flood",
    "river",
    "areal flood",
    "hydrologic",
    "dam",
    "debris flow",
)


def nws_flood_alert_metrics(alerts: dict[str, Any]) -> dict[str, Any]:
    """Subset of NWS alerts likely related to flooding / hydrology."""
    feats = alerts.get("features") or []
    flood_feats: list[dict[str, Any]] = []
    for f in feats:
        ev = ((f.get("properties") or {}).get("event") or "").lower()
        if any(k in ev for k in FLOOD_EVENT_KEYWORDS):
            flood_feats.append(f)
    events = list({(ff.get("properties") or {}).get("event") or "" for ff in flood_feats})
    sev = []
    for ff in flood_feats:
        s = ((ff.get("properties") or {}).get("severity") or "").lower()
        if s:
            sev.append(s)
    return {
        "flood_related_count": len(flood_feats),
        "flood_events": events[:15],
        "flood_has_severe": any(s in ("severe", "extreme") for s in sev),
    }


def nws_alert_metrics(alerts: dict[str, Any]) -> dict[str, Any]:
    feats = alerts.get("features") or []
    severities: list[str] = []
    events: list[str] = []
    for f in feats:
        p = f.get("properties") or {}
        sev = (p.get("severity") or "").lower()
        if sev:
            severities.append(sev)
        ev = p.get("event") or ""
        if ev:
            events.append(ev)
    high = any(s in ("extreme", "severe") for s in severities)
    moderate = any(s == "moderate" for s in severities)
    return {
        "active_count": len(feats),
        "events": events[:12],
        "has_high_severity": high,
        "has_moderate_or_higher": moderate or high,
    }


def build_metrics(
    lat: float,
    lon: float,
    usgs_epqs: dict[str, Any],
    usgs_iv_parsed: dict[str, Any],
    noaa_water: dict[str, Any],
    noaa_wind_summary: dict[str, Any],
    ndbc: dict[str, Any],
    open_meteo: dict[str, Any],
    nws_hourly: dict[str, Any],
    nws_alerts: dict[str, Any],
) -> dict[str, Any]:
    """Single flat-ish metrics dict for clients + scoring."""
    m: dict[str, Any] = {
        "query": {"latitude": lat, "longitude": lon},
        "terrain": {},
        "rivers": {},
        "coastal": {},
        "marine_buoy": {},
        "atmosphere_forecast": {},
        "official_short_term": {},
        "alerts": {},
    }

    if usgs_epqs.get("elevation_ft") is not None:
        m["terrain"]["ground_elevation_ft"] = round(float(usgs_epqs["elevation_ft"]), 2)

    m["rivers"] = usgs_iv_parsed.get("sites") or {}

    ns = noaa_water.get("summary") or {}
    if ns:
        m["coastal"]["coops_station"] = noaa_water.get("station")
        m["coastal"]["water_level_ft_mllw_latest"] = ns.get("latest_ft")
        m["coastal"]["water_level_ft_mllw_mean_window"] = ns.get("mean_ft")
        m["coastal"]["water_level_ft_mllw_min_window"] = ns.get("min_ft")
        m["coastal"]["water_level_ft_mllw_max_window"] = ns.get("max_ft")
        if ns.get("latest_ft") is not None and ns.get("mean_ft") is not None:
            m["coastal"]["water_level_anomaly_ft"] = round(
                float(ns["latest_ft"]) - float(ns["mean_ft"]), 3
            )

    for k, v in noaa_wind_summary.items():
        m["coastal"][f"coops_{k}"] = v

    if isinstance(ndbc, dict):
        bp = ndbc.get("parsed") or {}
        for k, v in bp.items():
            if v is not None and k != "parse_error":
                m["marine_buoy"][k] = v
        sid = ndbc.get("station")
        if sid:
            m["marine_buoy"]["station_id"] = sid

    om = open_meteo.get("summary") or {}
    if om:
        m["atmosphere_forecast"]["precip_in_next_24h"] = om.get("precip_in_next24h_sum")
        m["atmosphere_forecast"]["precip_in_next_48h"] = om.get("precip_in_next48h_sum")
        m["atmosphere_forecast"]["max_wind_gust_mph_24h_open_meteo"] = om.get("max_wind_gust_mph_24h")
        m["atmosphere_forecast"]["max_wind_gust_mph_48h"] = om.get("max_wind_gust_mph_48h")

    hm = nws_hourly_metrics(nws_hourly)
    if hm:
        m["official_short_term"].update(hm)

    am = nws_alert_metrics(nws_alerts)
    if am:
        m["alerts"].update(am)
    m["alerts"]["flood"] = nws_flood_alert_metrics(nws_alerts)

    return m


def merge_metric_extensions(
    m: dict[str, Any],
    *,
    open_meteo_flood: dict[str, Any] | None = None,
    nhc: dict[str, Any] | None = None,
    openfema: dict[str, Any] | None = None,
    nws_obs: dict[str, Any] | None = None,
) -> None:
    if open_meteo_flood and open_meteo_flood.get("summary"):
        m["hydrology_model"] = open_meteo_flood["summary"]
    if nhc and nhc.get("summary"):
        m["tropical"] = nhc["summary"]
    if openfema and openfema.get("summary"):
        m["historical_context"] = openfema["summary"]
    if nws_obs and nws_obs.get("summary"):
        m["surface_obs"] = nws_obs["summary"]


def build_detailed_report(metrics: dict[str, Any], threat: dict[str, Any]) -> str:
    """Human-readable narrative for demos / PDFs — not operational guidance."""
    lines: list[str] = []
    q = metrics.get("query") or {}
    lines.append(
        f"Hurricane Hub — situation summary for {q.get('latitude', '?')}, {q.get('longitude', '?')} "
        f"(WGS84). Threat index {threat.get('score')} / 100 ({threat.get('tier')})."
    )
    lines.append("")

    terr = metrics.get("terrain") or {}
    if terr.get("ground_elevation_ft") is not None:
        lines.append(
            f"Terrain: USGS National Map elevation at the point is about {terr['ground_elevation_ft']} ft NAVD88 (EPQS). "
            "Lower elevations are more exposed to surge + rainfall ponding."
        )

    coast = metrics.get("coastal") or {}
    if coast.get("water_level_ft_mllw_latest") is not None:
        lines.append(
            f"Coastal water level (NOAA CO-OPS): latest ~{coast['water_level_ft_mllw_latest']} ft MLLW; "
            f"anomaly vs recent window mean ~{coast.get('water_level_anomaly_ft', 'n/a')} ft."
        )

    buoy = metrics.get("marine_buoy") or {}
    if buoy.get("sig_wave_height_ft") is not None:
        lines.append(
            f"Marine (NDBC {buoy.get('station_id', '')}): significant wave height ~{buoy['sig_wave_height_ft']} ft "
            f"(nearshore sea state; not a surge forecast)."
        )

    atm = metrics.get("atmosphere_forecast") or {}
    if atm:
        lines.append(
            f"Rain/wind (Open-Meteo hourly blend): ~{atm.get('precip_in_next_24h', '?')} in precip next 24h, "
            f"~{atm.get('precip_in_next_48h', '?')} in / 48h; max modeled gust ~{atm.get('max_wind_gust_mph_24h_open_meteo', '?')} mph /24h."
        )

    hyd = metrics.get("hydrology_model") or {}
    if hyd.get("glofas_river_discharge_m3s_latest") is not None:
        lines.append(
            f"Hydrology model (GloFAS via Open-Meteo Flood API): river discharge ~{hyd['glofas_river_discharge_m3s_latest']} m³/s latest; "
            f"7d max in window ~{hyd.get('glofas_river_discharge_m3s_max_7d')} m³/s — coarse 5 km river routing, not a USGS gauge."
        )

    trop = metrics.get("tropical") or {}
    if trop.get("nhc_named_storms"):
        lines.append(
            f"NHC Atlantic/Pacific: {trop['nhc_named_storms']} named system(s) in CurrentStorms feed — "
            f"check nhc.noaa.gov for marine hazards."
        )
    elif trop.get("nhc_active_storms", 0) == 0:
        lines.append("NHC: no systems listed in CurrentStorms.json at fetch time (does not rule out future development).")

    al = metrics.get("alerts") or {}
    if al.get("active_count"):
        lines.append(
            f"NWS alerts for the point: {al['active_count']} active; "
            f"flood-tagged subset ~{al.get('flood', {}).get('flood_related_count', 0)}."
        )

    hist = metrics.get("historical_context") or {}
    if hist.get("recent_fl_major_disasters"):
        lines.append(
            "OpenFEMA (historical): recent Florida major-disaster examples include: "
            + "; ".join(hist["recent_fl_major_disasters"][:3])
            + " — context only, not current risk."
        )

    surf = metrics.get("surface_obs") or {}
    if surf.get("station_id"):
        lines.append(
            f"Latest surface obs ({surf['station_id']}): wind {surf.get('wind_mph', '?')} mph "
            f"gust {surf.get('wind_gust_mph', '?')} mph; vis {surf.get('visibility_mi', '?')} mi — ASOS/AWOS, good ground truth for wind."
        )

    lines.append("")
    lines.append(threat.get("disclaimer", ""))
    return "\n".join(lines)


def compute_threat_score_v2(metrics: dict[str, Any]) -> dict[str, Any]:
    """
    Weighted 0–100 heuristic from aggregated metrics. Includes per-component breakdown.
    Not for operational use.
    """
    components: list[dict[str, Any]] = []
    score = 0.0

    al = metrics.get("alerts") or {}
    flood = al.get("flood") or {}
    if flood.get("flood_has_severe") or (flood.get("flood_related_count") or 0) >= 1:
        fc = float(flood.get("flood_related_count") or 0)
        fb = min(18.0, 8.0 + fc * 2.0)
        if flood.get("flood_has_severe"):
            fb = max(fb, 16.0)
        fb = min(18.0, fb)
        components.append(
            {"id": "flood_products", "points": round(fb, 1), "detail": f"NWS flood/hydro-related alerts (~{int(fc)})"}
        )
        score += fb

    ac = int(al.get("active_count") or 0)
    if al.get("has_high_severity"):
        components.append({"id": "alerts_severe", "points": 32.0, "detail": "NWS: severe/extreme severity active"})
        score += 32.0
    elif ac > 0:
        evs = al.get("events") or []
        boost = 22.0 if any(
            any(
                k in (e or "").lower()
                for k in ("hurricane", "tropical", "storm", "tornado", "surge", "wind", "extreme")
            )
            for e in evs
        ) else 12.0
        components.append({"id": "alerts_active", "points": boost, "detail": f"{ac} active alert(s)"})
        score += boost

    atm = metrics.get("atmosphere_forecast") or {}
    rain24 = float(atm.get("precip_in_next_24h") or 0)
    rain48 = float(atm.get("precip_in_next_48h") or 0)
    pr = min(24.0, rain24 * 7.0 + rain48 * 2.0)
    if pr > 0:
        components.append({"id": "rain_accumulation", "points": round(pr, 1), "detail": f"Open-Meteo: ~{rain24:.2f} in /24h, ~{rain48:.2f} in /48h"})
        score += pr

    gust_om = float(atm.get("max_wind_gust_mph_24h_open_meteo") or 0)
    gust_nws = float(metrics.get("official_short_term", {}).get("max_wind_gust_mph_24h_nws") or 0)
    gust_surf = float(metrics.get("surface_obs", {}).get("wind_gust_mph") or 0)
    gust = max(gust_om, gust_nws, gust_surf)
    gw = min(22.0, gust * 0.38)
    if gw > 0:
        components.append(
            {
                "id": "wind_gusts",
                "points": round(gw, 1),
                "detail": f"Max gust ~{gust:.0f} mph (models + NWS hourly + ASOS if reported)",
            }
        )
        score += gw

    trop = metrics.get("tropical") or {}
    n_named = int(trop.get("nhc_named_storms") or 0)
    if n_named > 0:
        tb = min(22.0, 8.0 + n_named * 6.0)
        components.append({"id": "nhc_active_systems", "points": tb, "detail": trop.get("summary_line", "NHC active systems")})
        score += tb

    coast = metrics.get("coastal") or {}
    anom = coast.get("water_level_anomaly_ft")
    if anom is not None:
        aw = min(14.0, abs(float(anom)) * 5.0)
        if aw > 0.5:
            components.append(
                {"id": "tide_anomaly", "points": round(aw, 1), "detail": f"CO-OPS water level vs window mean: {float(anom):+.2f} ft"}
            )
            score += aw

    buoy = metrics.get("marine_buoy") or {}
    wv = buoy.get("sig_wave_height_ft")
    if wv is not None:
        ww = min(10.0, max(0.0, (float(wv) - 2.0) * 2.5))
        if ww > 0.5:
            components.append({"id": "sea_state", "points": round(ww, 1), "detail": f"NDBC sig. wave height ~{float(wv):.1f} ft"})
            score += ww

    el = metrics.get("terrain", {}).get("ground_elevation_ft")
    if el is not None:
        ef = float(el)
        if ef < 5:
            components.append({"id": "low_elevation", "points": 12.0, "detail": f"USGS EPQS elevation {ef:.1f} ft — high surge/rain exposure"})
            score += 12.0
        elif ef < 15:
            components.append({"id": "moderate_elevation", "points": 6.0, "detail": f"USGS EPQS elevation {ef:.1f} ft"})
            score += 6.0

    score = max(0.0, min(100.0, score))
    tier = "low"
    if score >= 70:
        tier = "extreme"
    elif score >= 45:
        tier = "high"
    elif score >= 25:
        tier = "elevated"

    comps = sorted(components, key=lambda c: -c["points"])
    return {
        "score": round(score, 1),
        "tier": tier,
        "components": comps,
        "reasons": [c["detail"] for c in comps[:10]],
        "disclaimer": "Heuristic index from public feeds — not a forecast of flooding. Follow NWS/TBW and local emergency managers.",
    }
