"""
Krishi-Sathi \u2014 Advanced ML Models Module
Multi-Parameter Soil Moisture, Pest Anomaly Detection, Yield Forecasting.

In production these would be trained PyTorch models exported to ONNX.
For the demo, we use physics-informed analytical models calibrated
to each agro-climatic zone, using 20+ spectral & meteorological parameters.

Spectral Indices Used:
  NDVI   \u2014 Normalized Difference Vegetation Index
  NDWI   \u2014 Normalized Difference Water Index
  EVI    \u2014 Enhanced Vegetation Index (atmosphere-corrected)
  SAVI   \u2014 Soil-Adjusted Vegetation Index
  MSAVI  \u2014 Modified Soil-Adjusted Vegetation Index
  NDRE   \u2014 Normalized Difference Red Edge Index
  GNDVI  \u2014 Green NDVI
  LSWI   \u2014 Land Surface Water Index
  NBR    \u2014 Normalized Burn Ratio
  RECI   \u2014 Red Edge Chlorophyll Index
  BSI    \u2014 Bare Soil Index
  CIG    \u2014 Chlorophyll Index Green
  NDMI   \u2014 Normalized Difference Moisture Index (= NDWI via B8A/B11)
  LAI    \u2014 Leaf Area Index (estimated)
  fCover \u2014 Fractional Vegetation Cover (estimated)

Meteorological Inputs:
  Rainfall (7-day, 14-day, 30-day cumulative)
  ET0 (FAO-56 reference evapotranspiration, 7-day)
  Temperature (max, min, mean, GDD accumulation)
  Humidity (relative %)
  Wind speed (m/s)
  VPD (Vapour Pressure Deficit)

Agronomic Inputs:
  Crop type & profile (Kc curve)
  Days after sowing / growth stage
  Irrigation type
  Agro-climatic zone calibration
"""

import math
import hashlib
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from config import CROP_PROFILES, PILOT_SITES, SMC_MODEL, ONNX_CONFIG, S2_BANDS


# ================================================================
#  Derived Feature Computation Helpers
# ================================================================

def estimate_lai(ndvi: float) -> float:
    """
    Estimate Leaf Area Index from NDVI using the Beer-Lambert relationship.
    LAI = -ln((0.95 - NDVI) / 0.9) / 0.5   (clipped to [0, 8])
    """
    ndvi_c = max(0.05, min(ndvi, 0.94))
    try:
        lai = -math.log((0.95 - ndvi_c) / 0.9) / 0.5
    except (ValueError, ZeroDivisionError):
        lai = 0.0
    return max(0.0, min(round(lai, 3), 8.0))


def estimate_fcover(ndvi: float) -> float:
    """
    Estimate Fractional Vegetation Cover from NDVI.
    fCover = ((NDVI - NDVIsoil) / (NDVIveg - NDVIsoil))^2
    """
    ndvi_soil = 0.05
    ndvi_veg = 0.90
    fc = ((ndvi - ndvi_soil) / (ndvi_veg - ndvi_soil)) ** 2
    return max(0.0, min(round(fc, 4), 1.0))


def compute_vpd(temp_max: float, temp_min: float, humidity: float) -> float:
    """
    Compute Vapour Pressure Deficit (kPa) from temperature and humidity.
    Uses the Tetens formula.
    """
    temp_mean = (temp_max + temp_min) / 2.0
    es = 0.6108 * math.exp((17.27 * temp_mean) / (temp_mean + 237.3))
    ea = es * (humidity / 100.0)
    vpd = es - ea
    return max(0.0, round(vpd, 3))


def compute_gdd(temp_max: float, temp_min: float, t_base: float = 5.0) -> float:
    """
    Compute Growing Degree Days for a single day.
    GDD = max(0, (Tmax + Tmin)/2 - Tbase)
    """
    return max(0.0, round((temp_max + temp_min) / 2.0 - t_base, 2))


def compute_cwsi(et_actual: float, et_potential: float) -> float:
    """
    Crop Water Stress Index.
    CWSI = 1 - (ETa / ETp)   where 0 = no stress, 1 = max stress
    """
    if et_potential <= 0:
        return 0.0
    return max(0.0, min(round(1.0 - et_actual / et_potential, 4), 1.0))


# ================================================================
#  Soil Moisture Estimator (CNN proxy - 22 input parameters)
# ================================================================

