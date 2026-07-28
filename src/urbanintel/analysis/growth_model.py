"""Predictive urban expansion model.

Answers: *given how this city has grown so far, where does it grow next?*

Design follows the CA-with-learned-transition-rules family that PLUS
(Liang et al. 2021, CEUS 85:101569) belongs to, in three stages:

1. **Suitability** — a logistic model learns, from observed conversions,
   how strongly each driver (distance to centre, road access, neighbourhood
   density, population) predicts that a non-urban cell becomes urban.
2. **Allocation** — a constrained cellular automaton allocates a demand
   quantity to the highest-suitability cells, with a neighbourhood term so
   growth accretes onto existing development rather than scattering.
3. **Validation** — the model is fitted on one period and tested against a
   *later observed* period it never saw.

Why the validation design matters
---------------------------------
A land-change model that is fitted and evaluated on the same period will
report excellent accuracy and mean nothing. Worse, plain overall accuracy is
actively misleading here: most of the AOI stays non-urban, so a model that
predicts "no change" everywhere scores ~97%.

This module therefore reports **Figure of Merit** (Pontius et al.), which
ignores the correctly-predicted non-change that inflates accuracy:

    FoM = hits / (hits + misses + false alarms)

Published land-change models typically achieve FoM between 0.1 and 0.3 at
these time steps. A null model is also computed so the gain is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from ..aoi import AnalysisFrame

# --------------------------------------------------------------------------
# Driver construction
# --------------------------------------------------------------------------

DRIVER_NAMES = [
    "distance_centre_km",
    "neighbourhood_built_500m",
    "neighbourhood_built_1500m",
    "distance_to_urban_edge_km",
    "road_density",
    "population_density",
    "builtup_fraction",
]


def build_drivers(
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    urban_threshold: float = 0.20,
) -> tuple[np.ndarray, list[str]]:
    """Stack driver layers into an (n_cells, n_drivers) design matrix.

    Neighbourhood density is computed at two scales because urban growth
    responds to both immediate adjacency (does my neighbour have a road and
    a water connection?) and district-scale agglomeration.
    """
    urban = builtup_frac >= urban_threshold

    def _circular_mean(arr: np.ndarray, radius_m: float) -> np.ndarray:
        r = max(1, int(round(radius_m / frame.res)))
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        k = ((xx**2 + yy**2) <= r**2).astype("float32")
        k /= k.sum()
        return ndimage.convolve(arr.astype("float32"), k, mode="nearest")

    nb500 = _circular_mean(urban.astype("float32"), 500.0)
    nb1500 = _circular_mean(urban.astype("float32"), 1500.0)

    # Distance to the nearest existing urban cell, in km.
    if urban.any():
        edge_dist = ndimage.distance_transform_edt(~urban) * frame.res / 1000.0
    else:
        edge_dist = np.full(urban.shape, 99.0, dtype="float32")

    layers = [
        distance_km,
        nb500,
        nb1500,
        edge_dist.astype("float32"),
        np.zeros_like(builtup_frac) if road_density is None else road_density,
        np.zeros_like(builtup_frac) if population is None else population,
        builtup_frac,
    ]
    X = np.stack([np.nan_to_num(l, nan=0.0).ravel() for l in layers], axis=1)
    return X.astype("float64"), list(DRIVER_NAMES)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

@dataclass
class ChangeMetrics:
    """Confusion of predicted vs observed *change*, and derived scores."""

    hits: int              # predicted change, observed change
    misses: int            # predicted persistence, observed change
    false_alarms: int      # predicted change, observed persistence
    correct_rejections: int
    figure_of_merit: float
    producers_accuracy: float
    users_accuracy: float
    overall_accuracy: float
    kappa: float
    null_overall_accuracy: float

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "false_alarms": self.false_alarms,
            "correct_rejections": self.correct_rejections,
            "figure_of_merit": round(self.figure_of_merit, 4),
            "producers_accuracy": round(self.producers_accuracy, 4),
            "users_accuracy": round(self.users_accuracy, 4),
            "overall_accuracy": round(self.overall_accuracy, 4),
            "kappa": round(self.kappa, 4),
            "null_model_accuracy": round(self.null_overall_accuracy, 4),
        }


def change_metrics(predicted_change: np.ndarray, observed_change: np.ndarray,
                   eligible: np.ndarray) -> ChangeMetrics:
    """Score predicted change against observed change over eligible cells.

    `eligible` restricts scoring to cells that *could* have changed (i.e.
    were non-urban at the start). Scoring over all cells would credit the
    model for correctly leaving already-urban land alone.
    """
    # Every quadrant must be counted *within* the eligible set. Masking only
    # `p` and `o` but counting `~p & ~o` over the full array silently credits
    # the model for every already-urban cell it left alone, which inflates
    # correct rejections and overall accuracy toward 1.
    p = predicted_change & eligible
    o = observed_change & eligible

    hits = int((p & o).sum())
    misses = int((~p & o & eligible).sum())
    false_alarms = int((p & ~o & eligible).sum())
    correct_rej = int((~p & ~o & eligible).sum())

    denom = hits + misses + false_alarms
    fom = hits / denom if denom else 0.0
    prod = hits / (hits + misses) if (hits + misses) else 0.0
    user = hits / (hits + false_alarms) if (hits + false_alarms) else 0.0

    n = hits + misses + false_alarms + correct_rej
    oa = (hits + correct_rej) / n if n else 0.0

    # Cohen's kappa
    pe = (
        ((hits + false_alarms) * (hits + misses) + (misses + correct_rej) * (false_alarms + correct_rej))
        / (n * n)
    ) if n else 0.0
    kappa = (oa - pe) / (1 - pe) if (1 - pe) else 0.0

    # Null model: predict no change anywhere.
    null_oa = (correct_rej + false_alarms) / n if n else 0.0

    return ChangeMetrics(
        hits=hits, misses=misses, false_alarms=false_alarms,
        correct_rejections=correct_rej, figure_of_merit=fom,
        producers_accuracy=prod, users_accuracy=user,
        overall_accuracy=oa, kappa=kappa, null_overall_accuracy=null_oa,
    )


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class GrowthModel:
    """Fitted suitability model plus its validation record."""

    coefficients: dict[str, float]
    intercept: float
    driver_names: list[str]
    means: np.ndarray
    scales: np.ndarray
    train_period: tuple[int, int]
    n_train_positive: int
    n_train_total: int
    auc: float
    validation: ChangeMetrics | None = None
    validation_period: tuple[int, int] | None = None
    notes: list[str] = field(default_factory=list)

    def suitability(self, X: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        """Probability surface in [0, 1]."""
        Xs = (X - self.means) / self.scales
        w = np.array([self.coefficients[n] for n in self.driver_names])
        z = Xs @ w + self.intercept
        return (1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))).reshape(shape).astype("float32")

    def as_dict(self) -> dict:
        d = {
            "train_period": f"{self.train_period[0]}-{self.train_period[1]}",
            "n_train_cells": self.n_train_total,
            "n_conversions_observed": self.n_train_positive,
            "conversion_rate": round(self.n_train_positive / max(self.n_train_total, 1), 5),
            "auc": round(self.auc, 4),
            "intercept": round(self.intercept, 4),
            "coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
        }
        if self.validation:
            d["validation_period"] = f"{self.validation_period[0]}-{self.validation_period[1]}"
            d["validation"] = self.validation.as_dict()
        if self.notes:
            d["notes"] = self.notes
        return d


def fit(
    builtup_frac_t0: np.ndarray,
    builtup_frac_t1: np.ndarray,
    drivers_t0: np.ndarray,
    driver_names: list[str],
    frame: AnalysisFrame,
    *,
    period: tuple[int, int],
    urban_threshold: float = 0.20,
    max_samples: int = 200_000,
    seed: int = 0,
) -> GrowthModel:
    """Fit a logistic suitability model on observed conversions t0 -> t1.

    Only cells that were non-urban at t0 are used: already-urban cells cannot
    convert, and including them would let the model learn "urban stays urban"
    instead of what actually drives new development.

    The classes are heavily imbalanced (a few percent convert), so the
    negative class is subsampled and the model is fitted with balanced class
    weights.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)

    urban_t0 = (builtup_frac_t0 >= urban_threshold).ravel()
    urban_t1 = (builtup_frac_t1 >= urban_threshold).ravel()

    eligible = ~urban_t0
    y = (urban_t1 & eligible)[eligible].astype("int8")
    X = drivers_t0[eligible]

    n_pos = int(y.sum())
    if n_pos < 30:
        raise ValueError(
            f"only {n_pos} observed conversions in {period[0]}-{period[1]}; "
            "too few to fit a transition model"
        )

    # Subsample for tractability, preserving all positives.
    if len(y) > max_samples:
        pos_idx = np.flatnonzero(y == 1)
        neg_idx = np.flatnonzero(y == 0)
        keep_neg = rng.choice(neg_idx, size=min(len(neg_idx), max_samples - len(pos_idx)),
                              replace=False)
        idx = np.concatenate([pos_idx, keep_neg])
        Xf, yf = X[idx], y[idx]
    else:
        Xf, yf = X, y

    means = Xf.mean(axis=0)
    scales = Xf.std(axis=0)
    scales[scales < 1e-9] = 1.0
    Xs = (Xf - means) / scales

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(Xs, yf)

    auc = float(roc_auc_score(yf, clf.decision_function(Xs)))
    coefs = {n: float(c) for n, c in zip(driver_names, clf.coef_[0])}

    return GrowthModel(
        coefficients=coefs, intercept=float(clf.intercept_[0]),
        driver_names=list(driver_names), means=means, scales=scales,
        train_period=period, n_train_positive=n_pos, n_train_total=int(eligible.sum()),
        auc=auc,
    )


