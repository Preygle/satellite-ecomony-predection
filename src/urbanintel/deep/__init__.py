from __future__ import annotations

# Submodules are imported on demand: `nets` and `train` need PyTorch, `boost`
# needs XGBoost, and neither belongs in the main pipeline's dependency set.
__all__ = ["stacks", "tiles", "nets", "train", "embed", "boost", "ensemble",
           "anomaly", "analytics"]
