# HACKUSF2026

## Hurricane Hub

A Flask-based prototype for storm readiness and flood risk assessment in Tampa Bay. This app combines live weather, water, emergency, and local flood-zone data with address-level home risk summaries, user profiles, and assistant chat.

## Key capabilities

- Real-time threat score dashboard (weather + water + advisories)
- Address-based home risk assessment with full/compact output
- Tampa Bay zip lookup / regional model (point & zip, heatmap mode)
- Saved home profiles with refresh and PDF report export
- Interactive heat map of Tampa metro zip risk
- Login/register, profile CRUD, protected user APIs
- Claude conversational assistant for dashboard/home insight
- Evacuation route planning (Nominatim + Mapbox fallback)

## Tech stack

- Python 3.11+ (tested)
- Flask
- SQLite (auth + saved homes + Tampa zips)
- requests, fpdf
- Frontend: HTML/CSS/Vanilla JS, Mapbox, Leaflet, Chart + SVG dials

## Repository structure

```
UIBuilder/
├── app.py                        # Flask routes, auth, business flows, API endpoints
├── requirements.txt              # Python dependencies
├── data/
│   └── tampa_metro_zips.csv      # regional ZIP metadata with coordinates, flood links
├── scripts/
│   ├── build_enriched_zips.py    # build local zip database with local risk fields
│   └── test_endpoints.py         # smoke API tests
├── services/
│   ├── apis.py                   # NOAA/NWS/USGS/Mapbox data aggregators + endpoint catalog
│   ├── auth_db.py                # user table and auth helpers
│   ├── claude_chat.py            # Claude API assist chat integration
│   ├── geocode.py                # address geocoding helpers, Mapbox fallback
│   ├── home_assessment.py        # full/compact risk engine, threat scoring, risk card
│   ├── regional_tampa.py         # Tampa lookup logic (county, flood zone, outage layers)
│   └── tampa_db.py               # local zip DB CRUD/search/stats and seeding
├── static/
│   ├── css/style.css
│   └── js/
│       ├── address-autocomplete.js
│       ├── app.js
│       ├── assistant-chat.js
│       ├── dashboard-heatmap.js
│       ├── home-share-report.js
│       ├── homes.js
│       └── score-ui.js
└── templates/
    ├── _assistant_chat.html
    ├── _home_results.html
    ├── base.html
    ├── dashboard.html
    ├── heatmap.html
    ├── home_snapshot.html
    ├── homes.html
    ├── how_scores.html
    ├── index.html
    ├── login.html
    └── register.html
```

## Getting started

1. Clone:
   ```bash
   git clone <repo-url>
   cd HACKUSF2026/UIBuilder
   ```
2. Python env
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Optional env vars
   ```bash
   export SECRET_KEY='super-secret'
   export HURRICANE_HUB_SEED_DEMO='1'  # seeds demo user/demo123 on startup
   export ANTHROPIC_API_KEY='your-key-here'  # for /api/assistant/chat
   ```
4. Run
   ```bash
   python app.py
   ```
5. Open `http://localhost:5000`

## Pages and UI

- `/`               → home dashboard
- `/dashboard`      → detailed threat dashboard page
- `/heatmap`        → Tampa metro risk heat map
- `/homes`          → saved homes management (login required)
- `/homes/<id>`     → saved home snapshot (login required)
- `/how-scores`     → methodology docs
- `/login` `/register` / logout

## Main API endpoints (stable)

- `GET /api/dashboard` (lat, lon, verbose, include_tampa)
- `GET /api/endpoints`
- `GET /api/report` (text report by lat/lon)
- `GET /api/geocode?q=...`
- `GET /api/geocode/suggest?q=...`
- `GET /api/tampa/point?lat=..&lon=..`
- `GET /api/tampa/hub?lat=..&lon=..`  (dashboard+regional)
- `GET /api/tampa/lookup?q=address` (home assessment)
- `GET /api/tampa/zip/<zip>`
- `GET /api/tampa/zips/search?q=`
- `GET /api/tampa/zips/stats`
- `GET /api/heatmap/data` (`simulate` optional mild/big)

Protected endpoints (login required):
- `GET/POST /api/assessment/home` (compact=1 param/body)
- `GET /api/assessment/home/pdf` (generates PDF report)
- `POST /api/profiles` (create profile)
- `GET /api/profiles` (list profiles)
- `GET/DELETE /api/profiles/<pid>`
- `POST /api/profiles/<pid>/refresh` (refresh saved profile assessment)
- `POST /api/profiles/evac-route` (from_lat/from_lon/destination)
- `POST /api/profiles/assess` (alias for assessment)
- `POST /api/assistant/chat` (Claude assist with `page`, `context`, `message`, optional `messages`)

## Data process

- Local seed of `data/tampa_metro_zips.csv` into sqlite via `seed_from_csv_if_empty()`
- `scripts/build_enriched_zips.py` enriches csv offline with contextual risk hints
- `scripts/test_endpoints.py` verifies API path outputs

## Security

- Session-based auth with `SECRET_KEY`
- `login_required` decorator for profile and assessment endpoints
- Safe redirect handling via `_safe_internal_next`

## Notes

- `api/assistant/chat` requires a valid `ANTHROPIC_API_KEY`, otherwise returns 503.
- `/api/heatmap/data` can simulate event intensity without real API calls.
- PDF export uses `fpdf` and assembles a storm risk summary.

## Contributing

1. Fork
2. branch/feature
3. tests + docs
4. pull request

## License

HACKUSF2026 internal/prototype work for Hack USF 2026.

## Disclaimer

Prototype only; not a certified emergency decision system. Verify with local authorities and NWS for real decisions.
