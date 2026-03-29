/** Floating “Ask about this page” — POST /api/assistant/chat with live JSON context. */

const FETCH_OPTS = { credentials: "same-origin" };

/**
 * @param {"dashboard"|"home_risk"} expectedPage
 * @param {() => Record<string, unknown>} getContext
 */
export function initAssistantDock(expectedPage, getContext) {
  const root = document.getElementById("assistant-root");
  if (!root) return;
  const page = root.getAttribute("data-page") || "";
  if (page !== expectedPage) return;

  const toggle = root.querySelector("#assistant-toggle");
  const panel = root.querySelector("#assistant-panel");
  const closeBtn = root.querySelector("#assistant-close");
  const messagesEl = root.querySelector("#assistant-messages");
  const form = root.querySelector("#assistant-form");
  const input = root.querySelector("#assistant-input");
  const sendBtn = root.querySelector("#assistant-send");
  const statusEl = root.querySelector("#assistant-status");

  /** @type {{ role: string, content: string }[]} */
  let history = [];

  function setOpen(open) {
    if (!panel) return;
    panel.hidden = !open;
    root.classList.toggle("assistant-root--open", open);
    toggle?.setAttribute("aria-expanded", open ? "true" : "false");
    if (toggle) {
      if (open) {
        toggle.hidden = true;
      } else {
        window.setTimeout(() => {
          toggle.hidden = false;
          toggle.focus();
        }, 0);
      }
    }
    if (open) input?.focus();
  }

  toggle?.addEventListener("click", () => {
    const willOpen = panel?.hidden !== false;
    setOpen(willOpen);
  });
  closeBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && root.classList.contains("assistant-root--open")) setOpen(false);
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
    body.textContent = text;
    wrap.appendChild(lab);
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = (input?.value || "").trim();
    if (!text || !sendBtn) return;

    const ctx = typeof getContext === "function" ? getContext() : {};
    appendBubble("user", text);
    history.push({ role: "user", content: text });
    input.value = "";
    sendBtn.disabled = true;
    if (statusEl) statusEl.textContent = "Thinking…";

    try {
      const res = await fetch("/api/assistant/chat", {
        ...FETCH_OPTS,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page,
          context: ctx && typeof ctx === "object" ? ctx : {},
          messages: history.slice(0, -1),
          message: text,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        window.location.href = data.login_url || `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!res.ok) {
        history.pop();
        messagesEl?.lastElementChild?.remove();
        if (statusEl) statusEl.textContent = data.error || res.statusText || "Something went wrong.";
        return;
      }
      const reply = data.reply || "";
      history.push({ role: "assistant", content: reply });
      appendBubble("assistant", reply);
      if (statusEl) statusEl.textContent = "";
    } catch (err) {
      history.pop();
      messagesEl?.lastElementChild?.remove();
      if (statusEl) statusEl.textContent = String(err?.message || err);
    } finally {
      sendBtn.disabled = false;
    }
  });
}
