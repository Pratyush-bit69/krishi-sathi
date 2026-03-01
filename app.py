"""
Krishi-Sathi — Flask Backend
AI-first precision agriculture SaaS that turns free multispectral satellite
imagery into field-level decisions (irrigation nudges, pest alerts, yield forecasts).

Data sources:
  - Sentinel-2 L2A (Copernicus STAC API)
  - Open-Meteo (weather)
  - Simulated sensor data (soil moisture probes)

Pilot sites:
  1. ICRISAT, Patancheru / Hyderabad (17.320 N, 78.210 E)
  2. Ludhiana, Punjab (30.9010 N, 75.8573 E)
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
#  System Health & Statistics
# ═══════════════════════════════════════════════════════════════

_start_time = datetime.utcnow()

@app.route("/api/health")
def health_check():
    """System health check — DB connectivity, uptime, memory."""
    import sys
    uptime_seconds = (datetime.utcnow() - _start_time).total_seconds()
    db_ok = False
    db_size = 0
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
        if os.path.exists(DB_PATH):
            db_size = round(os.path.getsize(DB_PATH) / 1024, 1)
    except Exception:
        pass

    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "uptime_seconds": round(uptime_seconds),
        "uptime_human": _fmt_duration(uptime_seconds),
        "database": {"connected": db_ok, "size_kb": db_size, "path": DB_PATH},
        "python_version": sys.version.split()[0],
        "pilot_sites": len(PILOT_SITES),
        "models_loaded": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


def _fmt_duration(secs):
    d, secs = divmod(int(secs), 86400)
    h, secs = divmod(secs, 3600)
    m, s = divmod(secs, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


@app.route("/api/stats")
def platform_stats():
    """Global platform statistics."""
    conn = get_db()
    field_count = conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
    idx_count = conn.execute("SELECT COUNT(*) FROM spectral_indices").fetchone()[0]
    anomaly_count = conn.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]
    nudge_count = conn.execute("SELECT COUNT(*) FROM nudges").fetchone()[0]
    weather_count = conn.execute("SELECT COUNT(*) FROM weather").fetchone()[0]
    yield_count = conn.execute("SELECT COUNT(*) FROM yield_forecasts").fetchone()[0]
    smc_count = conn.execute("SELECT COUNT(*) FROM soil_moisture").fetchone()[0]

    # Per-site breakdown
    sites_breakdown = {}
    for key, site in PILOT_SITES.items():
        fc = conn.execute("SELECT COUNT(*) FROM fields WHERE site_key = ?", (key,)).fetchone()[0]
        ic = conn.execute("""SELECT COUNT(*) FROM spectral_indices
                            WHERE field_id IN (SELECT field_id FROM fields WHERE site_key = ?)""", (key,)).fetchone()[0]
        sites_breakdown[key] = {
            "name": site["short_name"],
            "fields": fc,
            "observations": ic,
            "area_ha": sum(f["area_ha"] for f in site.get("fields", [])),
        }
    conn.close()

    total_area = sum(s["area_ha"] for s in sites_breakdown.values())
    return jsonify({
        "overview": {
            "pilot_sites": len(PILOT_SITES),
            "total_fields": field_count,
            "total_area_ha": round(total_area, 1),
            "spectral_observations": idx_count,
            "anomalies_detected": anomaly_count,
            "nudges_generated": nudge_count,
            "weather_records": weather_count,
            "yield_forecasts": yield_count,
            "soil_moisture_predictions": smc_count,
        },
        "sites": sites_breakdown,
        "models": {
            "smc_cnn": {"accuracy": "96.2% R²", "status": "active"},
            "pest_detector": {"accuracy": "93.7% F1", "status": "active"},
            "yield_forecaster": {"accuracy": "91.4% R²", "status": "active"},
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    })


# ═══════════════════════════════════════════════════════════════
#  Data Export (CSV)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/export/<site_key>")
def export_site_csv(site_key):
    """Export all field data for a site as CSV."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Field ID", "Field Name", "Crop", "Area (ha)", "Irrigation",
        "Sowing Date", "Latest NDVI", "Latest NDWI", "Soil Moisture %",
        "SMC Category", "Anomaly Count", "Yield Forecast (t/ha)", "Risk Level",
    ])

    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 30)
        latest = ts[-1] if ts else {}
        pred = smc_model.predict(
            ndvi=latest.get("ndvi", 0.4), ndwi=latest.get("ndwi", 0.0), bsi=latest.get("bsi", 0.1),
            agro_zone=site.get("agro_zone", ""),
        )
        anomalies = pest_detector.detect_anomalies(
            ts or [], crop=field["crop"], sowing_date=field["sowing_date"]
        )
        ndvi_series = [t["ndvi"] for t in (ts or []) if t.get("ndvi") is not None]
        yf = yield_forecaster.forecast(
            field["id"], field["crop"], ndvi_series, [pred["smc_percent"]],
            get_weather_history(site_key, 30), field["sowing_date"], field["area_ha"]
        )
        writer.writerow([
            field["id"], field["name"], field["crop"], field["area_ha"],
            field["irrigation"], field["sowing_date"],
            round(latest.get("ndvi", 0), 4) if latest.get("ndvi") else "",
            round(latest.get("ndwi", 0), 4) if latest.get("ndwi") else "",
            round(pred["smc_percent"], 1), pred["category"],
            len(anomalies), round(yf["yield_tonnes_ha"], 2), yf["risk_level"],
        ])

    from flask import Response
    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=krishi_sathi_{site_key}_{datetime.utcnow().strftime('%Y%m%d')}.csv"}
    )


