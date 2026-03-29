import { renderScoreDial } from "./score-ui.js";
import { attachAddressAutocomplete } from "./address-autocomplete.js";
import { downloadShareReport } from "./home-share-report.js";
import { initAssistantDock } from "./assistant-chat.js";

const FETCH_OPTS = { credentials: "same-origin" };

const HOME_DETAIL_KEYS = ["alerts", "coastal", "weather", "rivers", "terrain", "tds", "evac", "traffic", "local"];

/** Dashboard slice from last home assessment (metrics + threat) */
let lastHomeDashData = null;
let lastHomeAssessmentData = null;

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

function digestRowHome(label, value, note) {
  const n = note ? `<span class="digest__note">${esc(note)}</span>` : "";
  return `<tr><th scope="row">${esc(label)}</th><td>${esc(String(value))}${n}</td></tr>`;
}

function renderHomeDetailAlerts(d) {
  const block = document.getElementById("home-detail-alerts-body");
  if (!block) return;
  const m = d.metrics || {};
  const al = m.alerts || {};
  const fl = al.flood || {};
  const ost = m.official_short_term || {};
  const rows = [
    ["Active weather bulletins", al.active_count != null ? String(al.active_count) : "—", "Everything NWS has for this area right now"],
    ["Flood-related bulletins", fl.flood_related_count != null ? String(fl.flood_related_count) : "0", "Ones that mention flooding or water"],
    ["Top rain chance (24h)", ost.max_precip_probability_pct_24h != null ? `${ost.max_precip_probability_pct_24h}%` : "—", "From the hourly forecast grid"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRowHome(a, b, c)).join("");
}

function renderHomeDetailWeather(d) {
  const block = document.getElementById("home-detail-weather-body");
  if (!block) return;
  const atm = d.metrics?.atmosphere_forecast || {};
  const rows = [
    ["Rain next 24 hours", atm.precip_in_next_24h != null ? `${atm.precip_in_next_24h} in` : "—", "Added up from the hourly forecast"],
    ["Rain next 48 hours", atm.precip_in_next_48h != null ? `${atm.precip_in_next_48h} in` : "—", "Two-day picture"],
    ["Peak wind gust (24h)", atm.max_wind_gust_mph_24h_open_meteo != null ? `${atm.max_wind_gust_mph_24h_open_meteo} mph` : "—", "Highest gust in that window"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRowHome(a, b, c)).join("");
}

function renderHomeDetailCoastal(d) {
  const block = document.getElementById("home-detail-coastal-body");
  if (!block) return;
  const coast = d.metrics?.coastal || {};
  const buoy = d.metrics?.marine_buoy || {};
  const rows = [
    ["Water level now", coast.water_level_ft_mllw_latest != null ? `${coast.water_level_ft_mllw_latest} ft (tide gauge)` : "—", "NOAA station at the shore"],
    ["Compared to recent days", coast.water_level_anomaly_ft != null ? `${coast.water_level_anomaly_ft} ft` : "—", "Plus = higher than the recent average"],
    ["Wind at the gauge", coast.coops_max_gust_kt != null ? `${coast.coops_max_gust_kt} kt gust` : "—", "Same location as the tide reading"],
    ["Wave height offshore", buoy.sig_wave_height_ft != null ? `${buoy.sig_wave_height_ft} ft` : "—", buoy.station_id ? `Buoy ${buoy.station_id}` : "Offshore buoy"],
  ];
  block.innerHTML = rows.map(([a, b, c]) => digestRowHome(a, b, c)).join("");
}

function renderHomeDetailRivers(d) {
  const block = document.getElementById("home-detail-rivers-body");
  if (!block) return;
  const riv = d.metrics?.rivers || {};
  const entries = Object.entries(riv);
  if (!entries.length) {
    block.innerHTML = digestRowHome("River readings", "Nothing in this update", "We’ll show gauges when data comes back");
    return;
  }
  block.innerHTML = entries
    .map(([id, info]) => {
      const g = info.latest?.gage_height_ft;
      const q = info.latest?.discharge_cfs;
      const name = info.name || id;
      const val = [g != null ? `${g} ft deep` : null, q != null ? `${q} cfs flow` : null].filter(Boolean).join(" · ") || "—";
      return digestRowHome(name, val, `Gauge ID ${id}`);
    })
    .join("");
}

function renderHomeDetailTerrain(d) {
  const block = document.getElementById("home-detail-terrain-body");
  if (!block) return;
  const t = d.metrics?.terrain || {};
  block.innerHTML = digestRowHome(
    "Approx. height above sea level",
    t.ground_elevation_ft != null ? `${t.ground_elevation_ft} ft` : "—",
    "Single-point estimate — not a flood map"
  );
}

function homeDetailTopicSummary(topic, dash, assessment) {
  const data = { metrics: dash?.metrics || {}, threat: dash?.threat || {} };
  const m = data.metrics;
  if (!topic) return null;
  if (topic === "alerts") {
    const s = statusLevel("alerts", data);
    return { level: s.level, headline: "Official alerts", status: s.word, blurb: "Active NWS products and rain-chance context for this address." };
  }
  if (topic === "coastal") {
    const s = statusLevel("water", data);
    return { level: s.level, headline: "Bay water & seas", status: s.word, blurb: "Tide vs recent average and nearby sea state when sensors report." };
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
        blurb: "No gauge rows in this pull — other inland signals may still affect your score.",
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
      return { level: "unknown", headline: "Ground height", status: "No sample", blurb: "Elevation estimate not returned for this pin." };
    }
    if (ft < 8) {
      return {
        level: "alert",
        headline: "Ground height",
        status: "Very low",
        blurb: "Low ground can pond quickly — not a regulatory flood map.",
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
          ? `Index ${data.threat.score} / 100 in this snapshot — methodology below.`
          : "Model breakdown appears in this section when the API returns it.",
    };
  }
  if (topic === "evac") {
    const eh = evacModAndHint(assessment);
    return {
      level: eh.mod,
      headline: "Evacuation zone",
      status: eh.hint,
      blurb: "County and statewide evacuation layers — not an order to leave.",
    };
  }
  if (topic === "traffic") {
    const tn = assessment?.tampa_bay_regional?.traffic_near_home;
    const total = tn?.total_nearby ?? 0;
    if (!tn) {
      return { level: "unknown", headline: "Nearby traffic", status: "No feed", blurb: "Traffic-near payload missing in this response." };
    }
    if (total === 0) {
      return { level: "ok", headline: "Nearby traffic", status: "Quiet", blurb: "No FDOT features in the search radius right now — still check FL511 before driving." };
    }
    if (total < 5) {
      return { level: "watch", headline: "Nearby traffic", status: `${total} reports`, blurb: "Scan the table below and confirm on FL511." };
    }
    return { level: "alert", headline: "Nearby traffic", status: `${total} reports`, blurb: "Several road items near you — treat as a cue to read details and official sources." };
  }
  if (topic === "local") {
    return {
      level: "ok",
      headline: "ZIP & region",
      status: "Reference",
      blurb: "Metro seed ZIP notes plus regional power and traffic summaries.",
    };
  }
  return null;
}

function homeGaugeFillPercent(level) {
  if (level === "alert") return 96;
  if (level === "watch") return 58;
  if (level === "ok") return 28;
  return 18;
}

function renderHomeTopicGauge(topic) {
  const g = document.getElementById("home-detail-gauge");
  const vp = document.getElementById("home-detail-viewport");
  if (!g || !vp) return;
  vp.classList.remove("dash-detail-viewport--ok", "dash-detail-viewport--watch", "dash-detail-viewport--alert", "dash-detail-viewport--unknown");
  if (!topic || !lastHomeDashData) {
    g.hidden = true;
    g.innerHTML = "";
    return;
  }
  const sum = homeDetailTopicSummary(topic, lastHomeDashData, lastHomeAssessmentData);
  if (!sum) {
    g.hidden = true;
    g.innerHTML = "";
    return;
  }
  const lv = sum.level;
  vp.classList.add(`dash-detail-viewport--${lv}`);
  g.hidden = false;
  g.className = `dash-detail-gauge dash-detail-gauge--${lv}`;
  const pct = homeGaugeFillPercent(lv);
  g.innerHTML = `
    <div class="dash-detail-gauge__top">
      <span class="dash-detail-gauge__kicker">At a glance</span>
      <span class="dash-detail-gauge__badge">${esc(sum.status)}</span>
    </div>
    <div class="dash-detail-gauge__headline">${esc(sum.headline)}</div>
    <p class="dash-detail-gauge__blurb">${esc(sum.blurb)}</p>
    <div class="dash-detail-gauge__meter" role="presentation">
      <div class="dash-detail-gauge__fill" style="width:${pct}%"></div>
    </div>
    <div class="dash-detail-gauge__scale" aria-hidden="true">
      <span>Calmer</span><span>Elevated</span><span>Priority</span>
    </div>
  `;
}

function renderHomeDashboardDetailTables(dashboard) {
  if (!dashboard) return;
  renderHomeDetailAlerts(dashboard);
  renderHomeDetailCoastal(dashboard);
  renderHomeDetailWeather(dashboard);
  renderHomeDetailRivers(dashboard);
  renderHomeDetailTerrain(dashboard);
}

function initHomeDetailSelect() {
  const sel = document.getElementById("home-detail-select");
  const viewport = document.getElementById("home-detail-viewport");
  const placeholder = document.getElementById("home-detail-placeholder");
  const exploreCard = document.querySelector(".homes-explore-card");
  if (!sel || !viewport) return;

  const apply = () => {
    const v = sel.value;
    HOME_DETAIL_KEYS.forEach((k) => {
      const p = document.getElementById(`home-panel-${k}`);
      if (p) p.hidden = k !== v;
    });
    const show = Boolean(v);
    viewport.hidden = !show;
    if (placeholder) placeholder.hidden = show;
    if (exploreCard) exploreCard.classList.toggle("dash-explore-card--has-topic", show);
    renderHomeTopicGauge(v);
  };

  sel.addEventListener("change", apply);
  apply();
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function setLoading(on) {
  const el = document.getElementById("homes-loading");
  const btn = document.getElementById("btn-assess");
  const saveBtn = document.getElementById("btn-save");
  const downloadBtn = document.getElementById("btn-download-pdf");
  if (!el && !btn && !saveBtn && !downloadBtn) return;
  if (el) {
    el.hidden = !on;
    el.setAttribute("aria-hidden", on ? "false" : "true");
    el.setAttribute("aria-busy", on ? "true" : "false");
  }
  if (btn) btn.disabled = on;
  if (saveBtn) saveBtn.disabled = on;
  if (downloadBtn) downloadBtn.disabled = on;
}

function humanMatchMethod(m) {
  if (!m) return "—";
  if (m === "intersect") return "Point inside polygon";
  if (m === "buffer_100m") return "~100 m search (near zone edge)";
  if (m === "buffer_250m") return "~250 m search (near zone edge)";
  return String(m);
}

function fmtEpochMs(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return "—";
  try {
    return new Date(Number(ms)).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return "—";
  }
}

/** Plain-language lines for casual users (map lookup steps). */
function formatGisLookupFriendly(attempts) {
  if (!attempts || !attempts.length) return esc("No lookup steps recorded.");
  return attempts
    .map((a) => {
      let how = "Map check";
      if (a.mode === "intersect") how = "Pin inside an evacuation zone";
      else if (a.mode === "buffer_100m") how = "Pin near a zone edge (~100 m search)";
      else if (a.mode === "buffer_250m") how = "Pin near a zone edge (~250 m search)";
      const n = a.feature_count ?? 0;
      const err = a.arcgis_error ? ` — ${esc(String(a.arcgis_error))}` : "";
      return `${how}: ${esc(String(n))} possible match(es)${err}`;
    })
    .join("<br/>");
}

function humanizeEvacSource(srcStr) {
  if (!srcStr) return "—";
  const s = String(srcStr);
  if (s.includes("hillsborough")) return "Hillsborough County evacuation map";
  if (s.includes("florida_eoc")) return "Florida statewide evacuation zones";
  return s.replace(/_/g, " ");
}

function firstNonEmpty(...vals) {
  for (const v of vals) {
    if (v == null) continue;
    const s = typeof v === "string" ? v.trim() : v;
    if (s !== "" && s !== undefined) return typeof s === "string" ? s : String(s);
  }
  return null;
}

function renderEvacuation(ev, rc) {
  const root = document.getElementById("home-evac-root");
  if (!root) return;

  const ed = rc.evacuation_detail || {};
  const raw = ev.raw && typeof ev.raw === "object" ? ev.raw : {};
  const gis = rc.evacuation_gis || ev.gis || {};
  const hb = gis.hillsborough || {};
  const st = gis.statewide || {};
  const source = ev.source || rc.evacuation_source;
  const srcStr = source ? String(source) : "";
  const isHb = srcStr.includes("hillsborough");
  const isState = srcStr.includes("florida_eoc");
  const zoneVal = firstNonEmpty(rc.evacuation_level, ev.evac_level, ev.evac_zone, raw.EZone, raw.evac_zone);
  const zone = zoneVal ?? "—";
  const matchM = rc.evacuation_match_method ?? ev.match_method;
  const note = rc.evacuation_note || ev.note;

  const rowHtml = [];
  const addText = (k, v) => {
    const disp = v == null || v === "" ? "—" : String(v);
    rowHtml.push(`<tr><th scope="row">${esc(k)}</th><td>${esc(disp)}</td></tr>`);
  };
  const addHtml = (k, html) => {
    rowHtml.push(`<tr><th scope="row">${esc(k)}</th><td class="digest__cell--rich">${html}</td></tr>`);
  };

  const countyDisp = firstNonEmpty(ed.county_zone_label, ev.county, raw.County_Nam, raw.COUNTY_ZON);
  const windDisp = firstNonEmpty(ed.velocity_mph_band, ev.velocity_mph_band, raw.VELOCITY);
  const tideDisp = firstNonEmpty(ed.tide_heights_ft, ev.tide_heights_ft, raw.TIDE_HTS);
  const evacTxt = firstNonEmpty(ed.to_be_evacuated, ev.to_be_evacuated, raw.TO_BE_EVAC);
  const colorDisp = firstNonEmpty(rc.evacuation_color, ev.evac_color, raw.EVAC_COLOR);
  const popDisp = firstNonEmpty(ed.statewide_zone_pop_est, ev.statewide_zone_pop_est, raw.EST_ZONE_P, raw.SUM_POP_20);
  const editDisp = firstNonEmpty(ed.statewide_edit_date, ev.statewide_edit_date, raw.Edit_Date);
  const regionDisp = firstNonEmpty(ed.statewide_region, ev.statewide_region, raw.Region);
  const hbUpdateMs = firstNonEmpty(ed.layer_last_update_epoch_ms, ev.layer_last_update_epoch_ms, raw.LASTUPDATE);

  addText("Map source", source ? humanizeEvacSource(srcStr) : "—");
  addText("Your evacuation zone", zone);
  addText("How we matched your location", humanMatchMethod(matchM));
  if (isHb || (!source && !isState)) {
    addText("Zone color (planning key)", colorDisp ?? "—");
    addText("Wind speed used for planning", windDisp ?? "—");
    addText("Tide & surge notes from the map", tideDisp ?? "—");
    addText("When officials may tell people to leave", evacTxt ?? "—");
  }
  if (isState || (!source && !isHb)) {
    addText("County", countyDisp ?? "—");
    addText("Rough population in this zone", popDisp != null ? String(popDisp) : "—");
    addText("Map data last updated", editDisp ?? "—");
    addText("Region", regionDisp ?? "—");
  }
  if (isHb) {
    addText("County (for reference)", countyDisp ?? "—");
    addText("This map layer last updated", fmtEpochMs(hbUpdateMs));
  }
  const hbPlain = formatGisLookupFriendly(hb.attempts);
  const stPlain =
    st.attempts && st.attempts.length
      ? formatGisLookupFriendly(st.attempts)
      : isHb
        ? esc("Skipped — the county map already matched, so we didn’t need the statewide check.")
        : formatGisLookupFriendly(st.attempts);
  const techInner = `<details class="homes-tech-details"><summary>Map lookup details (optional)</summary><div class="homes-tech-details__inner"><p><strong>County map</strong><br/>${hbPlain}</p><p><strong>Statewide map</strong><br/>${stPlain}</p></div></details>`;
  addHtml("Extra detail", techInner);
  if (note) addText("Note for this address", note);

  const tableHtml = `<table class="digest digest--evac digest--dash"><tbody>${rowHtml.join("")}</tbody></table>`;

  const zoneTitle = zone === "—" ? "No zone matched" : `Zone ${zone}`;
  const sourceTitle = source ? humanizeEvacSource(srcStr) : "No zone on the map";

  root.innerHTML = `
    <div class="evac-card evac-card--homes">
      <header class="evac-card__head evac-card__head--homes">
        <div class="evac-card__head-text">
          <span class="evac-card__zone">${esc(zoneTitle)}</span>
          <span class="evac-card__source">${esc(sourceTitle)}</span>
        </div>
      </header>
      <div class="evac-card__body evac-card__body--homes">${tableHtml}</div>
    </div>`;
}

function tierBadge(tier) {
  const t = (tier || "low").toLowerCase();
  const cls = `badge badge--${t === "elevated" ? "elevated" : t}`;
  const labels = { low: "Low", elevated: "Elevated", high: "High", extreme: "Extreme" };
  return `<span class="${cls}">${labels[t] || tier || "—"}</span>`;
}

function digestRows(el, rows) {
  if (!el) return;
  el.innerHTML = rows
    .map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`)
    .join("");
}

function evacModAndHint(data) {
  const rc = data.risk_card || {};
  const ev = data.tampa_bay_regional?.evacuation || {};
  const src = ev.source || rc.evacuation_source;
  if (!src) return { mod: "unknown", hint: "No polygon match" };
  return { mod: "ok", hint: "Zone resolved" };
}

function setThreat(score, tier) {
  const dial = document.getElementById("home-score-dial");
  const badgeEl = document.getElementById("home-threat-badge");
  renderScoreDial(dial, score, tier);
  if (badgeEl) badgeEl.innerHTML = tierBadge(tier);
}

let lastAssessment = null;

function renderHomeTds(threat) {
  const live = document.getElementById("home-tds-live-inner");
  const eq = document.getElementById("home-tds-equation-inline");
  const paras = document.getElementById("home-tds-methodology-paras");
  const disc = document.getElementById("home-tds-disclaimer");
  const subBody = document.getElementById("home-tds-subscores-body");
  const reasons = document.getElementById("home-tds-reasons");
  const compEl = document.getElementById("home-tds-components");

  if (threat?.model === "TDS_v1") {
    if (live && threat.tds_inner_sum_ws2 != null && threat.zone_multiplier_Z != null) {
      const letter = threat.zone_letter != null && threat.zone_letter !== "" ? threat.zone_letter : "—";
      live.textContent = `This run: combined hazard strength ≈ ${threat.tds_inner_sum_ws2}, evacuation zone factor ${threat.zone_multiplier_Z} (zone ${letter}). Open Details → “How your risk score works” below for the full write-up.`;
    } else if (live) {
      live.textContent = "";
    }
    if (eq) eq.textContent = threat.methodology?.equation || "";
    if (paras) {
      const ps = threat.methodology?.paragraphs;
      paras.innerHTML =
        ps && ps.length
          ? ps.map((p) => `<p class="tds-methodology-p">${esc(p)}</p>`).join("")
          : "";
    }
    if (disc) disc.textContent = threat.disclaimer || "";
    if (subBody) {
      const subs = threat.subscores || [];
      subBody.innerHTML = subs.length
        ? subs
            .map(
              (s) =>
                `<tr><th scope="row">${esc(s.label)}</th><td>${esc(String(s.s))}</td><td>${esc(String(s.weight))}</td><td>${esc(String(s.contribution))}</td></tr>`
            )
            .join("")
        : `<tr><td colspan="4">No sub-score breakdown.</td></tr>`;
    }
  } else {
    if (live) live.textContent = "";
    if (eq) eq.textContent = "";
    if (paras) paras.innerHTML = "";
    if (disc) disc.textContent = threat?.disclaimer || "Detailed TDS methodology is shown when the model returns TDS_v1 for this address.";
    if (subBody) subBody.innerHTML = `<tr><td colspan="4">No sub-score breakdown for this run.</td></tr>`;
  }

  const list = threat?.reasons || [];
  if (reasons) {
    reasons.innerHTML = list.length ? list.map((x) => `<li>${esc(x)}</li>`).join("") : "<li>No single factor dominated this run.</li>";
  }
  const comps = threat?.components || [];
  if (compEl) {
    compEl.innerHTML = comps.length
      ? comps
          .map(
            (c) =>
              `<li><span>${esc(c.detail || c.id || "")}</span><span class="comp-list__pts">${esc(String(c.points ?? ""))}</span></li>`
          )
          .join("")
      : "<li><span>No breakdown lines returned.</span></li>";
  }
}

function renderAssessment(data) {
  lastAssessment = data;
  const rc = data.risk_card || {};
  const th = data.dashboard?.threat || {};
  const geo = data.geocode || {};
  const ev = data.tampa_bay_regional?.evacuation || {};
  const zip = data.zip_database_match;

  const results = document.getElementById("homes-results");
  if (results) results.hidden = false;

  const cc = document.getElementById("home-coords-chip");
  const uc = document.getElementById("home-updated-chip");
  if (cc && geo.lat != null && geo.lon != null) {
    cc.hidden = false;
    cc.textContent = `${Number(geo.lat).toFixed(3)}°, ${Number(geo.lon).toFixed(3)}°`;
  }
  if (uc) {
    uc.hidden = false;
    uc.textContent = `Updated ${new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  }

  setThreat(rc.threat_score ?? th.score, rc.threat_tier ?? th.tier);
  renderHomeTds(th);

  const reasons = document.getElementById("home-reasons");
  const rs = rc.threat_reasons || th.reasons || [];
  reasons.innerHTML = rs.length ? rs.map((r) => `<li>${esc(r)}</li>`).join("") : "<li>No strong signals in this run.</li>";

  const locEl = document.getElementById("home-loc-line");
  if (locEl) {
    locEl.textContent = geo.display_name || `${geo.lat?.toFixed(4)}°, ${geo.lon?.toFixed(4)}°`;
  }

  renderEvacuation(ev, rc);
  renderTrafficNear(data);

  const zr = rc.zip_reference;
  const zipRows = [
    ["ZIP code", data.matched_zip || "—"],
    ["City", zip?.city ?? "—"],
    ["County", zip?.county ?? "—"],
    ["Storm surge exposure (estimate)", zr?.storm_surge_exposure ?? zip?.storm_surge_exposure ?? "—"],
    ["Inland flood exposure (estimate)", zr?.river_inland_flood_exposure ?? zip?.river_inland_flood_exposure ?? "—"],
    ["Coastal character", zr?.coastal_character ?? zip?.coastal_character ?? "—"],
    ["Major roads & bridges", zr?.fdot_note ?? zip?.fdot_bridge_evac_note ?? "—"],
  ];
  const url = zr?.county_emergency_url || zip?.county_emergency_url;
  if (url) zipRows.push(["County emergency website", url]);
  const notes = zr?.planning_notes ?? zip?.zip_planning_notes;
  if (notes) zipRows.push(["Planning notes", notes]);
  if (!zip && !zr) {
    zipRows.push(["Database", "ZIP not in local metro seed — live metrics still apply."]);
  }
  digestRows(document.getElementById("home-zip-block"), zipRows);

  const tn = data.tampa_bay_regional?.traffic_near_home;
  const nearTotal = tn?.total_nearby;
  digestRows(document.getElementById("home-infra-block"), [
    ["Power outages (regional view)", rc.power_outage_polygons_in_bbox ?? "—"],
    ["Traffic events in the wider area", rc.fl511_incident_layers_total ?? "—"],
    ["Sample road alerts", (rc.fl511_headline_preview || []).join(" · ") || "—"],
    ["Road issues near your pin", nearTotal != null ? String(nearTotal) : "—"],
    ["River gauge snapshot", (rc.usgs_river_snapshot || []).join(" · ") || "—"],
  ]);

  lastHomeDashData = data.dashboard || null;
  lastHomeAssessmentData = data;
  renderHomeDashboardDetailTables(data.dashboard);
  const homeSel = document.getElementById("home-detail-select");
  if (homeSel?.value) renderHomeTopicGauge(homeSel.value);
}

function renderTrafficNear(data) {
  const root = document.getElementById("home-traffic-root");
  const routeBtn = document.getElementById("btn-traffic-route");
  const routeResult = document.getElementById("home-route-result");
  if (routeBtn) routeBtn.disabled = false;
  if (routeResult) {
    routeResult.hidden = true;
    routeResult.innerHTML = "";
  }
  if (!root) return;

  const tb = data.tampa_bay_regional?.traffic_near_home;
  const geo = data.geocode || {};
  if (!tb) {
    root.innerHTML = `<p class="homes-traffic__empty">No traffic-near payload in this response.</p>`;
    return;
  }

  const rMi = tb.radius_mi_rounded ?? "—";
  const total = tb.total_nearby ?? 0;
  const hw = tb.highways_or_roads_mentioned || [];
  const disc = tb.disclaimer || "";
  const rows = tb.incidents_chronological || [];

  const hwHtml = hw.length
    ? `<ul class="homes-traffic-hw" aria-label="Roads or highways mentioned near you">${hw.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>`
    : `<p class="homes-traffic__muted">No road names in the returned features — zoom FL511 for corridor detail.</p>`;

  const tableRows = rows.length
    ? rows
        .map(
          (it) => `
    <tr>
      <td>${esc(it.category || "—")}</td>
      <td>${esc(it.road_or_highway || "—")}</td>
      <td>${esc(it.county || "—")}</td>
      <td>${esc(it.title || "—")}</td>
      <td>${esc(it.detail || "—")}</td>
      <td>${esc(it.when || "—")}</td>
    </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="homes-traffic__muted">No FDOT features within ~${esc(rMi)} mi of this pin right now.</td></tr>`;

  const trafficLayerPlain = (k) => {
    const m = {
      fhp_closures: "Road closures (official)",
      fhp_crashes: "Crashes (law enforcement)",
      fhp_brush_fires: "Brush fires",
      fhp_other_incidents: "Other incidents",
      fl511_crashes: "Crashes (traffic feed)",
      fl511_congestion: "Heavy traffic",
      fl511_construction: "Construction",
      fl511_other: "Other traffic items",
    };
    return m[k] || k.replace(/_/g, " ");
  };
  const counts = tb.totals_by_layer || {};
  const countBits = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${esc(trafficLayerPlain(k))}: ${esc(n)}`)
    .join(" · ");

  root.innerHTML = `
    <div class="homes-traffic-summary">
      <p class="homes-traffic-summary__line"><strong>${esc(total)}</strong> road-related report(s) within ~<strong>${esc(rMi)} mi</strong> of your address.</p>
      ${countBits ? `<p class="homes-traffic-summary__counts">${countBits}</p>` : ""}
      <p class="homes-traffic-summary__disc">${esc(disc)}</p>
    </div>
    <div class="homes-traffic-highways">
      <h3 class="homes-traffic-subhead">Roads &amp; highways in nearby incidents</h3>
      ${hwHtml}
    </div>
    <div class="homes-traffic-panel__table-wrap">
      <h3 class="homes-traffic-subhead">Watch for (closures, crashes, congestion, …)</h3>
      <table class="digest digest--dash homes-traffic-table">
        <thead>
          <tr>
            <th scope="col">What it is</th>
            <th scope="col">Road</th>
            <th scope="col">County</th>
            <th scope="col">Short summary</th>
            <th scope="col">More detail</th>
            <th scope="col">When</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <p class="homes-traffic__foot muted">Origin for route estimates: ${esc(geo.display_name || `${geo.lat}, ${geo.lon}`)}</p>`;
}

function formatRouteResult(payload) {
  const lines = [];
  if (payload.to_label) lines.push(`<strong>To:</strong> ${esc(payload.to_label)}`);
  if (payload.straight_line_miles != null) {
    lines.push(`Straight-line distance: <strong>${esc(payload.straight_line_miles)} mi</strong>`);
  }
  if (payload.naive_drive_minutes != null) {
    lines.push(
      `Naive time (~45 mph along straight line): <strong>~${esc(payload.naive_drive_minutes)} min</strong> <span class="homes-traffic__muted">(${esc(payload.naive_drive_note || "")})</span>`
    );
  }
  if (payload.predicted_drive_minutes != null) {
    lines.push(
      `Driving estimate (roads): <strong>${esc(payload.predicted_drive_minutes)} min</strong>, <strong>${esc(payload.predicted_route_miles)} mi</strong> via ${esc(payload.routing_engine || "router")}`
    );
  }
  if (payload.routing_note) lines.push(`<span class="homes-traffic__muted">${esc(payload.routing_note)}</span>`);
  return lines.length ? `<div class="homes-traffic-route__body">${lines.map((l) => `<p>${l}</p>`).join("")}</div>` : "";
}

async function postAssess(address) {
  const res = await fetch("/api/assessment/home", {
    ...FETCH_OPTS,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ address }),
  });
  const data = await res.json();
  if (res.status === 401) {
    window.location.href = data.login_url || "/login?next=" + encodeURIComponent("/homes");
    throw new Error("Session expired — log in again.");
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function postSave(nickname, address) {
  const res = await fetch("/api/profiles", {
    ...FETCH_OPTS,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nickname, address }),
  });
  const data = await res.json();
  if (res.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent("/homes");
    throw new Error("Log in required");
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function loadProfiles() {
  const res = await fetch("/api/profiles", FETCH_OPTS);
  const data = await res.json();
  const ul = document.getElementById("profile-list");
  if (res.status === 401) {
    ul.innerHTML = "<li class=\"homes-profile-empty\">Log in to see saved homes.</li>";
    return;
  }
  const profiles = data.profiles || [];
  if (!profiles.length) {
    ul.innerHTML = "<li class=\"homes-profile-empty\">No saved profiles yet. Run an assessment and save.</li>";
    return;
  }
  ul.innerHTML = profiles
    .map(
      (p) => `
    <li class="homes-profile-item">
      <strong>${esc(p.nickname)}</strong>
      <span class="homes-profile-meta">${esc(p.address_line)}</span>
      <span class="homes-profile-meta">ZIP ${esc(p.zip || "—")} · ${esc(p.updated_at)}</span>
      <div class="homes-profile-actions">
        <button type="button" class="btn btn--small" data-refresh="${p.id}">Refresh</button>
        <button type="button" class="btn btn--small" data-load="${p.id}">View</button>
        <button type="button" class="btn btn--small" data-del="${p.id}">Delete</button>
      </div>
    </li>`
    )
    .join("");

  ul.querySelectorAll("[data-refresh]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-refresh");
      const st = document.getElementById("form-status");
      st.textContent = "Refreshing…";
      setLoading(true);
      try {
        const r = await fetch(`/api/profiles/${id}/refresh`, { ...FETCH_OPTS, method: "POST" });
        const d = await r.json();
        if (r.status === 401) {
          window.location.href = "/login?next=" + encodeURIComponent("/homes");
          return;
        }
        if (!r.ok) throw new Error(d.error);
        window.location.href = `/homes/${id}`;
      } catch (e) {
        st.textContent = String(e.message || e);
      } finally {
        setLoading(false);
      }
    });
  });

  ul.querySelectorAll("[data-load]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-load");
      if (id) window.location.href = `/homes/${id}`;
    });
  });

  ul.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-del");
      await fetch(`/api/profiles/${id}`, { ...FETCH_OPTS, method: "DELETE" });
      loadProfiles();
    });
  });
}

function readSnapshotAssessment() {
  const el = document.getElementById("home-snapshot-json");
  if (!el?.textContent?.trim()) return null;
  try {
    return JSON.parse(el.textContent);
  } catch {
    return null;
  }
}

function bindTrafficRouteForm() {
  document.getElementById("traffic-route-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const dest = document.getElementById("traffic-dest")?.value?.trim() || "";
    const out = document.getElementById("home-route-result");
    const geo = lastAssessment?.geocode;
    const nextPath = window.location.pathname.startsWith("/homes/") ? window.location.pathname : "/homes";
    if (!geo || geo.lat == null || geo.lon == null) {
      if (out) {
        out.hidden = false;
        out.innerHTML = `<p class="homes-traffic__warn">Run an assessment first so we know your starting point.</p>`;
      }
      return;
    }
    if (dest.length < 3) {
      if (out) {
        out.hidden = false;
        out.innerHTML = `<p class="homes-traffic__warn">Enter a longer destination.</p>`;
      }
      return;
    }
    if (out) {
      out.hidden = false;
      out.innerHTML = `<p class="homes-traffic__muted">Calculating…</p>`;
    }
    try {
      const res = await fetch("/api/profiles/evac-route", {
        ...FETCH_OPTS,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_lat: geo.lat, from_lon: geo.lon, destination: dest }),
      });
      const data = await res.json();
      if (res.status === 401) {
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(nextPath)}`;
        return;
      }
      if (!res.ok) {
        out.innerHTML = `<p class="homes-traffic__warn">${esc(data.error || res.statusText)}</p>`;
        return;
      }
      out.innerHTML = formatRouteResult(data);
    } catch (err) {
      out.innerHTML = `<p class="homes-traffic__warn">${esc(err.message || String(err))}</p>`;
    }
  });
}

