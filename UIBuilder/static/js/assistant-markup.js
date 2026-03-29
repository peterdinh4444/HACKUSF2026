/**
 * Safe subset of Markdown-style formatting for guide replies (HTML-escape first, then inline tags).
 * Not a full Markdown parser — avoids XSS by never trusting raw HTML from the model.
 */

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/**
 * Inline **bold**, *italic*, `code` on an already-HTML-escaped string.
 */
function inlineFormat(escaped) {
  let t = escaped;
  const codes = [];
  t = t.replace(/`([^`]+)`/g, (_, inner) => {
    const i = codes.length;
    codes.push(`<code class="assistant-md-code">${inner}</code>`);
    return `@@CODEPH${i}@@`;
  });
  t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  t = t.replace(/@@CODEPH(\d+)@@/g, (_, idx) => codes[Number(idx)] || "");
  return t;
}

/**
 * @param {string} raw
 * @returns {string} HTML fragment safe to assign to innerHTML inside a sandboxed subtree
 */
export function formatAssistantReplyHtml(raw) {
  if (!raw) return "";
  const lines = String(raw).split(/\r?\n/);
  const parts = [];
  let listOpen = false;

  const closeList = () => {
    if (listOpen) {
      parts.push("</ul>");
      listOpen = false;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("### ")) {
      closeList();
      parts.push(`<h4 class="assistant-md-h assistant-md-h--3">${inlineFormat(escapeHtml(trimmed.slice(4)))}</h4>`);
      continue;
    }
    if (trimmed.startsWith("## ")) {
      closeList();
      parts.push(`<h4 class="assistant-md-h assistant-md-h--2">${inlineFormat(escapeHtml(trimmed.slice(3)))}</h4>`);
      continue;
    }
    if (trimmed.startsWith("# ") && !trimmed.startsWith("##")) {
      closeList();
      parts.push(`<h4 class="assistant-md-h">${inlineFormat(escapeHtml(trimmed.slice(2)))}</h4>`);
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      if (!listOpen) {
        parts.push('<ul class="assistant-md-ul">');
        listOpen = true;
      }
      const item = trimmed.replace(/^[-*]\s+/, "");
      parts.push(`<li class="assistant-md-li">${inlineFormat(escapeHtml(item))}</li>`);
      continue;
    }

    closeList();

    if (trimmed === "") {
      parts.push('<div class="assistant-md-br" aria-hidden="true"></div>');
      continue;
    }

    parts.push(`<p class="assistant-md-p">${inlineFormat(escapeHtml(line))}</p>`);
  }

  closeList();
  return parts.join("");
}

/**
 * News briefs: same list/paragraph flow as the guide, but no `#` heading lines (avoids hashtag-style output).
 * Inline formatting is **bold** and *italic* only (no `code` spans).
 * @param {string} raw
 * @returns {string} HTML fragment safe for innerHTML
 */
export function formatNewsBriefHtml(raw) {
  if (!raw) return "";
  const lines = String(raw).split(/\r?\n/);
  const parts = [];
  let listOpen = false;

  const closeList = () => {
    if (listOpen) {
      parts.push("</ul>");
      listOpen = false;
    }
  };

  const inlineBoldItalic = (escaped) => {
    let t = escaped;
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    return t;
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (/^[-*]\s+/.test(trimmed)) {
      if (!listOpen) {
        parts.push('<ul class="assistant-md-ul">');
        listOpen = true;
      }
      const item = trimmed.replace(/^[-*]\s+/, "");
      parts.push(`<li class="assistant-md-li">${inlineBoldItalic(escapeHtml(item))}</li>`);
      continue;
    }

    closeList();

    if (trimmed === "") {
      parts.push('<div class="assistant-md-br" aria-hidden="true"></div>');
      continue;
    }

    parts.push(`<p class="assistant-md-p">${inlineBoldItalic(escapeHtml(trimmed))}</p>`);
  }

  closeList();
  return parts.join("");
}
