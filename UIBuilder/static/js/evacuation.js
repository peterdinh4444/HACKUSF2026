/** Evacuation & traffic companion — loads dashboard + regional snapshot for the map pin. */
import { attachAddressAutocomplete } from "./address-autocomplete.js";
import { buildTrafficNearHtml, escapeHtml } from "./traffic-near-html.js";

const FETCH_OPTS = { credentials: "same-origin" };
const DEFAULT_LAT = 27.9506;
const DEFAULT_LON = -82.4572;

/** @type {{ dashboard?: object, tampa_bay_regional?: object, location?: { latitude?: number, longitude?: number } } | null} */
let lastHub = null;
let currentLat = DEFAULT_LAT;
let currentLon = DEFAULT_LON;

function humanMatchMethod(m) {
  if (!m) return "—";
  if (m === "intersect") return "Point inside polygon";
  if (m === "buffer_100m") return "~100 m search (near zone edge)";
  if (m === "buffer_250m") return "~250 m search (near zone edge)";
  return String(m);
}

function humanizeEvacSource(srcStr) {
  if (!srcStr) return "—";
  const s = String(srcStr);
  if (s.includes("hillsborough")) return "Hillsborough County evacuation map";
  if (s.includes("florida_eoc")) return "Florida statewide evacuation zones";
  return s.replace(/_/g, " ");
}

function renderEvacCard(ev) {
  const root = document.getElementById("evac-evac-root");
  if (!root) return;
  if (!ev || typeof ev !== "object") {
    root.innerHTML = `<p class="evac-page__empty">No evacuation data returned.</p>`;
    return;
  }
  const zone =
    ev.evac_level != null && ev.evac_level !== ""
      ? String(ev.evac_level)
      : ev.evac_zone != null && ev.evac_zone !== ""
        ? String(ev.evac_zone)
        : "—";
  const src = ev.source ? humanizeEvacSource(String(ev.source)) : "—";
  const rows = [
    ["Map source", src],
    ["Zone at this pin", zone],
    ["How we matched", humanMatchMethod(ev.match_method)],
  ];
  if (ev.county) rows.push(["County (state layer)", String(ev.county)]);
  if (ev.velocity_mph_band) rows.push(["Wind band (planning)", String(ev.velocity_mph_band)]);
  if (ev.to_be_evacuated) rows.push(["Evacuation timing note (map)", String(ev.to_be_evacuated)]);
  if (ev.note) rows.push(["Note", String(ev.note)]);

  const tbody = rows
    .map(
      ([k, v]) =>
        `<tr><th scope="row">${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`
    )
    .join("");

  root.innerHTML = `
    <div class="evac-card evac-card--homes">
      <header class="evac-card__head evac-card__head--homes">
        <div class="evac-card__head-text">
          <span class="evac-card__zone">${escapeHtml(zone === "—" ? "No zone matched" : `Zone ${zone}`)}</span>
          <span class="evac-card__source">${escapeHtml(src)}</span>
        </div>
      </header>
      <div class="evac-card__body evac-card__body--homes">
        <table class="digest digest--evac digest--dash"><tbody>${tbody}</tbody></table>
        <p class="muted evac-page__fineprint">Planning reference only — not an evacuation order. Confirm with your county emergency manager and <a href="https://www.weather.gov/tbw/" rel="noopener">NWS Tampa Bay</a>.</p>
      </div>
    </div>`;
}

function renderFl511Summary(tf) {
  const el = document.getElementById("evac-fl511-summary");
  if (!el) return;
  if (!tf || !tf.layers) {
    el.innerHTML = `<p class="evac-page__empty">No regional traffic layer summary.</p>`;
    return;
  }
  const layers = tf.layers || {};
  const bits = Object.entries(layers)
    .map(([k, v]) => {
      const c = v && typeof v.count !== "undefined" ? v.count : "—";
      return `<li><strong>${escapeHtml(k.replace(/_/g, " "))}</strong>: ${escapeHtml(c)} features (Tampa Bay bbox)</li>`;
    })
    .join("");
  el.innerHTML = `<p class="evac-page__regional-lede">FDOT / FL511 counts across the Tampa Bay demo box (not only your pin):</p><ul class="evac-page__fl511-list">${bits}</ul>`;
}