class SoilMoistureCNN:
    """
    Advanced proxy for a CNN model that estimates soil moisture content (SMC)
    from Sentinel-2 multispectral bands.

    In production:
      - Architecture: 2D Conv + Temporal Encoder (TCN)
      - Input: 10 bands (B02-B12) x 5 time steps x 32x32 patch
      - Aux input: 8 meteorological + 4 agronomic features
      - Output: SMC in volumetric %
      - Training: PyTorch -> ONNX export -> INT8 PTQ -> ONNX Runtime (Ryzen AI NPU)

    Demo mode uses a physics-informed multi-parameter analytical model:
      SMC = f(NDVI, NDWI, EVI, SAVI, MSAVI, NDRE, GNDVI, LSWI, NBR, BSI,
              CIG, LAI, fCover, rainfall_7d, rainfall_14d, rainfall_30d,
              ET0_7d, temperature, humidity, wind, VPD,
              crop_kc, days_after_sowing, agro_zone)
    """

    INPUT_FEATURES = [
        "ndvi", "ndwi", "evi", "savi", "msavi", "ndre", "gndvi",
        "lswi", "nbr", "bsi", "cig", "reci",
        "lai", "fcover",
        "rainfall_7d", "rainfall_14d", "rainfall_30d",
        "et0_7d", "temp_mean", "humidity", "wind_speed", "vpd",
        "crop_kc", "days_after_sowing",
    ]

    def __init__(self):
        self.model_version = "v2.0-multi-param"
        self.n_features = len(self.INPUT_FEATURES)
        self.target_mae = SMC_MODEL["target_mae"]

        # Zone-specific calibration offsets (learned from probe data)
        self.zone_offsets = {
            "Southern Plateau": -2.0,
            "Semi-Arid Deccan": -4.5,
            "Indo-Gangetic Plains": 3.0,
            "Western Plateau": -1.5,
            "Western Ghats Foothills": 1.5,
            "Central Highlands": -0.5,
        }

        # Irrigation type moisture contribution
        self.irrigation_bonus = {
            "drip": 3.0,
            "canal": 5.0,
            "tubewell": 4.5,
            "sprinkler": 4.0,
            "rainfed": 0.0,
        }

    def predict(
        self,
        ndvi: float = 0.4,
        ndwi: float = 0.0,
        evi: float = 0.3,
        savi: float = 0.35,
        msavi: float = 0.35,
        ndre: float = 0.3,
        gndvi: float = 0.45,
        lswi: float = 0.0,
        nbr: float = 0.2,
        bsi: float = 0.1,
        cig: float = 1.0,
        reci: float = 1.2,
        lai: float = None,
        fcover: float = None,
        rainfall_7d: float = 0.0,
        rainfall_14d: float = 0.0,
        rainfall_30d: float = 0.0,
        et0_7d: float = 35.0,
        temp_max: float = 32.0,
        temp_min: float = 18.0,
        humidity: float = 55.0,
        wind_speed: float = 10.0,
        vpd: float = None,
        crop_kc: float = 0.7,
        days_after_sowing: int = 60,
        agro_zone: str = "Indo-Gangetic Plains",
        irrigation_type: str = "rainfed",
    ) -> Dict:
        """
        Predict soil moisture content from 22+ spectral, meteorological
        and agronomic parameters.
        """
        # Derive missing features
        if lai is None:
            lai = estimate_lai(ndvi)
        if fcover is None:
            fcover = estimate_fcover(ndvi)
        if vpd is None:
            vpd = compute_vpd(temp_max, temp_min, humidity)

        temp_mean = (temp_max + temp_min) / 2.0

        # -- Component 1: Spectral Moisture Signal --
        smc_ndwi = 25.0 + ndwi * 40.0
        smc_lswi = 22.0 + lswi * 35.0
        spectral_moisture = smc_ndwi * 0.60 + smc_lswi * 0.40

        # -- Component 2: Vegetation Correction --
        veg_signal = (
            ndvi * 0.30 + evi * 0.25 + savi * 0.20 +
            msavi * 0.15 + gndvi * 0.10
        )
        veg_correction = veg_signal * 8.0
        lai_correction = min(lai, 5.0) * 0.8
        fcover_correction = fcover * 2.5

        # -- Component 3: Canopy Health --
        chlorophyll_signal = ndre * 0.35 + cig * 0.10 + reci * 0.08
        chlorophyll_effect = -chlorophyll_signal * 2.0

        # -- Component 4: Soil Exposure --
        bsi_correction = -bsi * 10.0
        nbr_correction = nbr * 3.0

        # -- Component 5: Rainfall --
        rain_effect_7d = min(rainfall_7d * 0.45, 16.0)
        rain_effect_14d = min(rainfall_14d * 0.12, 6.0)
        rain_effect_30d = min(rainfall_30d * 0.03, 3.0)
        rain_total = rain_effect_7d + rain_effect_14d + rain_effect_30d

        # -- Component 6: Evaporative Demand --
        et_depletion = -et0_7d * 0.18
        vpd_effect = -vpd * 2.5
        temp_effect = -max(temp_mean - 25, 0) * 0.3
        humidity_effect = max(humidity - 50, 0) * 0.08
        wind_effect = -max(wind_speed - 8, 0) * 0.15

        # -- Component 7: Agronomic Adjustments --
        crop_effect = -crop_kc * 3.5
        irrigation_adj = self.irrigation_bonus.get(irrigation_type, 0.0)

        if 40 <= days_after_sowing <= 90:
            stage_modifier = -2.0
        elif days_after_sowing > 120:
            stage_modifier = 1.5
        else:
            stage_modifier = 0.0

        zone_adj = self.zone_offsets.get(agro_zone, 0.0)

        # -- Combine --
        smc = (
            spectral_moisture + veg_correction + lai_correction +
            fcover_correction + chlorophyll_effect + bsi_correction +
            nbr_correction + rain_total + et_depletion + vpd_effect +
            temp_effect + humidity_effect + wind_effect + crop_effect +
            irrigation_adj + stage_modifier + zone_adj
        )
        smc = max(3.0, min(smc, 58.0))

        # -- Confidence --
        moisture_agreement = 1.0 - abs(smc_ndwi - smc_lswi) / 30.0
        veg_agreement = 1.0 - abs(ndvi - evi) * 1.5
        data_coverage = min(1.0, (rainfall_7d + rainfall_14d + et0_7d) / 50.0)
        confidence = 0.70 * moisture_agreement + 0.15 * veg_agreement + 0.15 * data_coverage
        confidence = max(0.35, min(confidence, 0.96))

        return {
            "smc_percent": round(smc, 1),
            "confidence": round(confidence, 3),
            "category": self._categorize_smc(smc),
            "n_input_features": self.n_features,
            "components": {
                "spectral_moisture": round(spectral_moisture, 2),
                "vegetation_correction": round(veg_correction, 2),
                "lai_contribution": round(lai_correction, 2),
                "fcover_contribution": round(fcover_correction, 2),
                "chlorophyll_effect": round(chlorophyll_effect, 2),
                "bare_soil_index": round(bsi_correction, 2),
                "nbr_contribution": round(nbr_correction, 2),
                "rainfall_7d": round(rain_effect_7d, 2),
                "rainfall_14d": round(rain_effect_14d, 2),
                "rainfall_30d": round(rain_effect_30d, 2),
                "et_depletion": round(et_depletion, 2),
                "vpd_drying": round(vpd_effect, 2),
                "temperature": round(temp_effect, 2),
                "humidity": round(humidity_effect, 2),
                "wind": round(wind_effect, 2),
                "crop_demand": round(crop_effect, 2),
                "irrigation": round(irrigation_adj, 2),
                "growth_stage": round(stage_modifier, 2),
                "zone_calibration": round(zone_adj, 2),
            },
            "derived_features": {
                "lai": round(lai, 3),
                "fcover": round(fcover, 4),
                "vpd_kpa": round(vpd, 3),
                "temp_mean": round(temp_mean, 1),
            },
            "spectral_indices_used": {
                "ndvi": round(ndvi, 4), "ndwi": round(ndwi, 4),
                "evi": round(evi, 4), "savi": round(savi, 4),
                "msavi": round(msavi, 4), "ndre": round(ndre, 4),
                "gndvi": round(gndvi, 4), "lswi": round(lswi, 4),
                "nbr": round(nbr, 4), "bsi": round(bsi, 4),
                "cig": round(cig, 4), "reci": round(reci, 4),
            },
            "model_version": self.model_version,
        }

    def _categorize_smc(self, smc: float) -> str:
        if smc < 12:
            return "very_dry"
        elif smc < 20:
            return "dry"
        elif smc < 30:
            return "adequate"
        elif smc < 42:
            return "wet"
        else:
            return "saturated"

    def batch_predict(self, fields_data: List[Dict]) -> List[Dict]:
        """Run predictions for multiple fields."""
        results = []
        for fd in fields_data:
            valid_keys = set(self.predict.__code__.co_varnames[:self.predict.__code__.co_argcount])
            kwargs = {k: fd[k] for k in fd if k in valid_keys}
            pred = self.predict(**kwargs)
            pred["field_id"] = fd.get("field_id")
            results.append(pred)
        return results

    def get_onnx_config(self) -> Dict:
        """Return ONNX export configuration for this model."""
        return {
            "model_name": "krishi_sathi_smc_cnn_v2",
            "input_shape": [1, SMC_MODEL["time_steps"], len(S2_BANDS),
                           SMC_MODEL["patch_size"], SMC_MODEL["patch_size"]],
            "aux_input_shape": [1, self.n_features],
            "output_shape": [1, 1],
            "opset": ONNX_CONFIG["opset_version"],
            "quantization": ONNX_CONFIG["quantization"],
            "execution_provider": ONNX_CONFIG["execution_provider"],
            "target_device": ONNX_CONFIG["target_device"],
            "input_features": self.INPUT_FEATURES,
        }


