/**
 * Address / place autocomplete via GET /api/geocode/suggest (Mapbox or Nominatim).
 */
const FETCH_OPTS = { credentials: "same-origin" };

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/**
 * @param {HTMLInputElement | null} input
 * @param {{ debounceMs?: number, minChars?: number }} [options]
 * @returns {() => void} teardown
 */
export function attachAddressAutocomplete(input, options = {}) {
  if (!input) return () => {};
  const debounceMs = options.debounceMs ?? 280;
  const minChars = options.minChars ?? 3;

  const wrap = document.createElement("div");
  wrap.className = "addr-ac";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);

  const listId = `${input.id || "addr"}-ac-list`;
  const list = document.createElement("ul");
  list.className = "addr-ac__list";
  list.id = listId;
  list.hidden = true;
  list.setAttribute("role", "listbox");
  wrap.appendChild(list);

  input.setAttribute("autocomplete", "off");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", listId);
  input.setAttribute("aria-expanded", "false");

  let items = [];
  let active = -1;
  let open = false;
  let controller = null;

  function close() {
    open = false;
    active = -1;
    list.hidden = true;
    list.innerHTML = "";
    items = [];
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function renderSuggestions(suggestions) {
    items = suggestions;
    active = -1;
    list.innerHTML = suggestions
      .map(
        (s, i) =>
          `<li role="option" class="addr-ac__item" id="${listId}-opt-${i}" data-idx="${i}" tabindex="-1">${esc(s.label)}</li>`
      )
      .join("");
    if (!suggestions.length) {
      close();
      return;
    }
    open = true;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    list.querySelectorAll(".addr-ac__item").forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const idx = Number(el.getAttribute("data-idx"));
        pick(idx);
      });
    });
  }

  function pick(idx) {
    const s = items[idx];
    if (!s) return;
    input.value = s.label;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    close();
    input.focus();
  }

  function highlight(i) {
    if (!items.length) return;
    active = Math.max(0, Math.min(i, items.length - 1));
    list.querySelectorAll(".addr-ac__item").forEach((el, j) => {
      el.classList.toggle("addr-ac__item--active", j === active);
    });
    input.setAttribute("aria-activedescendant", `${listId}-opt-${active}`);
  }

  const runFetch = debounce(async () => {
    const q = input.value.trim();
    if (q.length < minChars) {
      close();
      return;
    }
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const res = await fetch(`/api/geocode/suggest?q=${encodeURIComponent(q)}`, { ...FETCH_OPTS, signal: controller.signal });
      const data = await res.json();
      if (!res.ok) {
        close();
        return;
      }
      renderSuggestions(data.suggestions || []);
    } catch (e) {
      if (e.name === "AbortError") return;
      close();
    }
  }, debounceMs);

  input.addEventListener("input", () => {
    runFetch();
  });

  input.addEventListener("keydown", (e) => {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      runFetch();
      return;
    }
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      highlight(active < 0 ? 0 : active + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlight(active <= 0 ? items.length - 1 : active - 1);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(active);
    }
  });

  document.addEventListener(
    "click",
    (e) => {
      if (!wrap.contains(e.target)) close();
    },
    true
  );

  return () => {
    close();
    wrap.replaceWith(input);
  };
}