function renderPower(po) {
  const el = document.getElementById("evac-power-root");
  if (!el) return;
  if (!po) {
    el.innerHTML = "";
    return;
  }
  const n = po.count_in_bbox != null ? String(po.count_in_bbox) : "—";
  const samples = po.sample_attributes || [];
  const preview = samples
    .slice(0, 4)
    .map((a) => `<li><code>${escapeHtml(JSON.stringify(a).slice(0, 120))}</code></li>`)
    .join("");
  el.innerHTML = `
    <p><strong>Power outages</strong> (public GIS in regional bbox): about <strong>${escapeHtml(n)}</strong> aggregated outage areas.</p>
    ${preview ? `<ul class="evac-page__power-samples">${preview}</ul>` : ""}
    <p class="muted evac-page__fineprint">Use your utility’s official map before relying on this feed.</p>`;
}

function renderReadinessStrip(dash) {
  const el = document.getElementById("evac-readiness-strip");
  if (!el) return;
  const th = dash?.threat || {};
  const tier = th.tier != null ? String(th.tier) : "—";
  const score = th.score != null ? String(th.score) : "—";
  el.innerHTML = `Same pin on the main dashboard shows risk index <strong>${escapeHtml(score)}</strong>/100 (<strong>${escapeHtml(tier)}</strong> tier) — see <a href="/dashboard">Readiness dashboard</a> for the full score breakdown.`;
}

