"""Claude Messages API — server-side only; key from environment."""
from __future__ import annotations

import json
import os
from typing import Any

import requests

from services.report_sanitize import strip_internal_api_refs

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Default: Haiku 4.5 (current; 3.5 IDs are deprecated for many keys). Override with ANTHROPIC_MODEL.
# Alias tracks Anthropic’s latest Haiku 4.5 snapshot; pin a dated ID in .env if you need stability.
DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PREFIX = """You are Hurricane Hub's in-app guide (Tampa Bay storm/flood planning prototype).

**Brevity first:** Default to **2–4 short sentences** unless the user clearly asks for more. No long intros.

Data:
- Use ONLY the JSON snapshot plus ordinary preparedness common sense. Say in one line if something is missing.
- If PAGE TYPE is `general`, the JSON may only have `site_path` / `note` — give brief general Tampa Bay readiness tips and point to Dashboard or Home risk in this app; do not pretend you see live metrics.
- If PAGE TYPE is `evacuation`, the JSON has `tampa_bay_regional` (evacuation zone lookup, traffic_near_home, regional traffic counts) plus a slim `dashboard` threat/location slice. Help users interpret traffic and zones as **planning cues** only — never issue evacuation orders; always defer to county EM, NWS, and FL511 for closures and mandatory routes.
- If PAGE TYPE is `notifications`, the JSON may include `news_feed_summary` (counts, last ingest) and optional `news_headlines_sample`. Help users understand email opt-in and ingested headlines as **second-hand planning context** — not official alerts; point to NWS Tampa Bay and county EM for orders.

Low / green tier (nothing to worry about from this index):
- If `threat.tier` or `risk_card.threat_tier` is **`low`** (the green band), say clearly: this snapshot shows **no elevated hazard signals** from the feeds the app tracks — the user is **fine from this planning index's perspective**. Add one short line that **active storms can still change quickly**, so they should still glance at **NWS (weather.gov)** and **county** sources for any live warnings. Do **not** invent problems when the tier is low.

Safety:
- Never invent alerts, closures, or zone text not in the JSON. Never issue evacuation orders. The score is a planning index from public data, not a personal guarantee.
- Tiny Markdown is OK (**bold** or a `-` bullet); avoid long structured markdown unless asked.
- Never include URLs or path strings for **this application's** `/api/...` routes (or phrases like `GET /api/...`) in your reply. Official NWS / county `.gov` links are fine when helpful.
"""


def _friendly_model_error(api_message: str | None) -> str | None:
    """Avoid showing raw model IDs in the UI when the API rejects the model name."""
    if not api_message:
        return None
    low = api_message.lower()
    if "model" not in low:
        return None
    if not any(
        x in low
        for x in (
            "not found",
            "invalid",
            "does not exist",
            "not available",
            "unknown model",
            "unsupported",
        )
    ):
        return None
    return (
        "The AI model configured for this app isn’t available for your API key. "
        "Remove ANTHROPIC_MODEL from your .env file to use the built-in default, "
        "or set ANTHROPIC_MODEL to a model your Anthropic project allows (see their model list in the console)."
    )


def _anthropic_error_message(data: dict[str, Any]) -> str | None:
    err = data.get("error")
    if isinstance(err, dict):
        m = err.get("message") or err.get("type")
        if m:
            return str(m)
    if isinstance(err, str) and err.strip():
        return err.strip()
    m = data.get("message")
    if isinstance(m, str) and m.strip():
        return m.strip()
    return None


def _truncate_context(obj: Any, max_bytes: int = 100_000) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)
    enc = raw.encode("utf-8")
    if len(enc) <= max_bytes:
        return raw
    return enc[: max_bytes - 60].decode("utf-8", errors="ignore") + "\n…[context truncated for size]"


