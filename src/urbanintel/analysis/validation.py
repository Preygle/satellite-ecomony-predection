"""Validation helpers: agreement between maps, and simple statistical tests.

Used by the Review 3 validation scripts (``scripts/cross_checks.py``,
``scripts/validate_*.py``). They live here, with unit tests, rather than
inline in the scripts, because the numbers they produce go straight into the
report and the presentation.
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def agreement(a: np.ndarray, b: np.ndarray, valid: np.ndarray | None = None) -> dict:
    """Cell-by-cell agreement between two yes/no maps, e.g. two built-up definitions.

    Cohen's kappa is agreement corrected for chance: 1 means identical maps,
    0 means no better than two random maps with the same amount of "yes".
    Overall agreement alone would look high for any pair of maps that are
    mostly "no", which every built-up map of a mostly rural area is.
    """
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    if valid is not None:
        a, b = a[valid], b[valid]
    a, b = a.ravel(), b.ravel()
    n = int(a.size)
    both = int((a & b).sum())
    only_a = int((a & ~b).sum())
    only_b = int((~a & b).sum())
    neither = n - both - only_a - only_b
    if n == 0:
        return {"n": 0, "kappa": float("nan"), "overall_agreement": float("nan")}
    po = (both + neither) / n
    pa, pb = a.mean(), b.mean()
    pe = pa * pb + (1 - pa) * (1 - pb)
    kappa = (po - pe) / (1 - pe) if (1 - pe) > 0 else float("nan")
    return {"n": n, "both": both, "only_a": only_a, "only_b": only_b, "neither": neither,
            "overall_agreement": float(po), "kappa": float(kappa)}


def mann_whitney_greater(x, y) -> dict:
    """One-sided Mann-Whitney U test: do values in `x` tend to be larger than in `y`?

    Rank-based, so it assumes nothing about the shape of either distribution.
    The effect size is the probability that a random value from `x` exceeds a
    random value from `y` (0.5 = no difference, 1.0 = every x beats every y).
    """
    x = np.asarray(x, dtype="float64").ravel()
    y = np.asarray(y, dtype="float64").ravel()
    x, y = x[np.isfinite(x)], y[np.isfinite(y)]
    out = {"n_x": int(x.size), "n_y": int(y.size),
           "median_x": float(np.median(x)) if x.size else None,
           "median_y": float(np.median(y)) if y.size else None}
    if x.size < 3 or y.size < 3:
        return {**out, "u": None, "p_value": None, "prob_superiority": None}
    r = stats.mannwhitneyu(x, y, alternative="greater")
    return {**out, "u": float(r.statistic), "p_value": float(r.pvalue),
            "prob_superiority": float(r.statistic / (x.size * y.size))}


def loglog_fit(x, y) -> dict:
    """Least-squares line through log(y) against log(x).

    The slope is an *elasticity*: the percentage change in y that goes with a
    1% change in x. This is how the night-light literature (e.g. Henderson,
    Storeygard & Weil 2012) relates lights to economic output.
    """
    x = np.asarray(x, dtype="float64").ravel()
    y = np.asarray(y, dtype="float64").ravel()
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "elasticity": None, "r2": None, "p_value": None}
    r = stats.linregress(np.log(x[ok]), np.log(y[ok]))
    return {"n": int(ok.sum()), "elasticity": float(r.slope), "intercept": float(r.intercept),
            "r2": float(r.rvalue**2), "p_value": float(r.pvalue), "stderr": float(r.stderr)}


def rank_correlation(x, y) -> dict:
    """Spearman rank correlation: do places that rank high on x also rank high on y?"""
    x = np.asarray(x, dtype="float64").ravel()
    y = np.asarray(y, dtype="float64").ravel()
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "rho": None, "p_value": None}
    r = stats.spearmanr(x[ok], y[ok])
    return {"n": int(ok.sum()), "rho": float(r.statistic), "p_value": float(r.pvalue)}


def paired_comparison(reference, test) -> dict:
    """Two measurements of the same quantity at the same places, e.g. Landsat
    and MODIS land surface temperature on a shared 1 km grid.

    Reports R^2 of the straight-line fit, the mean difference (bias,
    test - reference) and the root-mean-square difference.
    """
    a = np.asarray(reference, dtype="float64").ravel()
    b = np.asarray(test, dtype="float64").ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "r2": None, "bias": None, "rmse": None}
    a, b = a[ok], b[ok]
    r = stats.linregress(a, b)
    d = b - a
    return {"n": int(ok.sum()), "r2": float(r.rvalue**2), "slope": float(r.slope),
            "intercept": float(r.intercept), "bias": float(d.mean()),
            "rmse": float(np.sqrt((d**2).mean()))}
