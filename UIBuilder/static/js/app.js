import { renderScoreDial } from "./score-ui.js";
import { initAssistantDock } from "./assistant-chat.js";

const FETCH_OPTS = { credentials: "same-origin" };

const DASH_DETAIL_KEYS = ["alerts", "coastal", "weather", "rivers", "terrain", "tds"];

/** Latest dashboard payload for topic gauge + detail panels */
let lastDashData = null;

function tierBadge(tier) {
  const t = (tier || "low").toLowerCase();
  const cls = `badge badge--${t === "elevated" ? "elevated" : t}`;
  const labels = { low: "Low", elevated: "Elevated", high: "High", extreme: "Extreme" };
  return `<span class="${cls}">${labels[t] || tier || "—"}</span>`;
}

/** One-line decision headline from tier (imperative, scannable). */
function decisionHeadline(threat) {
  const tier = (threat?.tier || "low").toLowerCase();
  const map = {
    extreme:
      "Treat this snapshot as high-impact — confirm everything with NWS and your county.",
    high: "Several signals are up — check official alerts and water levels before you commit to plans.",
    elevated: "A few things deserve a closer look — skim alerts and the four checks below.",
    low: "Nothing major jumps out in this bundle — stay aware and re-check if conditions change.",
  };
  return map[tier] || map.low;
}

/** 2–3 short bullets: prefer API reasons, else plain hints from metrics. */
function decisionBullets(threat, data) {
  const raw = threat?.reasons || [];
  if (raw.length) return raw.slice(0, 3).map((s) => simplifyReason(s));

  const m = data?.metrics || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const atm = m.atmosphere_forecast || {};
  const coast = m.coastal || {};
  const out = [];

  const nAct = al.active_count;
  const nFlood = fl.flood_related_count;
  if (nAct != null && nAct > 0) {
    out.push(`${nAct} active NWS product${nAct === 1 ? "" : "s"} for this point — read the official text.`);
  } else {
    out.push("No active NWS products flagged for this grid in this pull.");
  }
  if (nFlood != null && nFlood > 0) {
    out.push(`${nFlood} flood- or coastal-related headline${nFlood === 1 ? "" : "s"} in the subset — worth scanning.`);
  }
  if (atm.precip_in_next_48h != null && atm.precip_in_next_48h >= 1.5) {
    out.push(`About ${atm.precip_in_next_48h} in of rain in the 48h model window — watch low spots and drainage.`);
  }
  const anom = coast.water_level_anomaly_ft;
  if (anom != null && Math.abs(anom) >= 0.4) {
    out.push(`Coastal water is ${anom >= 0 ? "above" : "below"} its recent average — factor surge/setup into coastal plans.`);
  }

  return out.slice(0, 3).length ? out.slice(0, 3) : ["Use the four checks below, then open details if something matters for your route or address."];
}

function simplifyReason(s) {
  const t = String(s || "").trim();
  if (t.length > 140) return `${t.slice(0, 137)}…`;
  return t;
}

function severestLevel(a, b) {
  const order = { unknown: 0, ok: 1, watch: 2, alert: 3 };
  const oa = order[a] ?? 0;
  const ob = order[b] ?? 0;
  return oa >= ob ? a : b;
}

function statusLevel(kind, data) {
  const m = data.metrics || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const atm = m.atmosphere_forecast || {};
  const coast = m.coastal || {};
  if (kind === "alerts") {
    const n = al.active_count;
    const f = fl.flood_related_count ?? 0;
    if (n == null) return { level: "unknown", word: "No data" };
    if (n === 0) return { level: "ok", word: "None active" };
    if (f >= 2 || n >= 4) return { level: "alert", word: "Review now" };
    if (f >= 1 || n >= 2) return { level: "watch", word: "Check text" };
    return { level: "watch", word: "Active" };
  }
  if (kind === "rain") {
    const r = atm.precip_in_next_48h;
    if (r == null) return { level: "unknown", word: "—" };
    if (r < 0.5) return { level: "ok", word: "Light" };
    if (r < 2) return { level: "watch", word: "Moderate" };
    if (r < 4) return { level: "alert", word: "Heavy" };
    return { level: "alert", word: "Very heavy" };
  }
  if (kind === "water") {
    const a = coast.water_level_anomaly_ft;
    if (a == null) return { level: "unknown", word: "—" };
    const abs = Math.abs(a);
    if (abs < 0.25) return { level: "ok", word: "Near normal" };
    if (abs < 0.75) return { level: "watch", word: a > 0 ? "Above avg" : "Below avg" };
    return { level: "alert", word: a > 0 ? "Well above" : "Well below" };
  }
  if (kind === "wind") {
    const g = atm.max_wind_gust_mph_24h_open_meteo;
    if (g == null) return { level: "unknown", word: "—" };
    if (g < 25) return { level: "ok", word: "Calm" };
    if (g < 40) return { level: "watch", word: "Breezy" };
    if (g < 55) return { level: "alert", word: "Strong" };
    return { level: "alert", word: "Very strong" };
  }
  return { level: "unknown", word: "—" };
}

