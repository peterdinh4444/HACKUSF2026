/**
 * One-line summaries for each "Show me…" topic + Ask AI (brief Claude summary).
 */

import { formatAssistantReplyHtml } from "./assistant-markup.js";

const FETCH_OPTS = { credentials: "same-origin" };

/** @param {HTMLButtonElement | null} btn */
function topicsAlreadyFetched(btn) {
  return new Set((btn?.dataset.aiTopicsUsed || "").split("|").filter(Boolean));
}

/** @param {HTMLButtonElement | null} btn */
function markTopicFetched(btn, topic) {
  if (!btn || !topic) return;
  const s = topicsAlreadyFetched(btn);
  s.add(topic);
  btn.dataset.aiTopicsUsed = [...s].join("|");
}

/** @param {HTMLButtonElement | null} btn */
export function clearAskAiTopicHistory(btn) {
  if (btn) delete btn.dataset.aiTopicsUsed;
}

/** Short hint shown under the topic dropdown for each option. */
export const TOPIC_SUMMARIES = {
  alerts:
    "NWS bulletins active near you, flood-tagged alerts, and short-term rain odds from the forecast grid.",
  coastal: "Tide vs a recent average plus nearby sea / buoy context — not a surge forecast.",
  weather: "Modeled rain totals for the next day or two and peak wind gusts from blended models.",
  rivers: "River gauge stages upstream of your point for inland flood context.",
  terrain: "Approximate ground elevation — lower areas can pond or take surge differently.",
  tds: "How the app’s risk score is built: weights, hazard strengths, and what moved the number.",
  evac: "Evacuation zone from county or state GIS — planning reference only, not an order to leave.",
  traffic: "Road incidents and closures near you from public feeds — always confirm on FL511.",
  local: "ZIP-level planning notes plus regional power and traffic snapshots.",
};

function isLoggedIn() {
  return document.body?.getAttribute("data-logged-in") === "1";
}

/**
 * @param {string | null} topicKey
 * @param {HTMLElement | null} summaryEl
 * @param {HTMLElement | null} aiBlockEl
 * @param {HTMLElement | null} guestEl
 * @param {HTMLElement | null} loggedEl
 * @param {HTMLElement | null} outEl
 * @param {{ snapshotLowTier?: boolean }} [opts]
 */
export function refreshTopicSummaryRow(topicKey, summaryEl, aiBlockEl, guestEl, loggedEl, outEl, opts) {
  if (!summaryEl || !aiBlockEl) return;
  if (!topicKey) {
    summaryEl.hidden = true;
    aiBlockEl.hidden = true;
    if (outEl) {
      outEl.hidden = true;
      outEl.replaceChildren();
    }
    return;
  }
  const low = opts?.snapshotLowTier === true;
  const base = TOPIC_SUMMARIES[topicKey] || "";
  summaryEl.textContent = low
    ? `Green (low) band on your score — nothing here looks urgent from this app’s data. ${base}`
    : base;
  summaryEl.hidden = false;
  aiBlockEl.hidden = false;
  if (outEl) {
    outEl.hidden = true;
    outEl.replaceChildren();
  }
  const li = isLoggedIn();
  if (guestEl) guestEl.hidden = li;
  if (loggedEl) loggedEl.hidden = !li;
}

/**
 * Disable Ask AI when logged out, no data, or a summary was already loaded for the current topic.
 * @param {HTMLButtonElement | null} btn
 * @param {() => string} getTopic
 * @param {() => unknown} getContext
 */
export function syncTopicAiButtonState(btn, getTopic, getContext) {
  if (!btn) return;
  const topic = (getTopic() || "").trim();
  const ctx = getContext();
  const li = document.body?.getAttribute("data-logged-in") === "1";
  const baseOff = !li || !topic || ctx == null;
  const used = Boolean(topic && topicsAlreadyFetched(btn).has(topic));
  btn.disabled = baseOff || used;
}

/**
 * @param {HTMLButtonElement | null} btn
 * @param {{ page: string, getTopic: () => string, getContext: () => Record<string, unknown> | null, outEl: HTMLElement | null }} opts
 */
export function bindTopicAiButton(btn, { page, getTopic, getContext, outEl }) {
  if (!btn || !outEl) return;
  btn.addEventListener("click", async () => {
    const topic = getTopic();
    const context = getContext();
    if (!topic || !context) return;
    if (topicsAlreadyFetched(btn).has(topic)) {
      outEl.hidden = false;
      outEl.classList.remove("dash-detail-ai-out--err");
      outEl.innerHTML = `<p class="muted dash-detail-ai-out__text">Ask AI already ran for this topic on this page. Refresh the snapshot or reload the page for a new paid summary.</p>`;
      return;
    }
    btn.disabled = true;
    outEl.classList.remove("dash-detail-ai-out--err");
    outEl.hidden = false;
    outEl.innerHTML = `<p class="muted dash-detail-ai-out__loading">Loading a short summary…</p>`;
    try {
      const res = await fetch("/api/assistant/topic-summary", {
        ...FETCH_OPTS,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page, topic, context }),
      });
      const raw = await res.text();
      let data = {};
      try {
        data = JSON.parse(raw);
      } catch {
        data = {};
      }
      if (res.status === 401) {
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!res.ok) {
        const err = typeof data.error === "string" ? data.error : raw.slice(0, 200) || `Error (${res.status})`;
        outEl.classList.add("dash-detail-ai-out--err");
        outEl.innerHTML = `<p class="dash-detail-ai-out__text">${escapeHtml(err)}</p>`;
        return;
      }
      const reply = typeof data.reply === "string" ? data.reply.trim() : "";
      if (!reply) {
        outEl.classList.add("dash-detail-ai-out--err");
        outEl.innerHTML = `<p class="dash-detail-ai-out__text">No summary returned.</p>`;
        return;
      }
      const wrap = document.createElement("div");
      wrap.className = "assistant-msg__body assistant-msg__body--md dash-detail-ai-out__md";
      wrap.innerHTML = formatAssistantReplyHtml(reply);
      outEl.replaceChildren(wrap);
      markTopicFetched(btn, topic);
    } catch (e) {
      outEl.classList.add("dash-detail-ai-out--err");
      outEl.innerHTML = `<p class="dash-detail-ai-out__text">${escapeHtml(String(e?.message || e))}</p>`;
    } finally {
      syncTopicAiButtonState(btn, getTopic, getContext);
    }
  });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
