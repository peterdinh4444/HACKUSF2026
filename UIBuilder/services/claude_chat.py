"""Claude Messages API — server-side only; key from environment."""
from __future__ import annotations

import json
import os
from typing import Any

import requests

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Default: fast / economical; override with ANTHROPIC_MODEL e.g. claude-3-5-sonnet-20241022
DEFAULT_MODEL = "claude-3-5-haiku-20241022"

SYSTEM_PREFIX = """You are the in-app guide for Hurricane Hub, a Tampa Bay storm and flood readiness prototype.
The user sees a live JSON snapshot from the app in your context block. Use ONLY that snapshot plus general storm-safety common sense.

Rules:
- Explain what the numbers and fields mean in plain language; say when something is missing or uncertain.
- Always tell the user to verify with official sources: National Weather Service (weather.gov) and their county emergency management. You do NOT issue evacuation orders or replace those agencies.
- The app risk score is a planning index from public feeds, not a personal safety guarantee.
- Be concise (short paragraphs or bullets). If asked something outside the snapshot, say you can only comment on what was provided or general preparedness.
- Never invent specific alert text, road closures, or zone assignments that are not in the JSON.
"""


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
    max_tokens: int = 2048,
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
        return None, f"Could not reach the assistant: {e}"

    try:
        data = res.json()
    except ValueError:
        return None, f"Assistant returned an invalid response (HTTP {res.status_code})."

    if res.status_code != 200:
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        msg = err.get("message") if isinstance(err, dict) else None
        return None, msg or f"Assistant error (HTTP {res.status_code})."

    parts = data.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
    text = "".join(texts).strip()
    if not text:
        return None, "The assistant returned an empty reply."
    return text, None
