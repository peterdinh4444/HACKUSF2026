# HACKUSF2026

## Hurricane Hub

A comprehensive web application for storm readiness and flood risk assessment in the Tampa Bay region. This Flask-based prototype aggregates data from multiple public APIs to provide real-time weather, water level, and advisory information with an intuitive user interface.

### Features

- **Storm Readiness Overview**: Real-time threat score dashboard combining weather, water, and advisory data
- **Home Risk Assessment**: Address-based flood and storm risk evaluation with detailed risk cards
- **Interactive Heat Map**: Visual representation of regional flood risk across Tampa metro ZIP codes
- **Regional Data Integration**: Tampa Bay-specific flood and emergency management data
- **User Authentication**: Secure user accounts for personalized home profiles
- **API Aggregation**: Unified access to multiple public data sources (NOAA, USGS, NWS, etc.)

### Technology Stack

- **Backend**: Python Flask
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla JS)
- **Data Sources**: NOAA Weather API, USGS Water Data, NWS Advisories, Mapbox Geocoding
- **Database**: SQLite (user auth and regional data)
- **Visualization**: Custom SVG dials and interactive maps

### Project Structure

```
UIBuilder/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── data/
│   └── tampa_metro_zips.csv  # Regional ZIP code data with flood risk metadata
├── scripts/
│   ├── build_enriched_zips.py  # Data enrichment script
│   └── test_endpoints.py       # API testing utilities
├── services/
│   ├── apis.py            # API aggregation and data fetching
│   ├── auth_db.py         # User authentication database
│   ├── geocode.py         # Address geocoding services
│   ├── home_assessment.py # Home risk assessment logic
│   ├── regional_tampa.py  # Tampa Bay regional data
│   └── tampa_db.py        # Regional database operations
├── static/
│   ├── css/style.css      # Application styles
│   └── js/
│       ├── app.js         # Main application logic
│       ├── homes.js       # Home management interface
│       └── score-ui.js    # Score visualization components
└── templates/
    ├── base.html          # Base template
    ├── index.html         # Overview/dashboard page
    ├── homes.html         # Home profiles page
    ├── heatmap.html       # Heat map visualization
    ├── login.html         # User login
    └── register.html      # User registration
```

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd HACKUSF2026
   ```

2. **Set up Python environment**:
   ```bash
   cd UIBuilder
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables** (optional):
   ```bash
   export SECRET_KEY="your-secret-key-here"
   export HURRICANE_HUB_SEED_DEMO="1"  # Enables demo user seeding
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Access the application**:
   Open http://localhost:5000 in your browser

### Usage

#### For General Users
- **Overview Page**: View current storm threat score and regional conditions
- **Heat Map**: Explore flood risk across Tampa Bay ZIP codes
- **Home Assessment**: Search for addresses to get personalized risk profiles

#### For Registered Users
- Create an account to save and manage multiple home profiles
- Access detailed risk assessments for saved addresses
- Track changes in risk levels over time

### API Endpoints

The application provides several REST API endpoints:

- `GET /api/dashboard` - Aggregated weather and threat data
- `GET /api/endpoints` - List of available data sources
- `GET /api/geocode` - Address geocoding
- `GET /api/tampa/point` - Regional data for coordinates
- `GET /api/tampa/zip/<zip>` - ZIP code specific data
- `GET /api/heatmap/data` - Heat map data points

### Data Sources

Hurricane Hub aggregates data from:
- **NOAA Weather API**: Current conditions and forecasts
- **USGS Water Services**: Real-time water level data
- **National Weather Service**: Weather advisories and warnings
- **Mapbox Geocoding**: Address-to-coordinate conversion
- **FL511**: Traffic and evacuation route information
- **County Emergency Management**: Local flood zone data

### Development

#### Running Tests
```bash
cd UIBuilder
python scripts/test_endpoints.py
```

#### Data Enrichment
```bash
python scripts/build_enriched_zips.py
```

#### Code Style
The project follows Python PEP 8 standards and uses type hints throughout.

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

### License

This project is developed as part of HACKUSF2026. See individual file headers for licensing information.

### Disclaimer

This application is a prototype and should not be used as the sole source for emergency decision-making. Always consult official sources like the National Weather Service, local emergency management, and county flood zone maps for critical safety information.
