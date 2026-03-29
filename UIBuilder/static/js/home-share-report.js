/**
 * PDF report download — POSTs assessment data to the server and triggers a PDF download.
 */

/**
 * @param {Record<string, unknown>} data — full home assessment payload (same as lastAssessment)
 */
export async function downloadShareReport(data) {
  if (!data || typeof data !== "object") return;

  const btn = document.getElementById("btn-download-share-report");
  const origText = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = "Generating PDF…"; }

  try {
    const res = await fetch("/api/report/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assessment: data }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.error || `Could not generate PDF (${res.status}). Make sure you are signed in.`);
      return;
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const day = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `hurricane-hub-report-${day}.pdf`;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}
