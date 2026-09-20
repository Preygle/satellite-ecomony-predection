from __future__ import annotations

import numpy as np

from ..analysis import growth_model as GM
from ..aoi import AnalysisFrame


def allocation_frequency(
    surfaces: np.ndarray,
    builtup_frac_start: np.ndarray,
    demand_cells: int,
    frame: AnalysisFrame,
    *,
    urban_threshold: float = 0.20,
    seeds: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """How often each cell is chosen, across draws of the model and the allocation.

    A single run answers "where do the next N cells go?" with a yes or a no,
    which reads as more certain than the model is. Re-running the allocation
    over several suitability draws — dropout samples of the network, or
    different tie-breaking seeds — and counting how often a cell is picked
    gives a probability a planner can act on: cells chosen in every draw are
    the confident core, cells chosen in half of them are genuinely marginal.

    Returns (probability, count of draws).
    """
    arr = np.asarray(surfaces, dtype="float32")
    draws = arr if arr.ndim == 3 else arr[None]
    if draws.shape[1:] != builtup_frac_start.shape:
        raise ValueError(f"surfaces are {draws.shape[1:]}, frame is {builtup_frac_start.shape}")
    seed_list = seeds if seeds is not None else list(range(len(draws)))

    hits = np.zeros(builtup_frac_start.shape, dtype="float64")
    for surface, seed in zip(draws, seed_list):
        placed = GM.allocate(surface.astype("float32"), builtup_frac_start, demand_cells,
                             frame, urban_threshold=urban_threshold, seed=seed)
        hits += placed
    n = len(draws)
    return (hits / n).astype("float32"), np.full(builtup_frac_start.shape, n, dtype="int16")


def binary_entropy(p: np.ndarray) -> np.ndarray:
    """Uncertainty of each cell's conversion probability, in bits (0 to 1)."""
    q = np.clip(p.astype("float64"), 1e-9, 1 - 1e-9)
    h = -(q * np.log2(q) + (1 - q) * np.log2(1 - q))
    return np.where((p <= 0) | (p >= 1), 0.0, h).astype("float32")


def consensus_prediction(probability: np.ndarray, demand_cells: int,
                         eligible: np.ndarray) -> np.ndarray:
    """The `demand_cells` most frequently chosen cells, as one map."""
    flat = np.where(eligible.ravel(), probability.ravel(), -np.inf)
    order = np.argsort(-flat, kind="stable")[:max(0, int(demand_cells))]
    out = np.zeros(probability.size, dtype=bool)
    out[order[np.isfinite(flat[order])]] = True
    return out.reshape(probability.shape)


def spread(surfaces: np.ndarray) -> dict:
    """How far apart the suitability draws are, before any allocation."""
    s = np.asarray(surfaces, dtype="float64")
    sd = s.std(axis=0)
    return {"n_draws": int(s.shape[0]),
            "mean_standard_deviation": round(float(np.nanmean(sd)), 5),
            "max_standard_deviation": round(float(np.nanmax(sd)), 5)}


def agreement(a: np.ndarray, b: np.ndarray, eligible: np.ndarray) -> dict:
    """Overlap between two predicted change maps over eligible cells."""
    pa, pb = a & eligible, b & eligible
    inter = int((pa & pb).sum())
    union = int((pa | pb).sum())
    return {"cells_a": int(pa.sum()), "cells_b": int(pb.sum()), "both": inter,
            "intersection_over_union": round(inter / union, 4) if union else 0.0}
