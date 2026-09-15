"""Train, test and run the Varanasi urban growth model from the command line.

    python demo/train.py                     random forest, 300 trees, all 8 drivers
    python demo/train.py --model lr          logistic regression
    python demo/train.py --trees 100 --no-roads
    python demo/train.py --permutation       also measure driver importance on the test years
    python demo/train.py --out runs/r1       also write runs/r1.json (metrics) and runs/r1.npz (maps)

Runs offline on the processed rasters. Every step prints what it did, how long
it took and the numbers behind it, so a training run can be followed live.
The demo website runs this same script and streams its output.

Output is plain ASCII so it prints on any Windows console.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import rasterio  # noqa: E402
import sklearn  # noqa: E402

from run_growth_model import random_baseline  # noqa: E402
from urbanintel.analysis import growth_model as GM  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

LABELS = {
    "distance_centre_km": "Distance to city centre",
    "neighbourhood_built_500m": "Built-up within 500 m",
    "neighbourhood_built_1500m": "Built-up within 1.5 km",
    "distance_to_urban_edge_km": "Distance to urban edge",
    "road_density": "Road density",
    "population_density": "Population",
    "builtup_fraction": "Built-up fraction",
    "slope_deg": "Terrain slope",
}
SOURCES = {
    "distance_centre_km": "city centre point",
    "neighbourhood_built_500m": "GHS-BUILT-S",
    "neighbourhood_built_1500m": "GHS-BUILT-S",
    "distance_to_urban_edge_km": "GHS-BUILT-S",
    "road_density": "OpenStreetMap",
    "population_density": "GHS-POP",
    "builtup_fraction": "GHS-BUILT-S",
    "slope_deg": "USGS/SRTMGL1_003",
}
NAMES = {"random_forest": "Random forest", "logistic_regression": "Logistic regression"}
T0 = time.time()
W = 78


def say(msg: str = "") -> None:
    print(msg, flush=True)


def log(tag: str, msg: str) -> None:
    say(f"{time.time() - T0:6.1f}s  [{tag:<8}] {msg}")


def sub(msg: str) -> None:
    say(" " * 19 + msg)


def bar(frac: float, width: int = 24) -> str:
    n = int(round(width * max(0.0, min(1.0, frac))))
    return "#" * n + "." * (width - n)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="train.py",
        description="Train on 2010-2015, test on 2015-2020, predict 2025 and 2030.")
    ap.add_argument("--model", default="rf",
                    choices=["rf", "lr", "random_forest", "logistic_regression"],
                    help="rf = random forest (default), lr = logistic regression")
    ap.add_argument("--trees", type=int, default=300, help="random-forest trees (default 300)")
    ap.add_argument("--no-roads", action="store_true", help="leave out the road-density driver")
    ap.add_argument("--batch", type=int, default=50, help="trees per progress line (default 50)")
    ap.add_argument("--permutation", action="store_true",
                    help="also measure driver importance on the test period (slower)")
    ap.add_argument("--out", help="write <out>.json (metrics) and <out>.npz (maps)")
    a = ap.parse_args()
    kind = {"rf": "random_forest", "lr": "logistic_regression"}.get(a.model, a.model)
    rf = kind == "random_forest"
    roads = not a.no_roads
    timings: dict[str, float] = {}

    say("=" * W)
    say(" VARANASI URBAN GROWTH MODEL  |  train 2010-2015  |  test 2015-2020  |  predict 2025, 2030")
    say("=" * W)
    log("setup", f"python {platform.python_version()} | scikit-learn {sklearn.__version__} | "
                 f"numpy {np.__version__} | {os.cpu_count()} CPU cores")
    log("setup", f"model: {NAMES[kind]}" + (f", {a.trees} trees" if rf else "")
        + ("" if roads else ", without road density"))

    # ---- data ---------------------------------------------------------------
    t = time.time()
    cfg = load_config()
    cfg.check_epochs()
    fine, _ = AOI(cfg).frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    rdir = cfg.processed_dir / "rasters"
    thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
    years = [int(y) for y in cfg.observational_epochs]
    t0, t1, t2 = years
    cell = fine.res ** 2
    km2 = cell / 1e6

    def read(name: str) -> np.ndarray:
        p = rdir / f"{name}.tif"
        if not p.exists():
            raise SystemExit(f"missing {p}; run the analysis pipeline first")
        with rasterio.open(p) as ds:
            return ds.read(1)

    h, w = fine.shape
    log("data", f"grid {h} x {w} = {h * w:,} cells of {fine.res:.0f} m ({h * w * km2:,.0f} km2), "
                "UTM zone 44N")
    log("data", f"epoch check passed: observed GHSL epochs {years}; 2025 is a projection, not used")
    built = {y: read(f"builtup_m2_{y}") / cell for y in years}
    pop = {y: read(f"population_{y}") for y in years}
    dist, road = read("distance_km"), read("road_density")
    sp = cfg.raw_dir / "gee" / "slope.tif"
    slope = np.nan_to_num(gee.to_frame(sp, fine), nan=0.0) if sp.exists() else None
    for y in years:
        log("data", f"GHS-BUILT-S {y}: built-up {np.nansum(built[y]) * km2:6.2f} km2 | "
                    f"urban cells (>= {thr:.0%} built): {int((built[y] >= thr).sum()):,}")
    timings["load"] = time.time() - t
    log("data", f"read {2 * len(years) + 3} rasters in {timings['load']:.1f}s")

    # ---- features -------------------------------------------------------------
    t = time.time()
    log("features", f"measuring the drivers of every cell in {t0} (training) and {t1} (test)")

    def drivers(year: int):
        return GM.build_drivers(built[year], fine, distance_km=dist,
                                road_density=road if roads else None,
                                population=pop[year], slope=slope, urban_threshold=thr)

    X_tr, names = drivers(t0)
    X_te, _ = drivers(t1)
    elig0 = ~(built[t0] >= thr).ravel()
    sub(f"{'#':>2}  {'driver':<27} {'source':<17} {'min':>8} {'mean':>8} {'max':>8}")
    for i, n in enumerate(names):
        col = X_tr[elig0, i]
        sub(f"{i + 1:>2}  {n:<27} {SOURCES.get(n, ''):<17} "
            f"{col.min():8.3f} {col.mean():8.3f} {col.max():8.3f}")
    timings["features"] = time.time() - t
    log("features", f"design matrix {X_tr.shape[0]:,} rows x {X_tr.shape[1]} columns "
                    f"({X_tr.nbytes / 1e6:.1f} MB), built in {timings['features']:.1f}s")

    # ---- sample ---------------------------------------------------------------
    y_all = ((built[t1] >= thr).ravel() & elig0)
    n_el, n_pos = int(elig0.sum()), int(y_all.sum())
    log("sample", f"eligible = not urban in {t0}: {n_el:,} cells | became urban by {t1}: "
                  f"{n_pos:,} ({100 * n_pos / n_el:.2f}%)")
    log("sample", f"class imbalance 1 : {(n_el - n_pos) / n_pos:.0f} -> balanced class weights")

    # ---- train ----------------------------------------------------------------
    t = time.time()
    if rf:
        log("train", f"random forest | {a.trees} trees | >= 20 cells per leaf | "
                     f"balanced_subsample | seed 0 | parallel on {os.cpu_count()} cores")

        def progress(done: int, total: int) -> None:
            log("train", f"  trees {done:>4}/{total}  [{bar(done / total)}]  {time.time() - t:5.1f}s")

        m = GM.fit_forest(built[t0], built[t1], X_tr, names, fine, period=(t0, t1),
                          urban_threshold=thr, n_estimators=a.trees, progress=progress,
                          batch=a.batch)
        depth = [e.get_depth() for e in m.estimator.estimators_]
        leaves = [e.get_n_leaves() for e in m.estimator.estimators_]
        timings["train"] = time.time() - t
        log("train", f"trained in {timings['train']:.1f}s | tree depth {min(depth)}-{max(depth)} | "
                     f"about {int(np.mean(leaves)):,} leaves per tree")
        log("train", f"out-of-bag AUC {m.auc:.4f} (each cell scored only by trees that never saw it)")
    else:
        log("train", "logistic regression | drivers standardised (mean 0, sd 1) | "
                     "balanced class weights | C = 1.0 | lbfgs solver")
        m = GM.fit(built[t0], built[t1], X_tr, names, fine, period=(t0, t1), urban_threshold=thr)
        timings["train"] = time.time() - t
        log("train", f"trained in {timings['train']:.2f}s | intercept {m.intercept:+.3f}")
        log("train", f"AUC on the training cells {m.auc:.4f} (in-sample; the test AUC is the honest one)")

    # ---- test -----------------------------------------------------------------
    t = time.time()
    log("test", f"{t1} -> {t2} held out: drivers measured in {t1}; the model never saw these years")
    _, pred, obs, elig = GM.validate(m, built, X_te, fine, test=(t1, t2), urban_threshold=thr)
    v = m.validation
    demand = int(obs.sum())
    log("test", f"ranking: AUC {m.test_auc:.4f} over {int(elig.sum()):,} eligible cells "
                "(0.5 = random, 1 = perfect)")
    log("test", "allocation: cellular automaton, 8 rounds, score = 0.65 x suitability "
                "+ 0.35 x urban share within 300 m")
    log("test", f"placed {int(pred.sum()):,} cells = the {demand:,} that really became urban")
    sub(f"{'':22}{'really urban':>14}{'not urban':>14}")
    sub(f"{'predicted urban':<22}{v.hits:>14,}{v.false_alarms:>14,}")
    sub(f"{'predicted not urban':<22}{v.misses:>14,}{v.correct_rejections:>14,}")
    log("test", f"Figure of Merit {v.figure_of_merit:.4f} = hits / (hits + misses + false alarms)")
    log("test", f"producer's accuracy {v.producers_accuracy:.1%} | kappa {v.kappa:.3f} | overall "
                f"accuracy {v.overall_accuracy:.1%} (all 'no change': {v.null_overall_accuracy:.1%})")
    base = random_baseline(obs, elig)
    skill = v.figure_of_merit / base["mean_figure_of_merit"] if base["mean_figure_of_merit"] else 0.0
    log("baseline", f"random placement of the same {demand:,} cells, 20 draws: {base['mean_hits']} "
                    f"hits, FoM {base['mean_figure_of_merit']:.4f}")
    log("baseline", f"the model is {skill:.1f}x better than random placement")
    timings["test"] = time.time() - t

    # ---- importance -------------------------------------------------------------
    if rf:
        imp = dict(zip(names, (float(x) for x in m.estimator.feature_importances_)))
        title = "importance while training (share of splitting gain)"
    else:
        imp = dict(m.coefficients)
        title = "weights (per standard deviation; negative lowers the chance)"
    log("drivers", title)
    top = max(abs(x) for x in imp.values()) or 1.0
    for n, x in sorted(imp.items(), key=lambda kv: -abs(kv[1])):
        sub(f"{n:<27} {x:+8.3f}  {bar(abs(x) / top, 20)}")
    if rf and not a.permutation:
        sub("(measured on the training years; --permutation measures it on the test years,")
        sub(" where shuffling population actually raises the AUC: a candidate to drop)")
    if rf and a.permutation:
        tp = time.time()
        perm = GM.permutation_importance_auc(m, X_te, obs, elig)
        log("drivers", f"on the test years: drop in AUC when each driver is shuffled "
                       f"({time.time() - tp:.1f}s)")
        for n, x in sorted(perm.items(), key=lambda kv: -kv[1]):
            sub(f"{n:<27} {x:+8.4f}")

    # ---- predict ----------------------------------------------------------------
    t = time.time()
    u0, u2 = int((built[t0] >= thr).sum()), int((built[t2] >= thr).sum())
    rate = (u2 / u0) ** (1 / (t2 - t0)) - 1
    demands = {y: GM.extrapolate_demand(built, fine, target_year=y, urban_threshold=thr)
               for y in (2025, 2030)}
    log("predict", f"demand: urban extent grew {rate:.2%} a year {t0}-{t2} -> "
                   f"{demands[2025]:,} new cells by 2025, {demands[2030]:,} by 2030")
    steps = GM.project_steps(m, built[t2], fine, demands=demands, distance_km=dist,
                             road_density=road if roads else None, population=pop[t2],
                             slope=slope, urban_threshold=thr)
    n25, n30 = int(steps[2025][1].sum()), int(steps[2030][1].sum())
    log("predict", f"step {t2} -> 2025: placed {n25:,} cells (+{n25 * km2:.2f} km2)")
    log("predict", f"step 2025 -> 2030: drivers rebuilt from the 2025 map, placed {n30 - n25:,} "
                   f"more (+{(n30 - n25) * km2:.2f} km2)")
    log("predict", "roads and population held at 2020 values; these are predictions, not observations")
    timings["predict"] = time.time() - t

    total = time.time() - T0
    metrics = {
        "model": NAMES[kind],
        "roads": roads,
        "trees": a.trees if rf else None,
        "drivers": [LABELS.get(n, n) for n in names],
        "train_period": f"{t0}-{t1}",
        "test_period": f"{t1}-{t2}",
        "train_cells": m.n_train_total,
        "train_positive": m.n_train_positive,
        "auc_train": round(m.auc, 3),
        "auc_train_kind": "out-of-bag" if rf else "on the training cells",
        "auc_test": round(m.test_auc, 3),
        "demand": demand,
        "hits": v.hits,
        "misses": v.misses,
        "false_alarms": v.false_alarms,
        "figure_of_merit": round(v.figure_of_merit, 4),
        "producers_accuracy": round(v.producers_accuracy * 100, 1),
        "kappa": round(v.kappa, 3),
        "overall_accuracy": round(v.overall_accuracy * 100, 1),
        "null_accuracy": round(v.null_overall_accuracy * 100, 1),
        "random_hits": base["mean_hits"],
        "random_fom": base["mean_figure_of_merit"],
        "skill": round(skill, 1),
        "demand_2025": demands[2025],
        "demand_2030": demands[2030],
        "pred_2025_km2": round(n25 * km2, 2),
        "pred_2030_km2": round(n30 * km2, 2),
        "importance_title": ("Importance of each driver while training (share of splitting gain)"
                             if rf else "Weight of each driver (per standard deviation)"),
        "importance": [[LABELS.get(n, n), round(x, 3)]
                       for n, x in sorted(imp.items(), key=lambda kv: -abs(kv[1]))],
        "seconds": round(total, 1),
        "timings": {k: round(x, 2) for k, x in timings.items()},
    }
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(p.with_suffix(".npz"), suit=steps[2025][0].astype("float32"),
                            pred=pred, obs=obs, urban_test_start=built[t1] >= thr,
                            urban_now=built[t2] >= thr, new25=steps[2025][1],
                            new30=steps[2030][1])
        p.with_suffix(".json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        log("save", f"metrics -> {p.with_suffix('.json').name}, maps -> {p.with_suffix('.npz').name}")

    say("-" * W)
    say(f" RESULT  {NAMES[kind]}: test AUC {m.test_auc:.3f} | Figure of Merit "
        f"{v.figure_of_merit:.4f} ({skill:.1f}x random)")
    say(f"         predicted +{n25 * km2:.2f} km2 by 2025, +{n30 * km2:.2f} km2 by 2030")
    say(f" TIME    {total:.1f}s total = " + ", ".join(f"{k} {x:.1f}s" for k, x in timings.items()))
    say("-" * W)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
