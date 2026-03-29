/** Floating “Ask about this page” — sends current page context to the assistant. */

import { attachAddressAutocomplete } from "./address-autocomplete.js";
import { formatAssistantReplyHtml } from "./assistant-markup.js";

const FETCH_OPTS = { credentials: "same-origin" };
const CHAT_TIMEOUT_MS = 120_000;

/**
 * @param {"dashboard"|"home_risk"|"general"|"evacuation"|"notifications"} page
 * @param {Record<string, unknown>} ctx
 * @returns {{ label: string, text: string }[]}
 */
export function buildStarterPrompts(page, ctx) {
  const starters = [];

  if (page === "evacuation") {
    const reg = ctx?.tampa_bay_regional;
    const ev = reg?.evacuation || {};
    const tn = reg?.traffic_near_home;
    const zone = ev.evac_level != null ? String(ev.evac_level) : ev.evac_zone != null ? String(ev.evac_zone) : "none matched";
    const nTraffic = tn?.total_nearby != null ? String(tn.total_nearby) : "unknown";
    const loc = ctx?.reference_coordinates || {};
    const locBit =
      loc.latitude != null && loc.longitude != null
        ? ` Pin ~${Number(loc.latitude).toFixed(3)}°, ${Number(loc.longitude).toFixed(3)}°.`
        : "";
    starters.push({
      label: "How to read this page",
      text: `Evacuation & traffic view.${locBit} Zone from GIS: ${zone}. Nearby road reports in the buffer: ${nTraffic}. In 3–4 sentences: how should I use this with county orders and FL511 — without treating the app as an evacuation order?`,
    });
    starters.push({
      label: "Traffic vs leaving home",
      text: `Same snapshot: ${nTraffic} nearby traffic-related features. What should I double-check on FL511 and local news before I drive, in one short paragraph?`,
    });
    starters.push({
      label: "If officials issue an order",
      text: "If my county issues an evacuation, what is a sensible order of steps (alerts, route, fuel, dependents) — one checklist, no specific roads from this app.",
    });
    return starters;
  }

  if (page === "notifications") {
    starters.push({
      label: "Reading these headlines",
      text: "These lines come from our ingested news database — not official alerts. In 3–4 sentences: how should I triage them with NWS Tampa Bay and my county?",
    });
    starters.push({
      label: "Email options",
      text: "Explain the two email options and the sample evacuation email in plain language. Remind me this is still not an official warning system.",
    });
    return starters;
  }

  if (page === "general") {
    const path = typeof ctx?.site_path === "string" ? ctx.site_path : "";
    starters.push({
      label: "What can I do here?",
      text: "In 2–3 sentences: what is Hurricane Hub for, and what should I never use it for? Mention Dashboard vs Home risk briefly.",
    });
    starters.push({
      label: "Official sources",
      text: "List the top 3 official Tampa Bay storm sources I should bookmark, in one short paragraph.",
    });
    if (path) starters.push({ label: "This page", text: `I'm on path ${path}. What should I read next in this app? Keep it brief.` });
    return starters;
  }

  if (page === "dashboard") {
    const d = ctx?.dashboard;
    const note = typeof ctx?.note === "string" ? ctx.note : "";
    if (!d) {
      starters.push({
        label: "General readiness (data still loading)",
        text: "My dashboard snapshot is still loading or failed. What are 3 practical hurricane-season checks I should do anyway, and where is official Tampa Bay info?",
      });
      if (note) starters[0].text += ` (${note})`;
      return starters;
    }
    const th = d.threat || {};
    const score = th.score != null ? String(th.score) : "—";
    const tierRaw = th.tier != null ? String(th.tier) : "—";
    const tierLow = tierRaw.toLowerCase() === "low";
    const loc = d.location || {};
    const locBit =
      loc.latitude != null && loc.longitude != null
        ? ` Reference coordinates about ${Number(loc.latitude).toFixed(3)}°, ${Number(loc.longitude).toFixed(3)}°.`
        : "";
    if (tierLow) {
      starters.push({
        label: "Green band — am I OK?",
        text: `My dashboard shows risk score ${score}/100 in the low (green) tier.${locBit} Does that mean nothing here looks worrisome from this app's data, and what tiny habit should I still keep with NWS/county? Answer in 2–4 short sentences.`,
      });
      starters.push({
        label: "What “low” does not mean",
        text: `Same green-tier dashboard (score ${score}/100). What should I still not assume, in one short paragraph?`,
      });
    } else {
      starters.push({
        label: "Top checks from this score",
        text: `Dashboard only: score ${score}/100, tier "${tierRaw}".${locBit} What are 2–3 things to verify with NWS or county? Be brief.`,
      });
      starters.push({
        label: "Rain, wind, water",
        text: `Same view (score ${score}/100, tier "${tierRaw}"). What should I watch locally — one short paragraph. Planning aid only.`,
      });
    }
    return starters;
  }

  if (page === "home_risk") {
    const a = ctx?.assessment;
    const note = typeof ctx?.note === "string" ? ctx.note : "";
    if (!a) {
      starters.push({
        label: "Before an assessment loads",
        text: "No home assessment on screen yet. What should I gather while I run one? One short paragraph; name official Tampa Bay sources.",
      });
      if (note) starters[0].text += ` (${note})`;
      return starters;
    }
    const rc = a.risk_card || {};
    const th = a.dashboard?.threat || {};
    const score = rc.threat_score ?? th.score;
    const tier = rc.threat_tier ?? th.tier;
    const tierStr = tier != null ? String(tier) : "—";
    const tierLow = tierStr.toLowerCase() === "low";
    const geo = a.geocode || {};
    const addr = geo.display_name || "this address";
    const scoreStr = score != null ? String(score) : "—";
    const zip = a.matched_zip != null ? String(a.matched_zip) : "";
    const zipBit = zip ? ` ZIP ${zip}.` : "";
    if (tierLow) {
      starters.push({
        label: "Green band at our home",
        text: `Home snapshot for ${addr}.${zipBit} Score ${scoreStr}/100, tier low (green). Confirm we're fine from this app's perspective and what to still check officially — 2–4 short sentences.`,
      });
      starters.push({
        label: "Routine habits",
        text: `Same low-tier home view (${addr}). One short paragraph: good habits during hurricane season without being alarmist.`,
      });
    } else {
      starters.push({
        label: "What this means for us",
        text: `Home snapshot for ${addr}.${zipBit} Score ${scoreStr}/100, tier "${tierStr}". Plain language in one short paragraph: what to verify officially.`,
      });
      starters.push({
        label: "Evacuation questions",
        text: `Same snapshot (${addr}). What should we ask our county emergency manager — without treating this app as an order to leave? Brief.`,
      });
    }
    return starters;
  }

  return starters;
}

