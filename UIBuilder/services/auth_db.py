"""
Authentication users — separate SQLite database from Tampa ZIP / profiles data.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

# pbkdf2:sha256 works on Python builds without hashlib.scrypt (some macOS system Pythons).
_PWHASH_METHOD = "pbkdf2:sha256"

_ROOT = Path(__file__).resolve().parents[1]
AUTH_DB_PATH = _ROOT / "data" / "auth.db"

CODE_TTL_MIN = 15
_CHALLENGE_WINDOW_MIN = 15
_MAX_CHALLENGES_PER_WINDOW = 5


def _connect() -> sqlite3.Connection:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUTH_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _smtp_app_password_raw() -> str:
    """Gmail App Password may contain spaces in .env — strip for length check; sending code strips all whitespace."""
    return re.sub(r"\s+", "", (os.environ.get("MAIL_PASSWORD") or "").strip())


def _mail_enforced() -> bool:
    u = (os.environ.get("MAIL_USERNAME") or "").strip()
    p = _smtp_app_password_raw()
    return bool(u and p)


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().encode("utf-8")).hexdigest()


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "email_verified" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    if "alert_email_opt_in" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN alert_email_opt_in INTEGER NOT NULL DEFAULT 0")
    if "severity_snapshot_tier" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN severity_snapshot_tier TEXT")
    if "severity_alert_last_sent_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN severity_alert_last_sent_at TEXT")
    if "evacuation_alert_opt_in" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN evacuation_alert_opt_in INTEGER NOT NULL DEFAULT 0")
    if "api_key_hash" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN api_key_hash TEXT")
    if "api_key_created_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN api_key_created_at TEXT")


def _ensure_challenge_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evc_user_exp ON email_verification_challenges (user_id, expires_at)"
    )


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
        _ensure_user_columns(conn)
        _ensure_challenge_table(conn)
        conn.commit()

        conn.execute(
            """
            UPDATE users SET email_verified = 1
            WHERE email IS NULL OR TRIM(COALESCE(email, '')) = ''
            """
        )
        conn.commit()

        n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if n == 0 and os.environ.get("HURRICANE_HUB_SEED_DEMO", "1") == "1":
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, email, email_verified, alert_email_opt_in)
                VALUES (?,?,?,?,1,0)
                """,
                ("demo", generate_password_hash("demo123", method=_PWHASH_METHOD), ts, None),
            )
            conn.commit()
    finally:
        conn.close()


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _valid_email_shape(email: str) -> bool:
    e = email.strip()
    if len(e) < 5 or len(e) > 254 or "@" not in e or " " in e:
        return False
    local, _, domain = e.partition("@")
    if not local or not domain or "." not in domain:
        return False
    return True


def create_user(username: str, password: str, email: str, *, alert_opt_in: bool = False) -> tuple[bool, str, int | None]:
    """
    Returns (ok, error_message, new_user_id).
    When SMTP is configured, new_user_id is set and email_verified is 0 until the user verifies.
    """
    username = (username or "").strip()
    email_n = _normalize_email(email)
    if len(username) < 2:
        return False, "Username too short", None
    if len(password) < 6:
        return False, "Password must be at least 6 characters", None
    if not _valid_email_shape(email_n):
        return False, "Enter a valid email address", None
    verified = 0 if _mail_enforced() else 1
    init_auth_db()
    conn = _connect()
    try:
        dup = conn.execute(
            "SELECT id FROM users WHERE lower(trim(COALESCE(email, ''))) = ?",
            (email_n,),
        ).fetchone()
        if dup:
            return False, "That email is already registered", None
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        opt = 1 if alert_opt_in else 0
        conn.execute(
            """
            INSERT INTO users (username, password_hash, created_at, email, email_verified, alert_email_opt_in)
            VALUES (?,?,?,?,?,?)
            """,
            (username, generate_password_hash(password, method=_PWHASH_METHOD), ts, email_n, verified, opt),
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        new_id = int(rid["id"]) if rid and rid["id"] is not None else None
        return True, "", new_id
    except sqlite3.IntegrityError:
        return False, "Username already taken", None
    finally:
        conn.close()


def verify_login(username: str, password: str) -> dict[str, Any] | None:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, username, password_hash, email, email_verified,
                   COALESCE(alert_email_opt_in, 0) AS alert_email_opt_in,
                   COALESCE(evacuation_alert_opt_in, 0) AS evacuation_alert_opt_in
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            ((username or "").strip(),),
        ).fetchone()
        if not row:
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        ev = row["email_verified"]
        try:
            ev_int = int(ev) if ev is not None else 0
        except (TypeError, ValueError):
            ev_int = 0
        try:
            ao = int(row["alert_email_opt_in"] or 0)
        except (TypeError, ValueError, KeyError):
            ao = 0
        try:
            eo = int(row["evacuation_alert_opt_in"] or 0)
        except (TypeError, ValueError, KeyError):
            eo = 0
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "email_verified": ev_int,
            "alert_email_opt_in": ao,
            "evacuation_alert_opt_in": eo,
        }
    finally:
        conn.close()


