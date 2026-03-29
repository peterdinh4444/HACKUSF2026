"""
SQLite: Tampa metro ZIP reference data + saved home profiles.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = _ROOT / "data" / "hurricane_hub.db"
CSV_PATH = _ROOT / "data" / "tampa_metro_zips.csv"
ZIP_SCHEMA_VERSION = "3"

ZIP_COLUMNS = [
    "zip",
    "city",
    "county",
    "lat",
    "lon",
    "storm_surge_exposure",
    "river_inland_flood_exposure",
    "coastal_character",
    "fdot_bridge_evac_note",
    "county_emergency_url",
    "county_emergency_label",
    "swfwmd_data_portal_url",
    "fl511_url",
    "zip_planning_notes",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")


def _zip_schema_ok(conn: sqlite3.Connection) -> bool:
    ver = conn.execute("SELECT v FROM meta WHERE k = 'zip_schema_version'").fetchone()
    if not ver or ver["v"] != ZIP_SCHEMA_VERSION:
        return False
    info = conn.execute("PRAGMA table_info(zip_codes)").fetchall()
    names = {row["name"] for row in info}
    return all(c in names for c in ZIP_COLUMNS)


def init_db() -> None:
    conn = _connect()
    try:
        _ensure_meta(conn)
        if not _zip_schema_ok(conn):
            conn.execute("DROP TABLE IF EXISTS zip_codes")
            parts = ['zip TEXT PRIMARY KEY']
            for c in ZIP_COLUMNS[1:]:
                parts.append(f'"{c}" REAL' if c in ("lat", "lon") else f'"{c}" TEXT')
            conn.execute(f"CREATE TABLE zip_codes ({', '.join(parts)})")
            conn.execute(
                "INSERT OR REPLACE INTO meta (k, v) VALUES ('zip_schema_version', ?)",
                (ZIP_SCHEMA_VERSION,),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS home_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                address_line TEXT NOT NULL,
                lat REAL,
                lon REAL,
                zip TEXT,
                last_assessment_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(home_profiles)").fetchall()}
        if "user_id" not in cols:
            conn.execute("ALTER TABLE home_profiles ADD COLUMN user_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_zip ON home_profiles(zip)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_user ON home_profiles(user_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_feed_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_key TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                url TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                keywords TEXT,
                raw_json TEXT,
                UNIQUE(source, external_key)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_feed_pub ON news_feed_items(published_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_feed_src ON news_feed_items(source)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geo_bundle_cache (
                grid_lat REAL NOT NULL,
                grid_lon REAL NOT NULL,
                verbose_int INTEGER NOT NULL DEFAULT 0,
                dashboard_json TEXT NOT NULL,
                regional_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (grid_lat, grid_lon, verbose_int)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_geo_bundle_fetched ON geo_bundle_cache(fetched_at)")
        conn.commit()
    finally:
        conn.close()


def seed_from_csv_if_empty() -> dict[str, Any]:
    init_db()
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM zip_codes").fetchone()["c"]
        if n > 0:
            return {"seeded": False, "rows": n}
        if not CSV_PATH.is_file():
            return {"seeded": False, "error": f"missing {CSV_PATH}"}
        rows = 0
        placeholders = ", ".join(["?"] * len(ZIP_COLUMNS))
        cols = ", ".join(f'"{c}"' for c in ZIP_COLUMNS)
        sql = f"INSERT OR REPLACE INTO zip_codes ({cols}) VALUES ({placeholders})"
        with CSV_PATH.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                vals = []
                for c in ZIP_COLUMNS:
                    v = row.get(c, "")
                    if c in ("lat", "lon"):
                        vals.append(float(v) if v not in ("", None) else None)
                    else:
                        vals.append((v or "").strip() if isinstance(v, str) else v)
                conn.execute(sql, vals)
                rows += 1
        conn.commit()
        return {"seeded": True, "rows": rows}
    finally:
        conn.close()


def force_reseed_from_csv() -> dict[str, Any]:
    """Drop ZIP rows and reload from CSV (after CSV regen)."""
    init_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM zip_codes")
        conn.commit()
    finally:
        conn.close()
    return seed_from_csv_if_empty()


def get_by_zip(zip_code: str) -> dict[str, Any] | None:
    seed_from_csv_if_empty()
    z = zip_code.strip().zfill(5) if len(zip_code.strip()) <= 5 else zip_code.strip()
    if len(z) == 4:
        z = z.zfill(5)
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM zip_codes WHERE zip = ?", (z,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def search_city(substr: str, limit: int = 25) -> list[dict[str, Any]]:
    seed_from_csv_if_empty()
    conn = _connect()
    try:
        q = f"%{substr.strip()}%"
        cur = conn.execute(
            "SELECT * FROM zip_codes WHERE city LIKE ? OR zip LIKE ? LIMIT ?",
            (q, q, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def stats() -> dict[str, Any]:
    seed_from_csv_if_empty()
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM zip_codes").fetchone()["c"]
        by = conn.execute(
            "SELECT county, COUNT(*) AS n FROM zip_codes GROUP BY county ORDER BY n DESC"
        ).fetchall()
        return {"total_rows": total, "by_county": [dict(r) for r in by], "zip_schema_version": ZIP_SCHEMA_VERSION}
    finally:
        conn.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_home_profiles(user_id: int, *, skip_zip_seed: bool = False) -> list[dict[str, Any]]:
    init_db()
    if not skip_zip_seed:
        seed_from_csv_if_empty()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, nickname, address_line, lat, lon, zip, updated_at
            FROM home_profiles
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_home_profile(pid: int, user_id: int) -> dict[str, Any] | None:
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM home_profiles WHERE id = ? AND user_id = ?", (pid, user_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_home_profile(
    user_id: int,
    nickname: str,
    address_line: str,
    lat: float | None,
    lon: float | None,
    zip_code: str | None,
    assessment: dict[str, Any] | None,
) -> int:
    init_db()
    conn = _connect()
    try:
        payload = json.dumps(assessment) if assessment is not None else None
        conn.execute(
            """
            INSERT INTO home_profiles (user_id, nickname, address_line, lat, lon, zip, last_assessment_json, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (user_id, nickname.strip(), address_line.strip(), lat, lon, zip_code, payload, _utc_now()),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        conn.close()


def update_profile_assessment(pid: int, user_id: int, assessment: dict[str, Any]) -> bool:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            UPDATE home_profiles
            SET last_assessment_json = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (json.dumps(assessment), _utc_now(), pid, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_home_profile(pid: int, user_id: int) -> bool:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM home_profiles WHERE id = ? AND user_id = ?", (pid, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def geo_bundle_cache_fetch_row(grid_lat: float, grid_lon: float, verbose_int: int) -> dict[str, Any] | None:
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT dashboard_json, regional_json, fetched_at
            FROM geo_bundle_cache
            WHERE grid_lat = ? AND grid_lon = ? AND verbose_int = ?
            """,
            (grid_lat, grid_lon, verbose_int),
        ).fetchone()
        if not row:
            return None
        return {
            "dashboard_json": row["dashboard_json"],
            "regional_json": row["regional_json"],
            "fetched_at": row["fetched_at"],
        }
    finally:
        conn.close()


def geo_bundle_cache_upsert(
    grid_lat: float,
    grid_lon: float,
    verbose_int: int,
    dashboard_obj: dict[str, Any],
    regional_obj: dict[str, Any],
    fetched_at: str | None = None,
) -> None:
    init_db()
    ts = fetched_at or _utc_now()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO geo_bundle_cache (grid_lat, grid_lon, verbose_int, dashboard_json, regional_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(grid_lat, grid_lon, verbose_int) DO UPDATE SET
                dashboard_json = excluded.dashboard_json,
                regional_json = excluded.regional_json,
                fetched_at = excluded.fetched_at
            """,
            (
                grid_lat,
                grid_lon,
                verbose_int,
                json.dumps(dashboard_obj, default=str),
                json.dumps(regional_obj, default=str),
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_news_feed_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Upsert normalized news rows. Each item: source, external_key, title?, summary?, url?,
    published_at?, keywords (list[str] | str JSON), raw_json (dict | str | None).
    """
    init_db()
    if not items:
        return {"upserted": 0, "skipped": 0}
    conn = _connect()
    now = _utc_now()
    upserted = 0
    skipped = 0
    sql = """
        INSERT INTO news_feed_items (
            source, external_key, title, summary, url, published_at, fetched_at, keywords, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_key) DO UPDATE SET
            title = excluded.title,
            summary = excluded.summary,
            url = excluded.url,
            published_at = excluded.published_at,
            fetched_at = excluded.fetched_at,
            keywords = excluded.keywords,
            raw_json = excluded.raw_json
    """
    try:
        for it in items:
            src = (it.get("source") or "").strip()
            ek = (it.get("external_key") or "").strip()
            if not src or not ek:
                skipped += 1
                continue
            kw = it.get("keywords")
            if isinstance(kw, list):
                kw_s = json.dumps(kw)
            elif isinstance(kw, str):
                kw_s = kw
            else:
                kw_s = None
            raw = it.get("raw_json")
            if isinstance(raw, dict):
                raw_s = json.dumps(raw)
            elif raw is None:
                raw_s = None
            else:
                raw_s = str(raw)
            conn.execute(
                sql,
                (
                    src,
                    ek,
                    (it.get("title") or None),
                    (it.get("summary") or None),
                    (it.get("url") or None),
                    (it.get("published_at") or None),
                    now,
                    kw_s,
                    raw_s,
                ),
            )
            upserted += 1
        conn.commit()
        return {"upserted": upserted, "skipped": skipped}
    finally:
        conn.close()


def list_news_feed_items(
    limit: int = 50,
    source: str | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    init_db()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    conn = _connect()
    try:
        if source and source.strip():
            cur = conn.execute(
                """
                SELECT id, source, external_key, title, summary, url, published_at, fetched_at, keywords, raw_json
                FROM news_feed_items
                WHERE source = ?
                ORDER BY published_at IS NULL, published_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (source.strip(), lim, off),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, source, external_key, title, summary, url, published_at, fetched_at, keywords, raw_json
                FROM news_feed_items
                ORDER BY published_at IS NULL, published_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (lim, off),
            )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            if d.get("keywords"):
                try:
                    d["keywords"] = json.loads(d["keywords"])
                except json.JSONDecodeError:
                    pass
            if d.get("raw_json"):
                try:
                    d["raw_json"] = json.loads(d["raw_json"])
                except json.JSONDecodeError:
                    pass
            rows.append(d)
        return rows
    finally:
        conn.close()


def news_feed_stats() -> dict[str, Any]:
    init_db()
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM news_feed_items").fetchone()["c"]
        by = conn.execute(
            "SELECT source, COUNT(*) AS n FROM news_feed_items GROUP BY source ORDER BY n DESC"
        ).fetchall()
        return {"total": total, "by_source": [dict(r) for r in by]}
    finally:
        conn.close()


def meta_get_value(key: str) -> str | None:
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return str(row["v"]) if row and row["v"] is not None else None
    finally:
        conn.close()


def meta_set_value(key: str, value: str) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()