function parseJsonSafe(raw) {
  if (!raw || !raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { _unparsed: true };
  }
}

function errorFromResponse(res, data, raw) {
  if (data && typeof data.error === "string" && data.error.trim()) return data.error.trim();
  if (data && data.error && typeof data.error.message === "string") return data.error.message;
  if (data && typeof data.message === "string" && data.message.trim()) return data.message.trim();
  if (data && data._unparsed && raw) return raw.trim().slice(0, 280) || `HTTP ${res.status}`;
  return res.statusText || `Request failed (${res.status})`;
}

/**
 * @param {() => Record<string, unknown>} getContext
 */
export function initAssistantDock(getContext) {
  const root = document.getElementById("assistant-root");
  if (!root) return;
  if (root.dataset.assistantBound === "1") return;
  root.dataset.assistantBound = "1";

  const page = (root.getAttribute("data-page") || "general").trim();

  const toggle = root.querySelector("#assistant-toggle");
  const panel = root.querySelector("#assistant-panel");
  const closeBtn = root.querySelector("#assistant-close");
  const expandBtn = root.querySelector("#assistant-expand");
  const messagesEl = root.querySelector("#assistant-messages");
  const startersEl = root.querySelector("#assistant-starters");
  const startersLabel = root.querySelector("#assistant-starters-label");
  const form = root.querySelector("#assistant-form");
  const input = root.querySelector("#assistant-input");
  const sendBtn = root.querySelector("#assistant-send");
  const statusEl = root.querySelector("#assistant-status");

  /** @type {{ role: string, content: string }[]} */
  let history = [];

  const addressWrap = document.getElementById("assistant-address-wrap");
  const addrInput = document.getElementById("assistant-addr-input");
  const addrSubmit = document.getElementById("assistant-addr-submit");
  let assistantAddressAcTeardown = () => {};
  let assistantAddressAcAttached = false;

  function ensureAssistantAddressAutocomplete() {
    if (page !== "home_risk" || !addrInput || assistantAddressAcAttached) return;
    assistantAddressAcTeardown = attachAddressAutocomplete(addrInput, { minChars: 3, debounceMs: 280 });
    assistantAddressAcAttached = true;
  }

  function prefillAssistantAddress() {
    if (!addrInput || page !== "home_risk") return;
    if (addrInput.value.trim()) return;
    const main = document.getElementById("addr");
    if (main?.value?.trim()) {
      addrInput.value = main.value.trim();
      return;
    }
    try {
      const ctx = typeof getContext === "function" ? getContext() : {};
      const g = ctx?.assessment?.geocode?.display_name;
      if (g) addrInput.value = String(g);
    } catch {
      /* ignore */
    }
  }

  function showAssistantAddressBar() {
    if (!addressWrap || page !== "home_risk") return;
    addressWrap.hidden = false;
    ensureAssistantAddressAutocomplete();
    prefillAssistantAddress();
    addrInput?.focus();
  }

  function setStatus(msg, isError = false) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("assistant-status--err", Boolean(isError && msg));
  }

  function refreshStarters() {
    if (!startersEl) return;
    let starters = [];
    try {
      const ctx = typeof getContext === "function" ? getContext() : {};
      starters = buildStarterPrompts(page, ctx);
    } catch {
      starters = [
        {
          label: "General readiness",
          text: "What are the most important official sources I should use for Tampa Bay storms, and how should I use this app alongside them?",
        },
      ];
    }
    startersEl.innerHTML = "";
    starters.forEach((s) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "assistant-starter btn btn--sm btn--ghost";
      b.textContent = s.label;
      b.addEventListener("click", () => {
        if (input) {
          input.value = s.text;
          input.focus();
        }
      });
      startersEl.appendChild(b);
    });
    startersEl.hidden = starters.length === 0;
    if (startersLabel) startersLabel.hidden = starters.length === 0;
  }

  function setExpanded(expanded) {
    if (!panel) return;
    panel.classList.toggle("assistant-panel--expanded", expanded);
    expandBtn?.setAttribute("aria-pressed", expanded ? "true" : "false");
    if (expandBtn) expandBtn.textContent = expanded ? "Shrink" : "Expand";
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  /** Location modal, address dropdowns, etc. — keeps one overlay stack. */
  function dismissExternalOverlays() {
    document.dispatchEvent(new CustomEvent("hurricanehub-close-overlays", { bubbles: true }));
  }

  /** Single source of truth: #assistant-root gets .assistant-root--open; CSS shows/hides panel + backdrop. */
  function assistantIsOpen() {
    return root.classList.contains("assistant-root--open");
  }

  function setAssistantOpen(open) {
    if (!panel) return;
    if (open) {
      dismissExternalOverlays();
      setExpanded(false);
    } else {
      if (addressWrap) addressWrap.hidden = true;
      setExpanded(false);
    }
    root.classList.toggle("assistant-root--open", Boolean(open));
    root.dataset.assistantOpen = open ? "1" : "0";
    toggle?.setAttribute("aria-expanded", open ? "true" : "false");
    const label = open ? "Close guide" : "Open guide";
    if (toggle) {
      toggle.setAttribute("aria-label", label);
      toggle.title = label;
    }
    if (open) {
      refreshStarters();
      input?.focus();
    } else {
      toggle?.focus();
    }
  }

  refreshStarters();

  function onFabClick(e) {
    e.preventDefault();
    e.stopPropagation();
    setAssistantOpen(!assistantIsOpen());
  }

  function onCloseClick(e) {
    e.preventDefault();
    e.stopPropagation();
    setAssistantOpen(false);
  }

  toggle?.addEventListener("click", onFabClick);
  closeBtn?.addEventListener("click", onCloseClick);

  expandBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !panel?.classList.contains("assistant-panel--expanded");
    setExpanded(next);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && assistantIsOpen()) setAssistantOpen(false);
  });

  const loadBtn = document.getElementById("assistant-btn-load");

  async function runAssistantPanelAssess() {
    if (!addrInput || page !== "home_risk") return;
    const addr = addrInput.value.trim();
    if (addr.length < 4) {
      setStatus("Enter at least 4 characters.", true);
      addrInput.focus();
      return;
    }
    setStatus("Running assessment…", false);
    addrSubmit?.setAttribute("disabled", "true");
    try {
      await new Promise((resolve, reject) => {
        window.dispatchEvent(
          new CustomEvent("hurricanehub-assistant-assess-address", {
            detail: {
              address: addr,
              done: (err) => (err ? reject(err) : resolve()),
            },
          })
        );
      });
      refreshStarters();
      appendNote("Assessment updated from the address bar. Quick questions match this snapshot.");
      setStatus("", false);
    } catch (err) {
      const msg = err?.message || String(err);
      setStatus(msg, true);
      appendNote(`Could not assess: ${msg}`);
    } finally {
      addrSubmit?.removeAttribute("disabled");
    }
  }

  addrSubmit?.addEventListener("click", () => runAssistantPanelAssess());
  addrInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      runAssistantPanelAssess();
    }
  });

  function appendBubble(role, text) {
    if (!messagesEl) return;
    const wrap = document.createElement("div");
    wrap.className = `assistant-msg assistant-msg--${role}`;
    const lab = document.createElement("div");
    lab.className = "assistant-msg__label";
    lab.textContent = role === "user" ? "You" : "Guide";
    const body = document.createElement("div");
    body.className = "assistant-msg__body";
    if (role === "assistant") {
      body.classList.add("assistant-msg__body--md");
      body.innerHTML = formatAssistantReplyHtml(text);
    } else {
      body.textContent = text;
    }
    wrap.appendChild(lab);
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendNote(text) {
    if (!messagesEl || !text) return;
    const wrap = document.createElement("div");
    wrap.className = "assistant-msg assistant-msg--note";
    const lab = document.createElement("div");
    lab.className = "assistant-msg__label";
    lab.textContent = "Hub";
    const body = document.createElement("div");
    body.className = "assistant-msg__body";
    body.textContent = text;
    wrap.appendChild(lab);
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  loadBtn?.addEventListener("click", async () => {
    if (page === "general" || page === "notifications") return;
    loadBtn.disabled = true;
    history = [];
    if (messagesEl) messagesEl.innerHTML = "";
    if (input) input.value = "";
    setStatus("", false);

    if (page === "home_risk") {
      showAssistantAddressBar();
    }

    const statusMsg =
      page === "dashboard"
        ? "Refreshing dashboard…"
        : page === "evacuation"
          ? "Refreshing evacuation & traffic…"
          : "Loading assessment…";
    setStatus(statusMsg, false);

    /** @type {{ ok?: boolean; message?: string }} */
    let result = { ok: true };
    if (page === "dashboard") {
      result =
        (await new Promise((resolve) => {
          window.dispatchEvent(new CustomEvent("hurricanehub-chat-load-dashboard", { detail: { done: resolve } }));
        })) || {};
    } else if (page === "evacuation") {
      result =
        (await new Promise((resolve) => {
          window.dispatchEvent(new CustomEvent("hurricanehub-evacuation-reload", { detail: { done: resolve } }));
        })) || {};
    } else {
      result =
        (await new Promise((resolve) => {
          window.dispatchEvent(new CustomEvent("hurricanehub-chat-load-home", { detail: { done: resolve } }));
        })) || {};
    }

    refreshStarters();

    if (result.ok === false && result.message === "no-input") {
      if (page === "home_risk") {
        appendNote(
          "Use the short address bar above (same suggestions as the main form), tap Assess, or open a saved home on the page."
        );
      }
    } else if (result.ok === false && result.message) {
      appendNote(`Could not refresh: ${result.message}`);
    } else if (result.ok === false) {
      appendNote(
        page === "dashboard"
          ? "Dashboard did not load — check the page above, then try again."
          : page === "evacuation"
            ? "Evacuation page did not refresh — check the page above, then try again."
            : "Assessment did not refresh — check the form or saved home above."
      );
    } else {
      appendNote(
        page === "dashboard"
          ? "Dashboard snapshot is refreshed. Quick questions and your next message use this data."
          : page === "evacuation"
            ? "Evacuation & traffic snapshot is refreshed for the guide."
            : "Assessment is loaded for the guide. Use quick questions or type below."
      );
    }

    setStatus("", false);
    loadBtn.disabled = false;
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = (input?.value || "").trim();
    if (!text || !sendBtn) return;

    const ctx = typeof getContext === "function" ? getContext() : {};
    let bodyStr;
    try {
      bodyStr = JSON.stringify({
        page,
        context: ctx && typeof ctx === "object" ? ctx : {},
        messages: history,
        message: text,
      });
    } catch (err) {
      setStatus("Could not package this page for the guide — try refreshing.", true);
      return;
    }

    appendBubble("user", text);
    history.push({ role: "user", content: text });
    input.value = "";
    sendBtn.disabled = true;
    setStatus("Thinking…", false);

    const ac = new AbortController();
    const timer = window.setTimeout(() => ac.abort(), CHAT_TIMEOUT_MS);

    try {
      const res = await fetch("/api/assistant/chat", {
        ...FETCH_OPTS,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: bodyStr,
        signal: ac.signal,
      });

      const raw = await res.text();
      const data = parseJsonSafe(raw);

      if (res.status === 401) {
        history.pop();
        messagesEl?.lastElementChild?.remove();
        setStatus("", false);
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }

      if (!res.ok) {
        history.pop();
        messagesEl?.lastElementChild?.remove();
        setStatus(errorFromResponse(res, data, raw), true);
        return;
      }

      const reply = typeof data.reply === "string" ? data.reply.trim() : "";
      if (!reply) {
        history.pop();
        messagesEl?.lastElementChild?.remove();
        setStatus(errorFromResponse(res, data, raw) || "No answer came back — try again.", true);
        return;
      }

      history.push({ role: "assistant", content: reply });
      appendBubble("assistant", reply);
      setStatus("", false);
    } catch (err) {
      history.pop();
      messagesEl?.lastElementChild?.remove();
      const name = err && err.name;
      if (name === "AbortError") {
        setStatus("That took too long — try a shorter question or check your connection.", true);
      } else {
        setStatus(String(err?.message || err), true);
      }
    } finally {
      window.clearTimeout(timer);
      sendBtn.disabled = false;
    }
  });
}
