import { formatNewsBriefHtml } from "./assistant-markup.js";

const FETCH_JSON = {
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
};

function show(el, text, persist = false) {
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
  if (!persist) {
    window.setTimeout(() => {
      el.hidden = true;
    }, 7000);
  }
}

document.getElementById("form-notification-prefs")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const tier = document.getElementById("notif-tier")?.checked ?? false;
  const evac = document.getElementById("notif-evac")?.checked ?? false;
  const st = document.getElementById("notif-pref-status");
  const btn = document.getElementById("btn-save-notification-prefs");
  btn.disabled = true;
  try {
    const r = await fetch("/api/user/notification-prefs", {
      method: "POST",
      ...FETCH_JSON,
      body: JSON.stringify({ tier_alerts: tier, evacuation_alerts: evac }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      show(st, j.error || "Could not save.", true);
      return;
    }
    let msg = "Preferences saved.";
    if (tier || evac) {
      msg += j.confirmation_email_sent
        ? " Check your inbox for a confirmation."
        : " (Confirmation email not sent — check mail settings or verification.)";
    }
    show(st, msg);
  } catch {
    show(st, "Network error — try again.", true);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-evac-sample-email")?.addEventListener("click", async () => {
  const st = document.getElementById("notif-sample-status");
  const btn = document.getElementById("btn-evac-sample-email");
  btn.disabled = true;
  try {
    const r = await fetch("/api/user/evacuation-alert-test-email", {
      method: "POST",
      ...FETCH_JSON,
      body: "{}",
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      show(st, j.error || "Could not send sample.", true);
      return;
    }
    show(st, `Sample sent (check inbox for ${j.sent_to || "your address"}).`);
  } catch {
    show(st, "Network error — try again.", true);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-refresh-news-feed")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-refresh-news-feed");
  btn.disabled = true;
  try {
    const r = await fetch("/api/news/refresh", { method: "POST", credentials: "same-origin" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      window.alert(j.error || "Could not queue refresh");
      return;
    }
    window.setTimeout(() => window.location.reload(), 2000);
  } catch {
    window.alert("Network error");
  } finally {
    btn.disabled = false;
  }
});

function readNotificationsMeta() {
  const el = document.getElementById("notifications-page-meta");
  if (!el?.textContent) return {};
  try {
    return JSON.parse(el.textContent);
  } catch {
    return {};
  }
}

const _notifMeta = readNotificationsMeta();

window.__hurricaneHubAssistantContext = () => ({
  site_path: "/notifications",
  news_feed_summary: _notifMeta,
  reader_location: _notifMeta.reader_location,
  page_note:
    "Alerts & news: use Save email preferences to opt in; headlines are ranked from the SQLite news_feed_items table using saved-home hints when they match article text (background ingest).",
});

document.getElementById("btn-ai-news-brief")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-ai-news-brief");
  const wrap = document.getElementById("news-ai-brief");
  const briefEl = document.getElementById("news-ai-brief-text");
  btn.disabled = true;
  if (briefEl) {
    briefEl.classList.remove("assistant-msg__body--md");
    briefEl.textContent = "Generating…";
  }
  wrap.hidden = false;
  try {
    const r = await fetch("/api/news/ai-brief", { method: "POST", credentials: "same-origin" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (briefEl) briefEl.textContent = j.error || "Could not generate summary.";
      return;
    }
    if (briefEl) {
      briefEl.classList.add("assistant-msg__body--md");
      briefEl.innerHTML = formatNewsBriefHtml(j.brief || "");
    }
  } catch {
    if (briefEl) {
      briefEl.classList.remove("assistant-msg__body--md");
      briefEl.textContent = "Network error.";
    }
  } finally {
    btn.disabled = false;
  }
});
