import { renderScoreDial } from "./score-ui.js";
import { postThreatTierWatch } from "./alert-email-pref.js";
import {
  bindTopicAiButton,
  clearAskAiTopicHistory,
  refreshTopicSummaryRow,
  syncTopicAiButtonState,
} from "./detail-topic-ai.js";

const FETCH_OPTS = { credentials: "same-origin" };

/** Short-lived session cache so revisiting the dashboard reuses SQLite-backed JSON without an extra round trip. */
const DASH_CACHE_TTL_MS = 45_000;

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
  const cap = document.getElementById("dashboard-hero-caption");
  if (cap) {
    const low = String(threat?.tier || "").toLowerCase() === "low";
    cap.textContent = low
      ? "Green band — no elevated signals in this snapshot from the feeds we track. Still follow NWS and your county when weather is active."
      : "Planning aid only — always follow NWS and your county.";
  }
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
  clearAskAiTopicHistory(document.getElementById("btn-dash-topic-ai"));
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
  const aiBtn = document.getElementById("btn-dash-topic-ai");
  const dashCtx = () =>
    lastDashData ? { dashboard: lastDashData, reference_coordinates: lastDashData.location } : null;
  syncTopicAiButtonState(aiBtn, () => sel?.value || "", dashCtx);
  postThreatTierWatch(threat.tier, threat.score);
}

async function fetchDashboardJson(url) {
  const key = `hhb-dash:${url}`;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) {
      const { t, data } = JSON.parse(raw);
      if (typeof t === "number" && data && Date.now() - t < DASH_CACHE_TTL_MS) {
        return data;
      }
    }
  } catch {
    /* ignore */
  }
  const res = await fetch(url, FETCH_OPTS);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  try {
    sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), data }));
  } catch {
    /* quota */
  }
  return data;
}

async function loadDashboard() {
  try {
    const data = await fetchDashboardJson("/api/dashboard");
    renderAll(data);
    return true;
  } catch (e) {
    console.error(e);
    lastDashData = null;
    clearAskAiTopicHistory(document.getElementById("btn-dash-topic-ai"));
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
    return false;
  }
}

window.addEventListener("hurricanehub-chat-load-dashboard", async (e) => {
  const done = e.detail?.done;
  const ok = await loadDashboard();
  done?.({ ok });
});

function initDashDetailSelect() {
  const sel = document.getElementById("dash-detail-select");
  const viewport = document.getElementById("dash-detail-viewport");
  const placeholder = document.getElementById("dash-detail-placeholder");
  const exploreCard = document.querySelector(".dash-explore-card");
  const summaryEl = document.getElementById("dash-detail-topic-summary");
  const aiBlock = document.getElementById("dash-detail-ai-block");
  const guestEl = document.getElementById("dash-detail-ai-guest");
  const loggedEl = document.getElementById("dash-detail-ai-logged");
  const outEl = document.getElementById("dash-detail-ai-out");
  const aiBtn = document.getElementById("btn-dash-topic-ai");
  if (!sel || !viewport) return;

  const getDashCtx = () =>
    lastDashData ? { dashboard: lastDashData, reference_coordinates: lastDashData.location } : null;

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
    const dashLow = String(lastDashData?.threat?.tier || "").toLowerCase() === "low";
    refreshTopicSummaryRow(v || null, summaryEl, aiBlock, guestEl, loggedEl, outEl, { snapshotLowTier: dashLow });
    syncTopicAiButtonState(aiBtn, () => sel.value, getDashCtx);
  };

  sel.addEventListener("change", apply);
  apply();

  bindTopicAiButton(aiBtn, {
    page: "dashboard",
    getTopic: () => sel.value,
    getContext: getDashCtx,
    outEl,
  });
}

initDashDetailSelect();
loadDashboard();

window.__hurricaneHubAssistantContext = () => {
  if (!lastDashData) {
    return { note: "Dashboard data is still loading or failed to load — refresh or wait for the chips above to update." };
  }
  return {
    reference_coordinates: lastDashData.location,
    dashboard: lastDashData,
  };
};