# ================================================================
#  Pest / Anomaly Detection (multi-index spectral change detector)
# ================================================================

class PestAnomalyDetector:
    """
    Advanced unsupervised anomaly detection on spectral index time series.

    Multi-index approach:
      1. NDVI trajectory vs crop phenology model
      2. EVI anomalies (atmosphere-corrected, more sensitive)
      3. NDRE / RedEdge analysis for early chlorophyll stress
      4. LSWI / NDWI divergence for water stress vs pest differentiation
      5. SAVI analysis in low-cover fields
      6. CIG / GNDVI for nutrient deficiency signatures
      7. Cross-index correlation for anomaly type classification
      8. Temporal derivative analysis for rate of change detection
    """

    def __init__(self):
        self.ndvi_drop_threshold = 0.08
        self.evi_drop_threshold = 0.06
        self.ndre_drop_threshold = 0.05
        self.reci_drop_threshold = 0.5
        self.lswi_drop_threshold = 0.07
        self.gndvi_drop_threshold = 0.06
        self.min_observations = 3

    def detect_anomalies(
        self,
        timeseries: List[Dict],
        crop: str = "wheat",
        sowing_date: str = "2025-11-01"
    ) -> List[Dict]:
        """
        Analyze a field's multi-spectral time series for pest/disease anomalies.
        Uses 8+ spectral indices for cross-validated detection.
        """
        if len(timeseries) < self.min_observations:
            return []

        anomalies = []
        sowing = datetime.strptime(sowing_date, "%Y-%m-%d")
        crop_profile = CROP_PROFILES.get(crop, CROP_PROFILES["wheat"])

        # Rolling statistics for z-score calculations
        index_names = ["ndvi", "evi", "savi", "ndre", "gndvi", "lswi", "ndwi", "reci", "cig"]
        stats = {}
        for idx_name in index_names:
            vals = [t.get(idx_name) for t in timeseries if t.get(idx_name) is not None]
            if len(vals) >= 3:
                stats[idx_name] = {
                    "mean": float(np.mean(vals)),
                    "std": float(np.std(vals)) + 0.001,
                    "trend": float(np.polyfit(range(len(vals)), vals, 1)[0]) if len(vals) > 2 else 0.0,
                }

        ndvi_values = [t.get("ndvi", 0) for t in timeseries if t.get("ndvi") is not None]
        if len(ndvi_values) < self.min_observations:
            return []

        for i in range(2, len(timeseries)):
            curr = timeseries[i]
            prev = timeseries[i - 1]
            prev2 = timeseries[i - 2]

            curr_date = datetime.strptime(curr["date"], "%Y-%m-%d")
            days_after_sowing = (curr_date - sowing).days
            expected_ndvi = self._expected_ndvi(days_after_sowing, crop_profile)

            # -- Multi-index drop analysis --
            drops = {}
            for idx_name, threshold in [
                ("ndvi", self.ndvi_drop_threshold),
                ("evi", self.evi_drop_threshold),
                ("ndre", self.ndre_drop_threshold),
                ("lswi", self.lswi_drop_threshold),
                ("gndvi", self.gndvi_drop_threshold),
            ]:
                if curr.get(idx_name) is not None and prev.get(idx_name) is not None:
                    drop = prev[idx_name] - curr[idx_name]
                    drops[idx_name] = drop
                    if drop > threshold:
                        drops[f"{idx_name}_alert"] = True

            # -- Classify anomaly type --
            if drops.get("ndvi_alert") or drops.get("evi_alert"):
                anomaly_type = self._classify_anomaly(drops)
                ndvi_drop = drops.get("ndvi", 0)
                severity = self._compute_severity(drops, days_after_sowing, crop_profile)
                anomaly_score = self._compute_anomaly_score(drops, stats, curr)

                anomalies.append({
                    "date": curr["date"],
                    "type": anomaly_type,
                    "severity": severity,
                    "anomaly_score": round(anomaly_score, 3),
                    "ndvi_drop": round(ndvi_drop, 4),
                    "expected_ndvi": round(expected_ndvi, 4),
                    "actual_ndvi": curr.get("ndvi"),
                    "multi_index_drops": {k: round(v, 4) for k, v in drops.items() if isinstance(v, float)},
                    "description": self._build_description(anomaly_type, drops, days_after_sowing),
                    "zone": self._estimate_affected_zone(curr),
                    "indices_triggered": [k.replace("_alert", "") for k in drops if k.endswith("_alert")],
                })

            # -- Growth lag detection --
            if curr.get("ndvi") is not None and expected_ndvi > 0:
                deviation = expected_ndvi - curr["ndvi"]
                if deviation > 0.12:
                    evi_lag = False
                    if curr.get("evi") is not None:
                        expected_evi = expected_ndvi * 0.85
                        evi_lag = (expected_evi - curr["evi"]) > 0.10

                    anomalies.append({
                        "date": curr["date"],
                        "type": "growth_lag",
                        "severity": "medium" if deviation < 0.2 else "high",
                        "anomaly_score": round(min(deviation * 3, 1.0), 3),
                        "ndvi_drop": round(deviation, 4),
                        "expected_ndvi": round(expected_ndvi, 4),
                        "actual_ndvi": curr.get("ndvi"),
                        "evi_confirmed": evi_lag,
                        "description": f"Crop growth {deviation:.1%} below expected for day {days_after_sowing}"
                                       + (" (EVI confirms)" if evi_lag else ""),
                        "zone": "full_field",
                        "indices_triggered": ["ndvi"] + (["evi"] if evi_lag else []),
                    })

            # -- RECI anomaly (chlorophyll stress) --
            if curr.get("reci") is not None and prev.get("reci") is not None:
                reci_drop = prev["reci"] - curr["reci"]
                if reci_drop > self.reci_drop_threshold:
                    cig_confirms = False
                    if curr.get("cig") is not None and prev.get("cig") is not None:
                        cig_confirms = (prev["cig"] - curr["cig"]) > 0.3

                    anomalies.append({
                        "date": curr["date"],
                        "type": "chlorophyll_stress",
                        "severity": "high" if reci_drop > 1.0 else "medium",
                        "anomaly_score": round(min(reci_drop / 2.0, 1.0), 3),
                        "ndvi_drop": round(reci_drop, 4),
                        "description": f"Chlorophyll index dropped {reci_drop:.2f}"
                                       + (" (CIG confirms nutrient issue)" if cig_confirms else "")
                                       + " - possible nutrient deficiency or disease",
                        "zone": self._estimate_affected_zone(curr),
                        "indices_triggered": ["reci"] + (["cig"] if cig_confirms else []),
                    })

            # -- Temporal derivative (acceleration) --
            if i >= 3:
                prev3 = timeseries[i - 3]
                ndvi_accel = self._compute_acceleration(
                    prev3.get("ndvi"), prev.get("ndvi"), curr.get("ndvi")
                )
                if ndvi_accel is not None and ndvi_accel < -0.03:
                    anomalies.append({
                        "date": curr["date"],
                        "type": "accelerating_decline",
                        "severity": "high",
                        "anomaly_score": round(min(abs(ndvi_accel) * 10, 1.0), 3),
                        "ndvi_drop": round(abs(ndvi_accel), 4),
                        "description": f"NDVI decline accelerating (d2/dt2 = {ndvi_accel:.4f}) - rapid crop deterioration",
                        "zone": self._estimate_affected_zone(curr),
                        "indices_triggered": ["ndvi_acceleration"],
                    })

        # Deduplicate
        seen = set()
        unique = []
        for a in anomalies:
            key = f"{a['date']}_{a['type']}"
            if key not in seen:
                seen.add(key)
                unique.append(a)
        return unique

    def _classify_anomaly(self, drops: Dict) -> str:
        ndvi_d = drops.get("ndvi_alert", False)
        evi_d = drops.get("evi_alert", False)
        ndre_d = drops.get("ndre_alert", False)
        lswi_d = drops.get("lswi_alert", False)
        gndvi_d = drops.get("gndvi_alert", False)

        if ndvi_d and lswi_d and not ndre_d:
            return "water_stress"
        elif ndvi_d and ndre_d and not lswi_d:
            return "pest_damage"
        elif not ndvi_d and ndre_d and gndvi_d:
            return "nutrient_deficiency"
        elif ndvi_d and ndre_d and evi_d:
            return "disease"
        elif ndvi_d:
            return "ndvi_drop"
        else:
            return "spectral_anomaly"

    def _compute_severity(self, drops: Dict, das: int, crop_profile: Dict) -> str:
        n_alerts = sum(1 for k in drops if k.endswith("_alert"))
        max_drop = max((v for k, v in drops.items() if isinstance(v, float)), default=0)
        base_severity = n_alerts * 0.2 + max_drop * 2.0

        for stage_name, stage in crop_profile.get("growth_stages", {}).items():
            d_start, d_end = stage["days"]
            if d_start <= das <= d_end and stage["kc"] > 0.9:
                base_severity *= 1.5
                break

        if base_severity > 1.0:
            return "critical"
        elif base_severity > 0.6:
            return "high"
        elif base_severity > 0.3:
            return "medium"
        else:
            return "low"

    def _compute_anomaly_score(self, drops: Dict, stats: Dict, curr: Dict) -> float:
        z_scores = []
        for idx_name in ["ndvi", "evi", "ndre", "gndvi", "lswi"]:
            if idx_name in stats and curr.get(idx_name) is not None:
                z = abs(curr[idx_name] - stats[idx_name]["mean"]) / stats[idx_name]["std"]
                z_scores.append(min(z / 3.0, 1.0))
        if not z_scores:
            return 0.0
        return float(np.mean(z_scores))

    def _build_description(self, anomaly_type: str, drops: Dict, das: int) -> str:
        alert_indices = [k.replace("_alert", "").upper() for k in drops if k.endswith("_alert")]
        idx_str = ", ".join(alert_indices)
        descriptions = {
            "pest_damage": f"Pest damage detected via {idx_str} - vegetation decline without moisture change (day {das})",
            "water_stress": f"Water stress via {idx_str} - both vegetation and surface water declining (day {das})",
            "nutrient_deficiency": f"Nutrient deficiency via {idx_str} - chlorophyll drop without canopy loss (day {das})",
            "disease": f"Possible disease via {idx_str} - rapid multi-index decline (day {das})",
            "ndvi_drop": f"NDVI dropped significantly ({idx_str}) - cause undetermined (day {das})",
            "spectral_anomaly": f"Spectral anomaly in {idx_str} (day {das})",
        }
        return descriptions.get(anomaly_type, f"Anomaly detected in {idx_str} (day {das})")

    def _compute_acceleration(self, v1, v2, v3) -> Optional[float]:
        if v1 is None or v2 is None or v3 is None:
            return None
        return v3 - 2 * v2 + v1

    def _expected_ndvi(self, days_after_sowing: int, crop_profile: Dict) -> float:
        peak_ndvi = crop_profile.get("optimal_ndvi_peak", 0.7)
        for stage_name, stage in crop_profile["growth_stages"].items():
            d_start, d_end = stage["days"]
            if d_start <= days_after_sowing <= d_end:
                progress = (days_after_sowing - d_start) / max(d_end - d_start, 1)
                kc = stage["kc"]
                return 0.15 + kc * (peak_ndvi - 0.15) * (0.7 + 0.3 * progress)
        return 0.2

    def _estimate_affected_zone(self, observation: Dict) -> str:
        ndvi = observation.get("ndvi", 0.5)
        evi = observation.get("evi", ndvi * 0.85)
        avg_health = (ndvi + evi) / 2.0
        if avg_health < 0.15:
            return "full_field"
        elif avg_health < 0.30:
            return "east_section"
        elif avg_health < 0.40:
            return "localized_patch"
        else:
            return "edge_strip"


