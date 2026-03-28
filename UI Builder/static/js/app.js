import { renderScoreDial } from "./score-ui.js";

const FETCH_OPTS = { credentials: "same-origin" };

function tierBadge(tier) {
  const t = (tier || "low").toLowerCase();
  const cls = `badge badge--${t === "elevated" ? "elevated" : t}`;
  const labels = { low: "Low", elevated: "Elevated", high: "High", extreme: "Extreme" };
  return `<span class="${cls}">${labels[t] || tier || "—"}</span>`;
}

function threatSummaryLine(threat) {
  const r = threat?.reasons || [];
  if (r.length) return r.slice(0, 2).join(" · ");
  const d = (threat?.disclaimer || "").trim();
  if (d.length > 12) return d.length > 220 ? `${d.slice(0, 217)}…` : d;
  const tier = (threat?.tier || "low").toLowerCase();
  const byTier = {
    low: "Conditions look relatively quiet in this snapshot.",
    elevated: "A few signals are elevated—review details below.",
    high: "Several risk signals are elevated—stay informed.",
    extreme: "Strong signals in the data—monitor official sources closely.",
  };
  return byTier[tier] || byTier.low;
}

function setThreatHero(threat) {
  const dial = document.getElementById("overview-score-dial");
  const wrap = document.getElementById("threat-badge-wrap");
  const summaryEl = document.getElementById("threat-summary");
  renderScoreDial(dial, threat?.score, threat?.tier);
  if (wrap) wrap.innerHTML = tierBadge(threat?.tier);
  if (summaryEl) summaryEl.textContent = threatSummaryLine(threat);
}

function setThreatDeep(threat) {
  const disc = document.getElementById("threat-disclaimer");
  const reasons = document.getElementById("threat-reasons");
  const compEl = document.getElementById("threat-components");
  if (disc) disc.textContent = threat?.disclaimer || "";
  if (reasons) {
    const list = threat?.reasons || [];
    reasons.innerHTML = list.length
      ? list.map((x) => `<li>${escapeHtml(x)}</li>`).join("")
      : "<li>No single factor dominated this run.</li>";
  }
  const comps = threat?.components || [];
  if (compEl) {
    compEl.innerHTML = comps.length
      ? comps
          .map(
            (c) =>
              `<li><span>${escapeHtml(c.detail || c.id || "")}</span><span class="comp-list__pts">${escapeHtml(String(c.points ?? ""))} pts</span></li>`
          )
          .join("")
      : "<li><span>No breakdown lines returned.</span></li>";
  }
}

function digestRow(label, value, note) {
  const n = note ? `<span class="digest__note">${escapeHtml(note)}</span>` : "";
  return `<tr><th scope="row">${escapeHtml(label)}</th><td>${escapeHtml(String(value))}${n}</td></tr>`;
}

function glanceRow(label, value) {
  return `<tr><th scope="row">${escapeHtml(label)}</th><td class="digest__value">${escapeHtml(String(value))}</td></tr>`;
}

function renderSnapshotChips(data) {
  const root = document.getElementById("snapshot-chips");
  if (!root) return;
  const m = data.metrics || {};
  const atm = m.atmosphere_forecast || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const coast = m.coastal || {};

  const rain48 = atm.precip_in_next_48h != null ? `${atm.precip_in_next_48h} in` : "—";
  const gust = atm.max_wind_gust_mph_24h_open_meteo != null ? `${atm.max_wind_gust_mph_24h_open_meteo} mph` : "—";
  const nAlert = al.active_count != null ? String(al.active_count) : "—";
  const floodN = fl.flood_related_count != null ? String(fl.flood_related_count) : "0";
  const tide = coast.water_level_ft_mllw_latest != null ? `${coast.water_level_ft_mllw_latest} ft` : "—";
  const anomaly = coast.water_level_anomaly_ft != null ? `${coast.water_level_anomaly_ft >= 0 ? "+" : ""}${coast.water_level_anomaly_ft} ft` : "—";

  const chips = [
    { k: "48h rain", v: rain48 },
    { k: "24h peak gust", v: gust },
    { k: "NWS products", v: nAlert },
    { k: "Flood-tagged", v: floodN },
    { k: "Water level", v: tide },
    { k: "Tide vs average", v: anomaly },
  ];

  root.innerHTML = chips
    .map(
      (c) =>
        `<div class="snapshot-chip"><span class="snapshot-chip__val">${escapeHtml(c.v)}</span><span class="snapshot-chip__lbl">${escapeHtml(c.k)}</span></div>`
    )
    .join("");
}

function renderGlance(data) {
  const block = document.getElementById("glance-body");
  if (!block) return;
  const m = data.metrics || {};
  const atm = m.atmosphere_forecast || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const coast = m.coastal || {};
  const ost = m.official_short_term || {};
  const buoy = m.marine_buoy || {};
  const t = m.terrain || {};
  const riv = m.rivers || {};
  const rivElevated = Object.keys(riv).length > 0;

  const rows = [
    ["Next 48 hours of rain", atm.precip_in_next_48h != null ? `${atm.precip_in_next_48h} in` : "—"],
    ["Strongest wind gust (24h outlook)", atm.max_wind_gust_mph_24h_open_meteo != null ? `${atm.max_wind_gust_mph_24h_open_meteo} mph` : "—"],
    ["Active weather statements", al.active_count != null ? String(al.active_count) : "—"],
    ["Flood-related statements (filtered)", fl.flood_related_count != null ? String(fl.flood_related_count) : "0"],
    ["Coastal water level", coast.water_level_ft_mllw_latest != null ? `${coast.water_level_ft_mllw_latest} ft (MLLW)` : "—"],
    ["Inland stream gauges reporting", rivElevated ? `${Object.keys(riv).length} sites` : "—"],
    ["Significant wave height", buoy.sig_wave_height_ft != null ? `${buoy.sig_wave_height_ft} ft` : "—"],
    ["Top rain chance (24h)", ost.max_precip_probability_pct_24h != null ? `${ost.max_precip_probability_pct_24h}%` : "—"],
    ["Ground elevation (reference point)", t.ground_elevation_ft != null ? `${t.ground_elevation_ft} ft` : "—"],
  ];
  block.innerHTML = rows.map(([a, b]) => glanceRow(a, b)).join("");
}