function formatAlertsValue(data) {
  const al = data.metrics?.alerts || {};
  const n = al.active_count;
  if (n == null) return "—";
  const f = data.metrics?.alerts?.flood?.flood_related_count ?? 0;
  return f > 0 ? `${n} (${f} flood-related)` : String(n);
}

function formatRainValue(data) {
  const r = data.metrics?.atmosphere_forecast?.precip_in_next_48h;
  return r != null ? `${r} in / 48h` : "—";
}

function formatWaterValue(data) {
  const coast = data.metrics?.coastal || {};
  const lvl = coast.water_level_ft_mllw_latest;
  const a = coast.water_level_anomaly_ft;
  if (lvl == null && a == null) return "—";
  const parts = [];
  if (lvl != null) parts.push(`${lvl} ft`);
  if (a != null) parts.push(`${a >= 0 ? "+" : ""}${a} ft vs avg`);
  return parts.join(" · ");
}

function formatWindValue(data) {
  const g = data.metrics?.atmosphere_forecast?.max_wind_gust_mph_24h_open_meteo;
  return g != null ? `${g} mph gust` : "—";
}

function dashMetricCard(label, value, status) {
  const lv = status.level;
  const mod =
    lv === "ok"
      ? "dash-metric--ok"
      : lv === "watch"
        ? "dash-metric--watch"
        : lv === "alert"
          ? "dash-metric--alert"
          : "dash-metric--unknown";
  return `
    <article class="dash-metric ${mod}" role="listitem">
      <div class="dash-metric__top">
        <span class="dash-metric__dot" aria-hidden="true"></span>
        <span class="dash-metric__label">${escapeHtml(label)}</span>
      </div>
      <p class="dash-metric__value">${escapeHtml(value)}</p>
      <p class="dash-metric__hint">${escapeHtml(status.word)}</p>
    </article>`;
}