# ================================================================
#  Yield Forecasting Model (Multi-Factor)
# ================================================================

class YieldForecaster:
    """
    Advanced multi-modal yield forecasting model.

    Input Factors (7 categories, 25+ individual features):
      1. Vegetation Vigor: NDVI, EVI, SAVI, GNDVI peak & mean
      2. Water Availability: NDWI, LSWI, soil moisture, rainfall
      3. Canopy Health: NDRE, RECI, CIG, LAI trajectory
      4. Weather Impact: Temperature, humidity, wind, VPD, GDD
      5. Soil Conditions: BSI, NBR, irrigation type
      6. Phenological Progress: Days after sowing, growth stage timing
      7. Temporal Dynamics: NDVI slope, EVI consistency, anomaly count

    Output:
      - Yield forecast (tonnes/ha) with uncertainty band
      - Multi-factor risk score (0-1) with decomposition
    """

    BASELINE_YIELDS = {
        "wheat": 3.5,
        "rice": 3.8,
        "sorghum": 1.2,
        "cotton": 0.5,
    }

    OPTIMAL_TEMP = {
        "wheat": (15, 25),
        "rice": (22, 32),
        "sorghum": (25, 35),
        "cotton": (20, 32),
    }

    def forecast(
        self,
        field_id: str,
        crop: str,
        ndvi_series: List[float],
        smc_series: List[float],
        weather: List[Dict],
        sowing_date: str,
        area_ha: float = 1.0,
        evi_series: List[float] = None,
        savi_series: List[float] = None,
        ndre_series: List[float] = None,
        gndvi_series: List[float] = None,
        lswi_series: List[float] = None,
        ndwi_series: List[float] = None,
        reci_series: List[float] = None,
        cig_series: List[float] = None,
        bsi_series: List[float] = None,
        lai_series: List[float] = None,
        anomaly_count: int = 0,
        irrigation_type: str = "rainfed",
    ) -> Dict:
        """Generate yield forecast using 25+ features."""
        baseline = self.BASELINE_YIELDS.get(crop, 2.5)
        crop_profile = CROP_PROFILES.get(crop, CROP_PROFILES["wheat"])
        optimal_temp = self.OPTIMAL_TEMP.get(crop, (20, 30))

        # -- Factor 1: Vegetation Vigor (weight: 0.25) --
        veg_scores = []
        if ndvi_series and len(ndvi_series) > 3:
            peak_ndvi = max(ndvi_series)
            optimal = crop_profile.get("optimal_ndvi_peak", 0.7)
            ndvi_score = min(peak_ndvi / optimal, 1.2)
            veg_scores.append(("ndvi", ndvi_score, 0.40))
        else:
            ndvi_score = 0.85
            peak_ndvi = 0.5
            veg_scores.append(("ndvi", ndvi_score, 0.40))

        if evi_series and len(evi_series) > 3:
            peak_evi = max(evi_series)
            evi_score = min(peak_evi / (crop_profile.get("optimal_ndvi_peak", 0.7) * 0.85), 1.2)
            veg_scores.append(("evi", evi_score, 0.30))
        elif ndvi_series:
            veg_scores.append(("evi", ndvi_score * 0.95, 0.30))

        if savi_series and len(savi_series) > 3:
            veg_scores.append(("savi", min(float(np.mean(savi_series)) / 0.5, 1.2), 0.15))
        if gndvi_series and len(gndvi_series) > 3:
            veg_scores.append(("gndvi", min(float(np.mean(gndvi_series)) / 0.55, 1.2), 0.15))

        total_w = sum(w for _, _, w in veg_scores)
        vegetation_score = sum(s * w for _, s, w in veg_scores) / total_w if total_w else 0.85

        # -- Factor 2: Water Availability (weight: 0.20) --
        water_scores = []
        if smc_series and len(smc_series) > 3:
            mean_smc = float(np.mean(smc_series))
            stress_days = sum(1 for s in smc_series if s < 18)
            smc_score = max(0.5, 1.0 - (stress_days / max(len(smc_series), 1)) * 0.4)
            water_scores.append(("smc", smc_score, 0.35))
        else:
            mean_smc = 25
            water_scores.append(("smc", 0.9, 0.35))

        if lswi_series and len(lswi_series) > 3:
            water_scores.append(("lswi", min(max(0.5 + float(np.mean(lswi_series)) * 2, 0.3), 1.2), 0.25))
        if ndwi_series and len(ndwi_series) > 3:
            water_scores.append(("ndwi", min(max(0.6 + float(np.mean(ndwi_series)) * 1.5, 0.3), 1.2), 0.20))

        rainfall_total = 0
        if weather and len(weather) > 7:
            rainfall_total = sum(w.get("rainfall_mm", 0) for w in weather)
            expected_rain = crop_profile.get("water_requirement_mm", 500) * (len(weather) / 120)
            rain_ratio = rainfall_total / max(expected_rain, 1)
            rain_score = 1.0 if 0.7 < rain_ratio < 1.3 else max(0.5, 1.0 - abs(rain_ratio - 1.0) * 0.5)
            water_scores.append(("rainfall", rain_score, 0.20))

        irr_bonus = {"drip": 0.08, "canal": 0.05, "tubewell": 0.06, "sprinkler": 0.07, "rainfed": 0.0}
        irr_adj = irr_bonus.get(irrigation_type, 0.0)
        total_w = sum(w for _, _, w in water_scores)
        water_score = (sum(s * w for _, s, w in water_scores) / total_w + irr_adj) if total_w else 0.9

        # -- Factor 3: Canopy Health (weight: 0.15) --
        health_scores = []
        if ndre_series and len(ndre_series) > 3:
            ndre_stability = 1.0 - float(np.std(ndre_series)) * 3
            ndre_mean = float(np.mean(ndre_series))
            ndre_health = min(ndre_mean / 0.35, 1.2) * 0.6 + max(ndre_stability, 0.3) * 0.4
            health_scores.append(("ndre", ndre_health, 0.35))
        if reci_series and len(reci_series) > 3:
            health_scores.append(("reci", min(float(np.mean(reci_series)) / 2.5, 1.2), 0.30))
        if cig_series and len(cig_series) > 3:
            health_scores.append(("cig", min(float(np.mean(cig_series)) / 1.5, 1.2), 0.20))
        if lai_series and len(lai_series) > 3:
            health_scores.append(("lai", min(max(lai_series) / 4.0, 1.2), 0.15))

        total_h = sum(w for _, _, w in health_scores)
        canopy_health_score = (sum(s * w for _, s, w in health_scores) / total_h) if total_h else 0.85

        # -- Factor 4: Weather (weight: 0.15) --
        gdd_total = 0
        vpd = 0
        if weather and len(weather) > 7:
            temps_max = [w.get("temp_max", 30) for w in weather]
            temps_min = [w.get("temp_min", 15) for w in weather]
            humidities = [w.get("humidity", 60) for w in weather]

            temp_means = [(mx + mn) / 2.0 for mx, mn in zip(temps_max, temps_min)]
            optimal_days = sum(1 for t in temp_means if optimal_temp[0] <= t <= optimal_temp[1])
            temp_score = optimal_days / max(len(temp_means), 1)

            heat_days = sum(1 for t in temps_max if t > 38)
            cold_days = sum(1 for t in temps_min if t < 5)
            stress_penalty = (heat_days + cold_days) / max(len(temps_max), 1) * 0.3

            gdd_total = sum(compute_gdd(mx, mn) for mx, mn in zip(temps_max, temps_min))

            mean_humidity = float(np.mean(humidities))
            vpd = compute_vpd(float(np.mean(temps_max)), float(np.mean(temps_min)), mean_humidity)
            vpd_score = 1.0 if vpd < 2.0 else max(0.6, 1.0 - (vpd - 2.0) * 0.2)

            gdd_per_day = gdd_total / max(len(weather), 1)
            weather_score = (temp_score * 0.35 + vpd_score * 0.25 +
                           (1.0 - stress_penalty) * 0.25 +
                           min(gdd_per_day / 20.0, 1.0) * 0.15)
        else:
            weather_score = 0.9

        # -- Factor 5: Soil Condition (weight: 0.10) --
        if bsi_series and len(bsi_series) > 3:
            soil_score = max(0.5, 1.0 - float(np.mean(bsi_series)) * 1.5)
        else:
            soil_score = 0.85

        # -- Factor 6: Temporal Dynamics (weight: 0.10) --
        temporal_score = 1.0
        if ndvi_series and len(ndvi_series) > 5:
            x = np.arange(len(ndvi_series))
            slope = float(np.polyfit(x, ndvi_series, 1)[0])
            temporal_score = min(1.2, max(0.5, 1.0 + slope * 4))
            cv = float(np.std(ndvi_series) / (np.mean(ndvi_series) + 0.001))
            consistency = max(0.5, 1.0 - cv * 0.5)
            temporal_score = temporal_score * 0.6 + consistency * 0.4

        anomaly_penalty = min(anomaly_count * 0.05, 0.25)

        # -- Weighted combination --
        factor_weights = {
            "vegetation": 0.25,
            "water": 0.20,
            "canopy_health": 0.15,
            "weather": 0.15,
            "soil": 0.10,
            "temporal": 0.10,
            "anomaly": 0.05,
        }
        yield_multiplier = (
            vegetation_score * factor_weights["vegetation"] +
            water_score * factor_weights["water"] +
            canopy_health_score * factor_weights["canopy_health"] +
            weather_score * factor_weights["weather"] +
            soil_score * factor_weights["soil"] +
            temporal_score * factor_weights["temporal"] +
            (1.0 - anomaly_penalty) * factor_weights["anomaly"]
        )
        predicted_yield = baseline * yield_multiplier

        # -- Uncertainty --
        available_series = sum(1 for s in [
            ndvi_series, evi_series, savi_series, ndre_series,
            gndvi_series, lswi_series, ndwi_series, reci_series,
            cig_series, bsi_series, lai_series, smc_series
        ] if s and len(s) > 3)

        data_points = sum(len(s) for s in [ndvi_series, smc_series] if s) + len(weather)
        base_uncertainty = baseline * 0.15
        coverage_factor = max(0.5, 1.0 - available_series / 12.0 * 0.4)
        data_factor = max(0.6, 1.0 - min(data_points, 100) / 100.0 * 0.3)
        uncertainty = min(base_uncertainty * coverage_factor * data_factor, baseline * 0.3)

        # -- Risk assessment --
        risk_factors = []
        risk_components = {}
        risk_score = 0.0

        if vegetation_score < 0.7:
            risk_factors.append("Low vegetation vigor across spectral indices")
            risk_components["vegetation_risk"] = round(0.7 - vegetation_score, 3)
            risk_score += 0.25
        if water_score < 0.75:
            risk_factors.append("Water stress detected (SMC + LSWI + NDWI)")
            risk_components["water_risk"] = round(0.75 - water_score, 3)
            risk_score += 0.22
        if canopy_health_score < 0.7:
            risk_factors.append("Canopy health declining (NDRE/RECI/CIG)")
            risk_components["canopy_risk"] = round(0.7 - canopy_health_score, 3)
            risk_score += 0.18
        if weather_score < 0.7:
            risk_factors.append("Adverse weather conditions")
            risk_components["weather_risk"] = round(0.7 - weather_score, 3)
            risk_score += 0.15
        if soil_score < 0.7:
            risk_factors.append("Poor soil cover / high bare soil exposure")
            risk_components["soil_risk"] = round(0.7 - soil_score, 3)
            risk_score += 0.10
        if temporal_score < 0.7:
            risk_factors.append("Declining growth trend")
            risk_components["temporal_risk"] = round(0.7 - temporal_score, 3)
            risk_score += 0.10
        if anomaly_count > 2:
            risk_factors.append(f"{anomaly_count} spectral anomalies detected")
            risk_score += anomaly_penalty
        if peak_ndvi < 0.4:
            risk_factors.append("Peak NDVI below critical threshold")
            risk_score += 0.10

        risk_score = min(risk_score, 1.0)
        risk_level = "low" if risk_score < 0.25 else (
            "medium" if risk_score < 0.5 else (
                "high" if risk_score < 0.75 else "critical"))

        return {
            "field_id": field_id,
            "crop": crop,
            "yield_tonnes_ha": round(predicted_yield, 2),
            "total_yield_tonnes": round(predicted_yield * area_ha, 2),
            "uncertainty": round(uncertainty, 2),
            "yield_range": {
                "low": round(max(predicted_yield - uncertainty, 0), 2),
                "high": round(predicted_yield + uncertainty, 2),
            },
            "risk_score": round(risk_score, 2),
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "risk_components": risk_components,
            "risk_note": "; ".join(risk_factors) if risk_factors else "No significant risks detected",
            "factors": {
                "vegetation_score": round(vegetation_score, 3),
                "water_score": round(water_score, 3),
                "canopy_health_score": round(canopy_health_score, 3),
                "weather_score": round(weather_score, 3),
                "soil_score": round(soil_score, 3),
                "temporal_score": round(temporal_score, 3),
                "anomaly_penalty": round(anomaly_penalty, 3),
                "combined_multiplier": round(yield_multiplier, 3),
            },
            "factor_weights": factor_weights,
            "indices_available": available_series,
            "total_data_points": data_points,
            "baseline_yield": baseline,
            "model_version": "v2.0-multi-factor",
            "forecast_date": datetime.utcnow().strftime("%Y-%m-%d"),
        }


