"""
Krishi-Sathi — Flask Backend
AI-first precision agriculture SaaS that turns free multispectral satellite
imagery into field-level decisions (irrigation nudges, pest alerts, yield forecasts).

Data sources:
  - Sentinel-2 L2A (Copernicus STAC API)
  - Open-Meteo (weather)
  - Simulated sensor data (soil moisture probes)

Pilot sites:
  1. Dr. Ambedkar Institute of Technology, Bengaluru (12.9588 N, 77.5038 E)
  2. ICRISAT, Patancheru / Hyderabad (17.320 N, 78.210 E)
  3. Ludhiana, Punjab (30.9010 N, 75.8573 E)
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import requests as http_requests
import sqlite3
import base64
import json
import os
import traceback

from config import (
    APP_NAME, APP_VERSION, APP_DESCRIPTION,
    STAC_API_URL, CDSE_TOKEN_URL, COLLECTIONS,
    PILOT_SITES, CROP_PROFILES, NUDGE_TEMPLATES,
    S2_BANDS, ONNX_CONFIG, DB_PATH, DEFAULT_PORT, DEBUG_MODE,
)
from pipeline import (
    init_pipeline_db, seed_pilot_fields, get_db,
    search_stac, build_bbox, build_datetime_range,
    generate_simulated_indices, store_indices, get_field_timeseries,
    fetch_weather, get_weather_history,
    compute_ndvi, compute_ndwi, compute_reci, compute_bsi,
    classify_ndvi, classify_ndwi,
)
from models import (
    smc_model, pest_detector, yield_forecaster,
    generate_model_export_script,
)
from nudge_engine import nudge_generator

# App Setup
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# Initialize database and seed pilot fields
init_pipeline_db()
seed_pilot_fields()


# ═══════════════════════════════════════════════════════════════
#  Credential Storage
# ═══════════════════════════════════════════════════════════════

def _init_cred_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

_init_cred_table()


def save_credentials(username: str, password: str):
    enc = base64.b64encode(password.encode()).decode()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO credentials (id, username, password) VALUES (1, ?, ?)",
        (username, enc),
    )
    conn.commit()
    conn.close()


def load_credentials():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT username, password FROM credentials WHERE id = 1").fetchone()
    conn.close()
    if row:
        return row[0], base64.b64decode(row[1]).decode()
    return None


def clear_credentials():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM credentials WHERE id = 1")
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Static & Info Routes
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/info")
def app_info():
    """Application metadata."""
    return jsonify({
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": APP_DESCRIPTION,
        "pilot_sites": len(PILOT_SITES),
        "crops_supported": list(CROP_PROFILES.keys()),
        "model_stack": {
            "soil_moisture": "CNN (2D Conv + Temporal Encoder)",
            "pest_detection": "Unsupervised Spectral Anomaly",
            "yield_forecast": "Multi-modal (NDVI + SMC + Weather)",
            "export_format": "ONNX (INT8 PTQ)",
            "target_device": ONNX_CONFIG["target_device"],
        },
    })


@app.route("/api/collections")
def get_collections():
    return jsonify(COLLECTIONS)


# ═══════════════════════════════════════════════════════════════
#  Authentication (Copernicus)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/credentials", methods=["GET"])
def get_credentials():
    creds = load_credentials()
    if creds:
        return jsonify({"saved": True, "username": creds[0]})
    return jsonify({"saved": False})


@app.route("/api/credentials", methods=["DELETE"])
def delete_credentials():
    clear_credentials()
    return jsonify({"ok": True})


@app.route("/api/token", methods=["POST"])
def get_token():
    data = request.get_json()
    username = data.get("username") if data else None
    password = data.get("password") if data else None
    should_save = data.get("save", True) if data else False

    if not username or not password:
        saved = load_credentials()
        if saved:
            username, password = saved
        else:
            return jsonify({"error": "Credentials required"}), 400

    try:
        resp = http_requests.post(
            CDSE_TOKEN_URL,
            data={
                "client_id": "cdse-public",
                "grant_type": "password",
                "username": username,
                "password": password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )

        if resp.status_code in (401, 400):
            return jsonify({"error": "Invalid credentials"}), 401

        resp.raise_for_status()
        token_data = resp.json()

        if should_save:
            save_credentials(username, password)

        return jsonify({
            "access_token": token_data.get("access_token", ""),
            "expires_in": token_data.get("expires_in", 600),
            "refresh_token": token_data.get("refresh_token", ""),
        })
    except http_requests.exceptions.RequestException as e:
        return jsonify({"error": f"Auth failed: {str(e)}"}), 500


# ═══════════════════════════════════════════════════════════════
#  STAC Search (Sentinel Imagery)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/search", methods=["POST"])
def search():
    """Search Copernicus STAC API for satellite imagery."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    lat = data.get("lat")
    lon = data.get("lon")
    date_str = data.get("date")
    days = data.get("days", 15)
    collections = data.get("collections", ["sentinel-2-l2a", "sentinel-1-grd"])
    cloud_cover = data.get("cloud_cover", 30)
    limit = min(data.get("limit", 10), 50)

    if lat is None or lon is None or not date_str:
        return jsonify({"error": "lat, lon, and date required"}), 400

    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinates"}), 400

    results = search_stac(lat, lon, date_str, collections, days, cloud_cover, limit)
    return jsonify(results)


