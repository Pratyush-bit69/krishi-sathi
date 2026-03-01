"""
Krishi-Sathi — ML Models Module
Soil Moisture CNN, Pest Anomaly Detection, Yield Forecasting.

In production these would be trained PyTorch models exported to ONNX.
For the demo, we use analytical/statistical models that produce
realistic outputs calibrated to each agro-climatic zone.
"""

import math
import hashlib
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from config import CROP_PROFILES, PILOT_SITES, SMC_MODEL, ONNX_CONFIG


# ═══════════════════════════════════════════════════════════════
#  Soil Moisture Estimator (CNN proxy)
# ═══════════════════════════════════════════════════════════════

class SoilMoistureCNN:
    """
    Proxy for a CNN model that estimates soil moisture content (SMC)
    from Sentinel-2 multispectral bands.
    
    In production:
      - Architecture: 2D Conv + Temporal Encoder (TCN)
      - Input: 5 bands (B04, B08, B8A, B11, B12) × 5 time steps × 32×32 patch
      - Output: SMC in volumetric %
      - Training: PyTorch → ONNX export → INT8 PTQ → ONNX Runtime (Ryzen AI NPU)
    
    Demo mode uses a physics-informed analytical model:
      SMC ≈ f(NDWI, NDVI, BSI, recent_rainfall, ET0, crop_stage)
    """

    def __init__(self):
        self.model_version = "v1.0-analytical"
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

    def predict(
        self,
        ndvi: float, ndwi: float, bsi: float,
        rainfall_7d: float = 0.0, et0_7d: float = 35.0,
        agro_zone: str = "Indo-Gangetic Plains",
        crop_kc: float = 0.7,
    ) -> Dict:
        """
        Predict soil moisture content from spectral indices & meteorological data.
        Returns SMC (%), confidence, and component breakdown.
        """
        # Base SMC from NDWI (primary indicator of surface moisture)
        smc_ndwi = 25 + ndwi * 40  # NDWI -0.3→13%, 0→25%, 0.3→37%

        # Vegetation correction (dense veg can mask soil signal)
        veg_correction = ndvi * 5  # Vegetation retains moisture

        # Bare soil index correction (bare soil → different moisture behavior)
        bsi_correction = -bsi * 8

        # Rainfall contribution (recent rain increases SMC)
        rain_effect = min(rainfall_7d * 0.4, 15)

        # ET0 depletion (more evapotranspiration → drier soil)
        et_depletion = -et0_7d * 0.15

        # Crop water demand
        crop_effect = -crop_kc * 3

        # Zone offset
        zone_adj = self.zone_offsets.get(agro_zone, 0)

        # Combine
        smc = smc_ndwi + veg_correction + bsi_correction + rain_effect + et_depletion + crop_effect + zone_adj
        smc = max(5, min(smc, 55))  # Clamp to realistic range

        # Confidence inversely proportional to uncertainty factors
        confidence = 0.85 - abs(ndvi - 0.4) * 0.2 - abs(ndwi) * 0.1
        confidence = max(0.4, min(confidence, 0.95))

        return {
            "smc_percent": round(smc, 1),
            "confidence": round(confidence, 3),
            "category": self._categorize_smc(smc),
            "components": {
                "ndwi_base": round(smc_ndwi, 1),
                "vegetation": round(veg_correction, 1),
                "bare_soil": round(bsi_correction, 1),
                "rainfall": round(rain_effect, 1),
                "evapotranspiration": round(et_depletion, 1),
                "crop_demand": round(crop_effect, 1),
                "zone_adj": round(zone_adj, 1),
            },
            "model_version": self.model_version,
        }

    def _categorize_smc(self, smc: float) -> str:
        if smc < 15:
            return "very_dry"
        elif smc < 22:
            return "dry"
        elif smc < 32:
            return "adequate"
        elif smc < 42:
            return "wet"
        else:
            return "saturated"

    def batch_predict(self, fields_data: List[Dict]) -> List[Dict]:
        """Run predictions for multiple fields."""
        results = []
        for fd in fields_data:
            pred = self.predict(
                ndvi=fd.get("ndvi", 0.4),
                ndwi=fd.get("ndwi", 0.0),
                bsi=fd.get("bsi", 0.1),
                rainfall_7d=fd.get("rainfall_7d", 0),
                et0_7d=fd.get("et0_7d", 35),
                agro_zone=fd.get("agro_zone", "Indo-Gangetic Plains"),
                crop_kc=fd.get("crop_kc", 0.7),
            )
            pred["field_id"] = fd.get("field_id")
            results.append(pred)
        return results

    def get_onnx_config(self) -> Dict:
        """Return ONNX export configuration for this model."""
        return {
            "model_name": "krishi_sathi_smc_cnn",
            "input_shape": [1, SMC_MODEL["time_steps"], len(SMC_MODEL["input_bands"]),
                           SMC_MODEL["patch_size"], SMC_MODEL["patch_size"]],
            "output_shape": [1, 1],
            "opset": ONNX_CONFIG["opset_version"],
            "quantization": ONNX_CONFIG["quantization"],
            "execution_provider": ONNX_CONFIG["execution_provider"],
            "target_device": ONNX_CONFIG["target_device"],
        }