function renderDetailWeather(data) {
  const block = document.getElementById("detail-weather-body");
  if (!block) return;
  const m = data.metrics || {};
  const atm = m.atmosphere_forecast || {};
  const rows = [
    ["Rain next 24 hours", atm.precip_in_next_24h != null ? `${atm.precip_in_next_24h} in` : "—", "Sum of hourly forecast (Open-Meteo)"],
    ["Rain next 48 hours", atm.precip_in_next_48h != null ? `${atm.precip_in_next_48h} in` : "—", "Same model, wider window"],
    ["Max wind gust (24h)", atm.max_wind_gust_mph_24h_open_meteo != null ? `${atm.max_wind_gust_mph_24h_open_meteo} mph` : "—", "Peak hourly gust in the forecast window"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRow(a, b, c)).join("");
}

function renderDetailCoastal(data) {
  const block = document.getElementById("detail-coastal-body");
  if (!block) return;
  const m = data.metrics || {};
  const coast = m.coastal || {};
  const buoy = m.marine_buoy || {};
  const rows = [
    ["Water level (latest)", coast.water_level_ft_mllw_latest != null ? `${coast.water_level_ft_mllw_latest} ft MLLW` : "—", "NOAA tide station"],
    ["Level vs recent average", coast.water_level_anomaly_ft != null ? `${coast.water_level_anomaly_ft} ft` : "—", "Positive means higher than the comparison window"],
    ["Max wind at tide station", coast.coops_max_gust_kt != null ? `${coast.coops_max_gust_kt} kt (gust)` : "—", "From CO-OPS wind product"],
    ["Significant wave height", buoy.sig_wave_height_ft != null ? `${buoy.sig_wave_height_ft} ft` : "—", buoy.station_id ? `NDBC ${buoy.station_id}` : "NDBC buoy"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRow(a, b, c)).join("");
}

function renderDetailRivers(data) {
  const block = document.getElementById("detail-rivers-body");
  if (!block) return;
  const m = data.metrics || {};
  const riv = m.rivers || {};
  const entries = Object.entries(riv);
  if (!entries.length) {
    block.innerHTML = digestRow("Gauges", "No recent readings in this bundle", "USGS instantaneous values near the hub point");
    return;
  }
  const rows = entries.map(([id, info]) => {
    const g = info.latest?.gage_height_ft;
    const q = info.latest?.discharge_cfs;
    const name = info.name || id;
    const val = [g != null ? `${g} ft stage` : null, q != null ? `${q} cfs` : null].filter(Boolean).join(" · ") || "—";
    return digestRow(name, val, `Site ${id}`);
  });
  block.innerHTML = rows.join("");
}

function renderDetailAlerts(data) {
  const block = document.getElementById("detail-alerts-body");
  if (!block) return;
  const m = data.metrics || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const ost = m.official_short_term || {};
  const rows = [
    ["Active NWS products", al.active_count != null ? String(al.active_count) : "—", "All hazards for the forecast grid"],
    ["Flood-related (keyword filter)", fl.flood_related_count != null ? String(fl.flood_related_count) : "0", "Subset of headlines mentioning flood/coastal wording"],
    ["Maximum POP (24h)", ost.max_precip_probability_pct_24h != null ? `${ost.max_precip_probability_pct_24h}%` : "—", "Hourly grid—how emphatic the rain forecast is"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRow(a, b, c)).join("");
}

function renderDetailTerrain(data) {
  const block = document.getElementById("detail-terrain-body");
  if (!block) return;
  const m = data.metrics || {};
  const t = m.terrain || {};
  const rows = [
    ["Elevation (EPQS)", t.ground_elevation_ft != null ? `${t.ground_elevation_ft} ft NAVD88 (typ.)` : "—", "USGS Elevation Point Query at hub coordinates"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRow(a, b, c)).join("");
}

function renderCoords(loc) {
  const el = document.getElementById("coords-display");
  if (!el || !loc) return;
  el.textContent = `${loc.latitude.toFixed(3)}°, ${loc.longitude.toFixed(3)}°`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderAll(data) {
  renderCoords(data.location);
  setThreatHero(data.threat || {});
  setThreatDeep(data.threat || {});
  renderSnapshotChips(data);
  renderGlance(data);
  renderDetailWeather(data);
  renderDetailCoastal(data);
  renderDetailRivers(data);
  renderDetailAlerts(data);
  renderDetailTerrain(data);
}

async function loadDashboard() {
  try {
    const res = await fetch("/api/dashboard", FETCH_OPTS);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAll(data);
  } catch (e) {
    console.error(e);
    setThreatHero({ score: "—", tier: "low", reasons: [], disclaimer: "" });
    const s = document.getElementById("threat-summary");
    if (s) s.textContent = "Could not load the regional snapshot. Try again shortly.";
    setThreatDeep({ disclaimer: `Load failed: ${e}`, reasons: [], components: [] });
  }
}

loadDashboard();