# ═══════════════════════════════════════════════════════════════
#  Pilot Sites
# ═══════════════════════════════════════════════════════════════

@app.route("/api/sites")
def get_sites():
    """Return all pilot sites with field details."""
    sites = {}
    for key, site in PILOT_SITES.items():
        sites[key] = {
            **site,
            "field_count": len(site.get("fields", [])),
        }
    return jsonify(sites)


@app.route("/api/sites/<site_key>")
def get_site(site_key):
    """Get detailed info for a specific pilot site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404
    return jsonify(site)


@app.route("/api/sites/<site_key>/fields")
def get_site_fields(site_key):
    """Get all fields for a pilot site from database."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM fields WHERE site_key = ?", (site_key,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ═══════════════════════════════════════════════════════════════
#  Spectral Indices & Time Series
# ═══════════════════════════════════════════════════════════════

@app.route("/api/indices/<field_id>")
def get_indices(field_id):
    """Get NDVI/NDWI time series for a field. Auto-generates if empty."""
    days = request.args.get("days", 90, type=int)

    # Check if data exists
    ts = get_field_timeseries(field_id, days)

    if not ts:
        # Auto-generate simulated data
        conn = get_db()
        field_row = conn.execute(
            "SELECT * FROM fields WHERE field_id = ?", (field_id,)
        ).fetchone()
        conn.close()

        if field_row:
            start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(
                field_id, dict(field_row)["site_key"], start, days
            )
            store_indices(records)
            ts = get_field_timeseries(field_id, days)

    # Compute summary statistics
    if ts:
        ndvi_vals = [t["ndvi"] for t in ts if t["ndvi"] is not None]
        ndwi_vals = [t["ndwi"] for t in ts if t["ndwi"] is not None]
        summary = {
            "ndvi_current": ndvi_vals[-1] if ndvi_vals else None,
            "ndvi_mean": round(sum(ndvi_vals) / len(ndvi_vals), 4) if ndvi_vals else None,
            "ndvi_min": round(min(ndvi_vals), 4) if ndvi_vals else None,
            "ndvi_max": round(max(ndvi_vals), 4) if ndvi_vals else None,
            "ndvi_trend": _compute_trend(ndvi_vals),
            "ndwi_current": ndwi_vals[-1] if ndwi_vals else None,
            "ndwi_mean": round(sum(ndwi_vals) / len(ndwi_vals), 4) if ndwi_vals else None,
            "ndvi_class": classify_ndvi(ndvi_vals[-1]) if ndvi_vals else "unknown",
            "ndwi_class": classify_ndwi(ndwi_vals[-1]) if ndwi_vals else "unknown",
            "observations": len(ts),
        }
    else:
        summary = {}

    return jsonify({"field_id": field_id, "timeseries": ts, "summary": summary})


def _compute_trend(values: list) -> str:
    """Simple trend detection over last 5 values."""
    if len(values) < 3:
        return "insufficient_data"
    recent = values[-5:]
    if len(recent) < 3:
        recent = values[-3:]
    diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    avg_diff = sum(diffs) / len(diffs)
    if avg_diff > 0.02:
        return "increasing"
    elif avg_diff < -0.02:
        return "decreasing"
    return "stable"


# ═══════════════════════════════════════════════════════════════
#  Soil Moisture
# ═══════════════════════════════════════════════════════════════

@app.route("/api/soil-moisture/<field_id>")
def get_soil_moisture(field_id):
    """Estimate soil moisture for a field using the CNN proxy model."""
    conn = get_db()
    field_row = conn.execute(
        "SELECT * FROM fields WHERE field_id = ?", (field_id,)
    ).fetchone()
    conn.close()

    if not field_row:
        return jsonify({"error": "Field not found"}), 404

    field = dict(field_row)
    site = PILOT_SITES.get(field["site_key"], {})

    # Get latest indices
    ts = get_field_timeseries(field_id, 30)
    if not ts:
        start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        records = generate_simulated_indices(field_id, field["site_key"], start, 90)
        store_indices(records)
        ts = get_field_timeseries(field_id, 30)

    latest = ts[-1] if ts else {"ndvi": 0.4, "ndwi": 0.0, "bsi": 0.1}

    # Get recent weather
    weather = get_weather_history(field["site_key"], 7)
    rainfall_7d = sum(w.get("rainfall_mm", 0) or 0 for w in weather) if weather else 0
    et0_7d = sum(w.get("et0", 5) or 5 for w in weather) if weather else 35

    # Get crop Kc
    crop_profile = CROP_PROFILES.get(field["crop"], CROP_PROFILES["wheat"])
    sowing = datetime.strptime(field["sowing_date"], "%Y-%m-%d")
    das = (datetime.utcnow() - sowing).days
    kc = 0.3
    for stage in crop_profile["growth_stages"].values():
        if stage["days"][0] <= das <= stage["days"][1]:
            kc = stage["kc"]
            break

    # Run model prediction
    prediction = smc_model.predict(
        ndvi=latest.get("ndvi", 0.4),
        ndwi=latest.get("ndwi", 0.0),
        bsi=latest.get("bsi", 0.1),
        rainfall_7d=rainfall_7d,
        et0_7d=et0_7d,
        agro_zone=site.get("agro_zone", "Indo-Gangetic Plains"),
        crop_kc=kc,
    )

    # Store prediction
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO soil_moisture (field_id, date, smc_percent, confidence, method)
        VALUES (?, ?, ?, ?, ?)
    """, (field_id, datetime.utcnow().strftime("%Y-%m-%d"),
          prediction["smc_percent"], prediction["confidence"], "cnn_proxy"))
    conn.commit()
    conn.close()

    prediction["field_id"] = field_id
    prediction["field_name"] = field["name"]
    prediction["crop"] = field["crop"]
    prediction["weather"] = {
        "rainfall_7d_mm": round(rainfall_7d, 1),
        "et0_7d_mm": round(et0_7d, 1),
    }

    return jsonify(prediction)


@app.route("/api/soil-moisture/site/<site_key>")
def get_site_soil_moisture(site_key):
    """Get soil moisture for all fields in a site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    results = []
    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 30)
        if not ts:
            start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(field["id"], site_key, start, 90)
            store_indices(records)
            ts = get_field_timeseries(field["id"], 30)

        latest = ts[-1] if ts else {"ndvi": 0.4, "ndwi": 0.0, "bsi": 0.1}

        weather = get_weather_history(site_key, 7)
        rainfall_7d = sum(w.get("rainfall_mm", 0) or 0 for w in weather) if weather else 0
        et0_7d = sum(w.get("et0", 5) or 5 for w in weather) if weather else 35

        pred = smc_model.predict(
            ndvi=latest.get("ndvi", 0.4),
            ndwi=latest.get("ndwi", 0.0),
            bsi=latest.get("bsi", 0.1),
            rainfall_7d=rainfall_7d,
            et0_7d=et0_7d,
            agro_zone=site.get("agro_zone", "Indo-Gangetic Plains"),
        )
        pred["field_id"] = field["id"]
        pred["field_name"] = field["name"]
        pred["crop"] = field["crop"]
        results.append(pred)

    return jsonify({"site": site["name"], "fields": results})


