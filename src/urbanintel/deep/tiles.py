from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..aoi import AnalysisFrame
from .stacks import TemporalStack


@dataclass
class Transition:
    """One supervised transition: input dates, and what happened five years on."""

    stack: TemporalStack                 # (T, C, H, W), already normalised
    label: np.ndarray                    # (H, W) uint8
    eligible: np.ndarray                 # (H, W) bool
    period: tuple[int, int]              # (t0, t1) of the *label*

    def as_dict(self) -> dict:
        return {"period": f"{self.period[0]}-{self.period[1]}",
                "input_years": self.stack.years,
                "eligible_cells": int(self.eligible.sum()),
                "conversions": int(self.label.sum())}


# --------------------------------------------------------------------------
# Spatial blocking
# --------------------------------------------------------------------------

def block_ids(shape: tuple[int, int], frame: AnalysisFrame, *,
              block_m: float = 5000.0) -> np.ndarray:
    """Label every pixel with the square block of `block_m` metres it sits in.

    Validation has to be split by block, not by pixel. Neighbouring pixels
    share drivers by construction — the neighbourhood layers are smoothed
    over 500 m and 1,500 m, and training tiles overlap — so a pixel-level
    split leaves near-copies of the validation data in the training set and
    the early-stopping curve stops meaning anything.
    """
    side = max(1, int(round(block_m / frame.res)))
    rows = np.arange(shape[0])[:, None] // side
    cols = np.arange(shape[1])[None, :] // side
    return (rows * (shape[1] // side + 1) + cols).astype("int32")


def block_split(ids: np.ndarray, *, val_fraction: float = 0.25,
                seed: int = 0) -> tuple[np.ndarray, list[int]]:
    """Choose whole blocks for validation. Returns (validation mask, block ids)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(ids)
    n_val = max(1, int(round(len(uniq) * val_fraction)))
    chosen = rng.choice(uniq, size=n_val, replace=False)
    mask = np.isin(ids, chosen)
    return mask, sorted(int(c) for c in chosen)


def block_folds(ids: np.ndarray, *, n_folds: int = 5, seed: int = 0) -> list[np.ndarray]:
    """Split the blocks into `n_folds` disjoint validation masks."""
    rng = np.random.default_rng(seed)
    uniq = rng.permutation(np.unique(ids))
    return [np.isin(ids, part) for part in np.array_split(uniq, n_folds)]


# --------------------------------------------------------------------------
# Tiling
# --------------------------------------------------------------------------

def tile_origins(shape: tuple[int, int], size: int, stride: int) -> list[tuple[int, int]]:
    """Top-left corners of every `size` x `size` tile, always covering the edges."""
    h, w = shape
    if size > h or size > w:
        raise ValueError(f"tile {size} does not fit in a {h} x {w} frame")
    rows = list(range(0, h - size + 1, stride))
    cols = list(range(0, w - size + 1, stride))
    if rows[-1] != h - size:
        rows.append(h - size)
    if cols[-1] != w - size:
        cols.append(w - size)
    return [(r, c) for r in rows for c in cols]


def select_origins(origins: list[tuple[int, int]], size: int, val_mask: np.ndarray, *,
                   want: str) -> list[tuple[int, int]]:
    """Keep tiles that lie wholly inside, or wholly outside, the validation blocks.

    Tiles straddling a block boundary are dropped by both sides. That gap is
    the buffer: without it a training tile can overlap validation pixels and
    the validation score drifts upward for no honest reason.
    """
    keep = []
    for r, c in origins:
        v = val_mask[r:r + size, c:c + size]
        inside = bool(v.all())
        outside = not bool(v.any())
        if (want == "val" and inside) or (want == "train" and outside):
            keep.append((r, c))
    return keep


@dataclass
class TileSet:
    """Tiles ready for the network: inputs, labels, eligibility, provenance."""

    x: np.ndarray                        # (N, T, C, size, size) float32
    y: np.ndarray                        # (N, size, size) uint8
    m: np.ndarray                        # (N, size, size) bool
    origins: list[tuple[int, int]] = field(default_factory=list)
    periods: list[tuple[int, int]] = field(default_factory=list)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    @property
    def n_positive(self) -> int:
        return int((self.y & self.m).sum())

    def sample_weights(self, *, oversample: float = 4.0) -> np.ndarray:
        """Sampling weight per tile, favouring tiles that contain conversions.

        About one eligible cell in a hundred converts, and conversions cluster
        at the built-up edge, so a uniform draw spends most batches on empty
        countryside. Weighting is preferred to dropping empty tiles: the model
        still has to learn where growth does *not* happen.
        """
        has_pos = (self.y * self.m).reshape(len(self), -1).sum(axis=1) > 0
        return np.where(has_pos, oversample, 1.0).astype("float64")


def build_tiles(transitions: list[Transition], origins: list[tuple[int, int]], *,
                size: int) -> TileSet:
    """Cut every transition at every origin into one tile set."""
    xs, ys, ms, og, pe = [], [], [], [], []
    for tr in transitions:
        for r, c in origins:
            xs.append(tr.stack.data[:, :, r:r + size, c:c + size])
            ys.append(tr.label[r:r + size, c:c + size])
            ms.append(tr.eligible[r:r + size, c:c + size])
            og.append((r, c))
            pe.append(tr.period)
    if not xs:
        raise ValueError("no tiles selected; loosen the tile size or the block split")
    return TileSet(np.stack(xs).astype("float32"), np.stack(ys).astype("uint8"),
                   np.stack(ms), og, pe)


def dihedral(x: np.ndarray, y: np.ndarray, m: np.ndarray,
             k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One of the eight rotations and reflections of a square, applied to a tile.

    A map has no natural "up" for this task — growth at the northern edge of
    the city looks like growth at the southern edge — so all eight symmetries
    are legitimate extra training examples. They would not be legitimate for a
    task with a fixed orientation, such as reading shadows.
    """
    rot, flip = k % 4, k >= 4
    if rot:
        x = np.rot90(x, rot, axes=(-2, -1))
        y = np.rot90(y, rot, axes=(-2, -1))
        m = np.rot90(m, rot, axes=(-2, -1))
    if flip:
        x, y, m = x[..., ::-1], y[..., ::-1], m[..., ::-1]
    return np.ascontiguousarray(x), np.ascontiguousarray(y), np.ascontiguousarray(m)


# --------------------------------------------------------------------------
# Pixel grid to analysis grid
# --------------------------------------------------------------------------

def cell_lookup(pixel_frame: AnalysisFrame, cell_frame: AnalysisFrame) -> np.ndarray:
    """Index of the analysis cell containing each pixel centre, -1 if outside.

    Works for any pair of resolutions, including 30 m pixels inside 100 m
    cells, where neither divides the other. Assigning by pixel centre keeps
    every pixel in exactly one cell, so aggregation neither double-counts nor
    drops area.
    """
    xs, ys = pixel_frame.xy_centres()
    col = np.floor((xs - cell_frame.minx) / cell_frame.res).astype("int64")
    row = np.floor((cell_frame.maxy - ys) / cell_frame.res).astype("int64")
    ok_c = (col >= 0) & (col < cell_frame.width)
    ok_r = (row >= 0) & (row < cell_frame.height)
    idx = np.where(ok_r[:, None] & ok_c[None, :],
                   row[:, None] * cell_frame.width + col[None, :], -1)
    return idx.astype("int64")


def aggregate_to_cells(values: np.ndarray, lookup: np.ndarray,
                       cell_frame: AnalysisFrame, *,
                       weights: np.ndarray | None = None) -> np.ndarray:
    """Mean of `values` over the pixels of each analysis cell."""
    n = cell_frame.width * cell_frame.height
    flat_idx = lookup.ravel()
    ok = flat_idx >= 0
    v = np.asarray(values, dtype="float64").ravel()[ok]
    w = np.ones_like(v) if weights is None else np.asarray(weights, "float64").ravel()[ok]
    total = np.bincount(flat_idx[ok], weights=v * w, minlength=n)
    count = np.bincount(flat_idx[ok], weights=w, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(count > 0, total / count, np.nan)
    return out.reshape(cell_frame.shape).astype("float32")