def call_claude(
    *,
    page: str,
    context: dict[str, Any],
    prior_messages: list[dict[str, str]],
    user_message: str,
    max_tokens: int = 768,
) -> tuple[str | None, str | None]:
    """
    Returns (assistant_text, error_message).
    prior_messages: alternating user/assistant, starting with user (each has role + content).
    """
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("api_key")
        or ""
    ).strip()
    if not api_key:
        return None, (
            "The assistant is not configured yet — set ANTHROPIC_API_KEY in UIBuilder/.env "
            "and run `pip install -r requirements.txt` so python-dotenv loads it."
        )

    model = (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    ctx_json = _truncate_context(context)
    system = (
        f"{SYSTEM_PREFIX}\n\n--- PAGE TYPE ---\n{page}\n\n"
        f"--- CURRENT SNAPSHOT (JSON) ---\n{ctx_json}"
    )

    msgs: list[dict[str, Any]] = []
    for m in prior_messages:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        msgs.append({"role": role, "content": content.strip()})
    msgs.append({"role": "user", "content": user_message.strip()})

    if not msgs or msgs[-1]["role"] != "user":
        return None, "Invalid message sequence."

    try:
        res = requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": msgs,
            },
            timeout=120,
        )
    except requests.RequestException as e:
        return None, f"Could not reach the answer service: {e}"

    try:
        data = res.json()
    except ValueError:
        return None, f"Assistant returned an invalid response (HTTP {res.status_code})."

    if res.status_code != 200:
        raw = _anthropic_error_message(data if isinstance(data, dict) else {})
        friendly = _friendly_model_error(raw)
        return None, friendly or raw or f"Assistant error (HTTP {res.status_code})."

    parts = data.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
    text = "".join(texts).strip()
    if not text:
        return None, "The assistant returned an empty reply."
    return strip_internal_api_refs(text), None


TOPIC_BRIEF_SYSTEM = """You summarize ONE "Show me…" report section for a resident.

**Hard limit: 2–3 short sentences.** Plain language; one **bold** phrase max if useful.

- Use ONLY JSON facts for that topic. If empty, say so in one sentence.
- If overall risk tier in the JSON is **`low`** (green), say this section fits a **calm snapshot** — nothing here looks worrisome from the app's data; one clause to still check NWS/county when weather is active.
- No evacuation orders. No invented alerts, closures, or zones.
- Never mention this app's `/api/...` paths or how to call them.
"""


def call_claude_topic_brief(
    *,
    page: str,
    context: dict[str, Any],
    topic_key: str,
    topic_label: str,
    max_tokens: int = 280,
) -> tuple[str | None, str | None]:
    """Single-shot brief summary for the topic dropdown + Ask AI."""
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("api_key")
        or ""
    ).strip()
    if not api_key:
        return None, (
            "The assistant is not configured yet — set ANTHROPIC_API_KEY in UIBuilder/.env "
            "and run `pip install -r requirements.txt` so python-dotenv loads it."
        )

    model = (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    ctx_json = _truncate_context(context, max_bytes=95_000)
    system = (
        f"{TOPIC_BRIEF_SYSTEM}\n\n--- PAGE TYPE ---\n{page}\n"
        f"--- TOPIC (internal key) ---\n{topic_key}\n"
        f"--- TOPIC (display) ---\n{topic_label}\n\n"
        f"--- SNAPSHOT (JSON) ---\n{ctx_json}"
    )
    user_line = (
        f"Topic: “{topic_label}”. Summarize what it shows for their location in 2–3 sentences — shorter if tier is low."
    )
    msgs: list[dict[str, Any]] = [{"role": "user", "content": user_line}]

    try:
        res = requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": msgs,
            },
            timeout=120,
        )
    except requests.RequestException as e:
        return None, f"Could not reach the answer service: {e}"

    try:
        data = res.json()
    except ValueError:
        return None, f"Assistant returned an invalid response (HTTP {res.status_code})."

    if res.status_code != 200:
        raw = _anthropic_error_message(data if isinstance(data, dict) else {})
        friendly = _friendly_model_error(raw)
        return None, friendly or raw or f"Assistant error (HTTP {res.status_code})."

    parts = data.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
    text = "".join(texts).strip()
    if not text:
        return None, "The assistant returned an empty reply."
    return strip_internal_api_refs(text), None


