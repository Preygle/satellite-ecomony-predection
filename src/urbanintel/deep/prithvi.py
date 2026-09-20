from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

# Prithvi-EO-2.0, IBM and NASA, Apache-2.0. Pretrained as a masked
# autoencoder on 4.2 million Harmonized Landsat and Sentinel-2 time series at
# 30 m, over the six bands this project exports.
REPO = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL"
WEIGHTS = "Prithvi_EO_V2_300M_TL.pt"
CONFIG = "config.json"

# The band order the model was pretrained on: blue, green, red, narrow near
# infrared, shortwave infrared 1, shortwave infrared 2.
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07"]


def _sincos_1d(dim: int, positions: np.ndarray) -> np.ndarray:
    omega = 1.0 / 10000 ** (np.arange(dim // 2, dtype="float64") / (dim / 2.0))
    out = positions.reshape(-1)[:, None] * omega[None, :]
    return np.concatenate([np.sin(out), np.cos(out)], axis=1)


def sincos_3d(embed_dim: int, grid: tuple[int, int, int]) -> np.ndarray:
    """The fixed three-dimensional position encoding Prithvi was pretrained with.

    Positions are not learned, so regenerating them here reproduces the
    pretraining encoding exactly at any tile size or number of dates — which
    is what lets a 300M model pretrained on 224-pixel, four-date samples be
    used on our tiles without retraining anything.
    """
    if embed_dim % 16:
        raise ValueError("embedding dimension must be a multiple of 16")
    t_size, h_size, w_size = grid
    w_dim = embed_dim // 16 * 6
    h_dim = embed_dim // 16 * 6
    t_dim = embed_dim // 16 * 4

    w_pos = _sincos_1d(w_dim, np.arange(w_size, dtype="float32"))
    h_pos = _sincos_1d(h_dim, np.arange(h_size, dtype="float32"))
    t_pos = _sincos_1d(t_dim, np.arange(t_size, dtype="float32"))

    w_pos = np.tile(w_pos[None, None, :, :], (t_size, h_size, 1, 1))
    h_pos = np.tile(h_pos[None, :, None, :], (t_size, 1, w_size, 1))
    t_pos = np.tile(t_pos[:, None, None, :], (1, h_size, w_size, 1))
    pos = np.concatenate([t_pos, h_pos, w_pos], axis=-1)
    return pos.reshape(t_size * h_size * w_size, embed_dim).astype("float32")


def fetch(repo: str = REPO) -> tuple[Path, dict]:
    """Download the published weights and configuration, or use the cache."""
    from huggingface_hub import hf_hub_download

    weights = Path(hf_hub_download(repo, WEIGHTS))
    cfg = json.loads(Path(hf_hub_download(repo, CONFIG)).read_text(encoding="utf-8"))
    return weights, cfg


def band_statistics(cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Prithvi's own per-band mean and standard deviation, in reflectance units.

    The published values are in the scaled integers the Harmonized Landsat and
    Sentinel-2 product uses, which are reflectance times 10,000. Our Landsat
    export is plain reflectance, so both are divided by 10,000 rather than
    multiplying every tile.
    """
    p = cfg.get("pretrained_cfg", cfg)
    mean = np.asarray(p["mean"], dtype="float32") / 10_000.0
    std = np.asarray(p["std"], dtype="float32") / 10_000.0
    return mean, std


class PrithviEncoder(nn.Module):
    """The Prithvi-EO-2.0 vision transformer, loading the published weights.

    A faithful reconstruction of the published encoder rather than a wrapper:
    the patch embedding, the twenty-four transformer blocks and the final
    normalisation are built here and the official tensors are loaded into
    them. That removes a heavy dependency, and it means the loader reports
    exactly how many tensors matched instead of failing quietly.

    The temporal and location embeddings of the "TL" variant are not used.
    Pretraining dropped that metadata at random precisely so the model would
    work without it, and our tiles carry no single acquisition date.
    """

    def __init__(self, *, n_dates: int = 1, tile: int = 224, freeze: bool = True,
                 repo: str = REPO, checkpoint: Path | None = None):
        super().__init__()
        from timm.models.vision_transformer import Block

        weights, cfg = (checkpoint, json.loads(
            (Path(checkpoint).parent / CONFIG).read_text(encoding="utf-8"))) \
            if checkpoint else fetch(repo)
        p = cfg.get("pretrained_cfg", cfg)
        self.embed_dim = int(p.get("embed_dim", 1024))
        self.depth = int(p.get("depth", 24))
        self.n_heads = int(p.get("num_heads", 16))
        patch = p.get("patch_size", [1, 16, 16])
        self.patch_t, self.patch_h, self.patch_w = (int(x) for x in patch)
        self.in_chans = int(p.get("in_chans", 6))
        self.mean, self.std = band_statistics(cfg)

        self.patch_embed = nn.Conv3d(
            self.in_chans, self.embed_dim,
            kernel_size=(self.patch_t, self.patch_h, self.patch_w),
            stride=(self.patch_t, self.patch_h, self.patch_w))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, self.embed_dim))
        self.blocks = nn.ModuleList([
            Block(self.embed_dim, self.n_heads, mlp_ratio=float(p.get("mlp_ratio", 4)),
                  qkv_bias=True, norm_layer=nn.LayerNorm) for _ in range(self.depth)])
        self.norm = nn.LayerNorm(self.embed_dim)

        self.loaded = self._load(weights)
        self.out_channels = [self.embed_dim]
        self.expects_time_axis = True
        self.n_dates = n_dates
        if freeze:
            for prm in self.parameters():
                prm.requires_grad = False

    def _load(self, weights: Path) -> dict:
        blob = torch.load(weights, map_location="cpu", weights_only=False)
        state = blob.get("model", blob) if isinstance(blob, dict) else blob
        clean: dict[str, torch.Tensor] = {}
        for k, v in state.items():
            if not isinstance(v, torch.Tensor):
                continue
            key = k[len("encoder."):] if k.startswith("encoder.") else k
            if key.startswith("decoder") or key.startswith("mask_token"):
                continue
            clean[key] = v
        report = self.load_state_dict(clean, strict=False)
        matched = len(set(clean) & set(self.state_dict()))
        if matched < 100:
            raise RuntimeError(
                f"only {matched} of {len(self.state_dict())} tensors matched the "
                f"published checkpoint; the architecture and the weights disagree")
        return {"tensors_in_checkpoint": len(clean), "tensors_loaded": matched,
                "missing": len(report.missing_keys),
                "unused_in_checkpoint": len(report.unexpected_keys)}

    @staticmethod
    def available() -> bool:
        import importlib.util

        return all(importlib.util.find_spec(m) for m in ("timm", "huggingface_hub"))

    def forward(self, x):                                # (B, T, C, H, W)
        b, t, c, h, w = x.shape
        z = self.patch_embed(x.permute(0, 2, 1, 3, 4))   # (B, D, t', h', w')
        _, d, tt, hh, ww = z.shape
        tokens = z.flatten(2).transpose(1, 2)            # (B, N, D)
        pos = torch.from_numpy(sincos_3d(d, (tt, hh, ww))).to(tokens.device)
        tokens = tokens + pos[None, :, :]
        cls = self.cls_token.expand(b, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        for blk in self.blocks:
            tokens = blk(tokens)
        tokens = self.norm(tokens)[:, 1:, :]             # drop the class token
        feat = tokens.transpose(1, 2).reshape(b, d, tt, hh, ww).mean(dim=2)
        return [feat]                                    # (B, D, h/16, w/16)