const TAMPA_VIEWBOX = { lonMin: -82.9, lonMax: -82.1, latMin: 27.5, latMax: 28.2 };

function inTampaBayArea(lon, lat) {
  if (lat == null || lon == null || Number.isNaN(lat) || Number.isNaN(lon)) return false;
  return lon >= TAMPA_VIEWBOX.lonMin && lon <= TAMPA_VIEWBOX.lonMax && lat >= TAMPA_VIEWBOX.latMin && lat <= TAMPA_VIEWBOX.latMax;
}

const COUNTY_EM_LINKS = [
  { re: /hillsborough/i, href: "https://www.hillsboroughcounty.org/en/residents/public-safety/emergency-management", label: "County emergency (Hillsborough)" },
  { re: /pinellas/i, href: "https://pinellas.gov/emergency-management/", label: "County emergency (Pinellas)" },
  { re: /pasco/i, href: "https://www.pascocountyfl.net/328/Emergency-Management", label: "County emergency (Pasco)" },
  { re: /hernando/i, href: "https://www.hernandocounty.us/departments/emergency-management", label: "County emergency (Hernando)" },
  { re: /manatee/i, href: "https://www.mymanatee.org/departments/public-safety", label: "County emergency (Manatee)" },
  { re: /polk/i, href: "https://www.polkcountyfl.net/emergency-management/", label: "County emergency (Polk)" },
  { re: /citrus/i, href: "https://www.citruscounty.org/government/departments/public_safety/emergency_management.php", label: "County emergency (Citrus)" },
  { re: /sarasota/i, href: "https://www.scgov.net/government/public-safety/emergency-services", label: "County emergency (Sarasota)" },
];