function bootSnapshotPage() {
  const data = readSnapshotAssessment();
  if (!data) return;
  renderAssessment(data);
  initHomeDetailSelect();
  attachAddressAutocomplete(document.getElementById("traffic-dest"), { minChars: 3, debounceMs: 280 });
  bindTrafficRouteForm();
  const refBtn = document.getElementById("btn-snapshot-refresh");
  refBtn?.addEventListener("click", async () => {
    const id = refBtn.getAttribute("data-profile-id");
    if (!id) return;
    const st = document.getElementById("snapshot-status");
    if (st) st.textContent = "Refreshing…";
    refBtn.disabled = true;
    try {
      const r = await fetch(`/api/profiles/${id}/refresh`, { ...FETCH_OPTS, method: "POST" });
      const j = await r.json();
      if (r.status === 401) {
        window.location.href = j.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!r.ok) throw new Error(j.error || r.statusText);
      window.location.reload();
    } catch (err) {
      if (st) st.textContent = String(err.message || err);
    } finally {
      refBtn.disabled = false;
    }
  });
}

function bootWorkflowPage() {
  document.getElementById("assess-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const addr = document.getElementById("addr")?.value?.trim() || "";
    const st = document.getElementById("form-status");
    if (st) st.textContent = "";
    setLoading(true);
    try {
      const data = await postAssess(addr);
      renderAssessment(data);
      if (st) st.textContent = "Done.";
    } catch (err) {
      if (st) st.textContent = err.message || String(err);
    } finally {
      setLoading(false);
    }
  });

  document.getElementById("btn-save")?.addEventListener("click", async () => {
    const addr = document.getElementById("addr")?.value?.trim() || "";
    const nick = document.getElementById("nick")?.value?.trim() || "My home";
    const st = document.getElementById("form-status");
    if (addr.length < 4) {
      if (st) st.textContent = "Enter an address first.";
      return;
    }
    if (st) st.textContent = "Saving…";
    setLoading(true);
    try {
      const data = await postSave(nick, addr);
      window.location.href = `/homes/${data.id}`;
    } catch (err) {
      if (st) st.textContent = err.message || String(err);
    } finally {
      setLoading(false);
    }
  });

  document.getElementById("btn-download-pdf")?.addEventListener("click", async () => {
    const addr = document.getElementById("addr")?.value?.trim() || "";
    const st = document.getElementById("form-status");
    if (addr.length < 4) {
      if (st) st.textContent = "Enter an address first.";
      return;
    }
    if (st) st.textContent = "Preparing PDF…";
    setLoading(true);
    try {
      const url = `/api/assessment/home/pdf?address=${encodeURIComponent(addr)}`;
      const res = await fetch(url, { ...FETCH_OPTS });
      if (res.status === 401) {
        const data = await res.json().catch(() => ({}));
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.error || res.statusText || "PDF download failed");
      }
      const blob = await res.blob();
      const filename = `hurricane-hub-${addr.replace(/[^a-zA-Z0-9]+/g, "-").replace(/-+/g, "-").replace(/(^-|-$)/g, "").slice(0, 40)}.pdf`;
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename || "hurricane-hub-report.pdf";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      if (st) st.textContent = "PDF downloaded.";
    } catch (err) {
      if (st) st.textContent = err.message || String(err);
    } finally {
      setLoading(false);
    }
  });

  document.getElementById("reload-profiles")?.addEventListener("click", loadProfiles);
  initHomeDetailSelect();
  attachAddressAutocomplete(document.getElementById("addr"), { minChars: 3, debounceMs: 280 });
  attachAddressAutocomplete(document.getElementById("traffic-dest"), { minChars: 3, debounceMs: 280 });
  bindTrafficRouteForm();
  loadProfiles();
}

if (readSnapshotAssessment()) {
  bootSnapshotPage();
} else if (document.getElementById("assess-form")) {
  bootWorkflowPage();
}

document.body.addEventListener("click", (e) => {
  const t = e.target.closest("#btn-download-share-report");
  if (!t) return;
  e.preventDefault();
  if (!lastAssessment) return;
  downloadShareReport(lastAssessment);
});

initAssistantDock("home_risk", () => {
  if (!lastAssessment) {
    return {
      note: "No home assessment on screen yet. Run “Run assessment” or open a saved home that has a snapshot.",
    };
  }
  return { page: "home_risk", assessment: lastAssessment };
});
