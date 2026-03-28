"""
Hurricane Hub — Flask prototype: aggregated public APIs for Tampa Bay flood / storm context.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from urllib.parse import urlparse

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
    mapbox_forward_geocode,
)
from services.auth_db import create_user, get_user_by_id, init_auth_db, verify_login
from services.home_assessment import assess_address, build_risk_card
from services.regional_tampa import regional_lookup
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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")


@app.route('/favicon.ico')
def favicon():
    return '', 204


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


@app.route("/api/tampa/zips/all")
def tampa_zips_all():
    seed_from_csv_if_empty()
    return jsonify({"zips": get_all_zips()})


@app.route("/api/heatmap/data")
def heatmap_data():
    seed_from_csv_if_empty()
    zips = get_all_zips()
    simulate = request.args.get("simulate", "").lower()
    heat_data = []
    
    if simulate:
        # For simulation, use fixed intensities to ensure visible change
        intensity = 0.3 if simulate == "mild" else 0.7
        for zip_row in zips:
            lat, lon = zip_row["lat"], zip_row["lon"]
            heat_data.append([lat, lon, intensity])
    else:
        # Real-time data
        for zip_row in zips:
            lat, lon = zip_row["lat"], zip_row["lon"]
            try:
                dash = aggregate_dashboard(lat=lat, lon=lon, verbose=False)
                threat = dash.get("threat", {})
                score = threat.get("score", 0)
                # Normalize score to 0-1 for heat intensity
                intensity = min(max(score / 100.0, 0.0), 1.0)
                heat_data.append([lat, lon, intensity])
            except Exception as e:
                print(f"Error getting threat for {zip_row['zip']}: {e}")
                heat_data.append([lat, lon, 0.0])
    
    return jsonify({"heat_data": heat_data})


@app.route("/homes")
@login_required
def homes_page():
    seed_from_csv_if_empty()
    return render_template("homes.html")


@app.route("/heatmap")
def heatmap_page():
    return render_template("heatmap.html")


@app.route("/api/profiles/assess", methods=["POST"])
@login_required
def api_profiles_assess():
    data = request.get_json(silent=True) or {}
    addr = (data.get("address") or "").strip()
    out = assess_address(addr)
    if out.get("error"):
        return jsonify(out), 400
    return jsonify(out)


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
    return jsonify({"id": pid, "saved": True, "assessment": out})


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
    return jsonify(out)


def create_app():
    init_auth_db()
    return app


init_auth_db()

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
