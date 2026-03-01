"""
Krishi-Sathi — Configuration & Pilot Site Definitions
Precision agriculture SaaS for smallholder farmers in India.
"""

import os
from datetime import datetime

# ─── Application ───
APP_NAME = "Krishi-Sathi"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "AI-first precision agriculture — satellite to field nudges"

# ─── Copernicus / STAC ───
STAC_API_URL = "https://stac.dataspace.copernicus.eu/v1/search"
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu"
    "/auth/realms/CDSE/protocol/openid-connect/token"
)

# Available satellite collections
COLLECTIONS = {
    "sentinel-2-l2a": "Sentinel-2 MSI (Level-2A)",
    "sentinel-1-grd": "Sentinel-1 SAR (GRD)",
}

# ─── Spectral band indices for Sentinel-2 ───
S2_BANDS = {
    "B02": {"name": "Blue", "wavelength": 490, "resolution": 10},
    "B03": {"name": "Green", "wavelength": 560, "resolution": 10},
    "B04": {"name": "Red", "wavelength": 665, "resolution": 10},
    "B05": {"name": "Red Edge 1", "wavelength": 705, "resolution": 20},
    "B06": {"name": "Red Edge 2", "wavelength": 740, "resolution": 20},
    "B07": {"name": "Red Edge 3", "wavelength": 783, "resolution": 20},
    "B08": {"name": "NIR", "wavelength": 842, "resolution": 10},
    "B8A": {"name": "NIR Narrow", "wavelength": 865, "resolution": 20},
    "B11": {"name": "SWIR 1", "wavelength": 1610, "resolution": 20},
    "B12": {"name": "SWIR 2", "wavelength": 2190, "resolution": 20},
}

# ─── Vegetation Index Thresholds ───
NDVI_THRESHOLDS = {
    "barren": (-1.0, 0.1),
    "sparse": (0.1, 0.2),
    "moderate": (0.2, 0.4),
    "dense": (0.4, 0.6),
    "very_dense": (0.6, 1.0),
}

NDWI_THRESHOLDS = {
    "very_dry": (-1.0, -0.3),
    "dry": (-0.3, -0.1),
    "moderate": (-0.1, 0.1),
    "wet": (0.1, 0.3),
    "saturated": (0.3, 1.0),
}

# ─── Soil Moisture Model Config ───
SMC_MODEL = {
    "input_bands": ["B04", "B08", "B8A", "B11", "B12"],
    "patch_size": 32,
    "time_steps": 5,
    "output_unit": "volumetric_%",
    "target_mae": 4.0,  # target MAE < 4%
}

# ─── Crop Profiles (ET curves & growth stages) ───
CROP_PROFILES = {
    "wheat": {
        "name": "Wheat (Rabi)",
        "season": "rabi",
        "sowing_months": [10, 11],
        "harvest_months": [3, 4],
        "growth_stages": {
            "germination": {"days": (0, 20), "kc": 0.3},
            "tillering": {"days": (20, 45), "kc": 0.7},
            "stem_extension": {"days": (45, 75), "kc": 1.05},
            "heading": {"days": (75, 100), "kc": 1.15},
            "grain_filling": {"days": (100, 125), "kc": 0.8},
            "maturation": {"days": (125, 150), "kc": 0.3},
        },
        "water_requirement_mm": 450,
        "optimal_ndvi_peak": 0.75,
    },
    "rice": {
        "name": "Rice (Kharif)",
        "season": "kharif",
        "sowing_months": [6, 7],
        "harvest_months": [10, 11],
        "growth_stages": {
            "transplanting": {"days": (0, 15), "kc": 1.05},
            "vegetative": {"days": (15, 45), "kc": 1.1},
            "reproductive": {"days": (45, 75), "kc": 1.2},
            "ripening": {"days": (75, 110), "kc": 0.9},
        },
        "water_requirement_mm": 1200,
        "optimal_ndvi_peak": 0.80,
    },
    "sorghum": {
        "name": "Sorghum",
        "season": "kharif",
        "sowing_months": [6, 7],
        "harvest_months": [10, 11],
        "growth_stages": {
            "emergence": {"days": (0, 20), "kc": 0.3},
            "growth": {"days": (20, 50), "kc": 0.7},
            "mid_season": {"days": (50, 90), "kc": 1.0},
            "late_season": {"days": (90, 120), "kc": 0.55},
        },
        "water_requirement_mm": 500,
        "optimal_ndvi_peak": 0.65,
    },
    "cotton": {
        "name": "Cotton",
        "season": "kharif",
        "sowing_months": [4, 5],
        "harvest_months": [11, 12],
        "growth_stages": {
            "establishment": {"days": (0, 30), "kc": 0.35},
            "vegetative": {"days": (30, 70), "kc": 0.7},
            "flowering": {"days": (70, 120), "kc": 1.15},
            "boll_opening": {"days": (120, 170), "kc": 0.7},
        },
        "water_requirement_mm": 700,
        "optimal_ndvi_peak": 0.70,
    },
}