# ═══════════════════════════════════════════════════════════════
#  Pest / Anomaly Detection (unsupervised spectral change detector)
# ═══════════════════════════════════════════════════════════════

class PestAnomalyDetector:
    """
    Unsupervised anomaly detection on spectral index time series.
    
    Approach:
      1. Compute expected NDVI from crop phenology model
      2. Flag deviations > 2σ from expected trajectory
      3. Cross-check with RedEdge/SWIR anomalies
      4. Score severity based on spatial extent and magnitude
    
    In production: trained U-Net or attention model on labeled pest images.
    """

    def __init__(self):
        self.ndvi_drop_threshold = 0.08  # Flag if NDVI drops > 8% in 10 days
        self.reci_drop_threshold = 0.5   # RedEdge Chlorophyll Index anomaly
        self.min_observations = 3        # Need at least 3 observations

    def detect_anomalies(
        self,
        timeseries: List[Dict],
        crop: str = "wheat",
        sowing_date: str = "2025-11-01"
    ) -> List[Dict]:
        """
        Analyze a field's spectral time series for pest/disease anomalies.
        """
        if len(timeseries) < self.min_observations:
            return []

        anomalies = []
        sowing = datetime.strptime(sowing_date, "%Y-%m-%d")
        crop_profile = CROP_PROFILES.get(crop, CROP_PROFILES["wheat"])

        # Compute rolling statistics
        ndvi_values = [t["ndvi"] for t in timeseries if t.get("ndvi") is not None]
        if len(ndvi_values) < self.min_observations:
            return []

        ndvi_mean = np.mean(ndvi_values)
        ndvi_std = np.std(ndvi_values) + 0.001

        for i in range(2, len(timeseries)):
            curr = timeseries[i]
            prev = timeseries[i - 1]

            curr_date = datetime.strptime(curr["date"], "%Y-%m-%d")
            days_after_sowing = (curr_date - sowing).days

            # Get expected NDVI for this growth stage
            expected_ndvi = self._expected_ndvi(days_after_sowing, crop_profile)

            # Check 1: Sudden NDVI drop
            ndvi_drop = prev.get("ndvi", 0) - curr.get("ndvi", 0)
            if ndvi_drop > self.ndvi_drop_threshold:
                severity = "high" if ndvi_drop > 0.15 else ("medium" if ndvi_drop > 0.10 else "low")
                anomalies.append({
                    "date": curr["date"],
                    "type": "ndvi_drop",
                    "severity": severity,
                    "ndvi_drop": round(ndvi_drop, 4),
                    "expected_ndvi": round(expected_ndvi, 4),
                    "actual_ndvi": curr.get("ndvi"),
                    "description": f"NDVI dropped {ndvi_drop:.1%} — possible pest damage, disease, or water stress",
                    "zone": self._estimate_affected_zone(curr),
                })

            # Check 2: NDVI significantly below expected for growth stage
            if curr.get("ndvi") is not None and expected_ndvi > 0:
                deviation = expected_ndvi - curr["ndvi"]
                if deviation > 0.12:
                    anomalies.append({
                        "date": curr["date"],
                        "type": "growth_lag",
                        "severity": "medium" if deviation < 0.2 else "high",
                        "ndvi_drop": round(deviation, 4),
                        "expected_ndvi": round(expected_ndvi, 4),
                        "actual_ndvi": curr.get("ndvi"),
                        "description": f"Crop growth {deviation:.1%} below expected for day {days_after_sowing}",
                        "zone": "full_field",
                    })

            # Check 3: RECI anomaly (chlorophyll stress)
            if i >= 2 and curr.get("reci") is not None and prev.get("reci") is not None:
                reci_drop = prev["reci"] - curr["reci"]
                if reci_drop > self.reci_drop_threshold:
                    anomalies.append({
                        "date": curr["date"],
                        "type": "chlorophyll_stress",
                        "severity": "medium",
                        "ndvi_drop": round(reci_drop, 4),
                        "description": f"Chlorophyll index dropped {reci_drop:.2f} — nutrient deficiency or disease",
                        "zone": self._estimate_affected_zone(curr),
                    })

        # Deduplicate by date + type
        seen = set()
        unique = []
        for a in anomalies:
            key = f"{a['date']}_{a['type']}"
            if key not in seen:
                seen.add(key)
                unique.append(a)

        return unique

    def _expected_ndvi(self, days_after_sowing: int, crop_profile: Dict) -> float:
        """Get expected NDVI based on crop growth stage."""
        peak_ndvi = crop_profile.get("optimal_ndvi_peak", 0.7)

        for stage_name, stage in crop_profile["growth_stages"].items():
            d_start, d_end = stage["days"]
            if d_start <= days_after_sowing <= d_end:
                progress = (days_after_sowing - d_start) / max(d_end - d_start, 1)
                kc = stage["kc"]
                return 0.15 + kc * (peak_ndvi - 0.15) * (0.7 + 0.3 * progress)

        return 0.2  # Post-harvest or pre-sowing default

    def _estimate_affected_zone(self, observation: Dict) -> str:
        """Estimate which zone of the field is affected."""
        # In production, this would use spatial analysis of band patches
        ndvi = observation.get("ndvi", 0.5)
        if ndvi < 0.2:
            return "full_field"
        elif ndvi < 0.35:
            return "east_section"
        else:
            return "localized_patch"


