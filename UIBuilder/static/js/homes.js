import { renderScoreDial } from "./score-ui.js";

const FETCH_OPTS = { credentials: "same-origin" };

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function tierBadge(tier) {
  const t = (tier || "low").toLowerCase();
  const cls = `badge badge--${t === "elevated" ? "elevated" : t}`;
  const labels = { low: "Low", elevated: "Elevated", high: "High", extreme: "Extreme" };
  return `<span class="${cls}">${labels[t] || tier || "—"}</span>`;
}

function digestRows(el, rows) {
  if (!el) return;
  el.innerHTML = rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
}

function setThreat(score, tier) {
  const dial = document.getElementById("home-score-dial");
  const badgeEl = document.getElementById("home-threat-badge");
  renderScoreDial(dial, score, tier);
  if (badgeEl) badgeEl.innerHTML = tierBadge(tier);
}

let lastAssessment = null;

function renderAssessment(data) {
  lastAssessment = data;
  const rc = data.risk_card || {};
  const th = data.dashboard?.threat || {};
  const geo = data.geocode || {};
  const ev = data.tampa_bay_regional?.evacuation || {};
  const zip = data.zip_database_match;

  document.getElementById("result-panel").hidden = false;
  setThreat(rc.threat_score ?? th.score, rc.threat_tier ?? th.tier);

  const reasons = document.getElementById("home-reasons");
  const rs = rc.threat_reasons || th.reasons || [];
  reasons.innerHTML = rs.length ? rs.map((r) => `<li>${esc(r)}</li>`).join("") : "<li>No strong signals in this run.</li>";

  document.getElementById("home-loc-line").textContent =
    geo.display_name || `${geo.lat?.toFixed(4)}°, ${geo.lon?.toFixed(4)}°`;

  const ed = rc.evacuation_detail || {};
  digestRows(document.getElementById("home-evac-block"), [
    ["Source", ev.source || "—"],
    ["Zone / level", rc.evacuation_level ?? "—"],
    ["Wind band (planning)", ed.velocity_mph_band ?? ev.velocity_mph_band ?? "—"],
    ["Tide text", ed.tide_heights_ft ?? ev.tide_heights_ft ?? "—"],
    ["Evacuation text", ed.to_be_evacuated ?? ev.to_be_evacuated ?? "—"],
    ["County label", ed.county_zone_label ?? ev.county ?? "—"],
  ]);

  const zr = rc.zip_reference;
  const zipRows = [
    ["Matched ZIP", data.matched_zip || "—"],
    ["City", zip?.city ?? "—"],
    ["County", zip?.county ?? "—"],
    ["Surge (heuristic)", zr?.storm_surge_exposure ?? zip?.storm_surge_exposure ?? "—"],
    ["River / pluvial (heuristic)", zr?.river_inland_flood_exposure ?? zip?.river_inland_flood_exposure ?? "—"],
    ["Coastal character", zr?.coastal_character ?? zip?.coastal_character ?? "—"],
    ["Bridges / corridors", zr?.fdot_note ?? zip?.fdot_bridge_evac_note ?? "—"],
  ];
  const url = zr?.county_emergency_url || zip?.county_emergency_url;
  if (url) zipRows.push(["County EM link", url]);
  const notes = zr?.planning_notes ?? zip?.zip_planning_notes;
  if (notes) zipRows.push(["Planning notes", notes]);
  if (!zip && !zr) {
    zipRows.push(["Database", "ZIP not in local metro seed — live metrics still apply."]);
  }
  digestRows(document.getElementById("home-zip-block"), zipRows);

  digestRows(document.getElementById("home-infra-block"), [
    ["Power outages (bbox)", rc.power_outage_polygons_in_bbox ?? "—"],
    ["FL511 layer hits (sum)", rc.fl511_incident_layers_total ?? "—"],
    ["USGS rivers", (rc.usgs_river_snapshot || []).join(" · ") || "—"],
  ]);
}

async function postAssess(address) {
  const res = await fetch("/api/profiles/assess", {
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

async function downloadAssessmentPdf(assessment) {
  const res = await fetch("/api/report/pdf", {
    ...FETCH_OPTS,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assessment }),
  });

  if (res.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent("/homes");
    throw new Error("Sign in to download a report.");
  }

  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.error || msg;
    } catch {
      // ignore parse failure
    }
    throw new Error(msg);
  }

  return res.blob();
}

async function loadProfiles() {
  const res = await fetch("/api/profiles", FETCH_OPTS);
  const data = await res.json();
  const ul = document.getElementById("profile-list");
  if (res.status === 401) {
    ul.innerHTML = "<li class=\"panel__hint\">Log in to see saved homes.</li>";
    return;
  }
  const profiles = data.profiles || [];
  if (!profiles.length) {
    ul.innerHTML = "<li class=\"panel__hint\">No saved profiles yet.</li>";
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
        <button type="button" class="btn btn--small" data-load="${p.id}">Load</button>
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
      try {
        const r = await fetch(`/api/profiles/${id}/refresh`, { ...FETCH_OPTS, method: "POST" });
        const d = await r.json();
        if (r.status === 401) {
          window.location.href = "/login?next=" + encodeURIComponent("/homes");
          return;
        }
        if (!r.ok) throw new Error(d.error);
        renderAssessment(d);
        st.textContent = "Updated.";
        loadProfiles();
      } catch (e) {
        st.textContent = String(e.message || e);
      }
    });
  });

  ul.querySelectorAll("[data-load]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-load");
      const r = await fetch(`/api/profiles/${id}`, FETCH_OPTS);
      const row = await r.json();
      if (!r.ok) return;
      let parsed = null;
      try {
        parsed = row.last_assessment_json ? JSON.parse(row.last_assessment_json) : null;
      } catch (_) {}
      document.getElementById("addr").value = row.address_line || "";
      document.getElementById("nick").value = row.nickname || "";
      if (parsed) renderAssessment(parsed);
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

document.getElementById("assess-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const addr = document.getElementById("addr").value.trim();
  const st = document.getElementById("form-status");
  st.textContent = "Loading…";
  try {
    const data = await postAssess(addr);
    renderAssessment(data);
    st.textContent = "Done.";
  } catch (err) {
    st.textContent = err.message || String(err);
  }
});

document.getElementById("btn-save").addEventListener("click", async () => {
  const addr = document.getElementById("addr").value.trim();
  const nick = document.getElementById("nick").value.trim() || "My home";
  const st = document.getElementById("form-status");
  if (addr.length < 4) {
    st.textContent = "Enter an address first.";
    return;
  }
  st.textContent = "Saving…";
  try {
    const data = await postSave(nick, addr);
    renderAssessment(data.assessment);
    st.textContent = `Saved (#${data.id}).`;
    loadProfiles();
  } catch (err) {
    st.textContent = err.message || String(err);
  }
});

document.getElementById("btn-download-report").addEventListener("click", async () => {
  const st = document.getElementById("form-status");
  if (!lastAssessment) {
    st.textContent = "Run an assessment first.";
    return;
  }

  st.textContent = "Generating PDF…";
  try {
    const blob = await downloadAssessmentPdf(lastAssessment);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "area-summary.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    st.textContent = "Downloaded report.";
  } catch (err) {
    st.textContent = err.message || String(err);
  }
});

document.getElementById("reload-profiles").addEventListener("click", loadProfiles);

loadProfiles();
