/** Shared HTML for FDOT / FL511 “near this pin” table (used by evacuation page). */

export function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/**
 * @param {Record<string, unknown>} tb traffic_near_home payload
 * @param {{ display_name?: string, lat?: number, lon?: number }} geo
 */
export function buildTrafficNearHtml(tb, geo) {
  if (!tb) {
    return `<p class="homes-traffic__empty">No traffic-near payload in this response.</p>`;
  }

  const rMi = tb.radius_mi_rounded ?? "—";
  const total = tb.total_nearby ?? 0;
  const hw = tb.highways_or_roads_mentioned || [];
  const disc = tb.disclaimer || "";
  const rows = tb.incidents_chronological || [];

  const hwHtml = hw.length
    ? `<ul class="homes-traffic-hw" aria-label="Roads or highways mentioned near you">${hw.map((h) => `<li>${escapeHtml(h)}</li>`).join("")}</ul>`
    : `<p class="homes-traffic__muted">No road names in the returned features — zoom FL511 for corridor detail.</p>`;

  const tableRows = rows.length
    ? rows
        .map(
          (it) => `
    <tr>
      <td>${escapeHtml(it.category || "—")}</td>
      <td>${escapeHtml(it.road_or_highway || "—")}</td>
      <td>${escapeHtml(it.county || "—")}</td>
      <td>${escapeHtml(it.title || "—")}</td>
      <td>${escapeHtml(it.detail || "—")}</td>
      <td>${escapeHtml(it.when || "—")}</td>
    </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="homes-traffic__muted">No FDOT features within ~${escapeHtml(rMi)} mi of this pin right now.</td></tr>`;

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
    return m[k] || String(k).replace(/_/g, " ");
  };
  const counts = tb.totals_by_layer || {};
  const countBits = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${escapeHtml(trafficLayerPlain(k))}: ${escapeHtml(n)}`)
    .join(" · ");

  const foot = geo.display_name || (geo.lat != null && geo.lon != null ? `${geo.lat}, ${geo.lon}` : "this pin");

  return `
    <div class="homes-traffic-summary">
      <p class="homes-traffic-summary__line"><strong>${escapeHtml(total)}</strong> road-related report(s) within ~<strong>${escapeHtml(rMi)} mi</strong> of your pin.</p>
      ${countBits ? `<p class="homes-traffic-summary__counts">${countBits}</p>` : ""}
      <p class="homes-traffic-summary__disc">${escapeHtml(disc)}</p>
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
    <p class="homes-traffic__foot muted">Reference point: ${escapeHtml(foot)}</p>`;
}
