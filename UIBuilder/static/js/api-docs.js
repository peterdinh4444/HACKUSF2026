const FETCH_JSON = { credentials: "same-origin", headers: { "Content-Type": "application/json" } };

document.getElementById("btn-generate-api-key")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-generate-api-key");
  const out = document.getElementById("api-key-reveal");
  const errEl = document.getElementById("api-key-error");
  if (!btn || !out) return;
  if (errEl) {
    errEl.textContent = "";
    errEl.hidden = true;
  }
  btn.disabled = true;
  out.textContent = "";
  out.hidden = true;
  try {
    const r = await fetch("/api/user/api-key", { method: "POST", ...FETCH_JSON, body: "{}" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (r.status === 401) {
        window.location.href = j.login_url || `/login?next=${encodeURIComponent("/data-api")}`;
        return;
      }
      if (errEl) {
        errEl.textContent = j.error || "Could not create a key.";
        errEl.hidden = false;
      }
      return;
    }
    if (j.api_key) {
      out.textContent = j.api_key;
      out.hidden = false;
    }
  } catch {
    if (errEl) {
      errEl.textContent = "Network error — try again.";
      errEl.hidden = false;
    }
  } finally {
    btn.disabled = false;
  }
});
