"""
Krishi-Sathi — Nudge Engine
Rule + ML hybrid system that generates actionable irrigation, pest, and yield
nudges for farmers via SMS/IVR/App channels.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import (
    PILOT_SITES, CROP_PROFILES, NUDGE_TEMPLATES, DB_PATH
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════
#  Irrigation Nudge Engine
# ═══════════════════════════════════════════════════════════════

class IrrigationNudgeEngine:
    """
    Hybrid rule + ML engine that decides whether a field needs irrigation.
    
    Decision factors:
      1. Current soil moisture (from SMC model)
      2. Crop water requirement for current growth stage
      3. Weather forecast (rainfall expected?)
      4. Recent irrigation history
      5. Farmer constraints (irrigation method, available hours)
    
    Output: A single clear nudge — "Irrigate X minutes tonight" or "Skip this week"
    """

    # Soil moisture thresholds by irrigation type
    IRRIGATION_THRESHOLDS = {
        "drip": {"trigger": 22, "target": 32, "critical": 15},
        "sprinkler": {"trigger": 24, "target": 34, "critical": 16},
        "flood": {"trigger": 20, "target": 35, "critical": 14},
        "canal": {"trigger": 20, "target": 33, "critical": 14},
        "tubewell": {"trigger": 22, "target": 33, "critical": 15},
        "rainfed": {"trigger": 18, "target": 28, "critical": 12},
    }

    # Duration estimates (minutes for 1 hectare)
    DURATION_PER_HA = {
        "drip": 45,
        "sprinkler": 60,
        "flood": 90,
        "canal": 75,
        "tubewell": 60,
        "rainfed": 0,
    }

    def generate_nudge(
        self,
        field_id: str,
        field_name: str,
        smc_percent: float,
        crop: str,
        sowing_date: str,
        irrigation_type: str,
        area_ha: float,
        rainfall_forecast_mm: float = 0.0,
        et0_today: float = 5.0,
        language: str = "en",
    ) -> Dict:
        """
        Generate an irrigation nudge for a single field.
        """
        thresholds = self.IRRIGATION_THRESHOLDS.get(irrigation_type, self.IRRIGATION_THRESHOLDS["drip"])
        crop_profile = CROP_PROFILES.get(crop, CROP_PROFILES["wheat"])

        # Determine growth stage and crop coefficient
        sowing = datetime.strptime(sowing_date, "%Y-%m-%d")
        days_after_sowing = (datetime.utcnow() - sowing).days
        kc = self._get_crop_kc(days_after_sowing, crop_profile)

        # Adjust thresholds by growth stage (critical stages need more water)
        stage_multiplier = 0.85 + kc * 0.3
        adjusted_trigger = thresholds["trigger"] * stage_multiplier

        # Decision logic
        if smc_percent >= thresholds["target"]:
            # Soil is adequately moist
            nudge_type = "skip_irrigation"
            water_savings = round(area_ha * self.DURATION_PER_HA.get(irrigation_type, 60) * 8, 0)  # Liters estimate
            
            template = NUDGE_TEMPLATES["skip_irrigation"]
            message_en = template["en"].format(
                field=field_name, savings=int(water_savings)
            )
            message_local = template.get(language, template["en"]).format(
                field=field_name, savings=int(water_savings)
            )

            return {
                "field_id": field_id,
                "nudge_type": nudge_type,
                "action": "skip",
                "urgency": "low",
                "message_en": message_en,
                "message_local": message_local,
                "language": language,
                "reasoning": {
                    "smc_current": smc_percent,
                    "smc_target": thresholds["target"],
                    "rainfall_expected_mm": rainfall_forecast_mm,
                    "crop_stage_kc": round(kc, 2),
                    "water_savings_liters": water_savings,
                },
            }

        elif smc_percent <= thresholds["critical"]:
            # Critical water stress
            duration = round(self.DURATION_PER_HA.get(irrigation_type, 60) * area_ha * 1.2)
            
            template = NUDGE_TEMPLATES["irrigate"]
            message_en = template["en"].format(
                field=field_name, duration=duration, method=irrigation_type
            )
            message_local = template.get(language, template["en"]).format(
                field=field_name, duration=duration, method=irrigation_type
            )

            return {
                "field_id": field_id,
                "nudge_type": "irrigate",
                "action": "irrigate_urgent",
                "urgency": "critical",
                "message_en": message_en,
                "message_local": message_local,
                "language": language,
                "duration_minutes": duration,
                "reasoning": {
                    "smc_current": smc_percent,
                    "smc_critical": thresholds["critical"],
                    "crop_stage_kc": round(kc, 2),
                    "days_after_sowing": days_after_sowing,
                },
            }

        elif smc_percent <= adjusted_trigger:
            # Check if rain is expected
            if rainfall_forecast_mm > 10:
                # Rain expected — suggest waiting
                return {
                    "field_id": field_id,
                    "nudge_type": "wait_for_rain",
                    "action": "wait",
                    "urgency": "low",
                    "message_en": f"Field {field_name}: Rain expected ({rainfall_forecast_mm}mm). Hold irrigation 24-48 hrs.",
                    "message_local": f"Field {field_name}: Rain expected ({rainfall_forecast_mm}mm). Hold irrigation 24-48 hrs.",
                    "language": language,
                    "reasoning": {
                        "smc_current": smc_percent,
                        "rainfall_forecast_mm": rainfall_forecast_mm,
                    },
                }

            # Irrigation needed
            duration = round(self.DURATION_PER_HA.get(irrigation_type, 60) * area_ha)
            
            template = NUDGE_TEMPLATES["irrigate"]
            message_en = template["en"].format(
                field=field_name, duration=duration, method=irrigation_type
            )
            message_local = template.get(language, template["en"]).format(
                field=field_name, duration=duration, method=irrigation_type
            )

            return {
                "field_id": field_id,
                "nudge_type": "irrigate",
                "action": "irrigate",
                "urgency": "medium",
                "message_en": message_en,
                "message_local": message_local,
                "language": language,
                "duration_minutes": duration,
                "reasoning": {
                    "smc_current": smc_percent,
                    "smc_trigger": round(adjusted_trigger, 1),
                    "crop_stage_kc": round(kc, 2),
                    "et0_today": et0_today,
                },
            }

        else:
            # Soil moisture is between trigger and target — monitor
            return {
                "field_id": field_id,
                "nudge_type": "monitor",
                "action": "monitor",
                "urgency": "low",
                "message_en": f"Field {field_name}: Soil moisture OK ({smc_percent}%). Next check in 2 days.",
                "message_local": f"Field {field_name}: Soil moisture OK ({smc_percent}%). Next check in 2 days.",
                "language": language,
                "reasoning": {
                    "smc_current": smc_percent,
                    "smc_trigger": round(adjusted_trigger, 1),
                    "smc_target": thresholds["target"],
                },
            }

    def _get_crop_kc(self, days_after_sowing: int, crop_profile: Dict) -> float:
        """Get crop coefficient for current growth stage."""
        for stage_name, stage in crop_profile["growth_stages"].items():
            d_start, d_end = stage["days"]
            if d_start <= days_after_sowing <= d_end:
                return stage["kc"]
        return 0.3  # Default (post-harvest or pre-sowing)


# ═══════════════════════════════════════════════════════════════
#  Pest Alert Engine
# ═══════════════════════════════════════════════════════════════

class PestAlertEngine:
    """Generates farmer-friendly pest/disease alert nudges from anomaly detections."""

    def generate_alert(
        self,
        field_id: str,
        field_name: str,
        anomaly: Dict,
        language: str = "en",
    ) -> Dict:
        """Convert an anomaly detection into a farmer nudge."""
        zone = anomaly.get("zone", "field")
        severity = anomaly.get("severity", "medium")

        template = NUDGE_TEMPLATES["pest_alert"]
        message_en = template["en"].format(field=field_name, zone=zone)
        message_local = template.get(language, template["en"]).format(field=field_name, zone=zone)

        urgency = "critical" if severity == "high" else ("medium" if severity == "medium" else "low")

        return {
            "field_id": field_id,
            "nudge_type": "pest_alert",
            "action": "inspect",
            "urgency": urgency,
            "message_en": message_en,
            "message_local": message_local,
            "language": language,
            "anomaly_details": anomaly,
        }


# ═══════════════════════════════════════════════════════════════
#  Complete Nudge Generator (orchestrates all engines)
# ═══════════════════════════════════════════════════════════════

class NudgeGenerator:
    """
    Orchestrates all nudge engines to produce a prioritized list of 
    actions for a site's fields.
    """

    def __init__(self):
        self.irrigation_engine = IrrigationNudgeEngine()
        self.pest_engine = PestAlertEngine()

    def generate_all_nudges(
        self,
        site_key: str,
        field_data: List[Dict],
        anomalies: Dict[str, List[Dict]] = None,
        weather: List[Dict] = None,
        language: str = "en",
    ) -> List[Dict]:
        """
        Generate all nudges for a site's fields.
        
        field_data: [{field_id, name, crop, sowing_date, irrigation_type, 
                       area_ha, smc_percent, ndvi, ndwi}]
        anomalies: {field_id: [anomaly_dicts]}
        weather: recent weather records
        """
        nudges = []

        # Get rainfall forecast
        rainfall_forecast = 0.0
        if weather and len(weather) > 0:
            recent = weather[-1] if weather else {}
            rainfall_forecast = recent.get("rainfall_mm", 0)

        et0_today = 5.0
        if weather and len(weather) > 0:
            et0_today = weather[-1].get("et0", 5.0) or 5.0

        for fd in field_data:
            # Irrigation nudge
            irr_nudge = self.irrigation_engine.generate_nudge(
                field_id=fd["field_id"],
                field_name=fd.get("name", fd["field_id"]),
                smc_percent=fd.get("smc_percent", 25),
                crop=fd.get("crop", "wheat"),
                sowing_date=fd.get("sowing_date", "2025-11-01"),
                irrigation_type=fd.get("irrigation_type", "drip"),
                area_ha=fd.get("area_ha", 1.0),
                rainfall_forecast_mm=rainfall_forecast,
                et0_today=et0_today,
                language=language,
            )
            nudges.append(irr_nudge)

            # Pest alerts
            if anomalies and fd["field_id"] in anomalies:
                for anomaly in anomalies[fd["field_id"]][:3]:  # Max 3 alerts per field
                    alert = self.pest_engine.generate_alert(
                        field_id=fd["field_id"],
                        field_name=fd.get("name", fd["field_id"]),
                        anomaly=anomaly,
                        language=language,
                    )
                    nudges.append(alert)

        # Sort by urgency (critical > medium > low)
        urgency_order = {"critical": 0, "medium": 1, "low": 2}
        nudges.sort(key=lambda n: urgency_order.get(n.get("urgency", "low"), 3))

        return nudges

    def store_nudges(self, nudges: List[Dict]):
        """Persist nudges to database."""
        conn = get_db()
        for n in nudges:
            conn.execute("""
                INSERT INTO nudges 
                (field_id, nudge_type, message_en, message_local, language, channel, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                n["field_id"], n["nudge_type"],
                n.get("message_en", ""), n.get("message_local", ""),
                n.get("language", "en"), "sms", "pending"
            ))
        conn.commit()
        conn.close()

    def get_nudge_history(self, field_id: str = None, limit: int = 50) -> List[Dict]:
        """Get nudge history, optionally filtered by field."""
        conn = get_db()
        if field_id:
            rows = conn.execute("""
                SELECT * FROM nudges WHERE field_id = ? 
                ORDER BY created_at DESC LIMIT ?
            """, (field_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM nudges ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# Global instance
nudge_generator = NudgeGenerator()
