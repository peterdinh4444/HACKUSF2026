"""
Hurricane Hub — Flask prototype: aggregated public APIs for Tampa Bay flood / storm context.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from functools import wraps
from urllib.parse import quote, urlparse

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services.apis import (
    DEFAULT_LAT,
    DEFAULT_LON,
    aggregate_dashboard,
    catalog_endpoints,
    geocode_suggestions,
    mapbox_forward_geocode,
    plan_evac_drive,
)
from services.auth_db import (
    create_email_challenge,
    create_user,
    get_user_by_id,
    init_auth_db,
    mint_user_api_key,
    resolve_user_from_api_key,
    set_user_alert_email_opt_in,
    set_user_evacuation_alert_opt_in,
    user_has_api_key,
    user_needs_email_verification,
    verify_email_challenge,
    verify_login,
)
from services.severity_notify import process_severity_change
from services.smtp_mail import (
    send_evacuation_zone_sample_email,
    send_login_verification_code,
    send_notification_preferences_confirmation_email,
    smtp_configured,
)
from services.geo_bundle_cache import get_or_build_dashboard_regional_pair
from services.home_assessment import (
    assess_address,
    assess_coordinates,
    build_risk_card,
    compact_home_assessment,
)
from services.regional_tampa import regional_lookup
from services.chat_sanitize import sanitize_chat_text
from services.report_sanitize import strip_internal_api_refs
from services.claude_chat import call_claude, call_claude_news_brief, call_claude_topic_brief
from services.news_ingest import run_full_ingest
from services.news_refresh import force_news_refresh_async, request_news_refresh_if_stale
from services.tampa_db import (
    delete_home_profile,
    get_by_zip,
    get_home_profile,
    list_home_profiles,
    list_news_feed_items,
    meta_get_value,
    news_feed_stats,
    save_home_profile,
    search_city,
    seed_from_csv_if_empty,
    stats as zip_stats,
    update_profile_assessment,
)

_APP_ROOT = Path(__file__).resolve().parent


def _load_project_env() -> None:
    """Load UIBuilder/.env regardless of the process working directory."""
    try:
        from dotenv import load_dotenv

        load_dotenv(_APP_ROOT / ".env")
    except ImportError:
        pass


_load_project_env()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")


def _session_user_id() -> int | None:
    raw = session.get("user_id")
    try:
        i = int(raw)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _mask_email(email: str) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return "your email"
    local, _, domain = e.partition("@")
    if len(local) <= 1:
        return f"***@{domain}"
    if len(local) <= 3:
        return f"{local[0]}***@{domain}"
    return f"{local[0]}***{local[-1]}@{domain}"


def _safe_internal_next(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw or "\n" in raw or "\r" in raw:
        return None
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        if parsed.netloc != request.host:
            return None
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        q = f"?{parsed.query}" if parsed.query else ""
        return f"{path}{q}"
    return None


def _news_ingest_allowed() -> bool:
    """POST /api/news/ingest — require secret if set, else localhost only."""
    secret = (os.environ.get("NEWS_INGEST_SECRET") or "").strip()
    if secret:
        return request.headers.get("X-News-Ingest-Secret") == secret
    addr = (request.remote_addr or "").strip()
    if addr in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        return True
    return False


def _request_api_key_raw() -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    for hdr in ("X-API-Key", "X-Hurricane-Hub-Key"):
        v = (request.headers.get(hdr) or "").strip()
        if v:
            return v
    return (request.args.get("api_key") or "").strip()


def _filter_profiles_by_house_name(profiles: list[dict], house_name: str) -> list[dict]:
    hn = (house_name or "").strip().lower()
    if not hn:
        return profiles
    exact = [p for p in profiles if (p.get("nickname") or "").strip().lower() == hn]
    if exact:
        return exact
    return [
        p
        for p in profiles
        if hn in (p.get("nickname") or "").lower() or hn in (p.get("address_line") or "").lower()
    ]


def _normalize_assistant_prior_messages(raw) -> list[dict[str, str]]:
    """Keep only a valid u→a→u→a prefix ending with assistant (completed turns)."""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in raw[-20:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        c = sanitize_chat_text(content, max_len=12000)
        if not c:
            continue
        cleaned.append({"role": role, "content": c})
    validated: list[dict[str, str]] = []
    for i, m in enumerate(cleaned):
        want = "user" if i % 2 == 0 else "assistant"
        if m["role"] != want:
            break
        validated.append(m)
    if validated and validated[-1]["role"] == "user":
        validated.pop()
    return validated


_TB_REGION_TERMS = (
    "hillsborough county",
    "pinellas county",
    "pasco county",
    "hernando county",
    "polk county",
    "manatee county",
    "tampa bay",
    "city of tampa",
    "st. petersburg",
    "st petersburg",
    "stpete",
    "clearwater",
    "brandon",
    "lakeland",
    "sarasota",
    "temple terrace",
    "plant city",
    "riverview",
    "brooksville",
    "hillsborough",
    "pinellas",
    "pasco",
    "hernando",
)

_PLACE_HINT_SKIP = frozenset(
    {
        "florida",
        "county",
        "avenue",
        "street",
        "st",
        "road",
        "drive",
        "lane",
        "boulevard",
        "blvd",
        "usa",
        "apt",
        "unit",
    }
)


def _news_haystack(item: dict) -> str:
    title = str(item.get("title") or "")
    sm = str(item.get("summary") or "")
    kw = item.get("keywords")
    if isinstance(kw, list):
        kws = " ".join(str(x) for x in kw)
    elif isinstance(kw, str):
        kws = kw
    else:
        kws = ""
    return f"{title} {sm} {kws}".lower()


def _reader_location_from_profiles(profiles: list[dict]) -> dict[str, object]:
    zips: list[str] = []
    hints: list[str] = []
    for p in profiles:
        z = str(p.get("zip") or "").strip()
        if z.isdigit() and len(z) == 5:
            zips.append(z)
        addr = str(p.get("address_line") or "")
        for part in re.split(r"[\d,]+", addr.lower()):
            t = part.strip()
            if len(t) >= 4 and t not in _PLACE_HINT_SKIP:
                hints.append(t)
    return {
        "zips": list(dict.fromkeys(zips)),
        "place_hints": list(dict.fromkeys(hints))[:24],
        "saved_home_count": len(profiles),
    }


def _rank_news_feed_for_user(
    items: list[dict],
    profiles: list[dict],
    *,
    limit: int = 72,
) -> tuple[list[dict], dict[str, object]]:
    loc = _reader_location_from_profiles(profiles)
    if not items:
        return [], loc
    scored: list[tuple[int, str, int, dict]] = []
    for it in items:
        hay = _news_haystack(it)
        score = 0
        for z in loc["zips"]:
            if isinstance(z, str) and z in hay:
                score += 7
        for term in _TB_REGION_TERMS:
            if term in hay:
                score += 2
        for hint in loc["place_hints"]:
            if isinstance(hint, str) and len(hint) >= 4 and hint in hay:
                score += 5
        pub = str(it.get("published_at") or "")
        eid = it.get("id")
        try:
            eid_n = int(eid) if eid is not None else 0
        except (TypeError, ValueError):
            eid_n = 0
        scored.append((score, pub, eid_n, it))
    scored.sort(key=lambda x: (-x[0], x[1], -x[2]))
    out = [t[3] for t in scored[:limit]]
    return out, loc


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _session_user_id() is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    uid = _session_user_id()
    user = get_user_by_id(uid) if uid is not None else None
    return {"current_user": user}


def _assistant_chat_page_for_request() -> str:
    ep = (request.endpoint or "").strip()
    if ep == "dashboard_page":
        return "dashboard"
    if ep == "evacuation_page":
        return "evacuation"
    if ep in ("homes_page", "home_snapshot_page"):
        return "home_risk"
    if ep == "notifications_page":
        return "notifications"
    return "general"


@app.context_processor
def inject_assistant_chat_page():
    return {"assistant_chat_page": _assistant_chat_page_for_request()}


@app.context_processor
def inject_support_contact():
    raw = (os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME") or "").strip()
    email = raw
    if "<" in raw and ">" in raw:
        m = re.search(r"<([^>]+)>", raw)
        if m:
            email = (m.group(1) or "").strip()
    if email:
        sub = quote("Hurricane Hub — API higher limits")
        bod = quote(
            "Hello,\n\nI would like to discuss higher API rate limits for Hurricane Hub.\n\nThank you,\n"
        )
        mailto_limits = f"mailto:{email}?subject={sub}&body={bod}"
    else:
        mailto_limits = ""
    return {"support_contact_email": email, "support_mailto_api_limits": mailto_limits}


@app.before_request
def _block_until_email_verified():
    """
    After password check, users with pending_verify_uid must complete the code step
    before any other page (except verify flow, static files, and API JSON — those stay 401).
    """
    if request.endpoint is None:
        return None
    if request.endpoint == "static":
        return None
    if request.path.startswith("/api/"):
        return None
    pending = session.get("pending_verify_uid")
    if not pending:
        return None
    if request.endpoint == "login" and request.args.get("abandon_verify") == "1":
        session.pop("pending_verify_uid", None)
        session.pop("pending_next", None)
        session.pop("pending_verify_reason", None)
        return None
    if request.endpoint == "verify_email":
        return None
    if request.endpoint == "login":
        return redirect(url_for("verify_email"))
    return redirect(url_for("verify_email"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/evacuation-traffic")
def evacuation_page():
    """Evacuation zones + traffic near pin + regional feeds (companion to main dashboard)."""
    return render_template("evacuation.html")


@app.route("/faq")
def faq_page():
    return render_template("faq.html")


@app.route("/how-scores")
def how_scores_page():
    """Short plain-language description of the risk score."""
    return render_template("how_scores.html")


@app.route("/data-api")
def data_api_page():
    """Reference page for public read-style JSON endpoints (news DB, ZIP catalog, regional lookup)."""
    return render_template("api_docs.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = (request.args.get("next") or "").strip()
    if request.method == "POST":
        next_url = (request.form.get("next") or "").strip()
        user = verify_login(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            if user_needs_email_verification(user):
                code, ch_err = create_email_challenge(user["id"])
                if not code:
                    flash(ch_err or "Could not send a verification code. Try again later.", "error")
                    return render_template("login.html", next_url=next_url, demo_hint=_login_demo_hint())
                ok_send, send_err = send_login_verification_code(
                    user["email"], code, username=str(user.get("username") or "")
                )
                if not ok_send:
                    flash(send_err or "Could not send email. Check mail settings.", "error")
                    return render_template("login.html", next_url=next_url, demo_hint=_login_demo_hint())
                session.clear()
                session["pending_verify_uid"] = user["id"]
                safe_next = _safe_internal_next(next_url)
                if safe_next:
                    session["pending_next"] = safe_next
                return redirect(url_for("verify_email"))
            session.clear()
            session["user_id"] = user["id"]
            flash("Signed in.", "success")
            dest = _safe_internal_next(next_url) or url_for("homes_page")
            return redirect(dest)
        flash("Invalid username or password.", "error")
    return render_template("login.html", next_url=next_url, demo_hint=_login_demo_hint())


def _login_demo_hint() -> str:
    if os.environ.get("HURRICANE_HUB_SEED_DEMO", "1") == "1":
        return "First-time install seeds user demo / demo123 (no email step)."
    return ""


@app.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    uid_raw = session.get("pending_verify_uid")
    try:
        uid = int(uid_raw)
    except (TypeError, ValueError):
        uid = None
    if uid is None or uid <= 0:
        flash("Sign in first to verify your email.", "error")
        return redirect(url_for("login"))

    row = get_user_by_id(uid)
    if not row:
        session.pop("pending_verify_uid", None)
        session.pop("pending_next", None)
        session.pop("pending_verify_reason", None)
        flash("Session expired. Please sign in again.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        action = (request.form.get("action") or "verify").strip().lower()
        if action == "resend":
            code, ch_err = create_email_challenge(uid)
            if not code:
                flash(ch_err or "Could not send another code yet.", "error")
            else:
                ok_send, send_err = send_login_verification_code(
                    row["email"],
                    code,
                    username=str(row.get("username") or ""),
                    for_signup=session.get("pending_verify_reason") == "signup",
                )
                if ok_send:
                    flash("A new code was sent to your email.", "success")
                else:
                    flash(send_err or "Could not send email.", "error")
            return render_template(
                "verify_email.html",
                email_mask=_mask_email(row.get("email") or ""),
            )

        code = (request.form.get("code") or "").strip().replace(" ", "")
        if not code.isdigit() or len(code) != 6:
            flash("Enter the 6-digit code from your email.", "error")
            return render_template(
                "verify_email.html",
                email_mask=_mask_email(row.get("email") or ""),
            )
        if verify_email_challenge(uid, code):
            session.pop("pending_verify_uid", None)
            session.pop("pending_verify_reason", None)
            next_raw = session.pop("pending_next", None)
            session["user_id"] = uid
            flash("Email verified. You're signed in.", "success")
            dest = _safe_internal_next(next_raw) if isinstance(next_raw, str) else None
            return redirect(dest or url_for("homes_page"))
        flash("That code is incorrect or expired. Try again or request a new code.", "error")

    return render_template(
        "verify_email.html",
        email_mask=_mask_email(row.get("email") or ""),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        ok, err, new_uid = create_user(
            request.form.get("username", ""),
            request.form.get("password", ""),
            request.form.get("email", ""),
            alert_opt_in=request.form.get("alert_severity_email") == "on",
        )
        if ok and new_uid is not None:
            row = get_user_by_id(new_uid)
            if row and int(row.get("email_verified") or 0) == 0:
                code, ch_err = create_email_challenge(new_uid)
                if not code:
                    flash(
                        ch_err or "Account was created but we could not send a verification code. Try logging in to request one.",
                        "error",
                    )
                    return render_template("register.html")
                ok_send, send_err = send_login_verification_code(
                    row["email"],
                    code,
                    username=str(row.get("username") or ""),
                    for_signup=True,
                )
                if not ok_send:
                    flash(
                        send_err
                        or "Could not send email. For Gmail use an App Password in MAIL_PASSWORD (not your normal Gmail password).",
                        "error",
                    )
                    return render_template("register.html")
                session.clear()
                session["pending_verify_uid"] = new_uid
                session["pending_verify_reason"] = "signup"
                session["pending_next"] = url_for("homes_page")
                return redirect(url_for("verify_email"))
            return render_template("register.html", account_created=True)
        if not ok:
            flash(err, "error")
    return render_template("register.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("index"))


@app.route("/api/dashboard")
def api_dashboard():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    verbose = request.args.get("verbose", "0") == "1"
    if request.args.get("include_tampa") == "1":
        plat = lat if lat is not None else DEFAULT_LAT
        plon = lon if lon is not None else DEFAULT_LON
        data, reg = get_or_build_dashboard_regional_pair(plat, plon, verbose=verbose)
        data["tampa_bay_regional"] = reg
    else:
        data = aggregate_dashboard(lat=lat, lon=lon, verbose=verbose)
    return jsonify(data)


@app.route("/api/endpoints")
def api_endpoints():
    return jsonify({"endpoints": catalog_endpoints()})


@app.route("/api/report")
def api_report():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    verbose = request.args.get("verbose", "0") == "1"
    data = aggregate_dashboard(lat=lat, lon=lon, verbose=verbose)
    text = strip_internal_api_refs(data.get("detailed_report") or "")
    return text, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/geocode")
def api_geocode():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"error": "query too short"}), 400
    return jsonify(mapbox_forward_geocode(q))


@app.route("/api/geocode/suggest")
def api_geocode_suggest():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"suggestions": [], "query": q, "error": "query too short"}), 400
    return jsonify(geocode_suggestions(q))


@app.route("/api/tampa/point")
def tampa_point():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    return jsonify(regional_lookup(lat, lon))


@app.route("/api/tampa/hub")
def tampa_hub():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    verbose = request.args.get("verbose", "0") == "1"
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    dash, reg = get_or_build_dashboard_regional_pair(lat, lon, verbose=verbose)
    return jsonify({"dashboard": dash, "tampa_bay_regional": reg})


@app.route("/api/tampa/lookup")
def tampa_lookup():
    q = (request.args.get("q") or request.args.get("address") or "").strip()
    out = assess_address(q)
    if out.get("error"):
        err = out["error"]
        code = 400 if "short" in err else 404
        return jsonify(out), code
    return jsonify(out)


@app.route("/api/tampa/zip/<zip_code>")
def tampa_zip(zip_code: str):
    seed_from_csv_if_empty()
    row = get_by_zip(zip_code)
    if not row:
        return jsonify({"error": "zip not in local Tampa metro database"}), 404
    lat, lon = row["lat"], row["lon"]
    dash, reg = get_or_build_dashboard_regional_pair(lat, lon, verbose=False)
    return jsonify(
        {
            "zip_record": row,
            "dashboard": dash,
            "tampa_bay_regional": reg,
            "risk_card": build_risk_card(dash, reg, row),
        }
    )


@app.route("/api/tampa/zips/search")
def tampa_zip_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"error": "query too short"}), 400
    seed_from_csv_if_empty()
    return jsonify({"results": search_city(q, limit=30)})


@app.route("/api/tampa/zips/stats")
def tampa_zip_stats():
    seed_from_csv_if_empty()
    return jsonify(zip_stats())


@app.route("/api/news/feed")
def api_news_feed():
    """News headlines from SQLite; triggers background re-ingest when the cache is stale or empty."""
    seed_from_csv_if_empty()
    refresh_info = request_news_refresh_if_stale()
    try:
        limit = int(request.args.get("limit", default=50) or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get("offset", default=0) or 0)
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    source = (request.args.get("source") or "").strip() or None
    house_name = (request.args.get("house_name") or request.args.get("home_nickname") or "").strip()

    key_raw = _request_api_key_raw()
    key_uid: int | None = None
    if key_raw:
        key_uid = resolve_user_from_api_key(key_raw)
        if key_uid is None:
            return jsonify({"error": "Invalid or revoked API key."}), 401

    stats = news_feed_stats()
    last_ingest = meta_get_value("news_last_ingest_at")

    if key_uid is not None:
        profiles = list_home_profiles(key_uid, skip_zip_seed=True)
        if house_name:
            profiles = _filter_profiles_by_house_name(profiles, house_name)
            if not profiles:
                return jsonify(
                    {"error": "house_name did not match any saved home for this API key."}
                ), 404
        raw = list_news_feed_items(320, source=source)
        ranked, reader_loc = _rank_news_feed_for_user(raw, profiles, limit=320)
        items = ranked[offset : offset + limit]
        return jsonify(
            {
                "items": items,
                "stats": stats,
                "last_ingest_at": last_ingest,
                "refresh": refresh_info,
                "query": {
                    "limit": limit,
                    "offset": offset,
                    "source": source,
                    "house_name": house_name or None,
                    "personalized": True,
                },
                "reader_location": reader_loc,
            }
        )

    items = list_news_feed_items(limit=limit, offset=offset, source=source)
    return jsonify(
        {
            "items": items,
            "stats": stats,
            "last_ingest_at": last_ingest,
            "refresh": refresh_info,
            "query": {
                "limit": limit,
                "offset": offset,
                "source": source,
                "house_name": None,
                "personalized": False,
            },
        }
    )


@app.route("/api/news/ingest", methods=["POST"])
def api_news_ingest():
    """
    Fetch Mediastack, GNews, RSS (FDEM URL + NHC), NWS TBW-filtered alerts, Reddit, HCFL page.
    Protected: set NEWS_INGEST_SECRET and send header X-News-Ingest-Secret, or call from localhost.
    """
    if not _news_ingest_allowed():
        return jsonify({"error": "Forbidden", "hint": "Set NEWS_INGEST_SECRET + X-News-Ingest-Secret, or use localhost."}), 403
    payload = request.get_json(silent=True) or {}
    md = payload.get("mediastack_date")
    mediastack_date = str(md).strip() if md not in (None, "") else None
    gf = payload.get("gnews_from")
    gt = payload.get("gnews_to")
    gnews_from = str(gf).strip() if gf not in (None, "") else None
    gnews_to = str(gt).strip() if gt not in (None, "") else None
    skip_hcfl = bool(payload.get("skip_hcfl"))
    reddit_limit = int(payload.get("reddit_limit") or 25)
    result = run_full_ingest(
        mediastack_date=mediastack_date,
        gnews_from=gnews_from,
        gnews_to=gnews_to,
        reddit_limit=max(1, min(reddit_limit, 100)),
        skip_hcfl=skip_hcfl,
    )
    return jsonify(result)


@app.route("/api/news/refresh", methods=["POST"])
@login_required
def api_news_refresh():
    """Queue a full re-ingest into the database (same sources as /api/news/ingest)."""
    seed_from_csv_if_empty()
    return jsonify(force_news_refresh_async())


@app.route("/api/news/ai-brief", methods=["POST"])
@login_required
def api_news_ai_brief():
    """Claude summary of articles currently stored in news_feed_items."""
    seed_from_csv_if_empty()
    uid = _session_user_id()
    profiles = list_home_profiles(uid, skip_zip_seed=True) if uid is not None else []
    raw = list_news_feed_items(200)
    items, loc = _rank_news_feed_for_user(raw, profiles, limit=72)
    if not items:
        return jsonify({"error": "No articles in the database yet — wait for the feed refresh to finish."}), 400
    brief, err = call_claude_news_brief(articles=items, reader_location=loc)
    if err:
        return jsonify({"error": err}), 502
    return jsonify({"brief": brief, "article_count": len(items)})


@app.route("/notifications")
@login_required
def notifications_page():
    """Email preferences, sample mail, and DB-backed news + AI brief (logged-in)."""
    seed_from_csv_if_empty()
    request_news_refresh_if_stale()
    uid = _session_user_id()
    profiles = list_home_profiles(uid, skip_zip_seed=True) if uid is not None else []
    raw = list_news_feed_items(200)
    news_items, news_reader_location = _rank_news_feed_for_user(raw, profiles, limit=72)
    return render_template(
        "notifications.html",
        news_items=news_items,
        news_last_sync=meta_get_value("news_last_ingest_at"),
        news_stats=news_feed_stats(),
        news_reader_location=news_reader_location,
    )


@app.route("/api/assessment/home", methods=["GET", "POST"])
@login_required
def api_assessment_home():
    """
    Dedicated home / property risk bundle (same engine as the Home risk UI).

    Full: all keys (dashboard, tampa_bay_regional, risk_card) for the interactive page.
    Compact: scores + risk_card + slim evacuation/traffic/snapshot only — for scripts and widgets.

    GET query: address=… OR lat=&lon=, optional compact=1
    POST JSON: {"address": "…"} OR {"lat": n, "lon": n}, optional "compact": true
    """
    compact = False
    address = ""
    lat: float | None = None
    lon: float | None = None

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        address = (data.get("address") or "").strip()
        compact = bool(data.get("compact"))
        try:
            if data.get("lat") is not None and data.get("lon") is not None:
                lat = float(data["lat"])
                lon = float(data["lon"])
        except (TypeError, ValueError):
            return jsonify({"error": "lat and lon must be numbers"}), 400
    else:
        address = (request.args.get("address") or request.args.get("q") or "").strip()
        compact = request.args.get("compact") == "1"
        lat = request.args.get("lat", type=float)
        lon = request.args.get("lon", type=float)

    seed_from_csv_if_empty()

    if address and len(address) >= 4:
        out = assess_address(address)
    elif lat is not None and lon is not None:
        out = assess_coordinates(lat, lon)
    else:
        return jsonify(
            {
                "error": "Provide address (4+ characters) or both lat and lon",
                "hint": "Use the address or lat/lon query parameters documented on the Data API page (signed-in home assessment uses the same fields).",
            }
        ), 400

    if out.get("error"):
        err = out["error"]
        low = err.lower()
        code = (
            404
            if "no geocode" in low or "zip not" in low or "not in tampa" in low or "not in local" in low
            else 400
        )
        return jsonify(out), code

    if compact:
        return jsonify(
            {
                "schema": "hurricane_hub.home_assessment.compact.v1",
                **compact_home_assessment(out),
            }
        )
    return jsonify({"schema": "hurricane_hub.home_assessment.full.v1", **out})


@app.route("/api/user/threat-tier-watch", methods=["POST"])
@login_required
def api_user_threat_tier_watch():
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    tier = (str(data.get("tier") or "")).strip().lower()
    allowed = {"low", "elevated", "high", "extreme"}
    if tier not in allowed:
        return jsonify({"error": "invalid tier"}), 400
    process_severity_change(uid, tier, data.get("score"))
    return jsonify({"ok": True})


@app.route("/api/user/alert-email-pref", methods=["POST"])
@login_required
def api_user_alert_email_pref():
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if "opt_in" not in data:
        return jsonify({"error": "opt_in required"}), 400
    opt_in = bool(data.get("opt_in"))
    set_user_alert_email_opt_in(uid, opt_in)
    return jsonify({"ok": True, "opt_in": opt_in})


@app.route("/api/user/me", methods=["GET"])
@login_required
def api_user_me():
    """Account flags and saved homes — all from SQLite (no live weather in this response)."""
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    user = get_user_by_id(uid)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    profiles = list_home_profiles(uid, skip_zip_seed=True)
    return jsonify(
        {
            "user": {
                "id": user["id"],
                "username": user.get("username"),
                "email": user.get("email"),
                "email_verified": int(user.get("email_verified") or 0),
                "alert_email_opt_in": int(user.get("alert_email_opt_in") or 0),
                "evacuation_alert_opt_in": int(user.get("evacuation_alert_opt_in") or 0),
            },
            "profiles": profiles,
        }
    )


@app.route("/api/user/evacuation-alert-pref", methods=["POST"])
@login_required
def api_user_evacuation_alert_pref():
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if "opt_in" not in data:
        return jsonify({"error": "opt_in required"}), 400
    opt_in = bool(data.get("opt_in"))
    set_user_evacuation_alert_opt_in(uid, opt_in)
    return jsonify({"ok": True, "opt_in": opt_in})


@app.route("/api/user/evacuation-alert-test-email", methods=["POST"])
@login_required
def api_user_evacuation_alert_test_email():
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    user = get_user_by_id(uid)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not int(user.get("email_verified") or 0):
        return jsonify({"error": "Verify your email before test sends."}), 400
    email = (user.get("email") or "").strip()
    if not email:
        return jsonify({"error": "No email on file."}), 400
    now = time.time()
    last = session.get("evac_alert_test_ts")
    if last is not None and now - float(last) < 60:
        return jsonify({"error": "Wait about a minute between test emails."}), 429
    profs = list_home_profiles(uid, skip_zip_seed=True)
    nick = (profs[0].get("nickname") if profs else None) or "My saved home"
    ok, err = send_evacuation_zone_sample_email(
        email,
        username=str(user.get("username") or ""),
        sample_home_nickname=str(nick),
    )
    if not ok:
        return jsonify({"error": err or "Send failed"}), 500
    session["evac_alert_test_ts"] = now
    return jsonify({"ok": True, "sent_to": _mask_email(email)})


@app.route("/api/user/notification-prefs", methods=["POST"])
@login_required
def api_user_notification_prefs():
    """Save tier + evacuation email flags together; confirm by email when any option is on."""
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    tier = bool(data.get("tier_alerts"))
    evac = bool(data.get("evacuation_alerts"))
    set_user_alert_email_opt_in(uid, tier)
    set_user_evacuation_alert_opt_in(uid, evac)
    user = get_user_by_id(uid)
    email_sent = False
    if (
        user
        and smtp_configured()
        and (tier or evac)
        and int(user.get("email_verified") or 0)
        and (user.get("email") or "").strip()
    ):
        ok, _ = send_notification_preferences_confirmation_email(
            (user.get("email") or "").strip(),
            username=str(user.get("username") or ""),
            tier_alerts=tier,
            evacuation_alerts=evac,
        )
        email_sent = bool(ok)
    return jsonify(
        {
            "ok": True,
            "tier_alerts": tier,
            "evacuation_alerts": evac,
            "confirmation_email_sent": email_sent,
        }
    )


@app.route("/api/user/api-key", methods=["GET", "POST"])
@login_required
def api_user_api_key():
    """Mint or check a personal API key for personalized news feed queries."""
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
    if request.method == "GET":
        return jsonify({"has_api_key": user_has_api_key(uid)})
    plain = mint_user_api_key(uid)
    return jsonify(
        {
            "api_key": plain,
            "message": "Copy this key now — the server only stores a hash. Use header X-API-Key or Authorization: Bearer …",
        }
    )


@app.route("/homes")
@login_required
def homes_page():
    seed_from_csv_if_empty()
    return render_template("homes.html")


@app.route("/homes/<int:pid>")
@login_required
def home_snapshot_page(pid: int):
    """Dedicated page for one saved profile — full snapshot without the address workflow above the fold."""
    seed_from_csv_if_empty()
    uid = _session_user_id()
    row = get_home_profile(pid, uid) if uid is not None else None
    if not row:
        flash("That saved home was not found.", "error")
        return redirect(url_for("homes_page"))
    assessment = None
    raw = row.get("last_assessment_json")
    if raw:
        try:
            assessment = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            assessment = None
    return render_template(
        "home_snapshot.html",
        profile_id=pid,
        profile_nickname=(row.get("nickname") or "Saved home").strip() or "Saved home",
        profile_address=(row.get("address_line") or "—").strip() or "—",
        assessment=assessment,
    )


@app.route("/api/profiles/evac-route", methods=["POST"])
@login_required
def api_profiles_evac_route():
    """Driving estimate from an assessed origin to a user-entered destination (Nominatim + optional Mapbox)."""
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
    data = request.get_json(silent=True) or {}
    try:
        from_lat = float(data.get("from_lat"))
        from_lon = float(data.get("from_lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "from_lat and from_lon required as numbers"}), 400
    dest = (data.get("destination") or data.get("to") or "").strip()
    out = plan_evac_drive(from_lat, from_lon, dest)
    if out.get("error"):
        return jsonify(out), 400
    return jsonify(out)


@app.route("/api/profiles/assess", methods=["POST"])
@login_required
def api_profiles_assess():
    """Backward-compatible alias — same payload as POST /api/assessment/home (full)."""
    data = request.get_json(silent=True) or {}
    addr = (data.get("address") or "").strip()
    seed_from_csv_if_empty()
    out = assess_address(addr)
    if out.get("error"):
        low = out["error"].lower()
        code = 404 if "no geocode" in low or "zip not" in low or "not in tampa" in low else 400
        return jsonify(out), code
    return jsonify({"schema": "hurricane_hub.home_assessment.full.v1", **out})


@app.route("/api/profiles", methods=["GET", "POST"])
@login_required
def api_profiles():
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
    if request.method == "GET":
        return jsonify({"profiles": list_home_profiles(uid, skip_zip_seed=True)})
    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "My home").strip()
    address = (data.get("address") or "").strip()
    if len(address) < 4:
        return jsonify({"error": "address required"}), 400
    out = assess_address(address)
    if out.get("error"):
        return jsonify(out), 400
    g = out.get("geocode") or {}
    pid = save_home_profile(
        uid,
        nickname,
        address,
        g.get("lat"),
        g.get("lon"),
        out.get("matched_zip"),
        out,
    )
    return jsonify({"id": pid, "saved": True, "assessment": {"schema": "hurricane_hub.home_assessment.full.v1", **out}})


@app.route("/api/profiles/<int:pid>", methods=["GET", "DELETE"])
@login_required
def api_profile_one(pid: int):
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
    if request.method == "DELETE":
        if delete_home_profile(pid, uid):
            return jsonify({"deleted": True})
        return jsonify({"error": "not found"}), 404
    row = get_home_profile(pid, uid)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


_TOPIC_SUMMARY_LABELS = {
    "alerts": "Weather alerts & rain chances",
    "coastal": "Bay water & seas",
    "weather": "Rain & wind (forecast)",
    "rivers": "Rivers & creek levels",
    "terrain": "Ground height at this spot",
    "tds": "How your risk score works",
    "evac": "Evacuation zone",
    "traffic": "Nearby traffic & route check",
    "local": "ZIP & regional context",
}
_TOPIC_SUMMARY_ALLOWED: dict[str, frozenset[str]] = {
    "dashboard": frozenset(
        {"alerts", "coastal", "weather", "rivers", "terrain", "tds"},
    ),
    "home_risk": frozenset(
        {
            "alerts",
            "coastal",
            "weather",
            "rivers",
            "terrain",
            "tds",
            "evac",
            "traffic",
            "local",
        },
    ),
}


@app.route("/api/assistant/topic-summary", methods=["POST"])
@login_required
def api_assistant_topic_summary():
    """Brief AI blurb for the dashboard / home “Show me…” topic (logged-in only)."""
    data = request.get_json(silent=True) or {}
    page = (data.get("page") or "").strip()
    allowed = _TOPIC_SUMMARY_ALLOWED.get(page)
    if allowed is None:
        return jsonify({"error": 'page must be "dashboard" or "home_risk"'}), 400
    topic = sanitize_chat_text((data.get("topic") or "").strip(), max_len=64)
    if topic not in allowed:
        return jsonify({"error": "invalid or unsupported topic"}), 400
    ctx = data.get("context")
    if ctx is None or not isinstance(ctx, dict):
        return jsonify({"error": "context must be a JSON object"}), 400
    label = _TOPIC_SUMMARY_LABELS.get(topic, topic)
    reply, err = call_claude_topic_brief(
        page=page,
        context=dict(ctx),
        topic_key=topic,
        topic_label=label,
    )
    if err:
        low = err.lower()
        code = 503 if "not configured" in low or "anthropic_api_key" in low else 502
        return jsonify({"error": err}), code
    return jsonify({"reply": reply})


@app.route("/api/assistant/chat", methods=["POST"])
@login_required
def api_assistant_chat():
    """In-app guide: answers using the page snapshot the client sends. Server needs API key in .env."""
    data = request.get_json(silent=True) or {}
    page = (data.get("page") or "").strip()
    if page not in ("dashboard", "home_risk", "general", "evacuation", "notifications"):
        return jsonify(
            {"error": 'page must be "dashboard", "home_risk", "evacuation", "notifications", or "general"'}
        ), 400
    ctx = data.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        return jsonify({"error": "context must be a JSON object"}), 400
    ctx = dict(ctx) if isinstance(ctx, dict) else {}
    prompt = sanitize_chat_text((data.get("message") or data.get("prompt") or ""), max_len=8000)
    if not prompt:
        return jsonify({"error": "message is required"}), 400

    prior = _normalize_assistant_prior_messages(data.get("messages"))
    reply, err = call_claude(page=page, context=ctx, prior_messages=prior, user_message=prompt)
    if err:
        low = err.lower()
        code = 503 if "not configured" in low or "anthropic_api_key" in low else 502
        return jsonify({"error": err}), code
    return jsonify({"reply": reply})


@app.route("/api/profiles/<int:pid>/refresh", methods=["POST"])
@login_required
def api_profile_refresh(pid: int):
    uid = _session_user_id()
    if uid is None:
        return jsonify({"error": "Unauthorized", "login_url": url_for("login")}), 401
    row = get_home_profile(pid, uid)
    if not row:
        return jsonify({"error": "not found"}), 404
    out = assess_address(row["address_line"])
    if out.get("error"):
        return jsonify(out), 400
    update_profile_assessment(pid, uid, out)
    return jsonify({"schema": "hurricane_hub.home_assessment.full.v1", **out})


def create_app():
    init_auth_db()
    return app


@app.errorhandler(404)
def page_not_found(_e):
    return render_template("404.html"), 404


init_auth_db()
request_news_refresh_if_stale()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
