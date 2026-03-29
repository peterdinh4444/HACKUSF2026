/**
 * One-page HTML download — matches app typography and score styling, shortened for sharing with family.
 */

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/** Drop Hurricane Hub /api/... paths from shared downloads (data may still echo internal hints). */
function stripInternalApiRefs(s) {
  let t = String(s ?? "");
  t = t.replace(/https?:\/\/[^\s"'<>]+\/api\/[^\s"'<>]*/gi, "");
  t = t.replace(/\/api\/[a-z0-9_\-./?=&+%[\]{}#]*/gi, "");
  t = t.replace(/\b(?:GET|POST|PUT|PATCH|DELETE)\s+\/api\/\S+/gi, "");
  return t.replace(/[ \t]{2,}/g, " ").trim();
}

const TIER_LABELS = {
  low: "Low concern",
  elevated: "Elevated",
  high: "High",
  extreme: "Extreme",
};

const TIER_THEME = {
  low: { stroke: "#16a34a", badgeBg: "linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%)", badgeBorder: "rgba(22, 163, 74, 0.28)", badgeColor: "#14532d" },
  elevated: {
    stroke: "#d97706",
    badgeBg: "linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%)",
    badgeBorder: "rgba(217, 119, 6, 0.3)",
    badgeColor: "#78350f",
  },
  high: {
    stroke: "#ea580c",
    badgeBg: "linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%)",
    badgeBorder: "rgba(234, 88, 12, 0.28)",
    badgeColor: "#7c2d12",
  },
  extreme: {
    stroke: "#dc2626",
    badgeBg: "linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%)",
    badgeBorder: "rgba(220, 38, 38, 0.32)",
    badgeColor: "#7f1d1d",
  },
};

const DIAL_LEN = 276.46;

function normalizeTier(t) {
  const x = (t || "low").toLowerCase();
  if (x === "elevated") return "elevated";
  if (TIER_THEME[x]) return x;
  return "low";
}

/**
 * @param {Record<string, unknown>} data — full home assessment payload (same as lastAssessment)
 */
export function downloadShareReport(data) {
  if (!data || typeof data !== "object") return;

  const rc = data.risk_card || {};
  const th = data.dashboard?.threat || {};
  const geo = data.geocode || {};
  const scoreRaw = rc.threat_score ?? th.score;
  const scoreNum = typeof scoreRaw === "number" ? scoreRaw : parseFloat(String(scoreRaw));
  const score = Number.isFinite(scoreNum) ? Math.round(scoreNum * 10) / 10 : null;
  const tier = normalizeTier(rc.threat_tier ?? th.tier);
  const theme = TIER_THEME[tier];
  const tierLabel = TIER_LABELS[tier] || tier;

  const loc = geo.display_name || (geo.lat != null && geo.lon != null ? `${geo.lat}, ${geo.lon}` : "Address on file");
  const reasons = (rc.threat_reasons || th.reasons || [])
    .slice(0, 3)
    .map((r) => stripInternalApiRefs(String(r).trim()))
    .filter(Boolean);

  const evac = rc.evacuation_level ?? data.tampa_bay_regional?.evacuation?.evac_level ?? data.tampa_bay_regional?.evacuation?.evac_zone;
  const evacLine =
    evac != null && String(evac).trim() !== "" && String(evac) !== "—"
      ? `Evacuation zone on the map we use: <strong>${esc(String(evac))}</strong> — this is <em>not</em> an order to leave; confirm with your county.`
      : "";

  const pct = score != null ? Math.min(100, Math.max(0, score)) / 100 : 0;
  const dashOffset = DIAL_LEN * (1 - pct);
  const strokeUse = score != null ? theme.stroke : "#a3a3a3";

  const when = new Date().toLocaleString(undefined, { dateStyle: "long", timeStyle: "short" });
  const safeStub = loc.replace(/[^\w\s-]/g, "").trim().slice(0, 32).replace(/\s+/g, "-") || "home";

  const bullets =
    reasons.length > 0
      ? `<ul class="reasons">${reasons.map((r) => `<li>${esc(r.length > 200 ? `${r.slice(0, 197)}…` : r)}</li>`).join("")}</ul>`
      : `<p class="muted">No detailed bullet list in this run — the score still reflects blended public feeds for this location.</p>`;

  const scoreDisplay = score != null ? esc(String(score)) : "—";

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hurricane Hub — home snapshot</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=Plus+Jakarta+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet" />
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 2rem 1.5rem 3rem;
      font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif;
      color: #0a0a0a;
      background: #fafafa;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }
    .shell { max-width: 40rem; margin: 0 auto; }
    .card {
      background: #fff;
      border: 1px solid rgba(10, 10, 10, 0.08);
      border-radius: 14px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 24px 48px -16px rgba(0,0,0,0.08);
      padding: 1.75rem 1.65rem 1.85rem;
    }
    .kicker {
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #737373;
      margin: 0 0 0.35rem;
    }
    h1 {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 0.25rem;
      line-height: 1.2;
    }
    .sub {
      font-size: 0.875rem;
      color: #525252;
      margin: 0 0 1.5rem;
    }
    .hero {
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 1.35rem;
      align-items: center;
      padding: 1.25rem 0 1.35rem;
      border-top: 1px solid rgba(10,10,10,0.06);
      border-bottom: 1px solid rgba(10,10,10,0.06);
    }
    @media (max-width: 520px) {
      .hero { grid-template-columns: 1fr; justify-items: center; text-align: center; }
    }
    .dial-wrap { width: 120px; height: 120px; position: relative; }
    .dial-svg { display: block; width: 100%; height: 100%; }
    .dial-track { stroke: rgba(10,10,10,0.07); fill: none; stroke-width: 7; }
    .dial-arc { fill: none; stroke-width: 7; stroke-linecap: round; stroke: ${strokeUse}; stroke-dasharray: ${DIAL_LEN}; stroke-dashoffset: ${dashOffset}; }
    .dial-inner {
      position: absolute; inset: 0;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      pointer-events: none; padding-bottom: 4px;
    }
    .dial-val { font-family: "IBM Plex Mono", monospace; font-size: 2rem; font-weight: 500; letter-spacing: -0.06em; }
    .dial-denom { font-size: 0.65rem; font-weight: 600; color: #525252; letter-spacing: 0.06em; margin-top: 2px; }
    .dial-lbl { font-size: 0.6rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.12em; color: #737373; margin-top: 6px; }
    .badge {
      display: inline-block;
      font-size: 0.6875rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      border: 1px solid ${theme.badgeBorder};
      background: ${theme.badgeBg};
      color: ${theme.badgeColor};
      margin-top: 0.5rem;
    }
    .summary h2 {
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #737373;
      margin: 0 0 0.4rem;
    }
    .loc { font-size: 1.05rem; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 0.65rem; line-height: 1.35; }
    .reasons { margin: 0; padding-left: 1.1rem; font-size: 0.875rem; color: #525252; }
    .reasons li { margin-bottom: 0.35rem; }
    .evac {
      font-size: 0.875rem;
      color: #404040;
      margin: 1.15rem 0 0;
      padding: 0.85rem 1rem;
      background: rgba(250,250,250,0.9);
      border-radius: 10px;
      border: 1px solid rgba(10,10,10,0.06);
    }
    .muted { color: #525252; font-size: 0.8125rem; }
    .disclaimer {
      margin: 1.35rem 0 0;
      font-size: 0.8125rem;
      color: #525252;
      line-height: 1.5;
    }
    .foot {
      margin-top: 1.5rem;
      padding-top: 1.15rem;
      border-top: 1px solid rgba(10,10,10,0.08);
      font-size: 0.75rem;
      color: #737373;
    }
    .foot a { color: #0a0a0a; }
  </style>
</head>
<body>
  <div class="shell">
    <div class="card">
      <p class="kicker">Hurricane Hub · Tampa Bay</p>
      <h1>Home risk snapshot</h1>
      <p class="sub">For family · ${esc(when)} · Planning reference only</p>

      <div class="hero">
        <div class="dial-wrap">
          <svg class="dial-svg" viewBox="0 0 120 120" aria-hidden="true">
            <g transform="rotate(-90 60 60)">
              <circle class="dial-track" cx="60" cy="60" r="44" />
              <circle class="dial-arc" cx="60" cy="60" r="44" />
            </g>
          </svg>
          <div class="dial-inner">
            <span class="dial-val">${scoreDisplay}</span>
            <span class="dial-denom">/ 100</span>
            <span class="dial-lbl">Risk score</span>
          </div>
        </div>
        <div class="summary">
          <span class="badge">${esc(tierLabel)}</span>
          <h2>This location</h2>
          <p class="loc">${esc(loc)}</p>
          ${bullets}
        </div>
      </div>

      ${evacLine ? `<p class="evac">${evacLine}</p>` : ""}

      <p class="disclaimer">
        This score blends public weather, water, and road data for one point on the map. It is <strong>not</strong> a forecast,
        <strong>not</strong> an evacuation order, and <strong>not</strong> a substitute for
        <a href="https://www.weather.gov/tbw/">National Weather Service Tampa Bay</a> or your county emergency manager.
      </p>

      <p class="foot">
        Generated from <strong>Hurricane Hub</strong> (public-data prototype). Open this file in any browser to view; you can attach it to an email or save it to your phone.
      </p>
    </div>
  </div>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const day = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `hurricane-hub-home-report-${day}-${safeStub}.html`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
