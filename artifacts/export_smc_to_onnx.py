# Krishi-Sathi v2.0: Multi-Parameter Model Export Script
# PyTorch -> ONNX -> INT8 PTQ -> ONNX Runtime (Ryzen AI NPU)

import torch
import torch.nn as nn
import numpy as np

# === 1. Multi-Input Model Definition ===
class SoilMoistureCNN_v2(nn.Module):
    """
    Multi-branch architecture for soil moisture estimation:
      Branch A: 2D Conv on Sentinel-2 multispectral patches (10 bands)
      Branch B: Temporal encoder on spectral index time series (12 indices)
      Branch C: Auxiliary features (meteorological + agronomic, 12 features)
    """
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
