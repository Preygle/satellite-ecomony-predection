from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..analysis import growth_model as GM


def eligible_rows(builtup_frac_t0: np.ndarray, builtup_frac_t1: np.ndarray,
                  drivers_t0: np.ndarray, blocks: np.ndarray, *,
                  urban_threshold: float = 0.20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Design matrix, label and block id for every cell that could convert.

    No subsampling: gradient boosting handles 110,000 rows in seconds, and
    keeping every negative means the class ratio the model sees is the real
    one rather than an artefact of the sample.
    """
    eligible = ~(builtup_frac_t0 >= urban_threshold).ravel()
    y = ((builtup_frac_t1 >= urban_threshold).ravel() & eligible)[eligible].astype("int8")
    return drivers_t0[eligible], y, blocks.ravel()[eligible]


@dataclass
class BoostedModel:
    """Fitted gradient-boosted suitability model, scored like the random forest."""

    booster: Any
    driver_names: list[str]
    train_period: tuple[int, int]
    n_train_positive: int
    n_train_total: int
    auc: float                           # validation blocks inside the training period
    params: dict[str, Any] = field(default_factory=dict)
    kind: str = "xgboost"
    best_iteration: int = 0
    test_auc: float | None = None
    validation: GM.ChangeMetrics | None = None
    validation_period: tuple[int, int] | None = None
    importance: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def _dmatrix(self, X: np.ndarray):
        import xgboost as xgb

        return xgb.DMatrix(np.ascontiguousarray(X), feature_names=self.driver_names)

    def probability(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(self._dmatrix(X),
                                    iteration_range=(0, self.best_iteration + 1))

    def suitability(self, X: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        if X.shape[1] != len(self.driver_names):
            raise ValueError(
                f"design matrix has {X.shape[1]} columns but the model was fitted on "
                f"{len(self.driver_names)} features"
            )
        return self.probability(X).reshape(shape).astype("float32")

    def shap_values(self, X: np.ndarray) -> np.ndarray:
        """Exact per-cell feature contributions (TreeSHAP), last column the base value."""
        return self.booster.predict(self._dmatrix(X), pred_contribs=True,
                                    iteration_range=(0, self.best_iteration + 1))

    def as_dict(self) -> dict:
        d = {
            "kind": self.kind,
            "drivers": self.driver_names,
            "params": {k: v for k, v in self.params.items() if k != "nthread"},
            "train_period": f"{self.train_period[0]}-{self.train_period[1]}",
            "n_train_cells": self.n_train_total,
            "n_conversions_observed": self.n_train_positive,
            "boosting_rounds_kept": self.best_iteration + 1,
            "auc_validation_blocks": round(self.auc, 4),
            "auc_test": None if self.test_auc is None else round(self.test_auc, 4),
        }
        if self.importance:
            d["mean_absolute_shap"] = self.importance
        if self.validation:
            d["validation_period"] = f"{self.validation_period[0]}-{self.validation_period[1]}"
            d["validation"] = self.validation.as_dict()
        if self.notes:
            d["notes"] = self.notes
        return d


def fit_booster(
    X: np.ndarray,
    y: np.ndarray,
    blocks: np.ndarray,
    *,
    feature_names: list[str],
    val_blocks: list[int],
    period: tuple[int, int],
    n_rounds: int = 800,
    early_stopping: int = 50,
    seed: int = 0,
    overrides: dict | None = None,
) -> BoostedModel:
    """Train gradient-boosted trees, stopping on spatially held-out blocks.

    Random k-fold cross-validation would leak here: the neighbourhood drivers
    are averages over 500 m and 1,500 m, so a cell and its neighbour share most
    of their features and a random split puts near-copies on both sides.
    Blocks of whole square kilometres are held out instead.

    `scale_pos_weight` is set to the inverse positive rate rather than
    resampling the data, which keeps every observed conversion in the training
    set. The cellular automaton ranks cells and takes the top ones, so the
    scores need to be ordered correctly, not calibrated.
    """
    import xgboost as xgb

    val = np.isin(blocks, val_blocks)
    if val.sum() == 0 or (~val).sum() == 0:
        raise ValueError("validation blocks select all or none of the training cells")
    n_pos = int((y[~val] == 1).sum())
    if n_pos < 30:
        raise ValueError(f"only {n_pos} conversions outside the validation blocks")

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 5,
        "min_child_weight": 20.0,
        "eta": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "scale_pos_weight": float((y[~val] == 0).sum() / max(n_pos, 1)),
        "seed": seed,
        "nthread": -1,
    }
    params.update(overrides or {})

    dtrain = xgb.DMatrix(np.ascontiguousarray(X[~val]), label=y[~val],
                         feature_names=feature_names)
    dval = xgb.DMatrix(np.ascontiguousarray(X[val]), label=y[val],
                       feature_names=feature_names)
    booster = xgb.train(params, dtrain, num_boost_round=n_rounds,
                        evals=[(dval, "blocks")], early_stopping_rounds=early_stopping,
                        verbose_eval=False)
    best = int(getattr(booster, "best_iteration", n_rounds - 1))

    model = BoostedModel(
        booster=booster, driver_names=list(feature_names), train_period=period,
        n_train_positive=int(y.sum()), n_train_total=int(len(y)),
        auc=float(booster.best_score), params=params, best_iteration=best,
        notes=["Boosting rounds chosen by early stopping on held-out spatial blocks "
               "inside the training period."],
    )
    return model


def mean_absolute_shap(model: BoostedModel, X: np.ndarray, *, max_rows: int = 30_000,
                       seed: int = 0) -> dict[str, float]:
    """Average size of each feature's contribution, in log-odds.

    TreeSHAP is exact for trees, so this is not an approximation of the
    model — it is what the model actually did, averaged over cells.
    """
    rng = np.random.default_rng(seed)
    idx = (rng.choice(len(X), size=max_rows, replace=False) if len(X) > max_rows
           else np.arange(len(X)))
    contrib = model.shap_values(X[idx])[:, :-1]
    return {n: round(float(v), 4)
            for n, v in zip(model.driver_names, np.abs(contrib).mean(axis=0))}


@dataclass
class SurfaceModel:
    """Wraps an already-computed suitability surface for the shared scoring path.

    `growth_model.validate` asks a model for `suitability(X, shape)`. The image
    model and the blend produce a surface directly rather than from a design
    matrix, so this adapter hands back the surface and ignores `X`. Everything
    downstream — allocation, Figure of Merit, TOC — then treats every model
    identically, which is the only way the comparison means anything.
    """

    surface: np.ndarray
    kind: str = "surface"
    driver_names: list[str] = field(default_factory=list)
    test_auc: float | None = None
    validation: GM.ChangeMetrics | None = None
    validation_period: tuple[int, int] | None = None
    notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def suitability(self, X: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
        if self.surface.shape != tuple(shape):
            raise ValueError(f"surface is {self.surface.shape}, frame is {tuple(shape)}")
        return self.surface.astype("float32")

    def as_dict(self) -> dict:
        d = {"kind": self.kind,
             "auc_test": None if self.test_auc is None else round(self.test_auc, 4)}
        d.update(self.extra)
        if self.validation:
            d["validation_period"] = f"{self.validation_period[0]}-{self.validation_period[1]}"
            d["validation"] = self.validation.as_dict()
        if self.notes:
            d["notes"] = self.notes
        return d


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    q = np.clip(p.astype("float64"), eps, 1 - eps)
    return np.log(q / (1 - q))


@dataclass
class Stacker:
    """Two weights and an intercept that blend the image and tabular surfaces."""

    weights: dict[str, float]
    intercept: float
    members: list[str]
    n_fit_cells: int
    fit_on: str

    def blend(self, surfaces: dict[str, np.ndarray]) -> np.ndarray:
        z = np.full(next(iter(surfaces.values())).shape, self.intercept, dtype="float64")
        for name in self.members:
            z = z + self.weights[name] * _logit(surfaces[name])
        return (1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))).astype("float32")

    def as_dict(self) -> dict:
        return {"members": self.members,
                "weights": {k: round(v, 4) for k, v in self.weights.items()},
                "intercept": round(self.intercept, 4),
                "fitted_on": self.fit_on, "n_cells": self.n_fit_cells}


def fit_stacker(surfaces: dict[str, np.ndarray], observed: np.ndarray,
                fit_mask: np.ndarray, *, fit_on: str = "validation blocks",
                seed: int = 0) -> Stacker:
    """Fit the blend where neither member was trained.

    Fitting the blend on the training period would just favour whichever model
    overfits hardest; fitting it on the test period would spend the hold-out.
    It is fitted on the validation blocks — held out from both members during
    training, and still inside the training period.
    """
    from sklearn.linear_model import LogisticRegression

    names = list(surfaces)
    rows = fit_mask.ravel()
    X = np.column_stack([_logit(surfaces[n]).ravel()[rows] for n in names])
    y = observed.ravel()[rows].astype("int8")
    if y.min() == y.max():
        raise ValueError("the blend needs both converted and unconverted cells to fit on")
    clf = LogisticRegression(max_iter=1000, class_weight="balanced", C=1.0,
                             random_state=seed).fit(X, y)
    return Stacker(weights={n: float(w) for n, w in zip(names, clf.coef_[0])},
                   intercept=float(clf.intercept_[0]), members=names,
                   n_fit_cells=int(rows.sum()), fit_on=fit_on)