# ─── Pilot Sites ───
PILOT_SITES = {
    "icrisat": {
        "name": "ICRISAT, Patancheru (Hyderabad)",
        "short_name": "ICRISAT Hyderabad",
        "lat": 17.320,
        "lon": 78.210,
        "type": "research_station",
        "agro_zone": "Semi-Arid Deccan",
        "primary_crops": ["sorghum", "cotton"],
        "demo_window": {
            "start": "2026-09-20",
            "end": "2026-10-05",
            "season": "End of Monsoon / Post-Monsoon",
            "purpose": "Crop stress, post-monsoon water management, NDWI/NDVI contrasts",
        },
        "fields": [
            {"id": "ICR-F01", "name": "Dryland Block 1", "area_ha": 5.0, "crop": "sorghum",
             "sowing_date": "2026-06-15", "irrigation": "rainfed",
             "bbox": [78.2000, 17.3100, 78.2200, 17.3300]},
            {"id": "ICR-F02", "name": "Irrigated Block 2", "area_ha": 3.2, "crop": "cotton",
             "sowing_date": "2026-05-01", "irrigation": "drip",
             "bbox": [78.2050, 17.3150, 78.2150, 17.3250]},
        ],
        "soil_probes": 20,
        "hub_hardware": "AMD Ryzen AI 9 365 Workstation",
    },
    "ludhiana": {
        "name": "Ludhiana Region (Punjab)",
        "short_name": "Ludhiana Punjab",
        "lat": 30.9010,
        "lon": 75.8573,
        "type": "smallholder_cluster",
        "agro_zone": "Indo-Gangetic Plains",
        "primary_crops": ["wheat", "rice"],
        "demo_window": {
            "start": "2026-03-15",
            "end": "2026-03-30",
            "season": "Peak Rabi Maturation",
            "purpose": "Irrigation scheduling for wheat, yield & water savings demo",
        },
        "fields": [
            {"id": "LDH-F01", "name": "Wheat Field Alpha", "area_ha": 4.0, "crop": "wheat",
             "sowing_date": "2025-11-10", "irrigation": "canal",
             "bbox": [75.8473, 30.8910, 75.8673, 30.9110]},
            {"id": "LDH-F02", "name": "Wheat Field Beta", "area_ha": 2.8, "crop": "wheat",
             "sowing_date": "2025-11-05", "irrigation": "tubewell",
             "bbox": [75.8503, 30.8960, 75.8643, 30.9060]},
            {"id": "LDH-F03", "name": "Wheat Field Gamma", "area_ha": 1.5, "crop": "wheat",
             "sowing_date": "2025-11-20", "irrigation": "drip",
             "bbox": [75.8533, 30.8980, 75.8613, 30.9040]},
            {"id": "LDH-F04", "name": "Rotation Plot Delta", "area_ha": 3.0, "crop": "rice",
             "sowing_date": "2025-06-15", "irrigation": "canal",
             "bbox": [75.8453, 30.8940, 75.8573, 30.9010]},
        ],
        "soil_probes": 15,
        "hub_hardware": "AMD Ryzen AI 9 HX 375 Workstation",
    },
    "nashik": {
        "name": "Nashik Wine & Grape Region (Maharashtra)",
        "short_name": "Nashik Maharashtra",
        "lat": 19.9975,
        "lon": 73.7898,
        "type": "commercial_viticulture",
        "agro_zone": "Western Plateau",
        "primary_crops": ["cotton", "sorghum"],
        "demo_window": {
            "start": "2026-07-01",
            "end": "2026-07-15",
            "season": "Early Kharif / Monsoon Onset",
            "purpose": "Monsoon water management, pest alert for cotton bollworm",
        },
        "fields": [
            {"id": "NSK-F01", "name": "Vineyard Block A", "area_ha": 3.5, "crop": "cotton",
             "sowing_date": "2026-04-20", "irrigation": "drip",
             "bbox": [73.7800, 19.9900, 73.7998, 20.0050]},
            {"id": "NSK-F02", "name": "Sorghum Terrace B", "area_ha": 2.2, "crop": "sorghum",
             "sowing_date": "2026-06-10", "irrigation": "rainfed",
             "bbox": [73.7830, 19.9920, 73.7960, 20.0010]},
            {"id": "NSK-F03", "name": "Cotton Plot C", "area_ha": 4.1, "crop": "cotton",
             "sowing_date": "2026-05-05", "irrigation": "sprinkler",
             "bbox": [73.7750, 19.9870, 73.7900, 19.9980]},
        ],
        "soil_probes": 10,
        "hub_hardware": "AMD Ryzen AI 9 365 Workstation",
    },
    "coimbatore": {
        "name": "Tamil Nadu Agricultural University, Coimbatore",
        "short_name": "TNAU Coimbatore",
        "lat": 11.0168,
        "lon": 76.9558,
        "type": "research_university",
        "agro_zone": "Western Ghats Foothills",
        "primary_crops": ["rice", "cotton"],
        "demo_window": {
            "start": "2026-08-15",
            "end": "2026-09-01",
            "season": "Samba Season Transplanting",
            "purpose": "Paddy water optimization, pest surveillance with RedEdge",
        },
        "fields": [
            {"id": "CBE-F01", "name": "Wetland Paddy Block", "area_ha": 6.0, "crop": "rice",
             "sowing_date": "2026-07-01", "irrigation": "canal",
             "bbox": [76.9450, 11.0100, 76.9660, 11.0240]},
            {"id": "CBE-F02", "name": "Upland Cotton Trial", "area_ha": 2.5, "crop": "cotton",
             "sowing_date": "2026-05-15", "irrigation": "drip",
             "bbox": [76.9480, 11.0130, 76.9600, 11.0200]},
            {"id": "CBE-F03", "name": "Millet Research Strip", "area_ha": 1.0, "crop": "sorghum",
             "sowing_date": "2026-06-20", "irrigation": "sprinkler",
             "bbox": [76.9520, 11.0150, 76.9580, 11.0190]},
        ],
        "soil_probes": 18,
        "hub_hardware": "AMD Ryzen AI 9 HX 375 Workstation",
    },
    "bhopal": {
        "name": "Bhopal Soybean Belt (Madhya Pradesh)",
        "short_name": "Bhopal MP",
        "lat": 23.2599,
        "lon": 77.4126,
        "type": "smallholder_cluster",
        "agro_zone": "Central Highlands",
        "primary_crops": ["wheat", "sorghum"],
        "demo_window": {
            "start": "2026-12-01",
            "end": "2026-12-15",
            "season": "Rabi Tillering Phase",
            "purpose": "Wheat irrigation scheduling, frost alert, yield benchmarking",
        },
        "fields": [
            {"id": "BPL-F01", "name": "Wheat Block North", "area_ha": 5.0, "crop": "wheat",
             "sowing_date": "2026-10-25", "irrigation": "tubewell",
             "bbox": [77.4020, 23.2500, 77.4230, 23.2700]},
            {"id": "BPL-F02", "name": "Sorghum Rainfed South", "area_ha": 3.0, "crop": "sorghum",
             "sowing_date": "2026-06-15", "irrigation": "rainfed",
             "bbox": [77.4050, 23.2520, 77.4200, 23.2650]},
            {"id": "BPL-F03", "name": "Wheat Terrace East", "area_ha": 2.0, "crop": "wheat",
             "sowing_date": "2026-11-01", "irrigation": "canal",
             "bbox": [77.4100, 23.2540, 77.4220, 23.2640]},
        ],
        "soil_probes": 14,
        "hub_hardware": "AMD Ryzen AI 9 365 Workstation",
    },
    "varanasi": {
        "name": "Varanasi Gangetic Corridor (Uttar Pradesh)",
        "short_name": "Varanasi UP",
        "lat": 25.3176,
        "lon": 82.9739,
        "type": "smallholder_cluster",
        "agro_zone": "Indo-Gangetic Plains",
        "primary_crops": ["rice", "wheat"],
        "demo_window": {
            "start": "2026-03-01",
            "end": "2026-03-15",
            "season": "Late Rabi / Pre-Harvest",
            "purpose": "Yield forecasting accuracy validation, water savings measurement",
        },
        "fields": [
            {"id": "VNS-F01", "name": "Gangetic Wheat Alpha", "area_ha": 3.5, "crop": "wheat",
             "sowing_date": "2025-11-08", "irrigation": "canal",
             "bbox": [82.9640, 25.3080, 82.9840, 25.3270]},
            {"id": "VNS-F02", "name": "Rice Paddy Beta", "area_ha": 4.0, "crop": "rice",
             "sowing_date": "2025-06-20", "irrigation": "canal",
             "bbox": [82.9660, 25.3100, 82.9820, 25.3250]},
            {"id": "VNS-F03", "name": "Mixed Crop Gamma", "area_ha": 1.8, "crop": "wheat",
             "sowing_date": "2025-11-15", "irrigation": "tubewell",
             "bbox": [82.9700, 25.3120, 82.9790, 25.3200]},
        ],
        "soil_probes": 12,
        "hub_hardware": "AMD Ryzen AI 9 HX 375 Workstation",
    },
}