# ═══════════════════════════════════════════════════════════════
#  Anomaly / Pest Detection
# ═══════════════════════════════════════════════════════════════

@app.route("/api/anomalies/<field_id>")
def get_anomalies(field_id):
    """Detect spectral anomalies (pest/disease indicators) for a field."""
    conn = get_db()
    field_row = conn.execute(
        "SELECT * FROM fields WHERE field_id = ?", (field_id,)
    ).fetchone()
    conn.close()

    if not field_row:
        return jsonify({"error": "Field not found"}), 404

    field = dict(field_row)

    ts = get_field_timeseries(field_id, 90)
    if not ts:
        start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        records = generate_simulated_indices(field_id, field["site_key"], start, 90)
        store_indices(records)
        ts = get_field_timeseries(field_id, 90)

    anomalies = pest_detector.detect_anomalies(
        timeseries=ts,
        crop=field.get("crop", "wheat"),
        sowing_date=field.get("sowing_date", "2025-11-01"),
    )

    conn = get_db()
    for a in anomalies:
        conn.execute("""
            INSERT OR IGNORE INTO anomalies
            (field_id, date, anomaly_type, severity, zone, ndvi_drop, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            field_id, a["date"], a["type"], a["severity"],
            a.get("zone"), a.get("ndvi_drop"), a.get("description")
        ))
    conn.commit()
    conn.close()

    return jsonify({
        "field_id": field_id,
        "field_name": field["name"],
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    })


@app.route("/api/anomalies/site/<site_key>")
def get_site_anomalies(site_key):
    """Get anomalies for all fields in a site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    all_anomalies = {}
    total = 0
    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 90)
        if not ts:
            start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(field["id"], site_key, start, 90)
            store_indices(records)
            ts = get_field_timeseries(field["id"], 90)

        anomalies = pest_detector.detect_anomalies(
            ts, crop=field["crop"], sowing_date=field["sowing_date"]
        )
        all_anomalies[field["id"]] = {
            "field_name": field["name"],
            "count": len(anomalies),
            "anomalies": anomalies[:5],
        }
        total += len(anomalies)

    return jsonify({
        "site": site["name"],
        "total_anomalies": total,
        "fields": all_anomalies,
    })


