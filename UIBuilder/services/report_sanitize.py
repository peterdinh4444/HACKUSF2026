"""Strip internal Hurricane Hub /api/... references from user-facing text (reports, AI replies)."""

from __future__ import annotations

import re

_RE_ABS_APP_API = re.compile(
    r"(?i)https?://[^\s\"'<>]+?/api/[a-z0-9_\-./?=&+%\[\]\{\}#]*",
)
_RE_REL_API = re.compile(
    r"(?i)/api/[a-z0-9_\-./?=&+%\[\]\{\}#]*",
)
_RE_VERB_PATH = re.compile(
    r"(?i)\b(?:GET|POST|PUT|PATCH|DELETE)\s+/api/\S+",
)


def strip_internal_api_refs(text: str) -> str:
    """
    Remove paths like /api/dashboard and phrases like GET /api/foo from narratives.
    Does not remove legitimate agency URLs (weather.gov, etc.).
    """
    if not isinstance(text, str):
        return ""
    t = text.strip()
    if not t:
        return text
    t = _RE_ABS_APP_API.sub("", t)
    t = _RE_REL_API.sub("", t)
    t = _RE_VERB_PATH.sub("", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" *\n *\n *\n+", "\n\n", t)
    return t.strip()
