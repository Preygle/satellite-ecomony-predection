"""Predictive urban expansion model.

Answers: *given how this city has grown so far, where does it grow next?*

Design follows the CA-with-learned-transition-rules family that PLUS
(Liang et al. 2021, CEUS 85:101569) belongs to, in three stages:

1. **Suitability** — a model learns, from observed conversions, how strongly
   each driver (distance to centre, road access, neighbourhood density,
   population, terrain slope) predicts that a non-urban cell becomes urban.
   Two models are fitted on identical data and compared:
   *logistic regression*, a straight-line model whose coefficients can be
   read directly, and a *random forest*, which combines many decision trees
   and can capture thresholds and interactions a straight line cannot
   (PLUS itself uses a random forest for this step).
2. **Allocation** — a constrained cellular automaton allocates a demand
   quantity to the highest-suitability cells, with a neighbourhood term so
   growth accretes onto existing development rather than scattering.
3. **Validation** — each model is fitted on one period and tested against a
   *later observed* period it never saw.

Why the validation design matters
---------------------------------
A land-change model that is fitted and evaluated on the same period will
report excellent accuracy and mean nothing. Worse, plain overall accuracy is
actively misleading here: most of the AOI stays non-urban, so a model that
predicts "no change" everywhere scores ~97%.

This module therefore reports, on the held-out period:

* **Figure of Merit** (Pontius et al.), which ignores the correctly
  predicted non-change that inflates accuracy::

      FoM = hits / (hits + misses + false alarms)

* **Test-period AUC** — how well the suitability surface *ranks* the cells
  that really converted, independent of how many cells are allocated.
* **TOC** (Total Operating Characteristic, Pontius & Si 2014) — the same
  ranking drawn with the counts kept, so the size of the change is visible.

Published land-change models typically achieve FoM between 0.1 and 0.3 at
these time steps. A random-allocation baseline is also computed so the gain
is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy import ndimage

from ..aoi import AnalysisFrame

# --------------------------------------------------------------------------
# Driver construction
# --------------------------------------------------------------------------

# Every driver the model can use, in design-matrix order. The four spatial
# drivers are always built; the others are included only when their input
# is supplied (see build_drivers).
DRIVER_NAMES = [
    "distance_centre_km",
    "neighbourhood_built_500m",
    "neighbourhood_built_1500m",
    "distance_to_urban_edge_km",
    "road_density",
    "population_density",
    "builtup_fraction",
    "slope_deg",
]


def _circular_mean(arr: np.ndarray, radius_m: float, frame: AnalysisFrame) -> np.ndarray:
    r = max(1, int(round(radius_m / frame.res)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = ((xx**2 + yy**2) <= r**2).astype("float32")
    k /= k.sum()
    return ndimage.convolve(arr.astype("float32"), k, mode="nearest")


def build_drivers(
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    urban_threshold: float = 0.20,
) -> tuple[np.ndarray, list[str]]:
    """Stack driver layers into an (n_cells, n_drivers) design matrix.

    Neighbourhood density is computed at two scales because urban growth
    responds to both immediate adjacency (does my neighbour have a road and
    a water connection?) and district-scale agglomeration.

    Optional drivers (roads, population, slope) are included only when
    supplied. A model fitted without roads therefore really has no road
    term, rather than a column of zeros standing in for one — which is what
    makes the with/without-roads comparison meaningful.
    """
    urban = builtup_frac >= urban_threshold

    nb500 = _circular_mean(urban.astype("float32"), 500.0, frame)
    nb1500 = _circular_mean(urban.astype("float32"), 1500.0, frame)

    # Distance to the nearest existing urban cell, in km.
    if urban.any():
        edge_dist = ndimage.distance_transform_edt(~urban) * frame.res / 1000.0
    else:
        edge_dist = np.full(urban.shape, 99.0, dtype="float32")

    layers: dict[str, np.ndarray] = {
        "distance_centre_km": distance_km,
        "neighbourhood_built_500m": nb500,
        "neighbourhood_built_1500m": nb1500,
        "distance_to_urban_edge_km": edge_dist.astype("float32"),
    }
    if road_density is not None:
        layers["road_density"] = road_density
    if population is not None:
        layers["population_density"] = population
    layers["builtup_fraction"] = builtup_frac
    if slope is not None:
        layers["slope_deg"] = slope

    names = list(layers)
    X = np.stack([np.nan_to_num(layers[n], nan=0.0).ravel() for n in names], axis=1)
    return X.astype("float64"), names


def _check_width(X: np.ndarray, names: list[str]) -> None:
    if X.shape[1] != len(names):
        raise ValueError(
            f"design matrix has {X.shape[1]} columns but the model was fitted on "
            f"{len(names)} drivers {names}; build it with the same optional inputs"
        )


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


def roc_auc(score: np.ndarray, observed: np.ndarray) -> float:
    """Area under the ROC curve.

    The probability that a randomly chosen converted cell has a higher
    suitability than a randomly chosen unconverted one: 0.5 is no better
    than random, 1.0 a perfect ranking. NaN when only one class is present.
    """
    from sklearn.metrics import roc_auc_score

    o = np.asarray(observed).ravel().astype("int8")
    if o.min() == o.max():
        return float("nan")
    return float(roc_auc_score(o, np.asarray(score, dtype="float64").ravel()))


def toc_curve(score: np.ndarray, observed: np.ndarray, eligible: np.ndarray,
              *, n_points: int = 200, seed: int = 0) -> dict:
    """Total Operating Characteristic (Pontius & Si 2014) over eligible cells.

    Cells are ranked from most to least suitable. For each cut-off the curve
    gives how many cells are flagged (x) and how many of them really
    converted (y). It carries the same ranking information as a ROC curve
    but keeps the counts: a perfect model climbs at 45 degrees until every
    converted cell is found; a random one follows the straight line from the
    origin to the top-right corner. Ties — common in random-forest scores —
    are broken randomly so they do not resolve in array (i.e. map) order.
    """
    rng = np.random.default_rng(seed)
    s = np.asarray(score, dtype="float64")[eligible]
    o = np.asarray(observed)[eligible].astype("int64")
    s = s + rng.uniform(0.0, 1e-9, s.shape)
    order = np.argsort(-s, kind="stable")
    cum = np.cumsum(o[order])
    n = len(s)
    idx = np.unique(np.linspace(0, n - 1, min(n_points, n)).round().astype(int))
    return {
        "flagged": [0] + (idx + 1).tolist(),
        "hits": [0] + cum[idx].astype(int).tolist(),
        "n_eligible": int(n),
        "n_observed": int(o.sum()),
    }


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

@dataclass
class GrowthModel:
    """Fitted logistic suitability model plus its validation record."""

    coefficients: dict[str, float]
    intercept: float
    driver_names: list[str]
    means: np.ndarray
    scales: np.ndarray
    train_period: tuple[int, int]
    n_train_positive: int
    n_train_total: int
    auc: float                                  # training period (in-sample)
    kind: str = "logistic_regression"
    test_auc: float | None = None               # held-out period
    validation: ChangeMetrics | None = None
    validation_period: tuple[int, int] | None = None
    notes: list[str] = field(default_factory=list)

    def suitability(self, X: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        """Probability surface in [0, 1]."""
        _check_width(X, self.driver_names)
        Xs = (X - self.means) / self.scales
        w = np.array([self.coefficients[n] for n in self.driver_names])
        z = Xs @ w + self.intercept
        return (1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))).reshape(shape).astype("float32")

    def as_dict(self) -> dict:
        d = {
            "kind": self.kind,
            "drivers": self.driver_names,
            "train_period": f"{self.train_period[0]}-{self.train_period[1]}",
            "n_train_cells": self.n_train_total,
            "n_conversions_observed": self.n_train_positive,
            "conversion_rate": round(self.n_train_positive / max(self.n_train_total, 1), 5),
            "auc_train": round(self.auc, 4),
            "auc_test": None if self.test_auc is None else round(self.test_auc, 4),
            "intercept": round(self.intercept, 4),
            "coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
        }
        if self.validation:
            d["validation_period"] = f"{self.validation_period[0]}-{self.validation_period[1]}"
            d["validation"] = self.validation.as_dict()
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class ForestModel:
    """Fitted random-forest suitability model plus its validation record."""

    estimator: Any
    driver_names: list[str]
    train_period: tuple[int, int]
    n_train_positive: int
    n_train_total: int
    auc: float                                  # out-of-bag, training period
    params: dict[str, Any] = field(default_factory=dict)
    kind: str = "random_forest"
    test_auc: float | None = None
    validation: ChangeMetrics | None = None
    validation_period: tuple[int, int] | None = None
    importance: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def suitability(self, X: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        """Share of trees voting 'converts', in [0, 1]."""
        _check_width(X, self.driver_names)
        return self.estimator.predict_proba(X)[:, 1].reshape(shape).astype("float32")

    def as_dict(self) -> dict:
        d = {
            "kind": self.kind,
            "drivers": self.driver_names,
            "params": self.params,
            "train_period": f"{self.train_period[0]}-{self.train_period[1]}",
            "n_train_cells": self.n_train_total,
            "n_conversions_observed": self.n_train_positive,
            "auc_train_out_of_bag": round(self.auc, 4),
            "auc_test": None if self.test_auc is None else round(self.test_auc, 4),
        }
        if self.importance:
            d["permutation_importance_auc_drop"] = self.importance
        if self.validation:
            d["validation_period"] = f"{self.validation_period[0]}-{self.validation_period[1]}"
            d["validation"] = self.validation.as_dict()
        if self.notes:
            d["notes"] = self.notes
        return d


def _training_sample(builtup_frac_t0, builtup_frac_t1, drivers_t0, *, period,
                     urban_threshold, max_samples, seed):
    """Eligible cells (non-urban at t0) and whether each converted by t1.

    Already-urban cells cannot convert; including them would let a model
    learn "urban stays urban" instead of what drives new development. The
    negative class is subsampled only when the eligible set is very large.
    """
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

    if len(y) > max_samples:
        rng = np.random.default_rng(seed)
        pos_idx = np.flatnonzero(y == 1)
        neg_idx = np.flatnonzero(y == 0)
        keep_neg = rng.choice(neg_idx, size=min(len(neg_idx), max_samples - len(pos_idx)),
                              replace=False)
        idx = np.concatenate([pos_idx, keep_neg])
        return X[idx], y[idx], n_pos, int(eligible.sum())
    return X, y, n_pos, int(eligible.sum())


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

    Drivers are standardised (mean 0, standard deviation 1) first, so each
    coefficient is the effect of a one-standard-deviation change and the
    coefficients can be compared with one another. The classes are heavily
    imbalanced (about 1% of eligible cells convert), so the model is fitted
    with balanced class weights.
    """
    from sklearn.linear_model import LogisticRegression

    Xf, yf, n_pos, n_elig = _training_sample(
        builtup_frac_t0, builtup_frac_t1, drivers_t0, period=period,
        urban_threshold=urban_threshold, max_samples=max_samples, seed=seed)

    means = Xf.mean(axis=0)
    scales = Xf.std(axis=0)
    scales[scales < 1e-9] = 1.0
    Xs = (Xf - means) / scales

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(Xs, yf)

    auc = roc_auc(clf.decision_function(Xs), yf)
    coefs = {n: float(c) for n, c in zip(driver_names, clf.coef_[0])}

    return GrowthModel(
        coefficients=coefs, intercept=float(clf.intercept_[0]),
        driver_names=list(driver_names), means=means, scales=scales,
        train_period=period, n_train_positive=n_pos, n_train_total=n_elig,
        auc=auc,
    )


