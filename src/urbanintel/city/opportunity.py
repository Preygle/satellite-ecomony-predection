from __future__ import annotations

import numpy as np
from scipy import ndimage, stats

from ..aoi import AnalysisFrame
from ..config import Config
from .economy import block
from .prepare import read, write

COMPONENTS = {
    "market_now": "people within 1.5 km (GHS-POP 2020)",
    "activity_now": "night-light level, latest two years",
    "activity_growth": "forecast night-light growth relative to the established core",
    "urban_growth": "forecast new urban cells within 1.5 km by 2025",
    "access": "road length per km2 within 1 km",
}
NEWS_WEIGHT = 0.10
DRAWS = 2000
SPACING_M = 1500.0


def _disk(radius: int) -> np.ndarray:
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    return ((xx ** 2 + yy ** 2) <= radius ** 2).astype("float32")


def _rank(v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = np.full(v.shape, np.nan, dtype="float32")
    x = np.nan_to_num(v[mask], nan=np.nanmedian(v[mask]) if mask.any() else 0.0)
    if x.size:
        r = stats.rankdata(x, method="average")
        out[mask] = (r - 1) / max(len(r) - 1, 1)
    return out


def spaced(values: np.ndarray, coarse: AnalysisFrame, n: int, spacing_m: float = SPACING_M) -> list[int]:
    # Best zones at least `spacing_m` apart, so the list names distinct places rather than neighbours
    order = np.argsort(-np.nan_to_num(values, nan=-np.inf).ravel())
    picked: list[tuple[int, int]] = []
    out = []
    lim = (spacing_m / coarse.res) ** 2
    for i in order:
        if not np.isfinite(values.ravel()[i]):
            break
        r, c = divmod(int(i), coarse.width)
        if all((r - a) ** 2 + (c - b) ** 2 >= lim for a, b in picked):
            picked.append((r, c))
            out.append(int(i))
            if len(out) == n:
                break
    return out


def score(cfg: Config, fine: AnalysisFrame, coarse: AnalysisFrame, econ: dict) -> dict:
    rdir = cfg.processed_dir / "rasters"
    f = int(round(coarse.res / fine.res))
    float(cfg.get("thresholds.builtup.surface_fraction_urban"))
    km2 = coarse.res ** 2 / 1e6
    built = block(read(rdir / "builtup_m2_2020.tif"), f) / fine.res ** 2
    pop = block(read(rdir / "population_2020.tif"), f, "sum")
    new = read(rdir / "predicted_new_urban_2025.tif")
    new_c = block(new, f, "sum") if new is not None else np.zeros(coarse.shape, "float32")
    roads = block(read(rdir / "road_density.tif"), f, "sum") / 1000.0 / km2
    last = econ["years"][-1]
    level = read(rdir / f"econ_level_{last}.tif")
    fc = sorted(rdir.glob("econ_growth_forecast_*.tif"))
    growth = read(fc[-1]) if fc else np.zeros(coarse.shape, "float32")

    r15 = max(1, int(round(1500 / coarse.res)))
    r10 = max(1, int(round(1000 / coarse.res)))
    comp = {
        "market_now": ndimage.convolve(pop, _disk(r15), mode="constant"),
        "activity_now": level,
        "activity_growth": growth,
        "urban_growth": ndimage.convolve(new_c, _disk(r15), mode="constant"),
        "access": ndimage.convolve(roads, _disk(r10), mode="nearest") / _disk(r10).sum(),
    }
    candidate = (built >= 0.10) | (new_c >= 3)
    candidate &= np.isfinite(level)
    ranks = {k: _rank(v, candidate) for k, v in comp.items()}
    stack = np.stack([ranks[k] for k in COMPONENTS])
    w = np.full(len(COMPONENTS), 1.0 / len(COMPONENTS))
    base = np.where(candidate, np.tensordot(w, np.nan_to_num(stack), axes=1), np.nan).astype("float32")

    idx = np.flatnonzero(candidate.ravel())
    vals = np.nan_to_num(stack.reshape(len(COMPONENTS), -1)[:, idx])
    rng = np.random.default_rng(0)
    weights = rng.dirichlet(np.ones(len(COMPONENTS)), size=DRAWS)
    k10 = min(10, len(idx))
    top_freq = np.zeros(len(idx))
    rank_sum = np.zeros(len(idx))
    for wd in weights:
        s = wd @ vals
        order = np.argsort(-s)
        top_freq[order[:k10]] += 1
        rank_sum[order] += np.arange(1, len(idx) + 1)
    top_freq /= DRAWS
    robust = np.full(coarse.width * coarse.height, np.nan, dtype="float32")
    robust[idx] = top_freq
    write(rdir / "opportunity_score.tif", base, coarse)
    write(rdir / "opportunity_top10_frequency.tif", robust.reshape(coarse.shape), coarse)
    np.save(rdir / "opportunity_components.npy", stack)

    xs, ys = coarse.xy_centres()
    order = spaced(base, coarse, 25)
    rows = []
    for rank, i in enumerate(order, start=1):
        r, c = divmod(int(i), coarse.width)
        j = int(np.searchsorted(idx, i))
        rows.append({"rank": rank, "row": r, "col": c, "x": float(xs[c]), "y": float(ys[r]),
                     "score": round(float(base[r, c]), 4),
                     "top10_share_under_random_weights": round(float(top_freq[j]), 3),
                     "median_rank_under_random_weights": int(round(rank_sum[j] / DRAWS)),
                     **{k: round(float(ranks[k][r, c]), 3) for k in COMPONENTS},
                     "population_1500m": int(comp["market_now"][r, c]),
                     "new_urban_cells_1500m": int(comp["urban_growth"][r, c]),
                     "activity_growth": None if not np.isfinite(growth[r, c]) else round(float(growth[r, c]), 4),
                     "builtup_fraction_2020": round(float(built[r, c]), 3)})
    return {"components": COMPONENTS, "weights": dict(zip(COMPONENTS, w.round(3).tolist())),
            "candidates": int(candidate.sum()), "zone_m": coarse.res, "top": rows,
            "robustness": {"draws": DRAWS, "rule": "Dirichlet(1,...,1) weights; share of draws in which "
                                                    "a zone ranks in the top 10"},
            "candidate_rule": "built-up fraction >= 0.10 in 2020, or at least 3 forecast new urban "
                              "cells in the zone by 2025",
            "spacing_m": SPACING_M}


def apply_news(cfg: Config, coarse: AnalysisFrame, opp: dict, news_zone: np.ndarray | None) -> dict:
    rdir = cfg.processed_dir / "rasters"
    base = read(rdir / "opportunity_score.tif")
    if news_zone is None:
        opp["news"] = None
        return opp
    adj = np.where(np.isfinite(base), base + NEWS_WEIGHT * np.clip(news_zone, -1, 1), np.nan)
    write(rdir / "opportunity_score_news.tif", adj.astype("float32"), coarse)
    for row in opp["top"]:
        row["news_adjustment"] = round(float(NEWS_WEIGHT * news_zone[row["row"], row["col"]]), 4)
        row["score_with_news"] = round(row["score"] + row["news_adjustment"], 4)
    order = spaced(adj, coarse, 25)
    xs, ys = coarse.xy_centres()
    opp["top_with_news"] = [{"rank": k, "row": int(i) // coarse.width, "col": int(i) % coarse.width,
                             "x": float(xs[int(i) % coarse.width]), "y": float(ys[int(i) // coarse.width]),
                             "score_with_news": round(float(adj.ravel()[i]), 4),
                             "news_adjustment": round(float(NEWS_WEIGHT * news_zone.ravel()[i]), 4)}
                            for k, i in enumerate(order, start=1)]
    opp["news"] = {"weight": NEWS_WEIGHT, "rule": "score + 0.10 x news index in [-1, 1]; the news "
                   "layer is a qualitative adjustment and is not validated against outcomes"}
    return opp
