"""
Geocode addresses via OpenStreetMap Nominatim (no API key; be polite — low rate).
"""
from __future__ import annotations

from typing import Any

import requests

# Reuse descriptive User-Agent for all outbound HTTP
UA = "HurricaneHub/0.1 (HACKUSF educational prototype; contact: local-dev)"


def nominatim_search(q: str, limit: int = 1) -> dict[str, Any]:
    q = (q or "").strip()
    if len(q) < 4:
        return {"error": "query too short", "results": []}
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "format": "json",
        "limit": min(limit, 5),
        "addressdetails": 1,
        # Prefer Tampa Bay but do not exclude valid matches elsewhere in FL
        "countrycodes": "us",
    }
    headers = {"User-Agent": UA, "Accept": "application/json"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        data = r.json()
        if not isinstance(data, list):
            return {"error": "unexpected response", "raw": data}
        out = []
        for item in data:
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "display_name": item.get("display_name"),
                    "osm_id": item.get("osm_id"),
                    "address": item.get("address"),
                }
            )
        return {"results": out, "query": q}
    except requests.RequestException as e:
        return {"error": str(e), "results": []}