# ═══════════════════════════════════════════════════════════════
#  Yield Forecasting
# ═══════════════════════════════════════════════════════════════

@app.route("/api/yield/<field_id>")
def get_yield_forecast(field_id):
    """Generate yield forecast for a field."""
    conn = get_db()
    field_row = conn.execute(
        "SELECT * FROM fields WHERE field_id = ?", (field_id,)
    ).fetchone()
    conn.close()

    if not field_row:
        return jsonify({"error": "Field not found"}), 404

    field = dict(field_row)

    ts = get_field_timeseries(field_id, 120)
    if not ts:
        start = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d")
        records = generate_simulated_indices(field_id, field["site_key"], start, 120)
        store_indices(records)
        ts = get_field_timeseries(field_id, 120)

    ndvi_series = [t["ndvi"] for t in ts if t.get("ndvi") is not None]
    weather = get_weather_history(field["site_key"], 60)

    smc_series = []
    for t in ts[-20:]:
        pred = smc_model.predict(
            ndvi=t.get("ndvi", 0.4), ndwi=t.get("ndwi", 0.0), bsi=t.get("bsi", 0.1),
        )
        smc_series.append(pred["smc_percent"])

    forecast = yield_forecaster.forecast(
        field_id=field_id,
        crop=field.get("crop", "wheat"),
        ndvi_series=ndvi_series,
        smc_series=smc_series,
        weather=weather,
        sowing_date=field.get("sowing_date", "2025-11-01"),
        area_ha=field.get("area_ha", 1.0),
    )

    conn = get_db()
    conn.execute("""
        INSERT INTO yield_forecasts
        (field_id, forecast_date, yield_tonnes_ha, uncertainty, risk_score, risk_note, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        field_id, forecast["forecast_date"], forecast["yield_tonnes_ha"],
        forecast["uncertainty"], forecast["risk_score"],
        forecast["risk_note"], forecast["model_version"]
    ))
    conn.commit()
    conn.close()

    return jsonify(forecast)


@app.route("/api/yield/site/<site_key>")
def get_site_yield(site_key):
    """Get yield forecasts for all fields in a site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    forecasts = []
    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 120)
        if not ts:
            start = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(field["id"], site_key, start, 120)
            store_indices(records)
            ts = get_field_timeseries(field["id"], 120)

        ndvi_series = [t["ndvi"] for t in ts if t.get("ndvi") is not None]
        weather = get_weather_history(site_key, 60)

        smc_series = []
        for t in ts[-10:]:
            pred = smc_model.predict(
                ndvi=t.get("ndvi", 0.4), ndwi=t.get("ndwi", 0.0), bsi=t.get("bsi", 0.1),
            )
            smc_series.append(pred["smc_percent"])

        forecast = yield_forecaster.forecast(
            field_id=field["id"], crop=field["crop"],
            ndvi_series=ndvi_series, smc_series=smc_series,
            weather=weather, sowing_date=field["sowing_date"],
            area_ha=field["area_ha"],
        )
        forecasts.append(forecast)

    total_yield = sum(f["total_yield_tonnes"] for f in forecasts)
    total_area = sum(
        PILOT_SITES[site_key]["fields"][i].get("area_ha", 1)
        for i in range(len(forecasts))
    )

    return jsonify({
        "site": site["name"],
        "total_yield_tonnes": round(total_yield, 2),
        "total_area_ha": total_area,
        "avg_yield_per_ha": round(total_yield / max(total_area, 0.1), 2),
        "forecasts": forecasts,
    })


