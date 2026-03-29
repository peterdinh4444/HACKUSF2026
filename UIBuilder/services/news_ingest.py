"""
Ingest Tampa / hurricane-related news and official feeds into SQLite (news_feed_items).

Sources (keys in DB `source` column):
  mediastack, gnews, fdem_rss, nhc_rss, nws_tbw_alerts, reddit_tampa, reddit_stpete, hcfl_stay_safe

API keys: MEDIASTACK_ACCESS_KEY, GNEWS_API_KEY (optional — skips if unset).
X/Twitter v2 and NewsAPI.ai are catalogued in services.apis but not fetched here (keys / TOS).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
import requests

from services.apis import HTTP_HEADERS, NWS_API
from services.tampa_db import upsert_news_feed_items

REDDIT_HEADERS = {
    **HTTP_HEADERS,
    "User-Agent": "HurricaneHub/0.1 (local research; Tampa Bay storm-prep prototype)",
}

MEDIASTACK_URL = "http://api.mediastack.com/v1/news"
GNEWS_SEARCH_URL = "https://gnews.io/api/v4/search"
DEFAULT_TAMPA_SOURCES = "tampabay,wtsp,wfla"
DEFAULT_HURRICANE_KEYWORDS = "hurricane,storm,surge"
NHC_ATLANTIC_RSS = "https://www.nhc.noaa.gov/index-at.xml"
LEGACY_FDEM_RSS = "https://www.floridadisaster.org/rss"
HCFL_STAY_SAFE = "https://www.hillsboroughcounty.org/en/residents/stay-safe"

REDDIT_SUBS = (
    ("tampa", "reddit_tampa"),
    ("stpetersburg", "reddit_stpete"),
)
REDDIT_KEYWORDS = re.compile(
    r"hurricane|tropical|storm|surge|flood|flooding|power\s*out|evacuat|closure|bridge",
    re.I,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _external_key(source: str, url: str | None, title: str, published: str | None) -> str:
    base = (url or "").strip() or f"{title}|{published or ''}"
    return hashlib.sha256(f"{source}:{base}".encode()).hexdigest()[:40]


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_rss_or_atom_xml(text: str) -> list[dict[str, str | None]]:
    """Return list of {title, link, summary, pub_date_raw} from RSS 2.0 or Atom."""
    out: list[dict[str, str | None]] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    root_local = _local_tag(root.tag)
    if root_local == "rss":
        channel = root.find("channel")
        if channel is None:
            return out
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            guid_el = item.find("guid")
            t = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
            link = (link_el.text or "").strip() if link_el is not None and link_el.text else None
            if not link and guid_el is not None and guid_el.text:
                link = guid_el.text.strip()
            desc = (desc_el.text or "").strip() if desc_el is not None and desc_el.text else None
            pub = (pub_el.text or "").strip() if pub_el is not None and pub_el.text else None
            if t or link:
                out.append({"title": t or "(no title)", "link": link, "summary": desc, "pub_date_raw": pub})
    elif root_local == "feed":
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            summ_el = entry.find("atom:summary", ns)
            upd_el = entry.find("atom:updated", ns)
            t = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
            href = None
            if link_el is not None:
                href = link_el.get("href")
            summ = (summ_el.text or "").strip() if summ_el is not None and summ_el.text else None
            pub = (upd_el.text or "").strip() if upd_el is not None and upd_el.text else None
            if t or href:
                out.append({"title": t or "(no title)", "link": href, "summary": summ, "pub_date_raw": pub})
    return out


def _pub_to_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_mediastack_tampa(
    *,
    sources: str | None = None,
    keywords: str | None = None,
    date: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    key = (os.environ.get("MEDIASTACK_ACCESS_KEY") or os.environ.get("MEDIASTACK_API_KEY") or "").strip()
    if not key:
        return {"source": "mediastack", "skipped": True, "reason": "MEDIASTACK_ACCESS_KEY not set", "items": []}
    try:
        default_lim = int((os.environ.get("MEDIASTACK_LIMIT") or "45").strip() or "45")
    except ValueError:
        default_lim = 45
    eff_limit = default_lim if limit is None else int(limit)
    params: dict[str, Any] = {
        "access_key": key,
        "countries": "us",
        "languages": "en",
        "limit": min(max(1, eff_limit), 100),
        "sources": (sources or os.environ.get("MEDIASTACK_SOURCES") or DEFAULT_TAMPA_SOURCES).strip(),
        "keywords": (keywords or os.environ.get("MEDIASTACK_KEYWORDS") or DEFAULT_HURRICANE_KEYWORDS).strip(),
    }
    if date:
        params["date"] = date
    try:
        r = requests.get(MEDIASTACK_URL, params=params, headers=HTTP_HEADERS, timeout=30)
        data = r.json() if r.headers.get("content-type", "").lower().find("json") >= 0 else {}
    except requests.RequestException as e:
        return {"source": "mediastack", "error": str(e), "items": []}
    if not isinstance(data, dict):
        return {"source": "mediastack", "error": "non-json response", "items": []}
    if data.get("error"):
        return {"source": "mediastack", "error": data.get("error"), "items": []}
    rows = data.get("data") or []
    items: list[dict[str, Any]] = []
    kw_list = [k.strip() for k in params["keywords"].split(",") if k.strip()]
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        title = (row.get("title") or "").strip() or "(no title)"
        published_raw = row.get("published_at") or row.get("date") or ""
        published = str(published_raw).strip()[:40] if published_raw else None
        desc = (row.get("description") or "")[:2000] or None
        items.append(
            {
                "source": "mediastack",
                "external_key": _external_key("mediastack", url or None, title, published),
                "title": title,
                "summary": desc,
                "url": url or None,
                "published_at": published,
                "keywords": kw_list,
                "raw_json": {"source_name": (row.get("source") or {}).get("name") if isinstance(row.get("source"), dict) else row.get("source")},
            }
        )
    return {"source": "mediastack", "http_status": r.status_code, "items": items}


def fetch_gnews_tampa_historic(
    *,
    query: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    token = (os.environ.get("GNEWS_API_KEY") or os.environ.get("GNEWS_TOKEN") or "").strip()
    if not token:
        return {"source": "gnews", "skipped": True, "reason": "GNEWS_API_KEY not set", "items": []}
    now = datetime.now(timezone.utc)
    if not to_iso:
        to_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not from_iso:
        from_dt = now - timedelta(days=int(os.environ.get("GNEWS_HISTORIC_DAYS", "30")))
        from_iso = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = (query or os.environ.get("GNEWS_QUERY") or "").strip()
    if not q:
        # GNews boolean query: core Tampa Bay metros + storm/flood terms.
        q = (
            '( "Tampa Bay" OR Tampa OR "St. Petersburg" OR St Petersburg OR Clearwater OR '
            "Pinellas OR Hillsborough OR Pasco OR Hernando OR Bradenton OR Sarasota ) "
            "AND ( hurricane OR tropical OR storm OR surge OR flood OR flooding OR evacuat )"
        )
    try:
        default_gn = int((os.environ.get("GNEWS_MAX") or "40").strip() or "40")
    except ValueError:
        default_gn = 40
    eff_gn = default_gn if limit is None else int(limit)
    params = {
        "token": token,
        "q": q,
        "lang": "en",
        "country": "us",
        "max": min(max(1, eff_gn), 100),
        "from": from_iso,
        "to": to_iso,
        "sortby": "publishedAt",
    }
    try:
        r = requests.get(GNEWS_SEARCH_URL, params=params, headers=HTTP_HEADERS, timeout=30)
        data = r.json() if "json" in r.headers.get("content-type", "").lower() else {}
    except requests.RequestException as e:
        return {"source": "gnews", "error": str(e), "items": []}
    if not isinstance(data, dict):
        return {"source": "gnews", "error": "non-json", "items": []}
    if data.get("errors"):
        return {"source": "gnews", "error": data.get("errors"), "items": []}
    articles = data.get("articles") or []
    items: list[dict[str, Any]] = []
    for a in articles:
        if not isinstance(a, dict):
            continue
        url = (a.get("url") or "").strip()
        title = (a.get("title") or "").strip() or "(no title)"
        pub = (a.get("publishedAt") or "").strip() or None
        desc = (a.get("description") or "")[:2000] or None
        items.append(
            {
                "source": "gnews",
                "external_key": _external_key("gnews", url or None, title, pub),
                "title": title,
                "summary": desc,
                "url": url or None,
                "published_at": pub,
                "keywords": ["gnews", "tampa", "historic_window"],
                "raw_json": {"source_name": a.get("source", {}).get("name") if isinstance(a.get("source"), dict) else None},
            }
        )
    return {"source": "gnews", "http_status": r.status_code, "from": from_iso, "to": to_iso, "items": items}


def fetch_rss_url(url: str, db_source: str, keyword_tag: str) -> dict[str, Any]:
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
        text = r.text if r.text else ""
    except requests.RequestException as e:
        return {"source": db_source, "url": url, "error": str(e), "items": []}
    if r.status_code != 200 or not text.lstrip().startswith("<"):
        return {
            "source": db_source,
            "url": url,
            "error": f"HTTP {r.status_code} or non-XML",
            "items": [],
        }
    parsed = parse_rss_or_atom_xml(text)
    items: list[dict[str, Any]] = []
    for p in parsed:
        link = p.get("link")
        title = str(p.get("title") or "")
        pub_iso = _pub_to_iso(p.get("pub_date_raw"))
        items.append(
            {
                "source": db_source,
                "external_key": _external_key(db_source, link, title, pub_iso),
                "title": title,
                "summary": (p.get("summary") or "")[:2000] or None,
                "url": link,
                "published_at": pub_iso,
                "keywords": [keyword_tag, "rss"],
                "raw_json": {"feed_url": url},
            }
        )
    return {"source": db_source, "url": url, "http_status": r.status_code, "items": items}


def fetch_fdem_rss() -> dict[str, Any]:
    custom = (os.environ.get("FDEM_RSS_URL") or "").strip()
    urls = [custom] if custom else [LEGACY_FDEM_RSS]
    last_err: dict[str, Any] | None = None
    for u in urls:
        out = fetch_rss_url(u, "fdem_rss", "fdem")
        if out.get("items"):
            return out
        last_err = out
    return last_err or {"source": "fdem_rss", "error": "no URL", "items": []}


def fetch_nhc_atlantic_rss() -> dict[str, Any]:
    return fetch_rss_url(NHC_ATLANTIC_RSS, "nhc_rss", "nhc_atlantic")


def fetch_nws_tbw_alerts() -> dict[str, Any]:
    """Active NWS alerts for Florida; keep items issued by Tampa Bay office (TBW)."""
    url = f"{NWS_API}/alerts/active"
    params = {"area": "FL"}
    try:
        r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=30)
        data = r.json() if "json" in r.headers.get("content-type", "").lower() else {}
    except requests.RequestException as e:
        return {"source": "nws_tbw_alerts", "error": str(e), "items": []}
    if not isinstance(data, dict):
        return {"source": "nws_tbw_alerts", "error": "non-json", "items": []}
    feats = data.get("features") or []
    items: list[dict[str, Any]] = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        if not isinstance(props, dict):
            continue
        sender = str(props.get("senderName") or props.get("sender") or "")
        if "TBW" not in sender.upper() and "TAMPA BAY" not in sender.upper():
            continue
        eid = str(props.get("id") or f.get("id") or "")
        title = str(props.get("event") or "NWS Alert")
        headline = props.get("headline") or props.get("description") or ""
        if isinstance(headline, str):
            summary = headline[:2000]
        else:
            summary = None
        sent = props.get("sent") or props.get("effective")
        url_link = None
        for u in props.get("references") or []:
            if isinstance(u, str) and u.startswith("http"):
                url_link = u
                break
        items.append(
            {
                "source": "nws_tbw_alerts",
                "external_key": eid or _external_key("nws_tbw_alerts", None, title, str(sent)),
                "title": title,
                "summary": summary,
                "url": url_link,
                "published_at": str(sent)[:32] if sent else None,
                "keywords": ["nws", "tbw", "alert", props.get("severity") or ""],
                "raw_json": {"senderName": sender, "event": props.get("event"), "severity": props.get("severity")},
            }
        )
    return {"source": "nws_tbw_alerts", "http_status": r.status_code, "items": items}


def fetch_reddit_sub_new(subreddit: str, db_source: str, limit: int = 25) -> dict[str, Any]:
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    params = {"limit": min(max(1, limit), 100)}
    try:
        r = requests.get(url, params=params, headers=REDDIT_HEADERS, timeout=25)
        data = r.json() if "json" in r.headers.get("content-type", "").lower() else {}
    except requests.RequestException as e:
        return {"source": db_source, "error": str(e), "items": []}
    if not isinstance(data, dict):
        return {"source": db_source, "error": "non-json", "items": []}
    children = ((data.get("data") or {}).get("children")) or []
    items: list[dict[str, Any]] = []
    for ch in children:
        if not isinstance(ch, dict) or ch.get("kind") != "t3":
            continue
        d = ch.get("data") or {}
        if not isinstance(d, dict):
            continue
        title = (d.get("title") or "").strip()
        selftext = (d.get("selftext") or "")[:1500]
        blob = f"{title}\n{selftext}"
        if not REDDIT_KEYWORDS.search(blob):
            continue
        permalink = (d.get("permalink") or "").strip()
        full_url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink or None
        created = d.get("created_utc")
        pub = None
        if isinstance(created, (int, float)):
            pub = datetime.fromtimestamp(float(created), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pid = str(d.get("name") or d.get("id") or "")
        items.append(
            {
                "source": db_source,
                "external_key": pid or _external_key(db_source, full_url, title, pub),
                "title": title or "(reddit)",
                "summary": selftext or None,
                "url": full_url,
                "published_at": pub,
                "keywords": ["reddit", subreddit, "crowd"],
                "raw_json": {"score": d.get("score"), "subreddit": subreddit},
            }
        )
    return {"source": db_source, "http_status": r.status_code, "items": items}


def fetch_hcfl_stay_safe_status() -> dict[str, Any]:
    """
    Best-effort parse of Hillsborough Stay Safe page (no official JSON API).
    Stores at most one summary row when EOC / level language is found.
    """
    try:
        r = requests.get(HCFL_STAY_SAFE, headers=HTTP_HEADERS, timeout=25)
        text = r.text or ""
    except requests.RequestException as e:
        return {"source": "hcfl_stay_safe", "error": str(e), "items": []}
    if r.status_code != 200:
        return {"source": "hcfl_stay_safe", "error": f"HTTP {r.status_code}", "items": []}
    # Strip scripts/styles to reduce noise
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    snippet = None
    m = re.search(
        r"(EOC[^.\n]{0,120}|Emergency Operations[^.\n]{0,120}|Level\s*[0-4][^.\n]{0,80})",
        plain,
        re.I,
    )
    if m:
        snippet = m.group(1).strip()[:500]
    title = "Hillsborough County — Stay Safe page snapshot"
    summary = snippet or f"Fetched stay-safe page ({len(plain)} chars); no EOC/level snippet matched."
    pub = _utc_now_iso()
    return {
        "source": "hcfl_stay_safe",
        "http_status": r.status_code,
        "items": [
            {
                "source": "hcfl_stay_safe",
                "external_key": _external_key("hcfl_stay_safe", HCFL_STAY_SAFE, title, pub),
                "title": title,
                "summary": summary,
                "url": HCFL_STAY_SAFE,
                "published_at": pub,
                "keywords": ["hcfl", "hillsborough", "stay_safe", "scrape"],
                "raw_json": {"page": HCFL_STAY_SAFE, "matched_eoc_snippet": bool(snippet)},
            }
        ],
    }


def run_full_ingest(
    *,
    mediastack_date: str | None = None,
    gnews_from: str | None = None,
    gnews_to: str | None = None,
    reddit_limit: int | None = None,
    skip_hcfl: bool = False,
) -> dict[str, Any]:
    """
    Fetch all configured sources and upsert into news_feed_items.
    Returns per-source summaries and global upsert counts.
    """
    try:
        rl_default = int((os.environ.get("REDDIT_NEWS_LIMIT") or "35").strip() or "35")
    except ValueError:
        rl_default = 35
    reddit_n = rl_default if reddit_limit is None else int(reddit_limit)

    tasks: list[tuple[str, Any]] = [
        ("mediastack", lambda: fetch_mediastack_tampa(date=mediastack_date)),
        ("gnews", lambda: fetch_gnews_tampa_historic(from_iso=gnews_from, to_iso=gnews_to)),
        ("fdem_rss", fetch_fdem_rss),
        ("nhc_rss", fetch_nhc_atlantic_rss),
        ("nws_tbw_alerts", fetch_nws_tbw_alerts),
        ("reddit_tampa", lambda: fetch_reddit_sub_new("tampa", "reddit_tampa", reddit_n)),
        ("reddit_stpete", lambda: fetch_reddit_sub_new("stpetersburg", "reddit_stpete", reddit_n)),
    ]
    if not skip_hcfl:
        tasks.append(("hcfl_stay_safe", fetch_hcfl_stay_safe_status))

    by_name: dict[str, Any] = {}
    all_items: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fn): name for name, fn in tasks}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                res = {"source": name, "error": repr(e), "items": []}
            by_name[name] = {k: v for k, v in res.items() if k != "items"}
            by_name[name]["item_count"] = len(res.get("items") or [])
            all_items.extend(res.get("items") or [])

    upsert = upsert_news_feed_items(all_items)
    return {
        "fetched_at": _utc_now_iso(),
        "sources": by_name,
        "upsert": upsert,
        "total_items_this_run": len(all_items),
    }