function updateCoordsChip() {
  const chip = document.getElementById("evac-coords-chip");
  const updated = document.getElementById("evac-updated-chip");
  if (chip) chip.textContent = `${currentLat.toFixed(4)}°, ${currentLon.toFixed(4)}°`;
  if (updated) updated.textContent = `Updated ${new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
}

async function loadHub() {
  const status = document.getElementById("evac-load-status");
  if (status) status.textContent = "Loading evacuation, traffic, and regional feeds…";
  const url = `/api/tampa/hub?lat=${encodeURIComponent(currentLat)}&lon=${encodeURIComponent(currentLon)}&verbose=0`;
  const res = await fetch(url, FETCH_OPTS);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  lastHub = data;
  const reg = data.tampa_bay_regional || {};
  const dash = data.dashboard || {};
  const loc = dash.location || {};
  const geo = {
    display_name:
      loc.city && loc.state
        ? `${loc.city}, ${loc.state}`
        : loc.latitude != null
          ? `${Number(loc.latitude).toFixed(4)}°, ${Number(loc.longitude).toFixed(4)}°`
          : undefined,
    lat: loc.latitude,
    lon: loc.longitude,
  };

  renderEvacCard(reg.evacuation || {});
  const trafficRoot = document.getElementById("evac-traffic-root");
  if (trafficRoot) {
    trafficRoot.innerHTML = buildTrafficNearHtml(reg.traffic_near_home, geo);
  }
  renderFl511Summary(reg.traffic_fl511);
  renderPower(reg.power_outages);
  renderReadinessStrip(dash);
  updateCoordsChip();
  if (status) status.textContent = "";
}

function formatRouteResult(payload) {
  const lines = [];
  if (payload.to_label) lines.push(`<strong>To:</strong> ${escapeHtml(payload.to_label)}`);
  if (payload.straight_line_miles != null) {
    lines.push(`Straight-line distance: <strong>${escapeHtml(payload.straight_line_miles)} mi</strong>`);
  }
  if (payload.naive_drive_minutes != null) {
    lines.push(
      `Naive time (~45 mph along straight line): <strong>~${escapeHtml(payload.naive_drive_minutes)} min</strong>`
    );
  }
  if (payload.predicted_drive_minutes != null) {
    lines.push(
      `Driving estimate (roads): <strong>~${escapeHtml(payload.predicted_drive_minutes)} min</strong>, <strong>${escapeHtml(payload.predicted_route_miles)} mi</strong>`
    );
  }
  if (payload.routing_note) lines.push(`<span class="homes-traffic__muted">${escapeHtml(payload.routing_note)}</span>`);
  return lines.length ? `<div class="homes-traffic-route__body">${lines.map((l) => `<p>${l}</p>`).join("")}</div>` : "";
}

function initRouteForm() {
  const form = document.getElementById("evac-route-form");
  const dest = document.getElementById("evac-route-dest");
  const out = document.getElementById("evac-route-result");
  if (!form || !dest || !out) return;
  attachAddressAutocomplete(dest, { minChars: 3, debounceMs: 280 });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = dest.value.trim();
    if (q.length < 3) {
      out.hidden = false;
      out.innerHTML = `<p class="homes-traffic__warn">Enter a longer destination.</p>`;
      return;
    }
    out.hidden = false;
    out.innerHTML = `<p class="homes-traffic__muted">Calculating…</p>`;
    try {
      const res = await fetch("/api/profiles/evac-route", {
        ...FETCH_OPTS,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          from_lat: currentLat,
          from_lon: currentLon,
          destination: q,
        }),
      });
      const data = await res.json();
      if (res.status === 401) {
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!res.ok) {
        out.innerHTML = `<p class="homes-traffic__warn">${escapeHtml(data.error || res.statusText)}</p>`;
        return;
      }
      out.innerHTML = formatRouteResult(data);
    } catch (err) {
      out.innerHTML = `<p class="homes-traffic__warn">${escapeHtml(err.message || String(err))}</p>`;
    }
  });
}

function initGeolocate() {
  const btn = document.getElementById("btn-evac-my-location");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (!navigator.geolocation) {
      alert("Location isn’t available in this browser.");
      return;
    }
    btn.disabled = true;
    const t = btn.textContent;
    btn.textContent = "Locating…";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        currentLat = pos.coords.latitude;
        currentLon = pos.coords.longitude;
        try {
          await loadHub();
        } catch (e) {
          console.error(e);
          const st = document.getElementById("evac-load-status");
          if (st) st.textContent = String(e.message || e);
        } finally {
          btn.disabled = false;
          btn.textContent = t;
        }
      },
      () => {
        btn.disabled = false;
        btn.textContent = t;
        alert("Could not read your location — allow access or enter coordinates on the main dashboard.");
      },
      { enableHighAccuracy: true, maximumAge: 120000, timeout: 20000 }
    );
  });
}

window.addEventListener("hurricanehub-evacuation-reload", async (e) => {
  const done = e.detail?.done;
  try {
    await loadHub();
    done?.({ ok: true });
  } catch (err) {
    console.error(err);
    done?.({ ok: false, message: String(err?.message || err) });
  }
});

window.__hurricaneHubAssistantContext = () => {
  if (!lastHub) {
    return {
      note: "Evacuation & traffic data is still loading or failed — refresh the page.",
      site_path: window.location.pathname,
    };
  }
  const dash = lastHub.dashboard || {};
  const reg = lastHub.tampa_bay_regional || {};
  return {
    page: "evacuation_traffic",
    reference_coordinates: { latitude: currentLat, longitude: currentLon },
    dashboard: {
      threat: dash.threat,
      location: dash.location,
      metrics: dash.metrics,
    },
    tampa_bay_regional: {
      evacuation: reg.evacuation,
      traffic_near_home: reg.traffic_near_home,
      traffic_fl511: reg.traffic_fl511,
      power_outages: {
        count_in_bbox: reg.power_outages?.count_in_bbox,
        features_in_bbox_returned: reg.power_outages?.features_in_bbox_returned,
      },
    },
  };
};

initGeolocate();
initRouteForm();
loadHub().catch((e) => {
  console.error(e);
  const st = document.getElementById("evac-load-status");
  if (st) st.textContent = `Could not load data: ${e.message || e}`;
});
