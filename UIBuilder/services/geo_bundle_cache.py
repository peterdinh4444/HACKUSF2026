"""
SQLite-backed cache for paired aggregate_dashboard + regional_lookup payloads.

Reduces repeated live calls to USGS/NOAA/NWS/ArcGIS when the same grid cell is
requested within GEO_BUNDLE_CACHE_TTL_SEC (default 300).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from services.tampa_db import geo_bundle_cache_fetch_row, geo_bundle_cache_upsert, init_db


def _ttl_sec() -> int:
    try:
        return max(60, int(os.environ.get("GEO_BUNDLE_CACHE_TTL_SEC", "300") or "300"))
    except (TypeError, ValueError):
        return 300


def _fetched_stale(fetched_at: str) -> bool:
    try:
        s = (fetched_at or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > _ttl_sec()
    except Exception:
        return True


def try_regional_from_cache(lat: float, lon: float) -> dict[str, Any] | None:
    """Return cached regional JSON for the grid cell if a non-stale row exists."""
    init_db()
    glat = round(float(lat), 4)
    glon = round(float(lon), 4)
    row = geo_bundle_cache_fetch_row(glat, glon, 0)
    if not row or _fetched_stale(row["fetched_at"]):
        return None
    try:
        return json.loads(row["regional_json"])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def get_or_build_dashboard_regional_pair(
    lat: float | None,
    lon: float | None,
    *,
    verbose: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from services.apis import DEFAULT_LAT, DEFAULT_LON, _aggregate_dashboard_uncached
    from services.regional_tampa import _regional_lookup_compute

    lat_f = float(lat if lat is not None else DEFAULT_LAT)
    lon_f = float(lon if lon is not None else DEFAULT_LON)
    v_int = 1 if verbose else 0

    if verbose:
        return (
            _aggregate_dashboard_uncached(lat_f, lon_f, True),
            _regional_lookup_compute(lat_f, lon_f),
        )

    init_db()
    glat = round(lat_f, 4)
    glon = round(lon_f, 4)
    row = geo_bundle_cache_fetch_row(glat, glon, 0)
    if row and not _fetched_stale(row["fetched_at"]):
        try:
            return json.loads(row["dashboard_json"]), json.loads(row["regional_json"])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    dash = _aggregate_dashboard_uncached(lat_f, lon_f, False)
    reg = _regional_lookup_compute(lat_f, lon_f)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    geo_bundle_cache_upsert(glat, glon, 0, dash, reg, now)
    return dash, reg
