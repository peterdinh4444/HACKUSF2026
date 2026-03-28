"""
Authentication users — separate SQLite database from Tampa ZIP / profiles data.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

# pbkdf2:sha256 works on Python builds without hashlib.scrypt (some macOS system Pythons).
_PWHASH_METHOD = "pbkdf2:sha256"

_ROOT = Path(__file__).resolve().parents[1]
AUTH_DB_PATH = _ROOT / "data" / "auth.db"


def _connect() -> sqlite3.Connection:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUTH_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if n == 0 and os.environ.get("HURRICANE_HUB_SEED_DEMO", "1") == "1":
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                ("demo", generate_password_hash("demo123", method=_PWHASH_METHOD), ts),
            )
            conn.commit()
    finally:
        conn.close()


def create_user(username: str, password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    if len(username) < 2:
        return False, "Username too short"
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    init_auth_db()
    conn = _connect()
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
            (username, generate_password_hash(password, method=_PWHASH_METHOD), ts),
        )
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Username already taken"
    finally:
        conn.close()


def verify_login(username: str, password: str) -> dict[str, Any] | None:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),),
        ).fetchone()
        if not row:
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        return {"id": row["id"], "username": row["username"]}
    finally:
        conn.close()


def get_user_by_id(uid: int) -> dict[str, Any] | None:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