# ═══════════════════════════════════════════════════════════════
#  Nudge Generation
# ═══════════════════════════════════════════════════════════════

@app.route("/api/nudges/<site_key>")
def generate_nudges(site_key):
    """Generate all nudges for a site's fields."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    language = request.args.get("lang", "en")

    field_data = []
    anomalies_map = {}

    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 30)
        if not ts:
            start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(field["id"], site_key, start, 90)
            store_indices(records)
            ts = get_field_timeseries(field["id"], 30)

        latest = ts[-1] if ts else {"ndvi": 0.4, "ndwi": 0.0, "bsi": 0.1}

        pred = smc_model.predict(
            ndvi=latest.get("ndvi", 0.4),
            ndwi=latest.get("ndwi", 0.0),
            bsi=latest.get("bsi", 0.1),
            agro_zone=site.get("agro_zone", "Indo-Gangetic Plains"),
        )

        field_data.append({
            "field_id": field["id"],
            "name": field["name"],
            "crop": field["crop"],
            "sowing_date": field["sowing_date"],
            "irrigation_type": field["irrigation"],
            "area_ha": field["area_ha"],
            "smc_percent": pred["smc_percent"],
            "ndvi": latest.get("ndvi"),
            "ndwi": latest.get("ndwi"),
        })

        # Get anomalies
        full_ts = get_field_timeseries(field["id"], 90)
        anomalies = pest_detector.detect_anomalies(
            full_ts, crop=field["crop"], sowing_date=field["sowing_date"]
        )
        if anomalies:
            anomalies_map[field["id"]] = anomalies[:2]

    weather = get_weather_history(site_key, 7)

    nudges = nudge_generator.generate_all_nudges(
        site_key=site_key,
        field_data=field_data,
        anomalies=anomalies_map,
        weather=weather,
        language=language,
    )

    nudge_generator.store_nudges(nudges)

    critical = sum(1 for n in nudges if n.get("urgency") == "critical")
    medium = sum(1 for n in nudges if n.get("urgency") == "medium")

    return jsonify({
        "site": site["name"],
        "total_nudges": len(nudges),
        "critical": critical,
        "medium": medium,
        "nudges": nudges,
    })


@app.route("/api/nudges/history")
def nudge_history():
    """Get nudge history with optional field filter."""
    field_id = request.args.get("field_id")
    limit = request.args.get("limit", 50, type=int)
    history = nudge_generator.get_nudge_history(field_id, limit)
    return jsonify({"nudges": history, "count": len(history)})


# ═══════════════════════════════════════════════════════════════
#  Weather
# ═══════════════════════════════════════════════════════════════

@app.route("/api/weather/<site_key>")
def get_weather(site_key):
    """Get weather data for a site. Fetches from Open-Meteo if needed."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    days = request.args.get("days", 30, type=int)
    force = request.args.get("force", "false") == "true"

    weather = get_weather_history(site_key, days)

    if not weather or force or len(weather) < days // 2:
        weather = fetch_weather(site["lat"], site["lon"], site_key, days)

    return jsonify({
        "site": site["name"],
        "lat": site["lat"],
        "lon": site["lon"],
        "days": len(weather),
        "weather": weather,
    })