# ================================================================
#  ONNX Export Skeleton (for production deployment)
# ================================================================

def generate_model_export_script() -> str:
    """
    Generate the PyTorch ONNX export + quantization script
    for deployment on AMD Ryzen AI NPU.
    v2.0: Multi-input architecture with spectral + auxiliary branches.
    """
    return """
# Krishi-Sathi v2.0: Multi-Parameter Model Export Script
# PyTorch -> ONNX -> INT8 PTQ -> ONNX Runtime (Ryzen AI NPU)

import torch
import torch.nn as nn
import numpy as np

# === 1. Multi-Input Model Definition ===
class SoilMoistureCNN_v2(nn.Module):
    \"\"\"
    Multi-branch architecture for soil moisture estimation:
      Branch A: 2D Conv on Sentinel-2 multispectral patches (10 bands)
      Branch B: Temporal encoder on spectral index time series (12 indices)
      Branch C: Auxiliary features (meteorological + agronomic, 12 features)
    \"\"\"
    def __init__(self, n_bands=10, time_steps=5, patch_size=32,
                 n_indices=12, n_aux=12):
        super().__init__()
        self.spatial = nn.Sequential(
            nn.Conv2d(n_bands, 48, 3, padding=1), nn.BatchNorm2d(48), nn.GELU(),
            nn.Conv2d(48, 96, 3, padding=1), nn.BatchNorm2d(96), nn.GELU(),
            nn.Conv2d(96, 128, 3, padding=1), nn.BatchNorm2d(128), nn.GELU(),
            nn.AdaptiveAvgPool2d(4), nn.Flatten(),
        )
        self.spatial_temporal = nn.GRU(input_size=2048, hidden_size=256,
            num_layers=2, batch_first=True, dropout=0.2)
        self.index_encoder = nn.Sequential(
            nn.Conv1d(n_indices, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64), nn.GELU(),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128), nn.GELU(),
        )
        self.index_lstm = nn.LSTM(input_size=128, hidden_size=128,
            num_layers=2, batch_first=True, dropout=0.2)
        self.aux_encoder = nn.Sequential(
            nn.Linear(n_aux, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 64), nn.GELU(),
        )
        self.fusion = nn.Sequential(
            nn.Linear(448, 256), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(256, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 1), nn.Sigmoid(),
        )
        self.smc_scale = 58.0

    def forward(self, spectral_patches, index_series, aux_features):
        B, T, C, H, W = spectral_patches.shape
        spatial_feats = [self.spatial(spectral_patches[:, t]) for t in range(T)]
        spatial_seq = torch.stack(spatial_feats, dim=1)
        spatial_out, _ = self.spatial_temporal(spatial_seq)
        spatial_repr = spatial_out[:, -1, :]
        idx_conv = self.index_encoder(index_series)
        idx_seq = idx_conv.permute(0, 2, 1)
        idx_out, _ = self.index_lstm(idx_seq)
        idx_repr = idx_out[:, -1, :]
        aux_repr = self.aux_encoder(aux_features)
        combined = torch.cat([spatial_repr, idx_repr, aux_repr], dim=1)
        return self.fusion(combined) * self.smc_scale

INDEX_LIST = [
    "NDVI", "NDWI", "EVI", "SAVI", "MSAVI", "NDRE",
    "GNDVI", "LSWI", "NBR", "BSI", "CIG", "RECI",
]
AUX_FEATURES = [
    "rainfall_7d", "rainfall_14d", "rainfall_30d",
    "et0_7d", "temp_mean", "humidity", "wind_speed", "vpd",
    "crop_kc", "days_after_sowing", "lai", "fcover",
]

def export_to_onnx(model, save_path="krishi_sathi_smc_v2.onnx"):
    model.eval()
    torch.onnx.export(
        model,
        (torch.randn(1,5,10,32,32), torch.randn(1,12,5), torch.randn(1,12)),
        save_path,
        input_names=["spectral_patches", "index_series", "aux_features"],
        output_names=["soil_moisture"],
        dynamic_axes={k: {0: "batch"} for k in
            ["spectral_patches","index_series","aux_features","soil_moisture"]},
        opset_version=17, do_constant_folding=True,
    )

if __name__ == "__main__":
    model = SoilMoistureCNN_v2()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {n_params:,}")
    export_to_onnx(model)
    print("Multi-parameter model pipeline ready for Ryzen AI deployment")
"""


# ================================================================
#  Model Instances (singleton-like for the app)
# ================================================================

smc_model = SoilMoistureCNN()
pest_detector = PestAnomalyDetector()
yield_forecaster = YieldForecaster()
