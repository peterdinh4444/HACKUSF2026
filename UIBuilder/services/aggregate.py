"""
Build unified metrics + threat score from raw source payloads.
"""
from __future__ import annotations

import math
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
    model = threat.get("model") or "heuristic"
    lines.append(
        f"Hurricane Hub — situation summary for {q.get('latitude', '?')}, {q.get('longitude', '?')} "
        f"(WGS84). Threat index {threat.get('score')} / 100 ({threat.get('tier')}); model {model}."
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


def _sigmoid_subscore_0_10(x: float, m: float, k: float) -> float:
    """
    Map a physical input x to 0–10 using a logistic (S) curve centered at m with steepness k.
    Higher k → sharper transition around the inflection m.
    """
    try:
        t = -k * (x - m)
        if t > 40:
            s = 0.0
        elif t < -40:
            s = 10.0
        else:
            s = 10.0 / (1.0 + math.exp(t))
    except (OverflowError, ValueError):
        s = 5.0
    return max(0.0, min(10.0, s))


def _extract_evac_letter(evac: dict[str, Any] | None) -> str:
    if not evac:
        return ""
    raw = evac.get("raw") if isinstance(evac.get("raw"), dict) else {}
    for key in ("EVAC_LEVEL", "EZone", "evac_level", "evac_zone"):
        v = evac.get(key) if key in ("evac_level", "evac_zone") else raw.get(key)
        if v is None:
            continue
        s = str(v).strip().upper()
        for ch in s:
            if ch in "ABCDE":
                return ch
    return ""


def evacuation_vulnerability_multiplier(evac: dict[str, Any] | None) -> tuple[float, str, str]:
    """
    Zone multiplier Z: encodes GIS evacuation letter (Hillsborough A–E or EOC EZone).
    Letters D/E and unknown matched polygons get modest elevation over non-evac baseline.
    """
    if not evac or not evac.get("source"):
        return 1.0, "—", "No evacuation polygon matched at this coordinate; Z = 1.0 (neutral)."
    letter = _extract_evac_letter(evac)
    z_map = {
        "A": (1.5, "Zone A — highest ordered-evacuation tier in this schema"),
        "B": (1.3, "Zone B"),
        "C": (1.1, "Zone C"),
        "D": (1.05, "Zone D"),
        "E": (1.0, "Zone E"),
    }
    if letter in z_map:
        z, desc = z_map[letter]
        return z, letter, desc
    return 1.08, letter or "?", "Matched evacuation feature without A–E letter — Z = 1.08 (slight uplift)."


def compute_true_threat_detection_score(
    metrics: dict[str, Any],
    evacuation: dict[str, Any] | None = None,
    traffic_near: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    True Threat Detection Score (TDS): weighted non-linear index (0–100).

    TDS = min(100, (Σᵢ wᵢ · sᵢ²) · Z)

    Each sᵢ ∈ [0, 10] is a sigmoid-normalized sub-score. Squaring ensures a single
    extreme hazard dominates the sum. Z scales vulnerability from official evacuation GIS.

    This is a research-style composite for prioritization — not a forecast and not
    a substitute for NWS products or county evacuation orders.
    """
    coast = metrics.get("coastal") or {}
    anom = coast.get("water_level_anomaly_ft")
    latest = coast.get("water_level_ft_mllw_latest")
    x_surge = 0.0
    if anom is not None:
        try:
            x_surge = max(x_surge, float(anom))
        except (TypeError, ValueError):
            pass
    if latest is not None:
        try:
            lf = float(latest)
            x_surge = max(x_surge, max(0.0, lf - 2.5) * 0.35)
        except (TypeError, ValueError):
            pass
    if x_surge <= 0 and anom is None and latest is None:
        x_surge = 0.0
    s_surge = _sigmoid_subscore_0_10(x_surge, m=1.15, k=1.35)
    if anom is None and latest is None:
        s_surge = min(s_surge, 3.5)

    atm = metrics.get("atmosphere_forecast") or {}
    ost = metrics.get("official_short_term") or {}
    surf = metrics.get("surface_obs") or {}
    gust_om = float(atm.get("max_wind_gust_mph_24h_open_meteo") or 0)
    gust_nws = float(ost.get("max_wind_gust_mph_24h_nws") or 0)
    gust_surf = float(surf.get("wind_gust_mph") or 0)
    coops_gust_kt = coast.get("coops_max_gust_kt")
    coops_mph = float(coops_gust_kt) * 1.15078 if coops_gust_kt is not None else 0.0
    x_wind = max(gust_om, gust_nws, gust_surf, coops_mph)
    trop = metrics.get("tropical") or {}
    n_named = int(trop.get("nhc_named_storms") or 0)
    x_wind += min(25.0, n_named * 8.0)
    al = metrics.get("alerts") or {}
    if al.get("has_high_severity"):
        x_wind += 12.0
    s_wind = _sigmoid_subscore_0_10(x_wind, m=74.0, k=0.085)

    fl = (al.get("flood") or {})
    flood_n = float(fl.get("flood_related_count") or 0)
    if fl.get("flood_has_severe"):
        flood_n += 2.0
    rivers = metrics.get("rivers") or {}
    max_stage = 0.0
    for _sid, info in rivers.items():
        if not isinstance(info, dict):
            continue
        gh = (info.get("latest") or {}).get("gage_height_ft")
        if gh is not None:
            try:
                max_stage = max(max_stage, float(gh))
            except (TypeError, ValueError):
                pass
    rain48 = float(atm.get("precip_in_next_48h") or 0)
    x_inland = flood_n * 2.2 + max_stage / 6.5 + rain48 * 1.8
    s_inland = _sigmoid_subscore_0_10(x_inland, m=4.0, k=0.28)

    totals = (traffic_near or {}).get("totals_by_layer") or {}
    n_close = int(totals.get("fhp_closures") or 0)
    n_close += int(0.55 * float(totals.get("fhp_crashes") or 0))
    n_close += int(0.35 * float(totals.get("fl511_congestion") or 0))
    x_iso = float(n_close)
    s_isolation = _sigmoid_subscore_0_10(x_iso, m=1.0, k=0.75)

    w_surge = 0.42
    w_wind = 0.28
    w_inland = 0.14
    w_iso = 0.10

    c_surge = w_surge * (s_surge**2)
    c_wind = w_wind * (s_wind**2)
    c_inland = w_inland * (s_inland**2)
    c_iso = w_iso * (s_isolation**2)

    z, z_letter, z_explain = evacuation_vulnerability_multiplier(evacuation)
    inner = c_surge + c_wind + c_inland + c_iso
    raw = inner * z
    score = max(0.0, min(100.0, raw))

    tier = "low"
    if score >= 70:
        tier = "extreme"
    elif score >= 45:
        tier = "high"
    elif score >= 25:
        tier = "elevated"

    subscores = [
        {
            "id": "storm_surge_coastal",
            "label": "Coastal water / surge proxy",
            "weight": w_surge,
            "s": round(s_surge, 2),
            "x_input": round(x_surge, 3),
            "contribution": round(c_surge, 2),
            "detail": "NOAA CO-OPS anomaly + level vs baseline; not SLOSH.",
        },
        {
            "id": "wind",
            "label": "Wind (gusts + synoptic context)",
            "weight": w_wind,
            "s": round(s_wind, 2),
            "x_input": round(x_wind, 2),
            "contribution": round(c_wind, 2),
            "detail": "NWS hourly / Open-Meteo / ASOS + NHC named systems + alert severity nudge.",
        },
        {
            "id": "inland_flood",
            "label": "Inland flood drivers",
            "weight": w_inland,
            "s": round(s_inland, 2),
            "x_input": round(x_inland, 2),
            "contribution": round(c_inland, 2),
            "detail": "NWS flood-tagged alerts, USGS stage, model rain (48h).",
        },
        {
            "id": "isolation_routes",
            "label": "Route friction (FHP / FL511 near pin)",
            "weight": w_iso,
            "s": round(s_isolation, 2),
            "x_input": round(x_iso, 2),
            "contribution": round(c_iso, 2),
            "detail": "Counts of closures/crashes/congestion within buffer — not bridge wind gates.",
        },
    ]

    components = [
        {
            "id": s["id"],
            "points": round(float(s["contribution"]), 2),
            "detail": f"{s['label']}: strength {s['s']}/10, impact {s['contribution']}",
        }
        for s in sorted(subscores, key=lambda u: -u["contribution"])
    ]
    components.append(
        {
            "id": "evac_zone_Z",
            "points": round(z, 3),
            "detail": f"Evacuation zone factor: {z} — {z_explain}",
        }
    )

    reasons = [
        f"Combined hazard index before zone factor: {round(inner, 2)}; zone factor {z} → score {round(score, 1)}",
        f"Evacuation zone on map: {z_letter} — {z_explain}",
    ]
    for s in sorted(subscores, key=lambda u: -u["contribution"]):
        if s["contribution"] >= 1.0:
            reasons.append(f"{s['label']}: strength {s['s']}/10 (impact {s['contribution']})")

    disclaimer = (
        "The True Threat Detection Score (TDS) is an experimental composite for situational awareness only. "
        "It is not a deterministic flood or surge forecast, not engineering advice, and not a replacement for "
        "National Weather Service warnings, county evacuation orders, or FL511. Model inputs are incomplete, "
        "delayed, and location-specific; errors and omissions are expected."
    )

    methodology = {
        "title": "How we make the True Threat Detection Score (TDS)",
        "equation": "TDS = min(100, (Σᵢ wᵢ · sᵢ²) · Z)",
        "paragraphs": [
            "Instead of adding independent hazard points, we use a weighted sum of squared sub-scores. "
            "Squaring means one hazard approaching its upper range dominates the aggregate — consistent with "
            "disaster risk where a single failure mode (e.g. extreme water level) can override otherwise calm conditions.",
            "Each sub-score sᵢ ∈ [0, 10] is produced by a logistic (sigmoid) curve s = 10 / (1 + e^(−k(x − m))). "
            "The midpoint m is where the hazard begins to ramp quickly; k controls steepness. This mimics nonlinear "
            "human perception of escalating wind or water, rather than treating every 1 mph increment equally.",
            "Weights (Tampa Bay–oriented defaults): coastal water / surge proxy w = 0.42; wind w = 0.28; "
            "inland flood composite w = 0.14; nearby route friction (FHP / FL511 counts) w = 0.10. "
            "These sum to 1.0 before squaring.",
            "Z is an evacuation-zone vulnerability multiplier from official ArcGIS evacuation layers (Hillsborough HEAT / "
            "statewide EOC zones). Example mapping used here: Zone A → Z = 1.5, B → 1.3, C → 1.1, D → 1.05, E → 1.0; "
            "no polygon match → Z = 1.0. Your county’s definitions and orders always prevail over this app.",
            "This calculation is not foolproof: gauges fault, models disagree, buffers miss your exact street, and "
            "evacuation letters are not automatically synchronized with every NWS watch or warning.",
        ],
    }

    return {
        "score": round(score, 1),
        "tier": tier,
        "model": "TDS_v1",
        "tds_inner_sum_ws2": round(inner, 3),
        "zone_multiplier_Z": round(z, 3),
        "zone_letter": z_letter,
        "zone_explanation": z_explain,
        "subscores": subscores,
        "components": components,
        "reasons": reasons[:12],
        "disclaimer": disclaimer,
        "methodology": methodology,
    }


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
