#!/usr/bin/env python3
"""Run unified news ingest into data/hurricane_hub.db (from repo root)."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

    from services.news_ingest import run_full_ingest
    from services.tampa_db import news_feed_stats

    p = argparse.ArgumentParser(description="Ingest Tampa/storm feeds into SQLite")
    p.add_argument("--mediastack-date", help="Mediastack historical day YYYY-MM-DD", default=None)
    p.add_argument("--gnews-from", help="GNews ISO start", default=None)
    p.add_argument("--gnews-to", help="GNews ISO end", default=None)
    p.add_argument("--reddit-limit", type=int, default=25)
    p.add_argument("--skip-hcfl", action="store_true", help="Skip Hillsborough Stay Safe fetch")
    p.add_argument("--stats-only", action="store_true", help="Print DB stats and exit")
    args = p.parse_args()

    if args.stats_only:
        print(json.dumps(news_feed_stats(), indent=2))
        return

    out = run_full_ingest(
        mediastack_date=args.mediastack_date,
        gnews_from=args.gnews_from,
        gnews_to=args.gnews_to,
        reddit_limit=args.reddit_limit,
        skip_hcfl=args.skip_hcfl,
    )
    print(json.dumps(out, indent=2))
    print("---")
    print(json.dumps(news_feed_stats(), indent=2))


if __name__ == "__main__":
    main()
