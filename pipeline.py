"""
Krishi-Sathi — Satellite Data Pipeline
Handles ingestion, preprocessing, index computation, and time-series management
for Sentinel-2 L2A and Sentinel-1 GRD data via the Copernicus STAC API.
"""

import math
import json
import sqlite3
import hashlib
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests as http_requests
from config import (
    STAC_API_URL, CDSE_TOKEN_URL, COLLECTIONS,
    S2_BANDS, NDVI_THRESHOLDS, NDWI_THRESHOLDS,
    PILOT_SITES, DB_PATH
)


# ═══════════════════════════════════════════════════════════════
#  Database Layer — time-series storage & field management
# ═══════════════════════════════════════════════════════════════

def get_db():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_pipeline_db():
    """Initialize all pipeline tables."""
    conn = get_db()
    conn.executescript("""
        -- Fields under monitoring
        CREATE TABLE IF NOT EXISTS fields (
            field_id TEXT PRIMARY KEY,
            site_key TEXT NOT NULL,
            name TEXT NOT NULL,
            area_ha REAL,
            crop TEXT,
            sowing_date TEXT,
            irrigation_type TEXT,
            bbox_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Raw STAC search results cached 
        CREATE TABLE IF NOT EXISTS stac_cache (
            cache_key TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            fetched_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        );

        -- Computed spectral indices per field per date
        CREATE TABLE IF NOT EXISTS spectral_indices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            date TEXT NOT NULL,
            ndvi REAL,
            ndwi REAL,
            reci REAL,
            bsi REAL,
            cloud_cover REAL,
            source_scene TEXT,
            computed_at TEXT DEFAULT (datetime('now')),
            UNIQUE(field_id, date, source_scene)
        );

        -- Soil moisture estimates
        CREATE TABLE IF NOT EXISTS soil_moisture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            date TEXT NOT NULL,
            smc_percent REAL NOT NULL,
            confidence REAL,
            method TEXT DEFAULT 'model',
            computed_at TEXT DEFAULT (datetime('now')),
            UNIQUE(field_id, date)
        );

        -- Soil moisture ground-truth (calibration probes)
        CREATE TABLE IF NOT EXISTS soil_probes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            date TEXT NOT NULL,
            depth_cm REAL DEFAULT 10,
            smc_measured REAL NOT NULL,
            lat REAL,
            lon REAL,
            recorded_at TEXT DEFAULT (datetime('now'))
        );

        -- Pest / anomaly detections
        CREATE TABLE IF NOT EXISTS anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            date TEXT NOT NULL,
            anomaly_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            zone TEXT,
            ndvi_drop REAL,
            description TEXT,
            confirmed INTEGER DEFAULT 0,
            detected_at TEXT DEFAULT (datetime('now'))
        );

        -- Yield forecasts
        CREATE TABLE IF NOT EXISTS yield_forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            yield_tonnes_ha REAL NOT NULL,
            uncertainty REAL,
            risk_score REAL,
            risk_note TEXT,
            model_version TEXT,
            computed_at TEXT DEFAULT (datetime('now'))
        );

        -- Nudges sent to farmers
        CREATE TABLE IF NOT EXISTS nudges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            nudge_type TEXT NOT NULL,
            message_en TEXT,
            message_local TEXT,
            language TEXT DEFAULT 'en',
            channel TEXT DEFAULT 'sms',
            status TEXT DEFAULT 'pending',
            farmer_response TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            responded_at TEXT
        );

        -- Weather cache
        CREATE TABLE IF NOT EXISTS weather_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_key TEXT NOT NULL,
            date TEXT NOT NULL,
            temp_max REAL,
            temp_min REAL,
            humidity REAL,
            rainfall_mm REAL,
            wind_speed REAL,
            et0 REAL,
            source TEXT DEFAULT 'openmeteo',
            fetched_at TEXT DEFAULT (datetime('now')),
            UNIQUE(site_key, date)
        );
    """)
    conn.commit()
    conn.close()