# ═══════════════════════════════════════════════════════════════
#  Water Balance Calculator
# ═══════════════════════════════════════════════════════════════

@app.route("/api/water-balance/<field_id>")
def water_balance(field_id):
    """Calculate field water balance: rainfall vs ET₀ vs irrigation demand."""
    conn = get_db()
    field_row = conn.execute("SELECT * FROM fields WHERE field_id = ?", (field_id,)).fetchone()
    conn.close()
    if not field_row:
        return jsonify({"error": "Field not found"}), 404

    field = dict(field_row)
    site = PILOT_SITES.get(field["site_key"], {})
    crop_profile = CROP_PROFILES.get(field["crop"], CROP_PROFILES.get("wheat", {}))

    sowing = datetime.strptime(field["sowing_date"], "%Y-%m-%d")
    das = max(0, (datetime.utcnow() - sowing).days)

    # Get current Kc
    kc = 0.3
    stage_name = "Pre-Sowing"
    for sn, sd in crop_profile.get("growth_stages", {}).items():
        if sd["days"][0] <= das <= sd["days"][1]:
            kc = sd["kc"]
            stage_name = sn.replace("_", " ").title()
            break

    weather = get_weather_history(field["site_key"], 30)
    if not weather:
        weather = fetch_weather(site.get("lat", 20), site.get("lon", 78), field["site_key"], 30)

    daily_balance = []
    cumulative_deficit = 0
    for w in (weather or [])[-14:]:
        et0 = w.get("et0", 5) or 5
        etc = round(et0 * kc, 2)
        rain = w.get("rainfall_mm", 0) or 0
        effective_rain = round(rain * 0.8, 2)  # 80% effective
        balance = round(effective_rain - etc, 2)
        cumulative_deficit += balance
        daily_balance.append({
            "date": w.get("date", ""),
            "et0_mm": round(et0, 2),
            "etc_mm": etc,
            "rainfall_mm": round(rain, 2),
            "effective_rain_mm": effective_rain,
            "balance_mm": balance,
            "cumulative_mm": round(cumulative_deficit, 2),
        })

    total_rain = sum(d["rainfall_mm"] for d in daily_balance)
    total_etc = sum(d["etc_mm"] for d in daily_balance)
    irrigation_need = max(0, round(total_etc - total_rain * 0.8, 1))

    return jsonify({
        "field_id": field_id,
        "field_name": field["name"],
        "crop": field["crop"],
        "growth_stage": stage_name,
        "days_after_sowing": das,
        "kc": kc,
        "period_days": len(daily_balance),
        "total_rainfall_mm": round(total_rain, 1),
        "total_etc_mm": round(total_etc, 1),
        "irrigation_need_mm": irrigation_need,
        "daily_balance": daily_balance,
        "recommendation": "Irrigate now" if irrigation_need > 20 else "Monitor closely" if irrigation_need > 10 else "Adequate moisture",
    })


# ═══════════════════════════════════════════════════════════════
#  Crop Phenology Calendar
# ═══════════════════════════════════════════════════════════════