def fit_forest(
    builtup_frac_t0: np.ndarray,
    builtup_frac_t1: np.ndarray,
    drivers_t0: np.ndarray,
    driver_names: list[str],
    frame: AnalysisFrame,
    *,
    period: tuple[int, int],
    urban_threshold: float = 0.20,
    n_estimators: int = 300,
    min_samples_leaf: int = 20,
    max_samples: int = 200_000,
    seed: int = 0,
    progress: Callable[[int, int], None] | None = None,
    batch: int = 25,
) -> ForestModel:
    """Fit a random-forest suitability model on exactly the sample `fit` uses.

    A random forest trains many decision trees, each on a random resample of
    the cells, and averages their votes. `min_samples_leaf` stops individual
    trees memorising single cells; ``class_weight="balanced_subsample"``
    handles the rarity of conversions the same way the logistic model's
    balanced weights do. Its training-period score is the *out-of-bag* AUC:
    each cell is scored only by the trees that never saw it.

    If `progress` is given, it is called as ``progress(trees_done, total)``
    while the forest grows `batch` trees at a time (used by the demo's
    command-line trainer). The forest is the same either way.
    """
    from sklearn.ensemble import RandomForestClassifier

    Xf, yf, n_pos, n_elig = _training_sample(
        builtup_frac_t0, builtup_frac_t1, drivers_t0, period=period,
        urban_threshold=urban_threshold, max_samples=max_samples, seed=seed)

    params = {"n_estimators": n_estimators, "min_samples_leaf": min_samples_leaf,
              "class_weight": "balanced_subsample", "random_state": seed}
    if progress is None:
        clf = RandomForestClassifier(oob_score=True, n_jobs=-1, **params)
        clf.fit(Xf, yf)
    else:
        # Grow the same forest in batches. With warm_start, scikit-learn
        # advances the random state exactly as a single fit would, so every
        # tree matches the one-shot forest; out-of-bag scoring runs once, on
        # the last batch, over all the trees.
        clf = RandomForestClassifier(warm_start=True, n_jobs=-1, **params)
        done = 0
        while done < n_estimators:
            done = min(done + max(1, batch), n_estimators)
            clf.set_params(n_estimators=done, oob_score=done == n_estimators)
            clf.fit(Xf, yf)
            progress(done, n_estimators)
        clf.set_params(warm_start=False)
    oob = np.nan_to_num(clf.oob_decision_function_[:, 1], nan=0.5)

    return ForestModel(
        estimator=clf, driver_names=list(driver_names), train_period=period,
        n_train_positive=n_pos, n_train_total=n_elig,
        auc=roc_auc(oob, yf), params=params,
    )