function initLocationAssessModal() {
  const btn = document.getElementById("btn-assess-my-location");
  const modal = document.getElementById("location-assess-modal");
  if (!btn || !modal) return;

  const backdrop = modal.querySelector(".loc-modal__backdrop");
  const closeBtn = document.getElementById("loc-modal-close");
  const titleEl = document.getElementById("loc-modal-title");
  const leadEl = document.getElementById("loc-modal-lead");
  const tierEl = document.getElementById("loc-modal-tier");
  const summaryEl = document.getElementById("loc-modal-summary");
  const bulletsEl = document.getElementById("loc-modal-bullets");
  const actionsEl = document.getElementById("loc-modal-actions");
  const hintEl = document.getElementById("loc-modal-hint");

  function closeModal() {
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    leadEl.classList.remove("loc-modal__lead--err");
    hintEl.hidden = false;
    btn.focus();
  }

  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);
  document.addEventListener("hurricanehub-close-overlays", () => {
    if (!modal.hidden) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });

  function showError(title, message) {
    titleEl.textContent = title;
    leadEl.textContent = message;
    leadEl.classList.add("loc-modal__lead--err");
    tierEl.innerHTML = "";
    if (summaryEl) summaryEl.textContent = "";
    bulletsEl.innerHTML = "";
    actionsEl.innerHTML = "";
    hintEl.hidden = true;
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    closeBtn?.focus();
  }

  function showSuccess(data) {
    const threat = data.threat || {};
    const loc = data.location || {};
    const reg = data.tampa_bay_regional || {};
    const ev = reg.evacuation || {};
    const lat = loc.latitude;
    const lon = loc.longitude;

    titleEl.textContent = "Your location — next steps";
    leadEl.classList.remove("loc-modal__lead--err");

    let lead = "";
    if (lat != null && lon != null) {
      lead = `Pin ≈ ${Number(lat).toFixed(3)}°, ${Number(lon).toFixed(3)}°.`;
    }
    if (!inTampaBayArea(lon, lat)) {
      lead += " Outside the Tampa Bay demo box — still follow your local NWS office and county.";
    }
    if (ev.evac_level != null) lead += ` Evacuation data: level ${ev.evac_level}.`;
    else if (ev.evac_zone != null) lead += ` Evacuation zone (state layer): ${ev.evac_zone}.`;
    else if (ev.county) lead += ` County from state layer: ${ev.county}.`;
    leadEl.textContent = lead.trim() || "Snapshot for your position.";

    const score = threat.score != null ? threat.score : "—";
    tierEl.innerHTML = `${tierBadge(threat.tier)}<span class="loc-modal__score-line">Risk index <strong>${escapeHtml(String(score))}</strong> / 100</span>`;

    if (summaryEl) summaryEl.textContent = decisionHeadline(threat);

    const evSource = typeof ev.source === "string" ? ev.source : "";

    const bullets = decisionBullets(threat, data);
    bulletsEl.innerHTML = bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join("");

    const steps = [];
    steps.push({ href: "https://www.weather.gov/tbw/", label: "Open NWS Tampa Bay", ext: true, primary: true });
    steps.push({ href: "https://www.fl511.com/", label: "Open FL511 (traffic & roads)", ext: true, primary: false });

    const county = typeof ev.county === "string" ? ev.county : "";
    let matchedCounty = false;
    if (evSource.toLowerCase().includes("hillsborough")) {
      const hb = COUNTY_EM_LINKS[0];
      steps.push({ href: hb.href, label: hb.label, ext: true, primary: false });
      matchedCounty = true;
    } else {
      for (const row of COUNTY_EM_LINKS) {
        if (county && row.re.test(county)) {
          steps.push({ href: row.href, label: row.label, ext: true, primary: false });
          matchedCounty = true;
          break;
        }
      }
    }
    if (county && !matchedCounty) {
      steps.push({
        href: "https://www.floridadisaster.org/planprepare/evacuation-zones/",
        label: "Florida evacuation zones (lookup)",
        ext: true,
        primary: false,
      });
    }
    steps.push({ href: "https://www.floridadisaster.org/planprepare/", label: "Florida Disaster — plan & prepare", ext: true, primary: false });
    steps.push({ href: "/homes", label: "Home risk — full address check", ext: false, primary: false });

    if (document.body.getAttribute("data-logged-in") === "1") {
      steps.push({ action: "guide", label: "Open Ask about this page (guide)", primary: true });
    }

    actionsEl.innerHTML = "";
    for (const x of steps) {
      if (x.action === "guide") {
        const b = document.createElement("button");
        b.type = "button";
        b.className = `btn btn--sm ${x.primary ? "btn--primary" : ""}`.trim();
        b.textContent = x.label;
        b.addEventListener("click", () => {
          document.getElementById("assistant-toggle")?.click();
          closeModal();
        });
        actionsEl.appendChild(b);
        continue;
      }
      const a = document.createElement("a");
      a.className = `btn btn--sm ${x.primary ? "btn--primary" : "btn--ghost"}`.trim();
      a.href = x.href;
      a.textContent = x.label;
      if (x.ext) {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      }
      actionsEl.appendChild(a);
    }

    hintEl.hidden = false;
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    closeBtn?.focus();
  }

  btn.addEventListener("click", () => {
    if (!navigator.geolocation) {
      showError("Location not available", "This browser doesn’t support geolocation, or the page isn’t on a secure origin.");
      return;
    }
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "Locating…";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        try {
          const url = `/api/dashboard?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&include_tampa=1`;
          const data = await fetchDashboardJson(url);
          renderAll(data);
          showSuccess(data);
        } catch (e) {
          showError("Couldn’t load snapshot", e?.message || String(e));
        } finally {
          btn.disabled = false;
          btn.textContent = label;
        }
      },
      (geoErr) => {
        btn.disabled = false;
        btn.textContent = label;
        const byCode = {
          1: "Permission denied — allow location for this site in your browser, or use Home risk with an address.",
          2: "Position unavailable.",
          3: "Location request timed out — try again outdoors or with Wi‑Fi location on.",
        };
        showError("Location needed", byCode[geoErr.code] || geoErr.message || "Could not read your position.");
      },
      { enableHighAccuracy: true, maximumAge: 120000, timeout: 20000 }
    );
  });
}

initLocationAssessModal();