# ═══════════════════════════════════════════════════════════════
#  Yield Forecasting Model
# ═══════════════════════════════════════════════════════════════

class YieldForecaster:
    """
    Multi-modal yield forecasting model.
    
    Inputs:
      - NDVI time series (satellite)
      - Soil moisture history
      - Weather data (temperature, rainfall, ET0)
      - Crop profile & growth stage
    
    Output:
      - Yield forecast (tonnes/ha) with uncertainty band
      - Risk score (0-1) and risk notes
    
    In production: LSTM/Transformer on multi-season labeled yield data.
    """

    # Baseline yields by crop (tonnes/ha, India averages)
    BASELINE_YIELDS = {
        "wheat": 3.5,
        "rice": 3.8,
        "sorghum": 1.2,
        "cotton": 0.5,  # lint yield
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
    ) -> Dict:
        """Generate yield forecast with uncertainty and risk assessment."""
        
        baseline = self.BASELINE_YIELDS.get(crop, 2.5)
        crop_profile = CROP_PROFILES.get(crop, CROP_PROFILES["wheat"])
        
        # Factor 1: NDVI vigor score (how well did the crop grow?)
        if ndvi_series and len(ndvi_series) > 3:
            peak_ndvi = max(ndvi_series)
            mean_ndvi = np.mean(ndvi_series[-10:]) if len(ndvi_series) >= 10 else np.mean(ndvi_series)
            optimal = crop_profile.get("optimal_ndvi_peak", 0.7)
            ndvi_score = min(peak_ndvi / optimal, 1.2)  # Can exceed 1 for exceptionally good growth
        else:
            ndvi_score = 0.85
            peak_ndvi = 0.5

        # Factor 2: Water stress score
        if smc_series and len(smc_series) > 3:
            mean_smc = np.mean(smc_series)
            stress_days = sum(1 for s in smc_series if s < 18)
            water_score = 1.0 - (stress_days / max(len(smc_series), 1)) * 0.4
            water_score = max(water_score, 0.5)
        else:
            water_score = 0.9
            mean_smc = 25

        # Factor 3: Weather score
        if weather and len(weather) > 7:
            temps = [w.get("temp_max", 30) for w in weather]
            rainfall_total = sum(w.get("rainfall_mm", 0) for w in weather)
            
            # Temperature stress
            heat_days = sum(1 for t in temps if t > 38)
            cold_days = sum(1 for t in temps if t < 5)
            temp_score = 1.0 - (heat_days + cold_days) / max(len(temps), 1) * 0.3
            
            # Rainfall adequacy
            expected_rain = crop_profile.get("water_requirement_mm", 500) * (len(weather) / 120)
            rain_ratio = min(rainfall_total / max(expected_rain, 1), 1.5)
            rain_score = 1.0 if 0.7 < rain_ratio < 1.3 else 0.8
            
            weather_score = (temp_score + rain_score) / 2
        else:
            weather_score = 0.9
            rainfall_total = 0

        # Combine factors
        yield_multiplier = ndvi_score * 0.45 + water_score * 0.30 + weather_score * 0.25
        predicted_yield = baseline * yield_multiplier

        # Uncertainty (wider when fewer data points)
        data_points = len(ndvi_series) + len(smc_series) + len(weather)
        base_uncertainty = baseline * 0.15
        data_uncertainty = base_uncertainty * max(1.0, 30 / max(data_points, 1))
        uncertainty = min(data_uncertainty, baseline * 0.3)

        # Risk assessment
        risk_factors = []
        risk_score = 0.0

        if ndvi_score < 0.7:
            risk_factors.append("Low vegetation vigor")
            risk_score += 0.3

        if water_score < 0.75:
            risk_factors.append("Water stress detected")
            risk_score += 0.25

        if weather_score < 0.8:
            risk_factors.append("Adverse weather conditions")
            risk_score += 0.2

        if peak_ndvi < 0.4:
            risk_factors.append("Peak NDVI below threshold")
            risk_score += 0.15

        risk_score = min(risk_score, 1.0)
        risk_level = "low" if risk_score < 0.3 else ("medium" if risk_score < 0.6 else "high")

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
            "risk_note": "; ".join(risk_factors) if risk_factors else "No significant risks detected",
            "factors": {
                "ndvi_score": round(ndvi_score, 3),
                "water_score": round(water_score, 3),
                "weather_score": round(weather_score, 3),
                "combined_multiplier": round(yield_multiplier, 3),
            },
            "baseline_yield": baseline,
            "model_version": "v1.0-analytical",
            "forecast_date": datetime.utcnow().strftime("%Y-%m-%d"),
        }