NEWS_BRIEF_SYSTEM = """You help Tampa Bay residents scan headlines stored in Hurricane Hub's database.

**Geographic scope:** This app is for the **Tampa Bay region** — roughly the Florida counties Hillsborough, Pinellas, Pasco, and Hernando, plus adjacent coastal/water areas this prototype targets. Summaries should center on that region.

The user message is a JSON object with:
- "articles": an array of items (source, title, optional summary, optional url, optional published_at).
- Optional "reader_location": saved-home hints (ZIP codes, address fragments, saved_home_count). Use only to prioritize bullets when article text actually mentions those places — do not invent local ties.

**Formatting (strict):**
- You may use only these inline marks: **double asterisks for bold** and *single asterisks for italic*.
- Do not use hashtags, words prefixed with #, markdown headings (# at line start), numbered heading styles, or social-style tags.
- Do not use backticks or code formatting.
- Use normal paragraphs; for lists use lines starting with "- " only.

**If location is wrong for this app:** If reader_location or the dominant story focus is clearly **outside** the Tampa Bay region above (and the articles are not about Florida-wide or Gulf-wide storm context that still matters locally), add one short sentence telling the user to **add or choose a saved address in the Tampa Bay region** in this app so alerts and rankings match where they live. Keep it polite and practical — not scolding.

Structure:
1) Two or three sentences summarizing only what the articles support (storm, flood, recovery, readiness, traffic, county pages, etc.).
2) Five to eight lines, each starting with "- ", with concrete angles to verify with official sources. If reader_location matches article text, put the most relevant bullets first.
3) One line starting exactly with "Bottom line: " — based only on these articles, either nothing material to worry about right now for storm/flood readiness here, or something worth watching and why. Not an evacuation order.
4) One line starting exactly with "Verify: " — confirm with NWS Tampa Bay (weather.gov/tbw) and their county emergency manager.

Rules:
- Do not invent events, closures, or orders not supported by the article text.
- If the feed is thin or off-topic, say so briefly and add calm seasonal preparedness reminders for the Florida hurricane season.
- Optional: at most one or two URLs only if they appeared in the JSON articles (e.g. publisher links). Never mention or invent this application's own `/api/...` endpoints.
"""


def call_claude_news_brief(
    *,
    articles: list[dict[str, Any]],
    reader_location: dict[str, Any] | None = None,
    max_tokens: int = 1024,
) -> tuple[str | None, str | None]:
    """Summarize ingested news rows for the Alerts & news page."""
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("api_key")
        or ""
    ).strip()
    if not api_key:
        return None, (
            "Set ANTHROPIC_API_KEY in .env to generate AI summaries of the news database."
        )

    model = (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    slim: list[dict[str, Any]] = []
    for a in articles[:72]:
        if not isinstance(a, dict):
            continue
        slim.append(
            {
                "source": a.get("source"),
                "title": a.get("title"),
                "summary": (a.get("summary") or "")[:400] or None,
                "url": a.get("url"),
                "published_at": a.get("published_at"),
            }
        )
    user_obj: dict[str, Any] = {"articles": slim}
    if reader_location and isinstance(reader_location, dict) and reader_location:
        user_obj["reader_location"] = reader_location
    payload = _truncate_context(user_obj, max_bytes=55_000)
    system = NEWS_BRIEF_SYSTEM
    user_line = f"Here is the JSON payload. Summarize it for a Tampa Bay household following your output rules.\n\n{payload}"
    msgs: list[dict[str, Any]] = [{"role": "user", "content": user_line}]

    try:
        res = requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": msgs,
            },
            timeout=120,
        )
    except requests.RequestException as e:
        return None, f"Could not reach the answer service: {e}"

    try:
        data = res.json()
    except ValueError:
        return None, f"Assistant returned an invalid response (HTTP {res.status_code})."

    if res.status_code != 200:
        raw = _anthropic_error_message(data if isinstance(data, dict) else {})
        friendly = _friendly_model_error(raw)
        return None, friendly or raw or f"Assistant error (HTTP {res.status_code})."

    parts = data.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
    text = "".join(texts).strip()
    if not text:
        return None, "The assistant returned an empty reply."
    return strip_internal_api_refs(text), None