# ═══════════════════════════════════════════════════════════════
#  Pipeline Control
# ═══════════════════════════════════════════════════════════════

@app.route("/api/pipeline/run/<site_key>", methods=["POST"])
def run_pipeline(site_key):
    """Run the complete daily pipeline for a site."""
    from pipeline import run_daily_pipeline

    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    try:
        result = run_daily_pipeline(site_key)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════════════════
#  Dashboard Summary (all-in-one endpoint)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/dashboard/<site_key>")
def dashboard(site_key):
    """
    Full dashboard data for a site in one call:
    - Site info, fields, latest indices, soil moisture, anomalies, nudges
    """
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    fields_data = []
    total_anomalies = 0
    total_area = 0

    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 90)
        if not ts:
            start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            records = generate_simulated_indices(field["id"], site_key, start, 90)
            store_indices(records)
            ts = get_field_timeseries(field["id"], 90)

        latest = ts[-1] if ts else {}

        pred = smc_model.predict(
            ndvi=latest.get("ndvi", 0.4),
            ndwi=latest.get("ndwi", 0.0),
            bsi=latest.get("bsi", 0.1),
            agro_zone=site.get("agro_zone", ""),
        )

        anomalies = pest_detector.detect_anomalies(
            ts, crop=field["crop"], sowing_date=field["sowing_date"]
        )
        total_anomalies += len(anomalies)

        ndvi_series = [t["ndvi"] for t in ts if t.get("ndvi") is not None]
        smc_series = [pred["smc_percent"]]
        weather = get_weather_history(site_key, 30)
        yf = yield_forecaster.forecast(
            field["id"], field["crop"], ndvi_series, smc_series,
            weather, field["sowing_date"], field["area_ha"]
        )

        total_area += field["area_ha"]

        fields_data.append({
            "field_id": field["id"],
            "name": field["name"],
            "crop": field["crop"],
            "area_ha": field["area_ha"],
            "irrigation": field["irrigation"],
            "sowing_date": field["sowing_date"],
            "bbox": field["bbox"],
            "latest_ndvi": latest.get("ndvi"),
            "latest_ndwi": latest.get("ndwi"),
            "ndvi_class": classify_ndvi(latest.get("ndvi", 0)) if latest.get("ndvi") else "unknown",
            "ndwi_class": classify_ndwi(latest.get("ndwi", 0)) if latest.get("ndwi") else "unknown",
            "soil_moisture": pred["smc_percent"],
            "smc_category": pred["category"],
            "smc_confidence": pred["confidence"],
            "anomaly_count": len(anomalies),
            "latest_anomaly": anomalies[-1] if anomalies else None,
            "yield_forecast": yf["yield_tonnes_ha"],
            "yield_risk": yf["risk_level"],
            "yield_risk_note": yf["risk_note"],
        })

    weather = get_weather_history(site_key, 7)
    if not weather:
        weather = fetch_weather(site["lat"], site["lon"], site_key, 7)

    return jsonify({
        "site": {
            "key": site_key,
            "name": site["name"],
            "short_name": site["short_name"],
            "lat": site["lat"],
            "lon": site["lon"],
            "type": site["type"],
            "agro_zone": site["agro_zone"],
            "hub_hardware": site["hub_hardware"],
            "demo_window": site["demo_window"],
            "soil_probes": site["soil_probes"],
        },
        "summary": {
            "total_fields": len(fields_data),
            "total_area_ha": round(total_area, 1),
            "total_anomalies": total_anomalies,
            "avg_ndvi": round(
                sum(f["latest_ndvi"] for f in fields_data if f["latest_ndvi"]) /
                max(len([f for f in fields_data if f["latest_ndvi"]]), 1), 4
            ),
            "avg_smc": round(
                sum(f["soil_moisture"] for f in fields_data) / max(len(fields_data), 1), 1
            ),
        },
        "fields": fields_data,
        "weather": weather[-7:] if weather else [],
    })