# ═══════════════════════════════════════════════════════════════
#  ONNX Export Skeleton (for production deployment)
# ═══════════════════════════════════════════════════════════════

def generate_model_export_script() -> str:
    """
    Generate the PyTorch → ONNX export + quantization script
    for deployment on AMD Ryzen AI NPU.
    """
    return '''
# ─── Krishi-Sathi: Model Export Script ───
# PyTorch → ONNX → INT8 PTQ → ONNX Runtime (Ryzen AI NPU)

import torch
import torch.nn as nn
import numpy as np

# ═══ 1. Model Definition ═══
class SoilMoistureCNN(nn.Module):
    """
    2D Conv + Temporal Encoder for soil moisture estimation
    from Sentinel-2 multispectral patches.
    """
    def __init__(self, in_channels=5, time_steps=5, patch_size=32):
        super().__init__()
        
        # Spatial feature extractor (per time step)
        self.spatial = nn.Sequential(
            nn.Conv2d(in_channels, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(4),
            nn.Flatten(),
        )
        
        # Temporal encoder (processes spatial features across time)
        spatial_out = 64 * 4 * 4  # 1024
        self.temporal = nn.GRU(
            input_size=spatial_out,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            dropout=0.2,
        )
        
        # Regression head
        self.head = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
            nn.Sigmoid(),  # Output 0-1, scale to 0-55% SMC
        )
        
        self.smc_scale = 55.0  # Max SMC %

    def forward(self, x):
        # x: [batch, time_steps, channels, H, W]
        B, T, C, H, W = x.shape
        
        # Process each time step
        spatial_feats = []
        for t in range(T):
            feat = self.spatial(x[:, t])  # [B, 1024]
            spatial_feats.append(feat)
        
        # Stack temporal features
        temporal_in = torch.stack(spatial_feats, dim=1)  # [B, T, 1024]
        
        # Temporal encoding
        temporal_out, _ = self.temporal(temporal_in)  # [B, T, 128]
        last_hidden = temporal_out[:, -1, :]  # [B, 128]
        
        # Predict SMC
        smc_normalized = self.head(last_hidden)  # [B, 1]
        return smc_normalized * self.smc_scale


# ═══ 2. ONNX Export ═══
def export_to_onnx(model, save_path="krishi_sathi_smc.onnx"):
    model.eval()
    dummy = torch.randn(1, 5, 5, 32, 32)  # [batch, time, channels, H, W]
    
    torch.onnx.export(
        model, dummy, save_path,
        input_names=["spectral_input"],
        output_names=["soil_moisture"],
        dynamic_axes={"spectral_input": {0: "batch"}, "soil_moisture": {0: "batch"}},
        opset_version=17,
        do_constant_folding=True,
    )
    print(f"Exported to {save_path}")


# ═══ 3. INT8 Post-Training Quantization ═══
def quantize_model(onnx_path, calibration_data, output_path="krishi_sathi_smc_int8.onnx"):
    """
    Quantize using ONNX Runtime quantization tools.
    Calibration data: representative samples from each agro-climatic zone.
    """
    from onnxruntime.quantization import quantize_static, CalibrationDataReader
    
    class ZoneCalibrationReader(CalibrationDataReader):
        def __init__(self, data):
            self.data = iter(data)
        
        def get_next(self):
            try:
                return {"spectral_input": next(self.data)}
            except StopIteration:
                return None
    
    reader = ZoneCalibrationReader(calibration_data)
    quantize_static(onnx_path, output_path, reader)
    print(f"Quantized model saved to {output_path}")


# ═══ 4. ONNX Runtime Inference with Ryzen AI NPU ═══
def run_inference(onnx_path, input_data):
    """
    Run inference using ONNX Runtime with hardware execution provider.
    Falls back to CPU if NPU is not available.
    """
    import onnxruntime as ort
    
    providers = [
        ("VitisAIExecutionProvider", {"config_file": "vaip_config.json"}),
        "CPUExecutionProvider",
    ]
    
    session = ort.InferenceSession(onnx_path, providers=providers)
    active_provider = session.get_providers()[0]
    print(f"Running on: {active_provider}")
    
    result = session.run(None, {"spectral_input": input_data})
    return result[0]  # Soil moisture prediction


if __name__ == "__main__":
    # Create and export model
    model = SoilMoistureCNN()
    export_to_onnx(model)
    print("Model pipeline ready for Ryzen AI deployment")
'''


# ═══════════════════════════════════════════════════════════════
#  Model Instances (singleton-like for the app)
# ═══════════════════════════════════════════════════════════════

# Global model instances
smc_model = SoilMoistureCNN()
pest_detector = PestAnomalyDetector()
yield_forecaster = YieldForecaster()