function setDashUpdated() {
  const el = document.getElementById("dash-updated");
  if (!el) return;
  const t = new Date();
  el.textContent = `Updated ${t.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
}

function renderDecisionLayer(data, threat) {
  const h = document.getElementById("decision-headline");
  const ul = document.getElementById("decision-bullets");
  const grid = document.getElementById("priority-grid");
  if (h) h.textContent = decisionHeadline(threat);
  if (ul) {
    const items = decisionBullets(threat, data);
    ul.innerHTML = items.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
  }
  if (grid) {
    const s1 = statusLevel("alerts", data);
    const s2 = statusLevel("rain", data);
    const s3 = statusLevel("water", data);
    const s4 = statusLevel("wind", data);
    grid.innerHTML = [
      dashMetricCard("Official alerts", formatAlertsValue(data), s1),
      dashMetricCard("Rain window", formatRainValue(data), s2),
      dashMetricCard("Coastal water", formatWaterValue(data), s3),
      dashMetricCard("Wind gust (24h)", formatWindValue(data), s4),
    ].join("");
  }
}

function setThreatHero(threat) {
  const dial = document.getElementById("overview-score-dial");
  const wrap = document.getElementById("threat-badge-wrap");
  renderScoreDial(dial, threat?.score, threat?.tier);
  if (wrap) wrap.innerHTML = tierBadge(threat?.tier);
}

function renderTdsBanner(threat) {
  const live = document.getElementById("tds-live-inner");
  if (!live) return;
  if (threat?.model !== "TDS_v1") {
    live.hidden = true;
    live.textContent = "";
    return;
  }
  if (threat.tds_inner_sum_ws2 != null && threat.zone_multiplier_Z != null) {
    const letter = threat.zone_letter != null && threat.zone_letter !== "" ? threat.zone_letter : "—";
    live.hidden = false;
    live.textContent = `Behind the number: combined hazard strength ≈ ${threat.tds_inner_sum_ws2}, evacuation zone factor ${threat.zone_multiplier_Z} (zone ${letter}). Open “How your risk score works” for the full picture.`;
  } else {
    live.hidden = true;
  }
}

function setThreatDeep(threat) {
  const disc = document.getElementById("threat-disclaimer");
  const reasons = document.getElementById("threat-reasons");
  const compEl = document.getElementById("threat-components");
  const eq = document.getElementById("tds-equation-inline");
  const paras = document.getElementById("tds-methodology-paras");
  const subBody = document.getElementById("tds-subscores-body");

  if (eq) eq.textContent = threat?.methodology?.equation || "";

  if (paras) {
    const ps = threat?.methodology?.paragraphs;
    paras.innerHTML =
      ps && ps.length
        ? ps.map((p) => `<p class="tds-methodology-p">${escapeHtml(p)}</p>`).join("")
        : "";
  }

  if (subBody) {
    const subs = threat?.subscores || [];
    subBody.innerHTML = subs.length
      ? subs
          .map(
            (s) =>
              `<tr><th scope="row">${escapeHtml(s.label)}</th><td>${escapeHtml(String(s.s))}</td><td>${escapeHtml(String(s.weight))}</td><td>${escapeHtml(String(s.contribution))}</td></tr>`
          )
          .join("")
      : `<tr><td colspan="4">No sub-score breakdown.</td></tr>`;
  }

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
              `<li><span>${escapeHtml(c.detail || c.id || "")}</span><span class="comp-list__pts">${escapeHtml(String(c.points ?? ""))}</span></li>`
          )
          .join("")
      : "<li><span>No breakdown lines returned.</span></li>";
  }
}

function digestRow(label, value, note) {
  const n = note ? `<span class="digest__note">${escapeHtml(note)}</span>` : "";
  return `<tr><th scope="row">${escapeHtml(label)}</th><td>${escapeHtml(String(value))}${n}</td></tr>`;
}

function renderDetailWeather(data) {
  const block = document.getElementById("detail-weather-body");
  if (!block) return;
  const m = data.metrics || {};
  const atm = m.atmosphere_forecast || {};
  const rows = [
    ["Rain next 24 hours", atm.precip_in_next_24h != null ? `${atm.precip_in_next_24h} in` : "—", "Added up from the hourly forecast"],
    ["Rain next 48 hours", atm.precip_in_next_48h != null ? `${atm.precip_in_next_48h} in` : "—", "Two-day picture"],
    ["Peak wind gust (24h)", atm.max_wind_gust_mph_24h_open_meteo != null ? `${atm.max_wind_gust_mph_24h_open_meteo} mph` : "—", "Highest gust in that window"],
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
    ["Water level now", coast.water_level_ft_mllw_latest != null ? `${coast.water_level_ft_mllw_latest} ft (tide gauge)` : "—", "NOAA station at the shore"],
    ["Compared to recent days", coast.water_level_anomaly_ft != null ? `${coast.water_level_anomaly_ft} ft` : "—", "Plus = higher than the recent average"],
    ["Wind at the gauge", coast.coops_max_gust_kt != null ? `${coast.coops_max_gust_kt} kt gust` : "—", "Same location as the tide reading"],
    ["Wave height offshore", buoy.sig_wave_height_ft != null ? `${buoy.sig_wave_height_ft} ft` : "—", buoy.station_id ? `Buoy ${buoy.station_id}` : "Offshore buoy"],
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
    block.innerHTML = digestRow("River readings", "Nothing in this update", "We’ll show gauges when data comes back");
    return;
  }
  const rows = entries.map(([id, info]) => {
    const g = info.latest?.gage_height_ft;
    const q = info.latest?.discharge_cfs;
    const name = info.name || id;
    const val = [g != null ? `${g} ft deep` : null, q != null ? `${q} cfs flow` : null].filter(Boolean).join(" · ") || "—";
    return digestRow(name, val, `Gauge ID ${id}`);
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
    ["Active weather bulletins", al.active_count != null ? String(al.active_count) : "—", "Everything NWS has for this area right now"],
    ["Flood-related bulletins", fl.flood_related_count != null ? String(fl.flood_related_count) : "0", "Ones that mention flooding or water"],
    ["Top rain chance (24h)", ost.max_precip_probability_pct_24h != null ? `${ost.max_precip_probability_pct_24h}%` : "—", "From the hourly forecast grid"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRow(a, b, c)).join("");
}

function renderDetailTerrain(data) {
  const block = document.getElementById("detail-terrain-body");
  if (!block) return;
  const m = data.metrics || {};
  const t = m.terrain || {};
  const rows = [
    ["Approx. height above sea level", t.ground_elevation_ft != null ? `${t.ground_elevation_ft} ft` : "—", "Single-point estimate — not a flood map"],
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

/** Summary row for the colored gauge above a dashboard detail panel */
function detailTopicSummary(topic, data) {
  const m = data?.metrics || {};
  if (!topic) return null;
  if (topic === "alerts") {
    const s = statusLevel("alerts", data);
    return {
      level: s.level,
      headline: "Official alerts",
      status: s.word,
      blurb: "Active NWS products and rain-chance context for this point.",
    };
  }
  if (topic === "coastal") {
    const s = statusLevel("water", data);
    return {
      level: s.level,
      headline: "Bay water & seas",
      status: s.word,
      blurb: "Tide vs recent average and nearby sea state when sensors report.",
    };
  }
  if (topic === "weather") {
    const sr = statusLevel("rain", data);
    const sw = statusLevel("wind", data);
    const L = severestLevel(sr.level, sw.level);
    return {
      level: L,
      headline: "Rain & wind",
      status: `${sr.word} rain · ${sw.word} gusts`,
      blurb: "Short-range totals and peak gust from the blended forecast.",
    };
  }
  if (topic === "rivers") {
    const riv = m.rivers || {};
    const n = Object.keys(riv).length;
    if (n === 0) {
      return {
        level: "ok",
        headline: "River gauges",
        status: "None in bundle",
        blurb: "No gauge rows in this pull — score may still use other inland signals.",
      };
    }
    return {
      level: "watch",
      headline: "River gauges",
      status: `${n} nearby`,
      blurb: "Gage height and flow for the sites in the table below.",
    };
  }
  if (topic === "terrain") {
    const ft = m.terrain?.ground_elevation_ft;
    if (ft == null) {
      return {
        level: "unknown",
        headline: "Ground height",
        status: "No sample",
        blurb: "Elevation estimate not returned for this pin.",
      };
    }
    if (ft < 8) {
      return {
        level: "alert",
        headline: "Ground height",
        status: "Very low",
        blurb: "Low ground can pond quickly — this is not a regulatory flood map.",
      };
    }
    if (ft < 22) {
      return {
        level: "watch",
        headline: "Ground height",
        status: "Relatively low",
        blurb: "Pair with surge and heavy-rain planning for your route and address.",
      };
    }
    return {
      level: "ok",
      headline: "Ground height",
      status: "Higher vs typical coast",
      blurb: "Still follow official flood products and evacuation orders.",
    };
  }
  if (topic === "tds") {
    const tier = (data.threat?.tier || "low").toLowerCase();
    const L =
      tier === "extreme" || tier === "high"
        ? "alert"
        : tier === "elevated"
          ? "watch"
          : tier === "low"
            ? "ok"
            : "unknown";
    const labels = { low: "Low tier", elevated: "Elevated", high: "High", extreme: "Extreme" };
    return {
      level: L,
      headline: "Risk score",
      status: labels[tier] || data.threat?.tier || "—",
      blurb:
        data.threat?.score != null
          ? `Index ${data.threat.score} / 100 in this snapshot — details and math below.`
          : "Model breakdown appears below when the API returns it.",
    };
  }
  return null;
}

function gaugeFillPercent(level) {
  if (level === "alert") return 96;
  if (level === "watch") return 58;
  if (level === "ok") return 28;
  return 18;
}

function renderDetailGauge(topic, data) {
  const g = document.getElementById("dash-detail-gauge");
  const vp = document.getElementById("dash-detail-viewport");
  if (!g || !vp) return;
  vp.classList.remove("dash-detail-viewport--ok", "dash-detail-viewport--watch", "dash-detail-viewport--alert", "dash-detail-viewport--unknown");
  if (!topic || !data) {
    g.hidden = true;
    g.innerHTML = "";
    return;
  }
  const sum = detailTopicSummary(topic, data);
  if (!sum) {
    g.hidden = true;
    g.innerHTML = "";
    return;
  }
  const lv = sum.level;
  vp.classList.add(`dash-detail-viewport--${lv}`);
  const pct = gaugeFillPercent(lv);
  g.hidden = false;
  g.className = `dash-detail-gauge dash-detail-gauge--${lv}`;
  g.innerHTML = `
    <div class="dash-detail-gauge__top">
      <span class="dash-detail-gauge__kicker">At a glance</span>
      <span class="dash-detail-gauge__badge">${escapeHtml(sum.status)}</span>
    </div>
    <div class="dash-detail-gauge__headline">${escapeHtml(sum.headline)}</div>
    <p class="dash-detail-gauge__blurb">${escapeHtml(sum.blurb)}</p>
    <div class="dash-detail-gauge__meter" role="presentation">
      <div class="dash-detail-gauge__fill" style="width:${pct}%"></div>
    </div>
    <div class="dash-detail-gauge__scale" aria-hidden="true">
      <span>Calmer</span><span>Elevated</span><span>Priority</span>
    </div>
  `;
}

function renderAll(data) {
  lastDashData = data;
  const threat = data.threat || {};
  renderCoords(data.location);
  renderTdsBanner(threat);
  setThreatHero(threat);
  setThreatDeep(threat);
  renderDecisionLayer(data, threat);
  renderDetailWeather(data);
  renderDetailCoastal(data);
  renderDetailRivers(data);
  renderDetailAlerts(data);
  renderDetailTerrain(data);
  setDashUpdated();
  const sel = document.getElementById("dash-detail-select");
  if (sel?.value) renderDetailGauge(sel.value, data);
}

async function loadDashboard() {
  try {
    const res = await fetch("/api/dashboard", FETCH_OPTS);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAll(data);
  } catch (e) {
    console.error(e);
    lastDashData = null;
    const low = { score: "—", tier: "low", reasons: [], disclaimer: "" };
    renderTdsBanner({});
    const sel = document.getElementById("dash-detail-select");
    if (sel) {
      sel.value = "";
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    DASH_DETAIL_KEYS.forEach((k) => {
      const p = document.getElementById(`dash-panel-${k}`);
      if (p) p.hidden = true;
    });
    const vp = document.getElementById("dash-detail-viewport");
    if (vp) vp.hidden = true;
    const ph = document.getElementById("dash-detail-placeholder");
    if (ph) ph.hidden = false;
    setThreatHero(low);
    setThreatDeep({ disclaimer: `Load failed: ${e}`, reasons: [], components: [] });
    const h = document.getElementById("decision-headline");
    if (h) h.textContent = "Snapshot unavailable — try again in a moment.";
    const ul = document.getElementById("decision-bullets");
    if (ul) ul.innerHTML = "<li>Check your connection, then refresh the page.</li>";
    const grid = document.getElementById("priority-grid");
    if (grid) grid.innerHTML = "";
    const du = document.getElementById("dash-updated");
    if (du) du.textContent = "Sync failed";
  }
}

function initDashDetailSelect() {
  const sel = document.getElementById("dash-detail-select");
  const viewport = document.getElementById("dash-detail-viewport");
  const placeholder = document.getElementById("dash-detail-placeholder");
  const exploreCard = document.querySelector(".dash-explore-card");
  if (!sel || !viewport) return;

  const apply = () => {
    const v = sel.value;
    DASH_DETAIL_KEYS.forEach((k) => {
      const p = document.getElementById(`dash-panel-${k}`);
      if (p) p.hidden = k !== v;
    });
    const show = Boolean(v);
    viewport.hidden = !show;
    if (placeholder) placeholder.hidden = show;
    if (exploreCard) exploreCard.classList.toggle("dash-explore-card--has-topic", show);
    renderDetailGauge(v, lastDashData);
  };

  sel.addEventListener("change", apply);
  apply();
}

initDashDetailSelect();
loadDashboard();

initAssistantDock("dashboard", () => {
  if (!lastDashData) {
    return { note: "Dashboard data is still loading or failed to load — refresh or wait for the chips above to update." };
  }
  return {
    page: "dashboard",
    reference_coordinates: lastDashData.location,
    dashboard: lastDashData,
  };
});
