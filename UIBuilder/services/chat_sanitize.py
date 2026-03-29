"""
Sanitize in-app guide (chat) text before it is sent to the model.
User input is never concatenated into raw SQL in this app — profiles/auth use bound parameters —
but stripping NUL / control characters avoids surprises and keeps payloads well-behaved.
"""

from __future__ import annotations


def sanitize_chat_text(s: str, *, max_len: int = 8000) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\x00", "")
    out = []
    for c in s:
        o = ord(c)
        if o == 9 or o == 10 or o == 13 or o >= 32:
            out.append(c)
    s = "".join(out)
    if len(s) > max_len:
        s = s[:max_len]
    return s.strip()