def get_user_by_id(uid: int) -> dict[str, Any] | None:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, username, email, email_verified,
                   COALESCE(alert_email_opt_in, 0) AS alert_email_opt_in,
                   COALESCE(evacuation_alert_opt_in, 0) AS evacuation_alert_opt_in
            FROM users WHERE id = ?
            """,
            (uid,),
        ).fetchone()
        if not row:
            return None
        u = dict(row)
        try:
            u["email_verified"] = int(u.get("email_verified") or 0)
        except (TypeError, ValueError):
            u["email_verified"] = 0
        try:
            u["alert_email_opt_in"] = int(u.get("alert_email_opt_in") or 0)
        except (TypeError, ValueError):
            u["alert_email_opt_in"] = 0
        try:
            u["evacuation_alert_opt_in"] = int(u.get("evacuation_alert_opt_in") or 0)
        except (TypeError, ValueError):
            u["evacuation_alert_opt_in"] = 0
        return u
    finally:
        conn.close()


def user_needs_email_verification(user: dict[str, Any]) -> bool:
    if not _mail_enforced():
        return False
    email = (user.get("email") or "").strip()
    if not email:
        return False
    try:
        v = int(user.get("email_verified") or 0)
    except (TypeError, ValueError):
        v = 0
    return v == 0


def _purge_expired_challenges(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("DELETE FROM email_verification_challenges WHERE expires_at < ?", (now,))


def _recent_challenge_count(conn: sqlite3.Connection, user_id: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=_CHALLENGE_WINDOW_MIN)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM email_verification_challenges
        WHERE user_id = ? AND created_at > ?
        """,
        (user_id, cutoff),
    ).fetchone()
    return int(row["c"]) if row else 0


def create_email_challenge(user_id: int) -> tuple[str | None, str]:
    """
    Issue a new login verification code. Returns (plaintext_code, error_message).
    """
    init_auth_db()
    conn = _connect()
    try:
        _purge_expired_challenges(conn)
        if _recent_challenge_count(conn, user_id) >= _MAX_CHALLENGES_PER_WINDOW:
            return None, "Too many codes sent. Please wait about 15 minutes before trying again."
        conn.execute("DELETE FROM email_verification_challenges WHERE user_id = ?", (user_id,))
        code = f"{secrets.randbelow(1000000):06d}"
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=CODE_TTL_MIN)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_exp = exp.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """
            INSERT INTO email_verification_challenges (user_id, code_hash, created_at, expires_at)
            VALUES (?,?,?,?)
            """,
            (user_id, _hash_code(code), ts, ts_exp),
        )
        conn.commit()
        return code, ""
    finally:
        conn.close()


def verify_email_challenge(user_id: int, code: str) -> bool:
    init_auth_db()
    conn = _connect()
    try:
        _purge_expired_challenges(conn)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = conn.execute(
            """
            SELECT id, code_hash FROM email_verification_challenges
            WHERE user_id = ? AND expires_at > ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, now),
        ).fetchone()
        if not row:
            return False
        if not hmac.compare_digest(row["code_hash"], _hash_code(code)):
            return False
        conn.execute("DELETE FROM email_verification_challenges WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def set_user_evacuation_alert_opt_in(user_id: int, opt_in: bool) -> None:
    init_auth_db()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET evacuation_alert_opt_in = ? WHERE id = ?",
            (1 if opt_in else 0, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_alert_email_opt_in(user_id: int, opt_in: bool) -> None:
    init_auth_db()
    conn = _connect()
    try:
        if opt_in:
            conn.execute(
                """
                UPDATE users SET alert_email_opt_in = 1,
                    severity_snapshot_tier = NULL,
                    severity_alert_last_sent_at = NULL
                WHERE id = ?
                """,
                (user_id,),
            )
        else:
            conn.execute(
                "UPDATE users SET alert_email_opt_in = 0 WHERE id = ?",
                (user_id,),
            )
        conn.commit()
    finally:
        conn.close()


def get_user_for_severity_notify(user_id: int) -> dict[str, Any] | None:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, username, email, email_verified,
                   COALESCE(alert_email_opt_in, 0) AS alert_email_opt_in,
                   severity_snapshot_tier, severity_alert_last_sent_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_severity_notify_state(
    user_id: int,
    snapshot_tier: str,
    *,
    mode: str,
) -> None:
    """mode: baseline | after_email | tier_only"""
    init_auth_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _connect()
    try:
        if mode == "baseline":
            conn.execute(
                """
                UPDATE users SET severity_snapshot_tier = ?, severity_alert_last_sent_at = NULL
                WHERE id = ?
                """,
                (snapshot_tier, user_id),
            )
        elif mode == "after_email":
            conn.execute(
                """
                UPDATE users SET severity_snapshot_tier = ?, severity_alert_last_sent_at = ?
                WHERE id = ?
                """,
                (snapshot_tier, now, user_id),
            )
        elif mode == "tier_only":
            conn.execute(
                "UPDATE users SET severity_snapshot_tier = ? WHERE id = ?",
                (snapshot_tier, user_id),
            )
        else:
            return
        conn.commit()
    finally:
        conn.close()


def _hash_api_key_plain(plain: str) -> str:
    return hashlib.sha256((plain or "").encode("utf-8")).hexdigest()


def mint_user_api_key(user_id: int) -> str:
    """
    Create or replace one API key for the user. Returns the plaintext token once (prefix hhb_).
    """
    init_auth_db()
    plain = "hhb_" + secrets.token_urlsafe(32)
    digest = _hash_api_key_plain(plain)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET api_key_hash = ?, api_key_created_at = ? WHERE id = ?",
            (digest, ts, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return plain


def resolve_user_from_api_key(header_or_query: str | None) -> int | None:
    """Match Bearer / raw token to user id."""
    raw = (header_or_query or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw.startswith("hhb_"):
        return None
    digest = _hash_api_key_plain(raw)
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM users WHERE api_key_hash = ?", (digest,)).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def user_has_api_key(user_id: int) -> bool:
    init_auth_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT api_key_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return bool(row and (row["api_key_hash"] or "").strip())
    finally:
        conn.close()
