/** Shared 0–100 score dial (SVG ring + tier styling). */
const DIAL_R = 44;
const DIAL_C = 2 * Math.PI * DIAL_R;

/**
 * @param {HTMLElement | null} rootEl - .score-dial
 * @param {unknown} score
 * @param {string | undefined} tier
 */
export function renderScoreDial(rootEl, score, tier) {
  if (!rootEl) return;
  const t = (tier || "low").toLowerCase();
  const tierClass = t === "elevated" ? "elevated" : t;
  rootEl.dataset.tier = tierClass;
  rootEl.classList.remove("score-dial--low", "score-dial--elevated", "score-dial--high", "score-dial--extreme");
  rootEl.classList.add(`score-dial--${tierClass}`);

  const valueEl = rootEl.querySelector(".score-dial__value");
  const arc = rootEl.querySelector(".score-dial__arc");
  const n = score != null && Number.isFinite(Number(score)) ? Math.round(Number(score)) : null;
  if (valueEl) valueEl.textContent = n != null ? String(n) : "—";
  const pct = n != null ? Math.max(0, Math.min(100, n)) : 0;
  if (arc) {
    arc.style.strokeDasharray = String(DIAL_C);
    arc.style.strokeDashoffset = String(DIAL_C * (1 - pct / 100));
  }
  const tierLabel = tierClass.charAt(0).toUpperCase() + tierClass.slice(1);
  const aria =
    n != null
      ? `Readiness index ${n} out of 100. ${tierLabel} concern tier.`
      : "Readiness index not available.";
  rootEl.setAttribute("aria-label", aria);
}
