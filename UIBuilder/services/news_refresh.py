"""
Background refresh of news_feed_items (SQLite). Triggered from API / pages when data is stale.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from services.tampa_db import meta_get_value, meta_set_value, news_feed_stats

_INGEST_LOCK = threading.Lock()
_INGEST_THREAD: threading.Thread | None = None

try:
    DEFAULT_STALE_MINUTES = max(5, int((os.environ.get("NEWS_STALE_MINUTES") or "15").strip() or "15"))
except ValueError:
    DEFAULT_STALE_MINUTES = 15


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _should_refresh(max_age_minutes: int = DEFAULT_STALE_MINUTES) -> bool:
    stats = news_feed_stats()
    if stats.get("total", 0) == 0:
        return True
    raw = meta_get_value("news_last_ingest_at")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last > timedelta(minutes=max_age_minutes):
            return True
    except ValueError:
        return True
    return False


def request_news_refresh_if_stale(*, max_age_minutes: int = DEFAULT_STALE_MINUTES) -> dict[str, Any]:
    """
    Start a daemon thread to run full ingest if DB is empty or last ingest is old.
    Returns immediately with { started: bool, reason: str }.
    """
    if not _should_refresh(max_age_minutes=max_age_minutes):
        return {"started": False, "reason": "fresh_enough"}

    global _INGEST_THREAD

    def _run() -> None:
        try:
            from services.news_ingest import run_full_ingest

            run_full_ingest()
        finally:
            meta_set_value("news_last_ingest_at", _utc_iso())

    with _INGEST_LOCK:
        if _INGEST_THREAD is not None and _INGEST_THREAD.is_alive():
            return {"started": False, "reason": "already_running"}
        _INGEST_THREAD = threading.Thread(target=_run, name="news-ingest", daemon=True)
        _INGEST_THREAD.start()
    return {"started": True, "reason": "stale_or_empty"}


def force_news_refresh_async() -> dict[str, Any]:
    """Always queue a full ingest (e.g. user clicked refresh)."""
    global _INGEST_THREAD

    def _run() -> None:
        try:
            from services.news_ingest import run_full_ingest

            run_full_ingest()
        finally:
            meta_set_value("news_last_ingest_at", _utc_iso())

    with _INGEST_LOCK:
        if _INGEST_THREAD is not None and _INGEST_THREAD.is_alive():
            return {"started": False, "reason": "already_running"}
        _INGEST_THREAD = threading.Thread(target=_run, name="news-ingest-force", daemon=True)
        _INGEST_THREAD.start()
    return {"started": True, "reason": "forced"}
