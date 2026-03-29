/** Mounts the floating guide on every logged-in page; page-specific scripts register context via window. */
import { initAssistantDock } from "./assistant-chat.js";

function getAssistantContext() {
  if (typeof window.__hurricaneHubAssistantContext === "function") {
    try {
      const c = window.__hurricaneHubAssistantContext();
      if (c && typeof c === "object") return c;
    } catch {
      /* ignore */
    }
  }
  return {
    site_path: typeof window !== "undefined" ? window.location.pathname : "/",
    note: "No live dashboard or home snapshot is wired on this page — use general Tampa Bay readiness guidance.",
  };
}

function mountAssistantDock() {
  const root = document.getElementById("assistant-root");
  if (root && root.parentElement !== document.body) {
    document.body.appendChild(root);
  }
  initAssistantDock(getAssistantContext);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAssistantDock, { once: true });
} else {
  mountAssistantDock();
}
