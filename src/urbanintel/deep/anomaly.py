from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ActivityAutoencoder:
    """Learns what a normally used built-up cell looks like, and flags the rest.

    Trained only on cells that are built and behaving normally, to reconstruct
    their own activity features. Cells it reconstructs badly are unlike
    anything it was shown — built-up land whose activity does not match its
    development. That is the ghost-growth pattern, found without a single
    hand label, which matters because the project has none yet.
    """

    net: Any
    mean: np.ndarray
    scale: np.ndarray
    names: list[str]
    train_error: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def _standardise(self, X: np.ndarray) -> np.ndarray:
        return (np.nan_to_num(X, nan=0.0) - self.mean) / self.scale

    def reconstruction_error(self, X: np.ndarray) -> np.ndarray:
        Z = self._standardise(X)
        return np.mean((self.net.predict(Z) - Z) ** 2, axis=1).astype("float32")

    def as_dict(self) -> dict:
        return {"kind": "activity_autoencoder", "features": self.names,
                "hidden_layers": list(self.net.hidden_layer_sizes),
                "train_error": self.train_error, "notes": self.notes}


def fit_autoencoder(X: np.ndarray, normal: np.ndarray, *, names: list[str],
                    hidden: tuple[int, ...] = (8, 3, 8), seed: int = 0,
                    max_iter: int = 600) -> ActivityAutoencoder:
    """Fit the reconstruction model on `normal` rows only."""
    from sklearn.neural_network import MLPRegressor

    Xn = np.nan_to_num(np.asarray(X, dtype="float64"), nan=0.0)
    mean = Xn[normal].mean(axis=0)
    scale = Xn[normal].std(axis=0)
    scale[scale < 1e-9] = 1.0
    Z = (Xn[normal] - mean) / scale

    net = MLPRegressor(hidden_layer_sizes=hidden, activation="tanh", solver="adam",
                       max_iter=max_iter, random_state=seed, early_stopping=True,
                       n_iter_no_change=20)
    net.fit(Z, Z)
    err = np.mean((net.predict(Z) - Z) ** 2, axis=1)
    return ActivityAutoencoder(
        net=net, mean=mean, scale=scale, names=list(names),
        train_error={"n_normal_cells": int(normal.sum()),
                     "median": round(float(np.median(err)), 5),
                     "p90": round(float(np.percentile(err, 90)), 5)},
        notes=["Trained only on built-up cells with ordinary activity, so a high "
               "error means 'unlike normal development', not 'badly modelled'."],
    )


def pu_probability(X: np.ndarray, labelled_positive: np.ndarray, *, seed: int = 0,
                   n_estimators: int = 300, holdout: float = 0.3) -> dict:
    """Positive-unlabelled learning from a handful of confirmed empty cells.

    Hand labels can only mark cells that *are* empty; a cell not on the list
    may be occupied or may simply never have been checked, so it cannot be
    treated as a negative. The Elkan and Noto correction handles that: train a
    classifier to separate labelled cells from unlabelled ones, estimate on
    held-out labelled cells how often a true positive gets labelled at all,
    and divide the scores by it.
    """
    from sklearn.ensemble import RandomForestClassifier

    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(labelled_positive)
    if len(pos) < 20:
        raise ValueError(f"need at least 20 labelled cells, got {len(pos)}")
    rng.shuffle(pos)
    cut = max(5, int(round(len(pos) * holdout)))
    held, train_pos = pos[:cut], pos[cut:]

    y = np.zeros(len(X), dtype="int8")
    y[train_pos] = 1
    mask = np.ones(len(X), dtype=bool)
    mask[held] = False

    clf = RandomForestClassifier(n_estimators=n_estimators, min_samples_leaf=5,
                                 class_weight="balanced_subsample", random_state=seed,
                                 n_jobs=-1).fit(np.nan_to_num(X[mask]), y[mask])
    c = float(np.mean(clf.predict_proba(np.nan_to_num(X[held]))[:, 1]))
    raw = clf.predict_proba(np.nan_to_num(X))[:, 1]
    return {
        "probability": np.clip(raw / max(c, 1e-6), 0, 1).astype("float32"),
        "label_frequency_c": round(c, 4),
        "n_labelled": int(len(pos)),
        "n_held_out": int(len(held)),
        "note": ("Probabilities are the classifier's score divided by the estimated "
                 "chance that a truly empty cell got labelled (Elkan and Noto, 2008)."),
    }
