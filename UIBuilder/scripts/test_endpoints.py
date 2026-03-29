#!/usr/bin/env python3
"""Smoke-test external endpoints used by Hurricane Hub (run from repo root)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    from services.apis import aggregate_dashboard
    from services.regional_tampa import regional_lookup
    from services.tampa_db import seed_from_csv_if_empty

    print("1. aggregate_dashboard() …")
    d = aggregate_dashboard()
    print("   OK", "threat", d["threat"]["score"], "keys", list(d.keys()))

    print("2. regional_lookup(Tampa) …")
    r = regional_lookup(27.9506, -82.4572)
    print("   evac source", r["evacuation"].get("source"))
    print("   power count", r["power_outages"].get("count_in_bbox"))
    print("   fl511 layers", list(r["traffic_fl511"].get("layers", {}).keys()))
    tn = r.get("traffic_near_home") or {}
    print("   traffic near pin", tn.get("total_nearby"), "in", tn.get("radius_m"), "m buffer")

    print("3. SQLite seed …")
    print("  ", seed_from_csv_if_empty())

    print("4. Done.")


if __name__ == "__main__":
    main()