# ─── Nudge Templates (multilingual) ───
NUDGE_TEMPLATES = {
    "irrigate": {
        "en": "Field {field}: Water stress detected — irrigate tonight ({duration} mins {method}). Reply YES to confirm.",
        "hi": "खेत {field}: पानी की कमी — आज रात सिंचाई करें ({duration} मिनट {method})। YES भेजें।",
        "pa": "ਖੇਤ {field}: ਪਾਣੀ ਦੀ ਘਾਟ — ਅੱਜ ਰਾਤ ਸਿੰਚਾਈ ਕਰੋ ({duration} ਮਿੰਟ {method})। YES ਭੇਜੋ।",
        "kn": "ಹೊಲ {field}: ನೀರಿನ ಕೊರತೆ — ಇಂದು ರಾತ್ರಿ ನೀರು ಹಾಕಿ ({duration} ನಿಮಿಷ {method})। YES ಕಳುಹಿಸಿ.",
        "te": "పొలం {field}: నీటి ఒత్తిడి — ఈ రాత్రి నీళ్ళు పెట్టండి ({duration} నిమిషాలు {method}). YES పంపండి.",
    },
    "skip_irrigation": {
        "en": "Field {field}: Soil moisture adequate — skip irrigation this week. Savings: ~{savings}L water.",
        "hi": "खेत {field}: मिट्टी में नमी पर्याप्त — इस हफ्ते सिंचाई न करें। बचत: ~{savings}L पानी।",
        "pa": "ਖੇਤ {field}: ਮਿੱਟੀ ਵਿੱਚ ਨਮੀ ਕਾਫ਼ੀ — ਇਸ ਹਫ਼ਤੇ ਸਿੰਚਾਈ ਨਾ ਕਰੋ। ਬੱਚਤ: ~{savings}L ਪਾਣੀ।",
    },
    "pest_alert": {
        "en": "⚠️ Field {field}: Spectral anomaly detected in {zone}. Possible pest/disease. Inspect and send photo via WhatsApp.",
        "hi": "⚠️ खेत {field}: {zone} में असामान्यता। कीट/रोग संभव। जांचें और WhatsApp पर फोटो भेजें।",
    },
    "yield_forecast": {
        "en": "Field {field}: Estimated yield {yield_val} ± {uncertainty} tonnes/ha. {risk_note}",
        "hi": "खेत {field}: अनुमानित उपज {yield_val} ± {uncertainty} टन/हे। {risk_note}",
    },
}

# ─── Model Export Config ───
ONNX_CONFIG = {
    "opset_version": 17,
    "quantization": "int8_ptq",
    "execution_provider": "VitisAIExecutionProvider",  # or CPUExecutionProvider fallback
    "target_device": "Ryzen AI NPU",
}

# ─── Database ───
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krishi_sathi.db")

# ─── Server ───
DEFAULT_PORT = 5000
DEBUG_MODE = True