def validate(
    model: GrowthModel | ForestModel,
    builtup: dict[int, np.ndarray],
    X_test: np.ndarray,
    frame: AnalysisFrame,
    *,
    test: tuple[int, int],
    urban_threshold: float = 0.20,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Score `model` on a held-out period it never saw.

    Demand for the test period is the *observed* number of conversions. That
    isolates the question the model is actually being asked — given that N
    cells converted, did it put them in the right places? — from the
    separate question of how large N would be.

    Returns (suitability, predicted change, observed change, eligible).
    """
    v0, v1 = test
    for y in (v0, v1):
        if y not in builtup:
            raise ValueError(f"missing built-up epoch {y}")

    suit = model.suitability(X_test, frame.shape)
    urban_v0 = builtup[v0] >= urban_threshold
    observed = (builtup[v1] >= urban_threshold) & ~urban_v0
    eligible = ~urban_v0
    demand = int(observed.sum())

    predicted = allocate(suit, builtup[v0], demand, frame,
                         urban_threshold=urban_threshold, seed=seed)
    model.validation = change_metrics(predicted, observed, eligible)
    model.validation_period = test
    model.test_auc = roc_auc(suit[eligible], observed[eligible])
    model.notes.append(
        f"Demand for the validation period was set to the observed count "
        f"({demand} cells), isolating allocation skill from demand estimation."
    )
    return suit, predicted, observed, eligible


def fit_and_validate(
    builtup: dict[int, np.ndarray],
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: dict[int, np.ndarray] | None = None,
    slope: np.ndarray | None = None,
    train: tuple[int, int] = (2010, 2015),
    test: tuple[int, int] = (2015, 2020),
    urban_threshold: float = 0.20,
) -> GrowthModel:
    """Fit logistic regression on `train`, then validate on `test`.

    The defaults are the observational GHSL epochs. Earlier versions
    defaulted to a 2020-2025 test period — 2025 is a GHSL projection, so
    that would have scored one model against another model's output.
    """
    t0, t1 = train
    v0, v1 = test
    for y in (t0, t1, v0, v1):
        if y not in builtup:
            raise ValueError(f"missing built-up epoch {y}")

    X_train, names = build_drivers(
        builtup[t0], frame, distance_km=distance_km, road_density=road_density,
        population=population.get(t0) if population else None, slope=slope,
        urban_threshold=urban_threshold,
    )
    model = fit(builtup[t0], builtup[t1], X_train, names, frame,
                period=train, urban_threshold=urban_threshold)

    X_test, _ = build_drivers(
        builtup[v0], frame, distance_km=distance_km, road_density=road_density,
        population=population.get(v0) if population else None, slope=slope,
        urban_threshold=urban_threshold,
    )
    validate(model, builtup, X_test, frame, test=test, urban_threshold=urban_threshold)
    return model


def permutation_importance_auc(
    model: ForestModel,
    X: np.ndarray,
    observed: np.ndarray,
    eligible: np.ndarray,
    *,
    max_negatives: int = 20_000,
    n_repeats: int = 5,
    seed: int = 0,
) -> dict[str, float]:
    """Drop in test-period AUC when each driver is shuffled.

    Shuffling a driver breaks its link to conversion while leaving everything
    else intact; the more the AUC falls, the more the model relies on it.
    Computed on the held-out period, on every converted cell plus a random
    sample of unconverted ones.
    """
    from sklearn.inspection import permutation_importance

    rng = np.random.default_rng(seed)
    e = eligible.ravel()
    y = observed.ravel()[e].astype("int8")
    Xe = X[e]
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    neg = rng.choice(neg, size=min(len(neg), max_negatives), replace=False)
    idx = np.concatenate([pos, neg])
    r = permutation_importance(model.estimator, Xe[idx], y[idx], scoring="roc_auc",
                               n_repeats=n_repeats, random_state=seed, n_jobs=-1)
    return {n: round(float(m), 4) for n, m in zip(model.driver_names, r.importances_mean)}


# --------------------------------------------------------------------------
# Allocation and projection
# --------------------------------------------------------------------------

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
    """Constrained CA allocation of exactly `demand_cells` new urban cells.

    Suitability alone would scatter growth across every well-connected cell.
    The neighbourhood term re-weights it each iteration by how much
    development has appeared nearby, which is what produces contiguous
    accretion rather than salt-and-pepper. Allocating over several iterations
    rather than all at once lets earlier conversions influence later ones —
    the essential feedback in a cellular automaton.

    Each iteration takes an equal share of what is still unplaced, so the
    last iteration always places the remainder. (An earlier version took
    ``demand // iterations`` every time and silently dropped
    ``demand % iterations`` cells — 6 of 1,214 in the Review 2 run.)
    """
    rng = np.random.default_rng(seed)
    urban = builtup_frac_start >= urban_threshold
    new = np.zeros_like(urban, dtype=bool)

    r = max(1, int(round(300.0 / frame.res)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    kernel = ((xx**2 + yy**2) <= r**2).astype("float32")
    kernel /= kernel.sum()

    remaining = int(demand_cells)
    for it in range(iterations):
        if remaining <= 0:
            break
        take = int(np.ceil(remaining / (iterations - it)))
        current = urban | new
        nb = ndimage.convolve(current.astype("float32"), kernel, mode="nearest")
        score = (1.0 - neighbourhood_weight) * suitability + neighbourhood_weight * nb
        score = np.where(current, -np.inf, score)

        flat = score.ravel()
        finite = np.isfinite(flat)
        if not finite.any():
            break
        # Small random tiebreak so ties do not resolve by array order.
        jitter = rng.normal(0, 1e-6, flat.shape)
        order = np.argsort(-(flat + jitter))
        chosen = order[:take]
        chosen = chosen[finite[chosen]]
        if chosen.size == 0:
            break
        new.ravel()[chosen] = True
        remaining -= int(chosen.size)

    return new


def project(
    model: GrowthModel | ForestModel,
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    demand_cells: int,
    urban_threshold: float = 0.20,
) -> tuple[np.ndarray, np.ndarray]:
    """Project future expansion in one step. Returns (suitability, predicted_new_urban)."""
    X, _ = build_drivers(
        builtup_frac, frame, distance_km=distance_km, road_density=road_density,
        population=population, slope=slope, urban_threshold=urban_threshold,
    )
    suit = model.suitability(X, frame.shape)
    new = allocate(suit, builtup_frac, demand_cells, frame,
                   urban_threshold=urban_threshold)
    return suit, new


def project_steps(
    model: GrowthModel | ForestModel,
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    demands: dict[int, int],
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    urban_threshold: float = 0.20,
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Project in five-year steps, feeding each step's growth into the next.

    `demands` maps target year -> cumulative new urban cells since the start.
    After each step the newly urban cells are set to the urban threshold and
    the neighbourhood and edge-distance drivers are rebuilt, so growth placed
    by 2025 attracts growth by 2030 — the feedback a single ten-year step
    would miss. Roads and population stay at their start values, since
    nothing forecasts them; the report says so.

    Returns {year: (suitability used for that step, cumulative new urban mask)}.
    """
    current = np.asarray(builtup_frac, dtype="float32").copy()
    new_total = np.zeros(current.shape, dtype=bool)
    placed = 0
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for year in sorted(demands):
        X, _ = build_drivers(
            current, frame, distance_km=distance_km, road_density=road_density,
            population=population, slope=slope, urban_threshold=urban_threshold,
        )
        suit = model.suitability(X, frame.shape)
        step = max(0, int(demands[year]) - placed)
        new = allocate(suit, current, step, frame, urban_threshold=urban_threshold)
        new_total |= new
        current = np.where(new, np.maximum(current, urban_threshold), current).astype("float32")
        placed += int(new.sum())
        out[year] = (suit, new_total.copy())
    return out


def extrapolate_demand(builtup: dict[int, np.ndarray], frame: AnalysisFrame,
                       *, target_year: int, urban_threshold: float = 0.20) -> int:
    """Estimate how many cells convert by `target_year`, from the observed trend.

    A compound growth rate fitted to observed urban extent between the first
    and last epochs supplied. Deliberately simple: with three observed epochs
    (2010, 2015, 2020), anything more elaborate would be fitting noise.
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