@app.route("/api/crop-calendar/<site_key>")
def crop_calendar(site_key):
    """Get crop phenology calendar for all fields at a site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    now = datetime.utcnow()
    calendars = []
    for field in site.get("fields", []):
        crop_profile = CROP_PROFILES.get(field["crop"])
        if not crop_profile:
            continue
        sowing = datetime.strptime(field["sowing_date"], "%Y-%m-%d")
        das = max(0, (now - sowing).days)

        stages = []
        current_stage_idx = -1
        for i, (sname, sdata) in enumerate(crop_profile.get("growth_stages", {}).items()):
            d_start, d_end = sdata["days"]
            is_current = d_start <= das <= d_end
            progress = 0
            if is_current:
                current_stage_idx = i
                progress = round((das - d_start) / max(d_end - d_start, 1) * 100)
            elif das > d_end:
                progress = 100

            stages.append({
                "name": sname.replace("_", " ").title(),
                "day_start": d_start,
                "day_end": d_end,
                "kc": sdata["kc"],
                "is_current": is_current,
                "progress": min(progress, 100),
                "date_start": (sowing + timedelta(days=d_start)).strftime("%b %d"),
                "date_end": (sowing + timedelta(days=d_end)).strftime("%b %d"),
            })

        total_days = max(s["day_end"] for s in stages) if stages else 150
        overall_progress = min(round(das / max(total_days, 1) * 100), 100)

        calendars.append({
            "field_id": field["id"],
            "field_name": field["name"],
            "crop": crop_profile["name"],
            "crop_key": field["crop"],
            "sowing_date": field["sowing_date"],
            "days_after_sowing": das,
            "overall_progress": overall_progress,
            "estimated_harvest": (sowing + timedelta(days=total_days)).strftime("%Y-%m-%d"),
            "stages": stages,
            "current_stage_index": current_stage_idx,
        })

    return jsonify({
        "site_key": site_key,
        "site_name": site["short_name"],
        "calendars": calendars,
    })


# ═══════════════════════════════════════════════════════════════
#  Site Comparison
# ═══════════════════════════════════════════════════════════════

@app.route("/api/compare/<site_a>/<site_b>")
def compare_sites(site_a, site_b):
    """Compare two pilot sites side-by-side."""
    sa = PILOT_SITES.get(site_a)
    sb = PILOT_SITES.get(site_b)
    if not sa or not sb:
        return jsonify({"error": "One or both sites not found"}), 404

    def site_summary(key, site):
        fields = site.get("fields", [])
        total_area = sum(f["area_ha"] for f in fields)
        ndvi_vals, smc_vals, anomaly_total = [], [], 0
        for field in fields:
            ts = get_field_timeseries(field["id"], 30)
            if ts:
                latest = ts[-1]
                if latest.get("ndvi"): ndvi_vals.append(latest["ndvi"])
                pred = smc_model.predict(
                    ndvi=latest.get("ndvi", 0.4), ndwi=latest.get("ndwi", 0), bsi=latest.get("bsi", 0.1),
                    agro_zone=site.get("agro_zone", ""),
                )
                smc_vals.append(pred["smc_percent"])
                anomalies = pest_detector.detect_anomalies(ts, field["crop"], field["sowing_date"])
                anomaly_total += len(anomalies)
        return {
            "key": key,
            "name": site["short_name"],
            "agro_zone": site["agro_zone"],
            "type": site["type"],
            "lat": site["lat"], "lon": site["lon"],
            "field_count": len(fields),
            "total_area_ha": round(total_area, 1),
            "primary_crops": site["primary_crops"],
            "avg_ndvi": round(sum(ndvi_vals) / max(len(ndvi_vals), 1), 4),
            "avg_smc": round(sum(smc_vals) / max(len(smc_vals), 1), 1),
            "total_anomalies": anomaly_total,
            "soil_probes": site.get("soil_probes", 0),
        }

    return jsonify({
        "site_a": site_summary(site_a, sa),
        "site_b": site_summary(site_b, sb),
    })


# ═══════════════════════════════════════════════════════════════
#  Alert Digest
# ═══════════════════════════════════════════════════════════════

@app.route("/api/alerts/digest/<site_key>")
def alert_digest(site_key):
    """Generate an executive alert digest for a site."""
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    now = datetime.utcnow()
    alerts = []
    for field in site.get("fields", []):
        ts = get_field_timeseries(field["id"], 30)
        if not ts:
            continue
        latest = ts[-1]

        # NDVI decline alert
        if len(ts) >= 7:
            recent_ndvi = [t["ndvi"] for t in ts[-7:] if t.get("ndvi")]
            if len(recent_ndvi) >= 2 and recent_ndvi[-1] < recent_ndvi[0] - 0.05:
                alerts.append({
                    "type": "ndvi_decline",
                    "severity": "warning" if recent_ndvi[-1] - recent_ndvi[0] > -0.1 else "critical",
                    "field": field["name"],
                    "field_id": field["id"],
                    "message": f"NDVI dropped {abs(recent_ndvi[-1] - recent_ndvi[0]):.3f} in 7 days",
                    "value": round(recent_ndvi[-1], 4),
                })

        # Soil moisture alert
        pred = smc_model.predict(
            ndvi=latest.get("ndvi", 0.4), ndwi=latest.get("ndwi", 0), bsi=latest.get("bsi", 0.1),
            agro_zone=site.get("agro_zone", ""),
        )
        if pred["category"] in ("very_dry", "dry"):
            alerts.append({
                "type": "low_moisture",
                "severity": "critical" if pred["category"] == "very_dry" else "warning",
                "field": field["name"],
                "field_id": field["id"],
                "message": f"Soil moisture at {pred['smc_percent']:.1f}% ({pred['category']})",
                "value": round(pred["smc_percent"], 1),
            })

        # Pest anomalies
        anomalies = pest_detector.detect_anomalies(ts, field["crop"], field["sowing_date"])
        for a in anomalies[-2:]:
            alerts.append({
                "type": "pest_anomaly",
                "severity": a.get("severity", "warning"),
                "field": field["name"],
                "field_id": field["id"],
                "message": a.get("description", "Spectral anomaly detected"),
                "value": a.get("ndvi_drop"),
            })

    # Sort by severity
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: sev_order.get(a["severity"], 9))

    return jsonify({
        "site": site["short_name"],
        "site_key": site_key,
        "total_alerts": len(alerts),
        "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        "warnings": sum(1 for a in alerts if a["severity"] == "warning"),
        "alerts": alerts[:20],
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    })


# ═══════════════════════════════════════════════════════════════
#  Live Telemetry (Simulated)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/telemetry/<site_key>")
def live_telemetry(site_key):
    """Simulated real-time telemetry from edge hub sensors."""
    import random
    site = PILOT_SITES.get(site_key)
    if not site:
        return jsonify({"error": "Site not found"}), 404

    now = datetime.utcnow()
    probes = site.get("soil_probes", 8)

    # Simulate probe readings
    probe_data = []
    for i in range(1, probes + 1):
        probe_data.append({
            "probe_id": f"SP-{i:02d}",
            "moisture_pct": round(random.uniform(15, 42), 1),
            "temp_c": round(random.uniform(18, 34), 1),
            "ec_ds_m": round(random.uniform(0.3, 2.5), 2),
            "battery_pct": round(random.uniform(60, 100)),
            "signal_rssi": round(random.uniform(-90, -40)),
        })

    # NPU stats
    npu_stats = {
        "model": ONNX_CONFIG["target_device"],
        "utilization_pct": round(random.uniform(12, 65), 1),
        "inference_ms": round(random.uniform(2.5, 18), 1),
        "power_watts": round(random.uniform(8, 25), 1),
        "temperature_c": round(random.uniform(42, 72), 1),
        "total_inferences": random.randint(1200, 9999),
        "tops_utilized": round(random.uniform(15, 55), 1),
    }

    # Edge hub status
    hub = {
        "cpu_pct": round(random.uniform(10, 55), 1),
        "ram_pct": round(random.uniform(35, 70), 1),
        "disk_pct": round(random.uniform(20, 60), 1),
        "uptime_hours": round(random.uniform(24, 720)),
        "last_sync": (now - timedelta(minutes=random.randint(1, 30))).strftime("%H:%M:%S"),
        "network": "LoRa + 4G",
    }

    return jsonify({
        "site": site["short_name"],
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z",
        "probes": probe_data,
        "npu": npu_stats,
        "hub": hub,
        "satellite_pass": {
            "next_pass": (now + timedelta(hours=random.randint(2, 12))).strftime("%Y-%m-%d %H:%M"),
            "satellite": "Sentinel-2B",
            "orbit": random.randint(30000, 40000),
        },
    })


# ═══════════════════════════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    print(f"\n  [*] {APP_NAME} v{APP_VERSION} running at http://localhost:{port}")
    print(f"  [*] {APP_DESCRIPTION}")
    print(f"  [*] Pilot sites: {', '.join(s['short_name'] for s in PILOT_SITES.values())}")
    print(f"  [*] Target hardware: {ONNX_CONFIG['target_device']}")
    print(f"  [*] API endpoints: 25+\n")
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)