# ═══════════════════════════════════════════════════════════════
#  Model & Crop Info
# ═══════════════════════════════════════════════════════════════

@app.route("/api/model/info")
def model_info():
    """Get model architecture and deployment info."""
    return jsonify({
        "soil_moisture_cnn": smc_model.get_onnx_config(),
        "pest_detector": {
            "method": "Unsupervised Spectral Anomaly Detection",
            "features": ["NDVI change", "RedEdge Chlorophyll Index", "Growth stage deviation"],
            "thresholds": {
                "ndvi_drop": pest_detector.ndvi_drop_threshold,
                "reci_drop": pest_detector.reci_drop_threshold,
            },
        },
        "yield_forecaster": {
            "method": "Multi-modal Analytical (NDVI + SMC + Weather)",
            "baseline_yields": yield_forecaster.BASELINE_YIELDS,
            "factor_weights": {"ndvi": 0.45, "water": 0.30, "weather": 0.25},
        },
        "deployment": {
            "format": "ONNX Runtime",
            "quantization": ONNX_CONFIG["quantization"],
            "execution_provider": ONNX_CONFIG["execution_provider"],
            "target_device": ONNX_CONFIG["target_device"],
        },
    })


@app.route("/api/model/export-script")
def model_export_script():
    """Get the PyTorch to ONNX export script for production deployment."""
    return jsonify({"script": generate_model_export_script()})


@app.route("/api/crops")
def get_crops():
    """Get all supported crop profiles."""
    return jsonify(CROP_PROFILES)


