from __future__ import annotations

import numpy as np

from .stacks import TemporalStack
from .tiles import tile_origins
from .train import ImageModel, resolve_device


def encoder_surface(model: ImageModel, stack: TemporalStack, *, tile: int | None = None,
                    stride: int | None = None, batch_size: int = 8,
                    device: str | None = None) -> np.ndarray:
    """The encoder's deepest feature map, upsampled back to the analysis grid.

    These are the learned descriptors of each neighbourhood — what the network
    noticed about the land around a cell. Handing them to the tabular model is
    the cheap way to combine a deep view of the imagery with drivers that
    cannot be seen from space, such as road class or population.
    """
    import torch
    import torch.nn.functional as F

    dev = resolve_device(device or model.config.device)
    net = model.net.to(dev)
    net.eval()

    data = model.normaliser.apply(stack).data
    h, w = stack.shape
    size = tile or model.tile_size
    step = stride or max(1, size // 2)
    origins = tile_origins((h, w), size, step)

    total = count = None
    with torch.no_grad():
        for s in range(0, len(origins), batch_size):
            chunk = origins[s:s + batch_size]
            xb = np.stack([data[:, :, r:r + size, c:c + size] for r, c in chunk])
            x = torch.from_numpy(xb).to(dev)
            b, t, c_, hh, ww = x.shape
            z = x if net.encoder.expects_time_axis else x.reshape(b, t * c_, hh, ww)
            deep = net.encoder(z)[-1]
            deep = F.interpolate(deep, size=(size, size), mode="bilinear",
                                 align_corners=False).cpu().numpy()
            if total is None:
                total = np.zeros((deep.shape[1], h, w), dtype="float32")
                count = np.zeros((h, w), dtype="float32")
            for (r, c), f in zip(chunk, deep):
                total[:, r:r + size, c:c + size] += f
                count[r:r + size, c:c + size] += 1.0
    return total / np.maximum(count, 1.0)[None, :, :]


def pca_components(features: np.ndarray, *, k: int = 16, seed: int = 0,
                   max_cells: int = 40_000) -> tuple[np.ndarray, dict]:
    """Reduce the feature map to `k` components, fitted on a sample of cells.

    A 128-channel feature map would swamp eight drivers and make the boosted
    model impossible to explain. Sixteen components keep most of the variation
    while leaving the driver contributions readable in the SHAP table.
    """
    from sklearn.decomposition import PCA

    d, h, w = features.shape
    flat = features.reshape(d, h * w).T
    rng = np.random.default_rng(seed)
    idx = (rng.choice(h * w, size=max_cells, replace=False) if h * w > max_cells
           else np.arange(h * w))
    pca = PCA(n_components=min(k, d), random_state=seed).fit(flat[idx])
    comps = pca.transform(flat).T.reshape(-1, h, w).astype("float32")
    info = {
        "n_components": int(comps.shape[0]),
        "explained_variance_ratio": [round(float(v), 4) for v in pca.explained_variance_ratio_],
        "cumulative_variance": round(float(pca.explained_variance_ratio_.sum()), 4),
        "fitted_on_cells": int(len(idx)),
    }
    return comps, info


def append_components(X: np.ndarray, names: list[str], components: np.ndarray,
                      eligible: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Add the image components to a design matrix of eligible cells."""
    rows = eligible.ravel()
    extra = components.reshape(components.shape[0], -1)[:, rows].T
    out_names = list(names) + [f"image_pc{i + 1:02d}" for i in range(components.shape[0])]
    return np.hstack([X, extra.astype(X.dtype)]), out_names