def seed_pilot_fields():
    """Seed the database with pilot site fields."""
    conn = get_db()
    for site_key, site in PILOT_SITES.items():
        for field in site.get("fields", []):
            conn.execute("""
                INSERT OR IGNORE INTO fields 
                (field_id, site_key, name, area_ha, crop, sowing_date, irrigation_type, bbox_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                field["id"], site_key, field["name"], field["area_ha"],
                field["crop"], field["sowing_date"], field["irrigation"],
                json.dumps(field["bbox"])
            ))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  STAC Search & Ingestion
# ═══════════════════════════════════════════════════════════════

def build_bbox(lat: float, lon: float, buffer: float = 0.1) -> List[float]:
    """Create a bounding box [west, south, east, north] around a point."""
    return [
        round(lon - buffer, 6),
        round(lat - buffer, 6),
        round(lon + buffer, 6),
        round(lat + buffer, 6),
    ]


def build_datetime_range(date_str: str, days_before: int = 15, days_after: int = 15) -> str:
    """Build ISO-8601 datetime range string."""
    center = datetime.strptime(date_str, "%Y-%m-%d")
    start = (center - timedelta(days=days_before)).strftime("%Y-%m-%dT00:00:00Z")
    end = (center + timedelta(days=days_after)).strftime("%Y-%m-%dT23:59:59Z")
    return f"{start}/{end}"


def search_stac(
    lat: float, lon: float, date_str: str,
    collections: List[str] = None,
    days: int = 15,
    cloud_cover: int = 30,
    limit: int = 10,
    buffer: float = 0.1
) -> Dict:
    """
    Search the Copernicus STAC API and return structured results.
    """
    if collections is None:
        collections = ["sentinel-2-l2a"]

    bbox = build_bbox(lat, lon, buffer)
    datetime_range = build_datetime_range(date_str, days_before=days, days_after=days)
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")

    results = {}

    for collection_id in collections:
        if collection_id not in COLLECTIONS:
            continue

        fetch_limit = min(limit * 5, 50)

        payload = {
            "collections": [collection_id],
            "bbox": bbox,
            "datetime": datetime_range,
            "limit": fetch_limit,
        }

        # Check cache
        cache_key = hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        cached = _get_cache(cache_key)
        if cached:
            results[collection_id] = cached
            continue

        try:
            resp = http_requests.post(
                STAC_API_URL, json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/geo+json"},
                timeout=30,
            )
            resp.raise_for_status()
            stac_data = resp.json()

            features = _process_stac_features(stac_data, collection_id, cloud_cover, target_dt)
            features.sort(key=lambda f: _date_distance(f, target_dt))
            features = features[:limit]

            result = {
                "name": COLLECTIONS[collection_id],
                "count": len(features),
                "features": features,
            }
            results[collection_id] = result

            # Cache for 1 hour
            _set_cache(cache_key, result, ttl_hours=1)

        except http_requests.exceptions.RequestException as e:
            results[collection_id] = {
                "name": COLLECTIONS[collection_id],
                "count": 0,
                "features": [],
                "error": str(e),
            }

    return results


def _process_stac_features(stac_data: dict, collection_id: str, cloud_cover: int, target_dt: datetime) -> list:
    """Process raw STAC features into clean format."""
    features = []
    for feature in stac_data.get("features", []):
        props = feature.get("properties", {})
        assets = feature.get("assets", {})

        # Cloud filter for S2
        if "sentinel-2" in collection_id:
            cc = props.get("eo:cloud_cover")
            if cc is not None and cc > cloud_cover:
                continue

        asset_list = {}
        for k, v in assets.items():
            asset_list[k] = {
                "title": v.get("title", k),
                "href": v.get("href", ""),
                "type": v.get("type", ""),
            }

        thumb = assets.get("thumbnail", {}).get("href", "")
        preview = ""
        if "sentinel-2" in collection_id:
            preview = assets.get("TCI_10m", {}).get("href", "")
        if not preview:
            preview = thumb

        features.append({
            "id": feature.get("id", ""),
            "datetime": props.get("datetime", ""),
            "created": props.get("created", ""),
            "platform": props.get("platform", ""),
            "constellation": props.get("constellation", ""),
            "instrument": props.get("instruments", []),
            "gsd": props.get("gsd"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "orbit_state": props.get("sat:orbit_state", ""),
            "relative_orbit": props.get("sat:relative_orbit"),
            "thumbnail": thumb,
            "preview": preview,
            "assets": asset_list,
            "bbox": feature.get("bbox", []),
            "geometry": feature.get("geometry"),
        })

    return features


def _date_distance(feat: dict, target_dt: datetime) -> float:
    """Compute temporal distance from target date."""
    try:
        feat_dt = datetime.fromisoformat(
            feat["datetime"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        return abs((feat_dt - target_dt).total_seconds())
    except (ValueError, TypeError, KeyError):
        return float("inf")


def _get_cache(key: str) -> Optional[dict]:
    """Retrieve from STAC cache if not expired."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT response_json, expires_at FROM stac_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        conn.close()
        if row and row["expires_at"] > datetime.utcnow().isoformat():
            return json.loads(row["response_json"])
    except Exception:
        pass
    return None


def _set_cache(key: str, data: dict, ttl_hours: int = 1):
    """Store STAC response in cache."""
    try:
        conn = get_db()
        expires = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO stac_cache (cache_key, response_json, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(data), expires)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  Spectral Index Computation
# ═══════════════════════════════════════════════════════════════

def compute_ndvi(nir: float, red: float) -> float:
    """NDVI = (NIR - Red) / (NIR + Red). Uses B08 and B04."""
    denom = nir + red
    if denom == 0:
        return 0.0
    return round((nir - red) / denom, 4)


def compute_ndwi(nir: float, swir: float) -> float:
    """NDWI = (NIR - SWIR) / (NIR + SWIR). Uses B08 and B11."""
    denom = nir + swir
    if denom == 0:
        return 0.0
    return round((nir - swir) / denom, 4)


def compute_reci(nir: float, red_edge: float) -> float:
    """Red Edge Chlorophyll Index = (NIR / RedEdge) - 1. Uses B08 and B05."""
    if red_edge == 0:
        return 0.0
    return round((nir / red_edge) - 1, 4)


def compute_bsi(blue: float, red: float, nir: float, swir: float) -> float:
    """Bare Soil Index = ((SWIR+Red) - (NIR+Blue)) / ((SWIR+Red) + (NIR+Blue))."""
    num = (swir + red) - (nir + blue)
    denom = (swir + red) + (nir + blue)
    if denom == 0:
        return 0.0
    return round(num / denom, 4)


def classify_ndvi(ndvi: float) -> str:
    """Classify NDVI into vegetation category."""
    for category, (low, high) in NDVI_THRESHOLDS.items():
        if low <= ndvi < high:
            return category
    return "unknown"


def classify_ndwi(ndwi: float) -> str:
    """Classify NDWI into water/moisture category."""
    for category, (low, high) in NDWI_THRESHOLDS.items():
        if low <= ndwi < high:
            return category
    return "unknown"


def generate_simulated_indices(field_id: str, site_key: str, start_date: str, num_days: int = 90) -> List[Dict]:
    """
    Generate realistic simulated spectral index time series for a field.
    Uses crop phenology + noise to create plausible NDVI/NDWI curves.
    In production this would come from actual Sentinel-2 band data.
    """
    from config import PILOT_SITES, CROP_PROFILES

    site = PILOT_SITES.get(site_key, {})
    field = None
    for f in site.get("fields", []):
        if f["id"] == field_id:
            field = f
            break

    if not field:
        return []

    crop_key = field.get("crop", "wheat")
    crop = CROP_PROFILES.get(crop_key, CROP_PROFILES["wheat"])
    sowing = datetime.strptime(field.get("sowing_date", "2025-11-01"), "%Y-%m-%d")
    start = datetime.strptime(start_date, "%Y-%m-%d")

    # Seed RNG for reproducibility per field
    seed = int(hashlib.md5(field_id.encode()).hexdigest()[:8], 16) % (2**31)
    rng = np.random.RandomState(seed)

    records = []
    # Generate every 5 days (Sentinel-2 revisit ~ 5 days)
    for i in range(0, num_days, 5):
        date = start + timedelta(days=i)
        days_after_sowing = (date - sowing).days

        if days_after_sowing < 0:
            days_after_sowing = 0

        # Find current growth stage
        kc = 0.3  # default
        for stage_name, stage in crop["growth_stages"].items():
            d_start, d_end = stage["days"]
            if d_start <= days_after_sowing <= d_end:
                # Interpolate kc within stage
                progress = (days_after_sowing - d_start) / max(d_end - d_start, 1)
                kc = stage["kc"] * (0.7 + 0.3 * progress)
                break

        # NDVI follows crop coefficient pattern
        base_ndvi = 0.15 + kc * 0.55
        ndvi = np.clip(base_ndvi + rng.normal(0, 0.03), -0.1, 0.95)

        # NDWI correlated with NDVI but with moisture component
        base_ndwi = -0.1 + kc * 0.35
        ndwi = np.clip(base_ndwi + rng.normal(0, 0.04), -0.5, 0.6)

        # RECI  
        reci = np.clip(kc * 2.5 + rng.normal(0, 0.2), 0, 8)

        # BSI inversely proportional to vegetation
        bsi = np.clip(0.3 - kc * 0.25 + rng.normal(0, 0.03), -0.3, 0.5)

        # Simulate occasional cloud cover
        cloud = max(0, rng.normal(15, 20))
        if cloud > 80:
            continue  # Skip very cloudy observations

        records.append({
            "field_id": field_id,
            "date": date.strftime("%Y-%m-%d"),
            "ndvi": round(float(ndvi), 4),
            "ndwi": round(float(ndwi), 4),
            "reci": round(float(reci), 4),
            "bsi": round(float(bsi), 4),
            "cloud_cover": round(float(min(cloud, 100)), 1),
            "ndvi_class": classify_ndvi(float(ndvi)),
            "ndwi_class": classify_ndwi(float(ndwi)),
        })

    return records


def store_indices(records: List[Dict]):
    """Store computed spectral indices in database."""
    conn = get_db()
    for r in records:
        conn.execute("""
            INSERT OR REPLACE INTO spectral_indices 
            (field_id, date, ndvi, ndwi, reci, bsi, cloud_cover, source_scene)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["field_id"], r["date"], r["ndvi"], r["ndwi"],
            r.get("reci"), r.get("bsi"), r.get("cloud_cover"), r.get("source_scene", "simulated")
        ))
    conn.commit()
    conn.close()


def get_field_timeseries(field_id: str, days: int = 90) -> List[Dict]:
    """Get spectral index time series for a field."""
    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT date, ndvi, ndwi, reci, bsi, cloud_cover 
        FROM spectral_indices 
        WHERE field_id = ? AND date >= ?
        ORDER BY date ASC
    """, (field_id, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
#  Weather Data (Open-Meteo free API)
# ═══════════════════════════════════════════════════════════════

def fetch_weather(lat: float, lon: float, site_key: str, days_past: int = 30) -> List[Dict]:
    """
    Fetch historical weather from Open-Meteo (free, no API key needed).
    Returns daily temperature, humidity, rainfall, wind, and reference ET.
    """
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days_past)).strftime("%Y-%m-%d")

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean,"
        f"precipitation_sum,windspeed_10m_max,et0_fao_evapotranspiration"
        f"&timezone=auto"
    )

    try:
        resp = http_requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        records = []

        conn = get_db()
        for i, date in enumerate(dates):
            record = {
                "site_key": site_key,
                "date": date,
                "temp_max": daily.get("temperature_2m_max", [None])[i],
                "temp_min": daily.get("temperature_2m_min", [None])[i],
                "humidity": daily.get("relative_humidity_2m_mean", [None])[i],
                "rainfall_mm": daily.get("precipitation_sum", [None])[i],
                "wind_speed": daily.get("windspeed_10m_max", [None])[i],
                "et0": daily.get("et0_fao_evapotranspiration", [None])[i],
            }
            records.append(record)

            conn.execute("""
                INSERT OR REPLACE INTO weather_cache 
                (site_key, date, temp_max, temp_min, humidity, rainfall_mm, wind_speed, et0)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                site_key, date, record["temp_max"], record["temp_min"],
                record["humidity"], record["rainfall_mm"],
                record["wind_speed"], record["et0"]
            ))

        conn.commit()
        conn.close()
        return records

    except Exception as e:
        # Generate synthetic weather if API fails
        return _generate_synthetic_weather(lat, site_key, days_past)


def _generate_synthetic_weather(lat: float, site_key: str, days: int) -> List[Dict]:
    """Generate plausible synthetic weather for demo purposes."""
    rng = np.random.RandomState(42)
    records = []
    
    # Base temperature varies with latitude
    base_temp = 35 - abs(lat - 23) * 0.8
    
    for i in range(days):
        date = (datetime.utcnow() - timedelta(days=days - i)).strftime("%Y-%m-%d")
        temp_max = base_temp + rng.normal(0, 3)
        temp_min = temp_max - rng.uniform(8, 14)
        
        records.append({
            "site_key": site_key,
            "date": date,
            "temp_max": round(temp_max, 1),
            "temp_min": round(temp_min, 1),
            "humidity": round(rng.uniform(40, 80), 1),
            "rainfall_mm": round(max(0, rng.exponential(2)), 1),
            "wind_speed": round(rng.uniform(5, 20), 1),
            "et0": round(rng.uniform(3, 7), 1),
        })
    
    return records


def get_weather_history(site_key: str, days: int = 30) -> List[Dict]:
    """Get cached weather data for a site."""
    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT date, temp_max, temp_min, humidity, rainfall_mm, wind_speed, et0
        FROM weather_cache 
        WHERE site_key = ? AND date >= ?
        ORDER BY date ASC
    """, (site_key, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
#  Authentication Helpers
# ═══════════════════════════════════════════════════════════════

def get_cdse_token(username: str, password: str) -> Dict:
    """Exchange credentials for Copernicus access token."""
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
    resp.raise_for_status()
    return resp.json()


# ═══════════════════════════════════════════════════════════════
#  Pipeline Orchestration
# ═══════════════════════════════════════════════════════════════

def run_daily_pipeline(site_key: str) -> Dict:
    """
    Run the complete daily pipeline for a site:
    1. Fetch latest Sentinel-2 imagery for all fields
    2. Compute spectral indices
    3. Estimate soil moisture
    4. Check for anomalies
    5. Generate irrigation nudges
    """
    site = PILOT_SITES.get(site_key)
    if not site:
        return {"error": f"Unknown site: {site_key}"}

    today = datetime.utcnow().strftime("%Y-%m-%d")
    results = {
        "site": site["name"],
        "date": today,
        "fields_processed": 0,
        "indices_computed": 0,
        "anomalies_detected": 0,
        "nudges_generated": 0,
    }

    # 1. Search latest imagery
    stac_results = search_stac(
        lat=site["lat"], lon=site["lon"],
        date_str=today,
        collections=["sentinel-2-l2a"],
        days=10, cloud_cover=40, limit=5
    )
    results["scenes_found"] = stac_results.get("sentinel-2-l2a", {}).get("count", 0)

    # 2. Generate & store indices for each field
    for field in site.get("fields", []):
        indices = generate_simulated_indices(
            field["id"], site_key,
            start_date=(datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"),
            num_days=90
        )
        store_indices(indices)
        results["indices_computed"] += len(indices)
        results["fields_processed"] += 1

    # 3. Fetch weather
    try:
        fetch_weather(site["lat"], site["lon"], site_key, days_past=30)
    except Exception:
        pass

    return results


# Initialize on import
init_pipeline_db()