@app.route("/api/advisory/<site_key>")
def get_advisory(site_key):
    """Get crop advisory for a pilot site based on current season and crop profiles."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    now = datetime.utcnow()
    month = now.month
    day_of_year = now.timetuple().tm_yday

    advisories = []
    for field in site["fields"]:
        crop_key = field["crop"]
        crop = CROP_PROFILES.get(crop_key)
        if not crop:
            continue

        sowing = datetime.strptime(field["sowing_date"], "%Y-%m-%d")
        days_after_sowing = (now - sowing).days
        if days_after_sowing < 0:
            days_after_sowing = 0

        # Determine current growth stage
        current_stage = "pre-sowing"
        current_kc = 0.3
        stage_progress = 0
        for stage_name, stage_data in crop["growth_stages"].items():
            d_start, d_end = stage_data["days"]
            if d_start <= days_after_sowing <= d_end:
                current_stage = stage_name.replace("_", " ").title()
                current_kc = stage_data["kc"]
                stage_progress = round((days_after_sowing - d_start) / max(d_end - d_start, 1) * 100)
                break
        else:
            if days_after_sowing > 0:
                current_stage = "Post-Harvest"
                current_kc = 0.0
                stage_progress = 100

        # Generate advisory tips
        tips = []
        if current_kc > 0.9:
            tips.append("High water demand — ensure consistent irrigation schedule")
        elif current_kc < 0.4 and days_after_sowing > 10:
            tips.append("Low water demand — reduce irrigation frequency to save water")

        if "heading" in current_stage.lower() or "flowering" in current_stage.lower() or "reproductive" in current_stage.lower():
            tips.append("Critical growth phase — avoid any water stress")
            tips.append("Scout for pest damage: aphids, caterpillars, and fungal infections")

        if "grain" in current_stage.lower() or "ripening" in current_stage.lower() or "boll" in current_stage.lower():
            tips.append("Reduce nitrogen application; focus on potassium for grain quality")
            tips.append("Monitor for lodging risk if recent rainfall is heavy")

        if "tillering" in current_stage.lower() or "vegetative" in current_stage.lower():
            tips.append("Apply top-dressing of nitrogen fertilizer for vigorous growth")
            tips.append("Weed management is critical at this stage")

        if "germination" in current_stage.lower() or "emergence" in current_stage.lower() or "establishment" in current_stage.lower() or "transplanting" in current_stage.lower():
            tips.append("Ensure adequate soil moisture for root establishment")
            tips.append("Protect young seedlings from pest damage")

        if not tips:
            tips.append("Continue standard field monitoring")
            tips.append("Check soil moisture regularly with sensor readings")

        # Season-based general tip
        if 6 <= month <= 9:
            tips.append("Monsoon season: watch for waterlogging and drainage issues")
        elif 11 <= month <= 2:
            tips.append("Winter: protect crops from frost in early morning hours")
        elif 3 <= month <= 5:
            tips.append("Pre-monsoon heat: mulch fields to retain soil moisture")

        advisories.append({
            "field_id": field["id"],
            "field_name": field["name"],
            "crop": crop["name"],
            "crop_key": crop_key,
            "season": crop["season"],
            "days_after_sowing": days_after_sowing,
            "current_stage": current_stage,
            "stage_progress": min(stage_progress, 100),
            "water_demand_kc": current_kc,
            "water_requirement_mm": crop["water_requirement_mm"],
            "optimal_ndvi": crop["optimal_ndvi_peak"],
            "tips": tips[:4],
            "irrigation_type": field["irrigation"],
        })

    return jsonify({
        "site_key": site_key,
        "site_name": site["short_name"],
        "agro_zone": site["agro_zone"],
        "primary_crops": site["primary_crops"],
        "advisories": advisories,
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
    })


# ═══════════════════════════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    print(f"\n  [*] {APP_NAME} v{APP_VERSION} running at http://localhost:{port}")
    print(f"  [*] {APP_DESCRIPTION}")
    print(f"  [*] Pilot sites: {', '.join(s['short_name'] for s in PILOT_SITES.values())}")
    print(f"  [*] Target hardware: {ONNX_CONFIG['target_device']}\n")
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)
