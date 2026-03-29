"""
Hurricane Hub — Flask prototype: aggregated public APIs for Tampa Bay flood / storm context.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from functools import wraps
from io import BytesIO
from datetime import datetime
import math
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from fpdf import FPDF

from services.apis import (
    DEFAULT_LAT,
    DEFAULT_LON,
    aggregate_dashboard,
    catalog_endpoints,
    geocode_suggestions,
    mapbox_forward_geocode,
    plan_evac_drive,
)
from services.auth_db import create_user, get_user_by_id, init_auth_db, verify_login
from services.home_assessment import (
    assess_address,
    assess_coordinates,
    build_risk_card,
    compact_home_assessment,
)
from services.regional_tampa import regional_lookup
from services.claude_chat import call_claude
from services.tampa_db import (
    delete_home_profile,
    get_all_zips,
    get_by_zip,
    get_home_profile,
    list_home_profiles,
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
        c = content.strip()
        if not c:
            continue
        if len(c) > 12000:
            c = c[:12000] + "…"
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


def _fpdf_safe(s: str) -> str:
    """PyFPDF 1.x encodes page text as Latin-1 internally; drop unsupported code points."""
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_text(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _format_coord(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.5f}"
    return _pdf_text(value)


def _render_assessment_pdf(assessment: dict) -> bytes:
    geo = assessment.get("geocode") or {}
    risk = assessment.get("risk_card") or {}
    dash = assessment.get("dashboard") or {}
    zip_info = assessment.get("zip_database_match") or {}

    address = _pdf_text(geo.get("display_name") or assessment.get("address") or "Selected location")
    score = _pdf_text(risk.get("threat_score") or dash.get("threat", {}).get("score"))
    tier = _pdf_text(risk.get("threat_tier") or dash.get("threat", {}).get("tier"))
    evacuation = _pdf_text(risk.get("evacuation_level"))
    county_url = _pdf_text(zip_info.get("county_emergency_url"))
    power_polygons = _pdf_text(risk.get("power_outage_polygons_in_bbox"))
    fl511_hits = _pdf_text(risk.get("fl511_incident_layers_total"))
    matched_zip = _pdf_text(assessment.get("matched_zip") or zip_info.get("zip") or zip_info.get("zip_code"))
    city = _pdf_text(zip_info.get("city"))
    county = _pdf_text(zip_info.get("county"))

    reasons = risk.get("threat_reasons") or dash.get("threat", {}).get("reasons") or []
    if reasons:
        recommendations = [f"{r}" for r in reasons[:5]]
    else:
        recommendations = ["No strong signals in this run."]

    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(False)

    pdf.set_fill_color(10, 41, 104)
    pdf.rect(0, 0, 210, 32, "F")
    pdf.set_fill_color(0, 102, 204)
    pdf.rect(0, 32, 210, 4, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 16)
    pdf.set_xy(12, 9)
    pdf.cell(0, 8, _fpdf_safe("HURRICANE HUB REPORT"), ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.set_xy(12, 18)
    pdf.cell(0, 6, _fpdf_safe("Weekly home risk assessment"), ln=1)
    pdf.set_font("Arial", "", 9)
    pdf.set_xy(12, 24)
    pdf.cell(0, 5, _fpdf_safe("Trusted Tampa metro flood + storm context"), ln=1)

    pdf.ln(12)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 7, _fpdf_safe("Report details"), ln=1)
    pdf.ln(1)
    pdf.set_draw_color(10, 41, 104)
    pdf.set_line_width(0.5)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 6, _fpdf_safe(f"Customer: {address}"), border=0)
    pdf.multi_cell(0, 6, _fpdf_safe(f"Report date: {generated_at}"), border=0)
    pdf.ln(2)

    summary = [
        ("Threat score", score),
        ("Threat tier", tier),
        ("Matched ZIP", matched_zip),
        ("City", city),
        ("County", county),
        ("Evacuation zone", evacuation),
        ("Power outage polygons", power_polygons),
        ("FL511 layer hits", fl511_hits),
    ]

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 7, _fpdf_safe("Assessment summary"), ln=1)
    pdf.ln(1)
    summary_start_y = pdf.get_y()

    ring_thickness = 8
    risk_circle_size = 32
    risk_circle_x = 150
    risk_circle_y = pdf.get_y() + risk_circle_size

    pdf.set_draw_color(230, 230, 230)
    pdf.set_line_width(ring_thickness)
    pdf.ellipse(
        risk_circle_x - risk_circle_size,
        risk_circle_y - risk_circle_size,
        risk_circle_size * 2,
        risk_circle_size * 2,
    )

    score_value = 0
    try:
        score_value = min(max(int(float(score)), 0), 100)
    except (TypeError, ValueError):
        score_value = 0

    if score_value > 0:
        filled_angle = score_value * 3.6
        steps = max(40, int(filled_angle / 3) + 1)
        points = []
        for step in range(steps + 1):
            angle = math.radians(-90 + filled_angle * step / steps)
            x = risk_circle_x + risk_circle_size * math.cos(angle)
            y = risk_circle_y + risk_circle_size * math.sin(angle)
            points.append((x, y))

        pdf.set_draw_color(10, 41, 104)
        pdf.set_line_width(ring_thickness)
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            pdf.line(x1, y1, x2, y2)

    pdf.set_font("Arial", "B", 16)
    pdf.set_text_color(10, 41, 104)
    pdf.set_xy(risk_circle_x - risk_circle_size, risk_circle_y - 5)
    pdf.cell(risk_circle_size * 2, 8, _fpdf_safe(score), border=0, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.set_text_color(10, 41, 104)
    pdf.set_xy(risk_circle_x - risk_circle_size, risk_circle_y + 4)
    pdf.cell(risk_circle_size * 2, 5, _fpdf_safe("Risk score"), border=0, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(15, summary_start_y)

    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.set_font("Arial", "", 9)
    for label, value in summary:
        pdf.set_font("Arial", "B", 9)
        pdf.set_text_color(10, 41, 104)
        pdf.cell(40, 5, _fpdf_safe(f"{label}: "), border=0, ln=0)
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 5, _fpdf_safe(value), border=0, align='L')
        pdf.ln(1)
        pdf.set_x(15)

    pdf.set_xy(15, max(pdf.get_y(), risk_circle_y + risk_circle_size) + 8)
    pdf.set_text_color(10, 41, 104)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 7, _fpdf_safe("Recommendations"), ln=1)
    pdf.ln(2)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 10)
    for item in recommendations:
        pdf.multi_cell(0, 6, _fpdf_safe(f"- {item}"), border=0)
        pdf.ln(1)

    # push County emergency URL down only if there is enough space on the same page
    url_block_top = pdf.h - 42
    if pdf.get_y() < url_block_top:
        pdf.set_y(url_block_top)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 5, _fpdf_safe("County emergency URL:"), border=0, ln=1)
    pdf.set_text_color(0, 102, 204)
    pdf.set_font("Arial", "U", 9)
    pdf.multi_cell(0, 5, _fpdf_safe(county_url), border=0, align='L')
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 10)

    footer_y = pdf.h - 18
    if pdf.get_y() < footer_y:
        pdf.set_y(footer_y)

    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, _fpdf_safe("Thank you for choosing Hurricane Hub. Questions? Contact our team anytime."), ln=1, align="C")
    pdf.cell(0, 6, _fpdf_safe(generated_at), ln=1, align="C")

    return pdf.output(dest="S").encode("latin-1", errors="replace")


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/how-scores")
def how_scores_page():
    """Technical methodology for TDS — public; rest of the app stays plain-language."""
    return render_template("how_scores.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = (request.args.get("next") or "").strip()
    if request.method == "POST":
        next_url = (request.form.get("next") or "").strip()
        user = verify_login(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            session.clear()
            session["user_id"] = user["id"]
            flash("Signed in.", "success")
            dest = _safe_internal_next(next_url) or url_for("homes_page")
            return redirect(dest)
        flash("Invalid username or password.", "error")
    demo_hint = ""
    if os.environ.get("HURRICANE_HUB_SEED_DEMO", "1") == "1":
        demo_hint = "First-time install seeds user demo / demo123."
    return render_template("login.html", next_url=next_url, demo_hint=demo_hint)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        ok, err = create_user(request.form.get("username", ""), request.form.get("password", ""))
        if ok:
            flash("Account created. Log in below.", "success")
            return redirect(url_for("login"))
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
    data = aggregate_dashboard(lat=lat, lon=lon, verbose=verbose)
    if request.args.get("include_tampa") == "1":
        plat = lat if lat is not None else DEFAULT_LAT
        plon = lon if lon is not None else DEFAULT_LON
        data["tampa_bay_regional"] = regional_lookup(plat, plon)
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
    text = data.get("detailed_report") or ""
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
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_dash = pool.submit(aggregate_dashboard, lat, lon, verbose)
        f_reg = pool.submit(regional_lookup, lat, lon)
        dash = f_dash.result()
        reg = f_reg.result()
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
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_dash = pool.submit(aggregate_dashboard, lat, lon, False)
        f_reg = pool.submit(regional_lookup, lat, lon)
        dash = f_dash.result()
        reg = f_reg.result()
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


@app.route("/api/heatmap/data")
def heatmap_data():
    seed_from_csv_if_empty()
    zips = get_all_zips()
    simulate = (request.args.get("simulate") or "").strip().lower()
    heat_data: list[list[float]] = []

    if simulate in ("mild", "big"):
        intensity = 0.30 if simulate == "mild" else 0.70
        for zip_row in zips:
            lat = zip_row.get("lat")
            lon = zip_row.get("lon")
            if lat is None or lon is None:
                continue
            heat_data.append([float(lat), float(lon), intensity])
        return jsonify({"heat_data": heat_data, "simulate": simulate})

    for zip_row in zips:
        lat = zip_row.get("lat")
        lon = zip_row.get("lon")
        if lat is None or lon is None:
            continue
        try:
            dash = aggregate_dashboard(lat=float(lat), lon=float(lon), verbose=False)
            score = (dash.get("threat") or {}).get("score", 0)
            intensity = min(max(float(score) / 100.0, 0.0), 1.0)
        except Exception:
            intensity = 0.0
        heat_data.append([float(lat), float(lon), intensity])

    return jsonify({"heat_data": heat_data, "simulate": ""})


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
                "hint": "GET /api/assessment/home?address=Tampa+FL or ?lat=27.95&lon=-82.45&compact=1",
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


@app.route("/api/assessment/home/pdf")
@login_required
def api_assessment_home_pdf():
    address = (request.args.get("address") or request.args.get("q") or "").strip()
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if address and len(address) >= 4:
        out = assess_address(address)
    elif lat is not None and lon is not None:
        out = assess_coordinates(lat, lon)
    else:
        return (
            jsonify(
                {
                    "error": "Provide address (4+ characters) or both lat and lon",
                    "hint": "GET /api/assessment/home/pdf?address=Tampa+FL or ?lat=27.95&lon=-82.45",
                }
            ),
            400,
        )

    if out.get("error"):
        err = out["error"]
        low = str(err).lower()
        code = 404 if "no geocode" in low or "zip not" in low or "not in tampa" in low or "not in local" in low else 400
        return jsonify({"error": err}), code

    pdf_bytes = _render_assessment_pdf(out)
    safe = address.replace("/", "-").replace("\\\\", "-")
    safe = "".join([c if c.isalnum() or c in " -_" else "-" for c in safe]).strip().replace(" ", "-")
    if not safe:
        safe = "home-summary"
    filename = f"hurricane-hub-home-summary-{safe[:40]}.pdf"
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@app.route("/homes")
@login_required
def homes_page():
    seed_from_csv_if_empty()
    return render_template("homes.html")


@app.route("/heatmap")
def heatmap_page():
    return render_template("heatmap.html")


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
        return jsonify({"profiles": list_home_profiles(uid)})
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


@app.route("/api/assistant/chat", methods=["POST"])
@login_required
def api_assistant_chat():
    """
    Claude-powered Q&A using the JSON snapshot the client sends (dashboard or home assessment).
    Requires ANTHROPIC_API_KEY on the server.
    """
    data = request.get_json(silent=True) or {}
    page = (data.get("page") or "").strip()
    if page not in ("dashboard", "home_risk"):
        return jsonify({"error": 'page must be "dashboard" or "home_risk"'}), 400
    ctx = data.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        return jsonify({"error": "context must be a JSON object"}), 400
    ctx = dict(ctx) if isinstance(ctx, dict) else {}
    prompt = (data.get("message") or data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "message is required"}), 400
    if len(prompt) > 8000:
        return jsonify({"error": "message too long"}), 400

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


init_auth_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
