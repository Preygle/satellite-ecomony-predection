"""Fit, validate, compare and project the urban expansion models.

    python scripts/run_growth_model.py

Reads the pipeline's processed rasters and:

1. fits two suitability models — logistic regression and random forest — on
   the conversions observed 2010-2015, using identical data;
2. validates both on 2015-2020, a period neither model saw, with the same
   allocation step, so their Figures of Merit are directly comparable;
3. benchmarks them against random allocation and records TOC curves;
4. refits logistic regression without the road driver. OpenStreetMap roads
   are a present-day snapshot, so using them to explain 2010-2015 growth lets
   later information leak into the past; the no-roads model shows how much
   the result depends on that;
5. projects expansion +5 (2025) and +10 (2030) years from 2020 with the
   better of the two models.

Epoch discipline
----------------
GHS-BUILT-S R2023A supplies epochs to 2030, but **only 1975-2020 are
observational; 2025 and 2030 are the GHSL model's own projections.** Only
2010/2015/2020 are used for fitting and validation. GHSL 2025 appears only as
an independent projection to compare against — never as ground truth.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from urbanintel.analysis import growth_model as GM  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("growth_model")


def random_baseline(observed_change: np.ndarray, eligible: np.ndarray,
                    n_draws: int = 20, seed: int = 0) -> dict:
    """Allocate the same demand uniformly at random, repeatedly.

    Without this, a Figure of Merit is uninterpretable — the reader cannot
    tell whether 0.07 reflects real skill or the base rate.
    """
    rng = np.random.default_rng(seed)
    elig_idx = np.flatnonzero(eligible.ravel())
    demand = int((observed_change & eligible).sum())
    obs_flat = observed_change.ravel()

    foms, hits = [], []
    for _ in range(n_draws):
        pick = rng.choice(elig_idx, size=min(demand, len(elig_idx)), replace=False)
        h = int(obs_flat[pick].sum())
        m = demand - h
        fa = demand - h
        foms.append(h / (h + m + fa) if (h + m + fa) else 0.0)
        hits.append(h)
    return {
        "mean_hits": round(float(np.mean(hits)), 1),
        "mean_figure_of_merit": round(float(np.mean(foms)), 5),
        "n_draws": n_draws,
        "demand": demand,
    }


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def write(rdir: Path, name: str, arr: np.ndarray, profile: dict) -> None:
    with rasterio.open(rdir / f"{name}.tif", "w", **profile) as ds:
        ds.write(arr.astype("float32"), 1)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    t_start = time.time()
    cfg = load_config()
    cfg.check_epochs()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    obs = cfg.observational_epochs
    train = tuple(int(y) for y in cfg.get("growth_model.train", [2010, 2015]))
    test = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))
    proj_years = [int(y) for y in cfg.get("growth_model.projection_years", [2025, 2030])]
    rf_cfg = cfg.get("growth_model.random_forest", {}) or {}
    for y in (*train, *test):
        if y not in obs:
            log.error("growth_model epoch %d is not an observational epoch %s", y, obs)
            return 2

    rdir = cfg.processed_dir / "rasters"
    if read(rdir, f"builtup_m2_{obs[-1]}") is None:
        log.error("no processed rasters; run the pipeline first")
        return 2

    cell = fine.res**2
    built = {y: read(rdir, f"builtup_m2_{y}") / cell for y in obs}
    pop = {y: read(rdir, f"population_{y}") for y in obs}
    dist = read(rdir, "distance_km")
    roads = read(rdir, "road_density")
    notes: list[str] = []

    slope = None
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    if slope_p.exists():
        slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0)
    else:
        notes.append("Slope driver unavailable: run scripts/export_review3_layers.py first.")

    def drivers(year: int, *, with_roads: bool = True):
        return GM.build_drivers(built[year], fine, distance_km=dist,
                                road_density=roads if with_roads else None,
                                population=pop[year], slope=slope, urban_threshold=thr)

    t0, t1 = train
    v0, v1 = test
    log.info("observational epochs %s | train %d-%d | test %d-%d", obs, t0, t1, v0, v1)
    for y in obs:
        log.info("  %d urban cells: %d", y, int((built[y] >= thr).sum()))

    X_tr, names = drivers(t0)
    X_te, _ = drivers(v0)

    # ---- logistic regression, all drivers ---------------------------------
    lr = GM.fit(built[t0], built[t1], X_tr, names, fine, period=train, urban_threshold=thr)
    suit_lr_test, _, observed, eligible = GM.validate(lr, built, X_te, fine, test=test,
                                                      urban_threshold=thr)
    log.info("logistic regression  AUC train %.4f  test %.4f  FoM %.4f",
             lr.auc, lr.test_auc, lr.validation.figure_of_merit)

    # ---- logistic regression without roads (leakage check) ----------------
    X_tr_nr, names_nr = drivers(t0, with_roads=False)
    X_te_nr, _ = drivers(v0, with_roads=False)
    lr_nr = GM.fit(built[t0], built[t1], X_tr_nr, names_nr, fine, period=train,
                   urban_threshold=thr)
    GM.validate(lr_nr, built, X_te_nr, fine, test=test, urban_threshold=thr)
    log.info("  ... without roads  AUC test %.4f  FoM %.4f",
             lr_nr.test_auc, lr_nr.validation.figure_of_merit)

    # ---- random forest ------------------------------------------------------
    rf = GM.fit_forest(built[t0], built[t1], X_tr, names, fine, period=train,
                       urban_threshold=thr,
                       n_estimators=int(rf_cfg.get("n_estimators", 300)),
                       min_samples_leaf=int(rf_cfg.get("min_samples_leaf", 20)))
    suit_rf_test, _, _, _ = GM.validate(rf, built, X_te, fine, test=test, urban_threshold=thr)
    rf.importance = GM.permutation_importance_auc(rf, X_te, observed, eligible)
    log.info("random forest        AUC oob %.4f  test %.4f  FoM %.4f",
             rf.auc, rf.test_auc, rf.validation.figure_of_merit)

    baseline = random_baseline(observed, eligible)
    base_fom = baseline["mean_figure_of_merit"]

    toc = {
        "logistic_regression": GM.toc_curve(suit_lr_test, observed, eligible),
        "random_forest": GM.toc_curve(suit_rf_test, observed, eligible),
    }
    n_e = toc["random_forest"]["n_eligible"]
    n_o = toc["random_forest"]["n_observed"]
    toc["random"] = {"flagged": [0, n_e], "hits": [0, n_o], "n_eligible": n_e, "n_observed": n_o}

    models = {"logistic_regression": lr, "logistic_regression_no_roads": lr_nr,
              "random_forest": rf}
    best_name = max(("logistic_regression", "random_forest"),
                    key=lambda k: models[k].validation.figure_of_merit)
    best = models[best_name]
    log.info("better model on the held-out period: %s", best_name)

    # ---- suitability now, both models (for the dashboard) ------------------
    last = obs[-1]
    X_now, _ = drivers(last)
    suit_now = {"logistic_regression": lr.suitability(X_now, fine.shape),
                "random_forest": rf.suitability(X_now, fine.shape)}

    # ---- projection +5 and +10 years from the last observed epoch ---------
    demands = {y: GM.extrapolate_demand(built, fine, target_year=y, urban_threshold=thr)
               for y in proj_years}
    steps = GM.project_steps(
        best, built[last], fine, demands=demands, distance_km=dist,
        road_density=roads if "road_density" in best.driver_names else None,
        population=pop[last], slope=slope if "slope_deg" in best.driver_names else None,
        urban_threshold=thr,
    )
    for y in proj_years:
        log.info("projection %d: demand %d cells (%.2f km2), placed %d",
                 y, demands[y], demands[y] * cell / 1e6, int(steps[y][1].sum()))

    # ---- independent cross-check against the GHSL projection ---------------
    cross = None
    urban_last = built[last] >= thr
    g25 = read(rdir, "builtup_m2_2025_projected")
    if g25 is not None and 2025 in steps:
        ghsl_new = ((g25 / cell) >= thr) & ~urban_last
        ours_equal = GM.allocate(suit_now[best_name], built[last], int(ghsl_new.sum()), fine,
                                 urban_threshold=thr)
        cross = {
            "ghsl_new_urban_cells_2020_2025": int(ghsl_new.sum()),
            "equal_demand": GM.change_metrics(ours_equal, ghsl_new, ~urban_last).as_dict(),
            "our_2025_projection": GM.change_metrics(steps[2025][1], ghsl_new, ~urban_last).as_dict(),
            "note": ("Agreement between two projections, not accuracy: neither 2025 map "
                     "is an observation."),
        }
        log.info("agreement with GHSL's own 2025 projection (equal demand): FoM %.4f",
                 cross["equal_demand"]["figure_of_merit"])

    # ---- write rasters ------------------------------------------------------
    prof = fine.profile("float32")
    write(rdir, "growth_suitability", suit_now[best_name], prof)
    write(rdir, "growth_suitability_lr", suit_now["logistic_regression"], prof)
    write(rdir, "growth_suitability_rf", suit_now["random_forest"], prof)
    for y, (_, new) in steps.items():
        write(rdir, f"pred_new_urban_{y}", new.astype("float32"), prof)
    log.info("wrote suitability surfaces and %s projection rasters", proj_years)

    def km2(n: int) -> float:
        return round(n * cell / 1e6, 2)

    slope_info = None
    if slope is not None:
        slope_info = {
            "dataset": cfg.get("sources.gee.assets.srtm"),
            "median_deg": round(float(np.median(slope)), 2),
            "share_cells_over_2_deg": round(float((slope > 2).mean()), 4),
            "lr_coefficient": round(lr.coefficients.get("slope_deg", float("nan")), 4),
            "rf_importance": rf.importance.get("slope_deg"),
        }

    payload = {
        "epoch_discipline": {
            "observational_epochs": obs,
            "projected_epochs_excluded_from_fitting": cfg.projected_epochs,
            "reason": ("GHS-BUILT-S R2023A epochs after 2020 are the GHSL model's own "
                       "projections, not observations. Fitting or validating against them "
                       "would measure agreement between two models rather than accuracy "
                       "against reality."),
        },
        "train_period": f"{t0}-{t1}",
        "test_period": f"{v0}-{v1}",
        "models": {k: m.as_dict() for k, m in models.items()},
        "random_baseline": baseline,
        "skill_vs_random": {k: (round(m.validation.figure_of_merit / base_fom, 2)
                                if base_fom > 0 else None) for k, m in models.items()},
        "best_model": best_name,
        "best_model_rule": f"higher Figure of Merit on the held-out {v0}-{v1} period",
        "toc": toc,
        "road_leakage_check": {
            "fom_with_roads": round(lr.validation.figure_of_merit, 4),
            "fom_without_roads": round(lr_nr.validation.figure_of_merit, 4),
            "auc_test_with_roads": round(lr.test_auc, 4),
            "auc_test_without_roads": round(lr_nr.test_auc, 4),
            "note": ("OpenStreetMap roads are a present-day snapshot; the model without "
                     "them shows how much the result depends on that later information."),
        },
        "slope_driver": slope_info,
        "projections": {
            str(y): {"from_year": last, "horizon_years": y - last, "model": best_name,
                     "demand_cells": demands[y], "demand_km2": km2(demands[y]),
                     "placed_cells": int(steps[y][1].sum()),
                     "label": "prediction, not observation"}
            for y in proj_years
        },
        "projection_method": (
            f"Demand: compound annual growth of urban extent {obs[0]}-{last}, extrapolated. "
            "Allocation: constrained cellular automaton in five-year steps, each step's growth "
            "feeding the next; roads and population held at their last observed values."),
        "cross_check_vs_ghsl_2025_projection": cross,
        "notes": notes,
        "runtime_s": round(time.time() - t_start, 1),
    }
    out = cfg.outputs_dir / f"{aoi.slug}_growth_model.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("summary -> %s", out)

    print("\n" + "=" * 70)
    print(f"GROWTH MODELS — train {t0}-{t1}, validate {v0}-{v1} (held out)")
    print("=" * 70)
    print(f"  {'model':32s} {'AUC train':>9s} {'AUC test':>9s} {'FoM':>7s} {'x random':>9s}")
    for k, m in models.items():
        print(f"  {k:32s} {m.auc:9.4f} {m.test_auc:9.4f} "
              f"{m.validation.figure_of_merit:7.4f} {payload['skill_vs_random'][k]:9.1f}")
    print(f"  {'random allocation':32s} {'':9s} {0.5:9.4f} {base_fom:7.4f} {1.0:9.1f}")
    print(f"\n  Better model: {best_name}")
    for y in proj_years:
        print(f"  {y} projection   +{km2(demands[y]):.2f} km2 urban extent from {last}")
    if cross:
        print(f"  Agreement with GHSL 2025 projection (equal demand): "
              f"FoM {cross['equal_demand']['figure_of_merit']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