def allocate(
    suitability: np.ndarray,
    builtup_frac_start: np.ndarray,
    demand_cells: int,
    frame: AnalysisFrame,
    *,
    urban_threshold: float = 0.20,
    neighbourhood_weight: float = 0.35,
    iterations: int = 8,
    seed: int = 0,
) -> np.ndarray:
    """Constrained CA allocation of `demand_cells` new urban cells.

    Suitability alone would scatter growth across every well-connected cell.
    The neighbourhood term re-weights it each iteration by how much
    development has appeared nearby, which is what produces contiguous
    accretion rather than salt-and-pepper. Allocating over several iterations
    rather than all at once lets earlier conversions influence later ones —
    the essential feedback in a cellular automaton.
    """
    rng = np.random.default_rng(seed)
    urban = builtup_frac_start >= urban_threshold
    new = np.zeros_like(urban, dtype=bool)

    r = max(1, int(round(300.0 / frame.res)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    kernel = ((xx**2 + yy**2) <= r**2).astype("float32")
    kernel /= kernel.sum()

    remaining = int(demand_cells)
    per_iter = max(1, remaining // iterations)

    for _ in range(iterations):
        if remaining <= 0:
            break
        current = urban | new
        nb = ndimage.convolve(current.astype("float32"), kernel, mode="nearest")
        score = (1.0 - neighbourhood_weight) * suitability + neighbourhood_weight * nb
        score = np.where(current, -np.inf, score)

        take = min(per_iter, remaining)
        flat = score.ravel()
        finite = np.isfinite(flat)
        if not finite.any():
            break
        # Small random tiebreak so ties do not resolve by array order.
        jitter = rng.normal(0, 1e-6, flat.shape)
        order = np.argsort(-(flat + jitter))
        chosen = [i for i in order[: take * 3] if finite[i]][:take]
        if not chosen:
            break
        new.ravel()[np.array(chosen)] = True
        remaining -= len(chosen)

    return new


def fit_and_validate(
    builtup: dict[int, np.ndarray],
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: dict[int, np.ndarray] | None = None,
    train: tuple[int, int] = (2010, 2020),
    test: tuple[int, int] = (2020, 2025),
    urban_threshold: float = 0.20,
) -> GrowthModel:
    """Fit on `train`, then validate on a later period the model never saw.

    Demand for the test period is taken from the *observed* number of
    conversions. This isolates the question the model is actually being asked:
    given that N cells converted, did it put them in the right places? A model
    that also had to guess N would confound two different errors.
    """
    t0, t1 = train
    v0, v1 = test
    for y in (t0, t1, v0, v1):
        if y not in builtup:
            raise ValueError(f"missing built-up epoch {y}")

    pop_t0 = population.get(t0) if population else None
    X_train, names = build_drivers(
        builtup[t0], frame, distance_km=distance_km,
        road_density=road_density, population=pop_t0,
        urban_threshold=urban_threshold,
    )
    model = fit(builtup[t0], builtup[t1], X_train, names, frame,
                period=train, urban_threshold=urban_threshold)

    # --- validation on the held-out period -------------------------------
    pop_v0 = population.get(v0) if population else None
    X_test, _ = build_drivers(
        builtup[v0], frame, distance_km=distance_km,
        road_density=road_density, population=pop_v0,
        urban_threshold=urban_threshold,
    )
    suit = model.suitability(X_test, frame.shape)

    urban_v0 = builtup[v0] >= urban_threshold
    urban_v1 = builtup[v1] >= urban_threshold
    observed_change = urban_v1 & ~urban_v0
    demand = int(observed_change.sum())

    predicted_change = allocate(
        suit, builtup[v0], demand, frame, urban_threshold=urban_threshold
    )
    model.validation = change_metrics(predicted_change, observed_change, ~urban_v0)
    model.validation_period = test
    model.notes.append(
        f"Demand for the validation period was set to the observed count "
        f"({demand} cells), isolating allocation skill from demand estimation."
    )
    return model


def project(
    model: GrowthModel,
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    demand_cells: int,
    urban_threshold: float = 0.20,
) -> tuple[np.ndarray, np.ndarray]:
    """Project future expansion. Returns (suitability, predicted_new_urban)."""
    X, _ = build_drivers(
        builtup_frac, frame, distance_km=distance_km,
        road_density=road_density, population=population,
        urban_threshold=urban_threshold,
    )
    suit = model.suitability(X, frame.shape)
    new = allocate(suit, builtup_frac, demand_cells, frame,
                   urban_threshold=urban_threshold)
    return suit, new


def extrapolate_demand(builtup: dict[int, np.ndarray], frame: AnalysisFrame,
                       *, target_year: int, urban_threshold: float = 0.20) -> int:
    """Estimate how many cells convert by `target_year`, from the observed trend.

    A compound growth rate fitted to observed urban extent. Deliberately
    simple: with four epochs, anything more elaborate would be fitting noise.
    """
    years = sorted(builtup)
    counts = [int((builtup[y] >= urban_threshold).sum()) for y in years]
    y0, y1 = years[0], years[-1]
    c0, c1 = counts[0], counts[-1]
    if c0 <= 0 or y1 <= y0:
        return 0
    rate = (c1 / c0) ** (1.0 / (y1 - y0)) - 1.0
    projected = c1 * ((1.0 + rate) ** (target_year - y1))
    return max(0, int(round(projected - c1)))
