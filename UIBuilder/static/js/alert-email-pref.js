/** Logged-in: POST current threat tier for optional tier-increase emails (prefs saved on Alerts & news page). */

const ALLOWED_TIERS = new Set(["low", "elevated", "high", "extreme"]);

export function postThreatTierWatch(tier, score) {
  if (document.body?.getAttribute("data-logged-in") !== "1") return;
  const t = String(tier || "").trim().toLowerCase();
  if (!ALLOWED_TIERS.has(t)) return;
  void fetch("/api/user/threat-tier-watch", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier: t, score: score ?? null }),
  });
}
