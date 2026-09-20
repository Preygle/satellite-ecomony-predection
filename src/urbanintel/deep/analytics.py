from __future__ import annotations

import numpy as np

from ..analysis import growth_model as GM


# --------------------------------------------------------------------------
# Ranking: can the model tell converting cells from the rest?
# --------------------------------------------------------------------------

def discrimination(score: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
                   *, seed: int = 0) -> dict:
    """Ranking quality of a suitability surface, independent of any threshold.

    Average precision matters more than AUC here. With one converting cell in
    a hundred, a model can reach an impressive AUC while still being wrong
    about almost every cell it ranks first; average precision is computed
    against the positive class alone and stays honest about that.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    s = np.asarray(score, dtype="float64")[eligible]
    o = np.asarray(observed)[eligible].astype("int8")
    if o.min() == o.max():
        return {"auc": None, "average_precision": None, "n_eligible": int(o.size),
                "n_converted": int(o.sum())}
    base = float(o.mean())
    ap = float(average_precision_score(o, s))
    return {
        "auc": round(float(roc_auc_score(o, s)), 4),
        "average_precision": round(ap, 4),
        "base_rate": round(base, 5),
        "average_precision_lift": round(ap / base, 2) if base else None,
        "n_eligible": int(o.size),
        "n_converted": int(o.sum()),
        "toc": GM.toc_curve(score, observed, eligible, seed=seed),
    }


def precision_at_k(score: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
                   *, fractions: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10)) -> list[dict]:
    """Share of real conversions among the top-ranked cells.

    This is the number a planner actually experiences: if we hand over the
    top one percent of the map, how much of it really develops?
    """
    s = np.asarray(score, dtype="float64")[eligible]
    o = np.asarray(observed)[eligible].astype("int8")
    order = np.argsort(-s, kind="stable")
    out = []
    for f in fractions:
        k = max(1, int(round(f * len(s))))
        hits = int(o[order[:k]].sum())
        out.append({"top_fraction": f, "cells": k, "hits": hits,
                    "precision": round(hits / k, 4),
                    "recall": round(hits / max(int(o.sum()), 1), 4)})
    return out


# --------------------------------------------------------------------------
# Allocation: is the predicted map right?
# --------------------------------------------------------------------------

def allocation(predicted: np.ndarray, observed: np.ndarray, eligible: np.ndarray) -> dict:
    return GM.change_metrics(predicted, observed, eligible).as_dict()


def rank_only_allocation(score: np.ndarray, observed: np.ndarray,
                         eligible: np.ndarray, demand: int) -> dict:
    """Take the top `demand` cells by suitability, with no cellular automaton.

    The difference between this and the full result is exactly what the
    automaton contributes. Without it, a model that ranks cells well but
    scatters them across the map gets credit it would lose once growth has
    to be contiguous — and that turns out to separate these models more
    than their ranking does.
    """
    flat = np.where(eligible.ravel(), np.asarray(score, dtype="float64").ravel(),
                    -np.inf)
    top = np.argsort(-flat, kind="stable")[:max(0, int(demand))]
    pred = np.zeros(flat.size, dtype=bool)
    pred[top[np.isfinite(flat[top])]] = True
    return GM.change_metrics(pred.reshape(score.shape), observed, eligible).as_dict()


def neighbourhood_weight_sweep(score: np.ndarray, builtup_frac_start: np.ndarray,
                               observed: np.ndarray, eligible: np.ndarray,
                               frame, demand: int, *,
                               weights: tuple[float, ...] = (0.0, 0.1, 0.2, 0.35, 0.5),
                               urban_threshold: float = 0.20, seed: int = 0) -> dict:
    """Figure of Merit against how much the allocation leans on the neighbourhood.

    The cellular automaton mixes suitability with how much development is
    already nearby, at a weight fixed by hand. That weight was never tested
    against the alternative. Sweeping it shows whether contiguity helps this
    city at all: where growth leapfrogs past the edge, insisting on
    contiguity moves predictions to the wrong places.
    """
    rows = []
    for w in weights:
        pred = GM.allocate(score.astype("float32"), builtup_frac_start, demand,
                           frame, urban_threshold=urban_threshold,
                           neighbourhood_weight=float(w), seed=seed)
        m = GM.change_metrics(pred, observed, eligible)
        rows.append({"neighbourhood_weight": w, "hits": m.hits,
                     "figure_of_merit": round(m.figure_of_merit, 4)})
    best = max(rows, key=lambda r: r["figure_of_merit"])
    return {"sweep": rows, "best_weight": best["neighbourhood_weight"],
            "best_figure_of_merit": best["figure_of_merit"],
            "weight_in_use": 0.35}


def random_allocation_baseline(observed: np.ndarray, eligible: np.ndarray, *,
                               n_draws: int = 20, seed: int = 0) -> dict:
    """Place the same demand uniformly at random, repeatedly.

    Without this a Figure of Merit cannot be read: the reader cannot tell
    whether 0.10 reflects real skill or the base rate of the study area.
    """
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(eligible.ravel())
    demand = int((observed & eligible).sum())
    obs = observed.ravel()
    foms, hits = [], []
    for _ in range(n_draws):
        pick = rng.choice(idx, size=min(demand, len(idx)), replace=False)
        h = int(obs[pick].sum())
        foms.append(h / (h + (demand - h) * 2) if demand else 0.0)
        hits.append(h)
    return {"mean_hits": round(float(np.mean(hits)), 1),
            "mean_figure_of_merit": round(float(np.mean(foms)), 5),
            "n_draws": n_draws, "demand": demand}


def error_by_band(predicted: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
                  values: np.ndarray, edges: list[float], *, name: str) -> dict:
    """Break the confusion down by a third variable, such as distance to the centre.

    A single Figure of Merit hides where a model fails. Most of these models
    do well at the built-up edge and badly on isolated development, and that
    difference is what a planner needs to know before trusting a map.
    """
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        band = eligible & (values >= lo) & (values < hi)
        if not band.any():
            continue
        m = GM.change_metrics(predicted & band, observed & band, band)
        rows.append({"from": lo, "to": hi, "eligible": int(band.sum()),
                     "observed": m.hits + m.misses, "hits": m.hits,
                     "figure_of_merit": round(m.figure_of_merit, 4),
                     "producers_accuracy": round(m.producers_accuracy, 4)})
    return {"variable": name, "bands": rows}


# --------------------------------------------------------------------------
# Calibration: are the probabilities honest?
# --------------------------------------------------------------------------

def calibration(probability: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
                *, n_bins: int = 10) -> dict:
    """Do cells given a 30% chance convert about 30% of the time?

    The allocation step only ranks cells, so calibration does not change the
    predicted map. It matters for the dashboard, where a probability is shown
    to a reader who will take it literally.
    """
    p = np.asarray(probability, dtype="float64")[eligible]
    o = np.asarray(observed)[eligible].astype("float64")
    if p.size == 0:
        return {"bins": [], "brier_score": None, "expected_calibration_error": None}
    edges = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if not m.any():
            continue
        pred, obs = float(p[m].mean()), float(o[m].mean())
        rows.append({"n": int(m.sum()), "mean_predicted": round(pred, 5),
                     "observed_rate": round(obs, 5)})
        ece += m.mean() * abs(pred - obs)
    return {"bins": rows,
            "brier_score": round(float(np.mean((p - o) ** 2)), 6),
            "expected_calibration_error": round(float(ece), 5)}


# --------------------------------------------------------------------------
# Stability: does the score survive being asked somewhere else?
# --------------------------------------------------------------------------

def block_scores(score: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
                 folds: list[np.ndarray], *, seed: int = 0) -> dict:
    """Score the same surface separately on each block of the study area.

    One number over the whole city can be carried by a single well-predicted
    district. The spread across blocks says how much of the skill is general.
    """
    from sklearn.metrics import roc_auc_score

    rows = []
    for i, fold in enumerate(folds):
        m = eligible & fold
        o = observed[m].astype("int8")
        if o.size < 50 or o.min() == o.max():
            continue
        rows.append({"fold": i, "eligible": int(m.sum()), "converted": int(o.sum()),
                     "auc": round(float(roc_auc_score(o, score[m])), 4)})
    aucs = [r["auc"] for r in rows]
    return {"folds": rows,
            "mean_auc": round(float(np.mean(aucs)), 4) if aucs else None,
            "sd_auc": round(float(np.std(aucs)), 4) if aucs else None,
            "min_auc": round(float(np.min(aucs)), 4) if aucs else None}


def comparison_table(results: dict[str, dict], *, baseline_fom: float | None = None) -> list[dict]:
    """One row per model: the table that goes in the report."""
    rows = []
    for name, r in results.items():
        val = r.get("validation") or {}
        fom = val.get("figure_of_merit")
        rows.append({
            "model": name,
            "auc_test": r.get("auc_test"),
            "average_precision": r.get("average_precision"),
            "figure_of_merit": fom,
            "figure_of_merit_rank_only": (r.get("ranking_only") or {}).get(
                "figure_of_merit"),
            "producers_accuracy": val.get("producers_accuracy"),
            "kappa": val.get("kappa"),
            "hits": val.get("hits"),
            "x_random": (round(fom / baseline_fom, 1)
                         if fom is not None and baseline_fom else None),
        })
    return sorted(rows, key=lambda r: (r["figure_of_merit"] is None, -(r["figure_of_merit"] or 0)))


def summarise(name: str, *, score: np.ndarray, predicted: np.ndarray,
              observed: np.ndarray, eligible: np.ndarray,
              folds: list[np.ndarray] | None = None,
              bands: list[tuple[str, np.ndarray, list[float]]] | None = None,
              seed: int = 0) -> dict:
    """Every analytic for one model, in one dictionary."""
    disc = discrimination(score, observed, eligible, seed=seed)
    demand = int((observed & eligible).sum())
    out = {
        "model": name,
        "auc_test": disc.get("auc"),
        "average_precision": disc.get("average_precision"),
        "average_precision_lift": disc.get("average_precision_lift"),
        "validation": allocation(predicted, observed, eligible),
        "ranking_only": rank_only_allocation(score, observed, eligible, demand),
        "precision_at_k": precision_at_k(score, observed, eligible),
        "calibration": calibration(score, observed, eligible),
        "toc": disc.get("toc"),
    }
    if folds:
        out["block_stability"] = block_scores(score, observed, eligible, folds, seed=seed)
    if bands:
        out["error_by_band"] = [error_by_band(predicted, observed, eligible, v, e, name=n)
                                for n, v, e in bands]
    return out
