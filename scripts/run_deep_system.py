from __future__ import annotations

import argparse
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
from urbanintel.deep import analytics as AN  # noqa: E402
from urbanintel.deep import anomaly as AD  # noqa: E402
from urbanintel.deep import boost as BO  # noqa: E402
from urbanintel.deep import embed as EM  # noqa: E402
from urbanintel.deep import ensemble as EN  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402
from urbanintel.deep import tiles as TL  # noqa: E402

log = logging.getLogger("deep_system")


def versions() -> dict:
    """Library versions, because a fitted model is only reproducible against them.

    Re-running the Review 3 script on this machine gives a random forest with a
    Figure of Merit of 0.1016 where the recorded run gave 0.1031 — same code,
    same data, a different scikit-learn. The logistic model reproduces exactly.
    Anything quoted from a forest needs the version beside it.
    """
    import platform

    import sklearn
    import torch
    import xgboost

    return {"python": platform.python_version(), "numpy": np.__version__,
            "scikit_learn": sklearn.__version__, "xgboost": xgboost.__version__,
            "torch": torch.__version__}


def usage() -> str:
    return ("Run the full system: image model, boosted drivers, their blend, the "
            "allocation ensemble and the label-free ghost check.")


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def write(rdir: Path, name: str, arr: np.ndarray, profile: dict) -> None:
    with rasterio.open(rdir / f"{name}.tif", "w", **profile) as ds:
        ds.write(np.asarray(arr).astype("float32"), 1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--checkpoint", default=None,
                    help="image model to load (default: the one the trainer wrote)")
    ap.add_argument("--components", type=int, default=16,
                    help="image components handed to the boosted model")
    ap.add_argument("--draws", type=int, default=20,
                    help="dropout draws behind the conversion probability")
    ap.add_argument("--ensemble", choices=["auto", "seeds", "dropout"], default="auto",
                    help="where the uncertainty comes from: separately trained "
                         "models, or dropout left on at prediction time")
    ap.add_argument("--no-image", action="store_true",
                    help="run the tabular half only, without the image model")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    t_start = time.time()

    cfg = load_config()
    cfg.check_epochs()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    obs = cfg.observational_epochs
    train_period = tuple(int(y) for y in cfg.get("growth_model.train", [2010, 2015]))
    test_period = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))
    t0, t1 = train_period
    v0, v1 = test_period

    rdir = cfg.processed_dir / "rasters"
    if read(rdir, f"builtup_m2_{obs[-1]}") is None:
        log.error("no processed rasters; run the pipeline first")
        return 2
    cell = fine.res**2
    built = {y: read(rdir, f"builtup_m2_{y}") / cell for y in obs}
    pop = {y: read(rdir, f"population_{y}") for y in obs}
    dist = read(rdir, "distance_km")
    roads = read(rdir, "road_density")
    slope = None
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    if slope_p.exists():
        slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0)

    # The image model recorded how it split the study area; every model here
    # reuses that split, so the blend can be fitted where none of them trained.
    img_json = cfg.outputs_dir / f"{aoi.slug}_image_model.json"
    block_km, val_fraction, seed = 8.0, 0.25, args.seed
    ckpt = Path(args.checkpoint) if args.checkpoint else None
    if img_json.exists():
        rec = json.loads(img_json.read_text(encoding="utf-8"))
        block_km = float(rec["spatial_blocks"]["block_km"])
        seed = int(rec["model"]["config"]["seed"])
        ckpt = ckpt or Path(rec["checkpoint"])
    use_image = not args.no_image and ckpt is not None and ckpt.exists()
    if not use_image:
        log.warning("no image model checkpoint; running the tabular half only")

    ids = TL.block_ids(fine.shape, fine, block_m=block_km * 1000.0)
    val_mask, val_blocks = TL.block_split(ids, val_fraction=val_fraction, seed=seed)
    folds = TL.block_folds(ids, n_folds=5, seed=seed)
    log.info("spatial blocks: %d km, %d of %d held out (seed %d)", int(block_km),
             len(val_blocks), len(np.unique(ids)), seed)

    def drivers(year: int):
        return GM.build_drivers(built[year], fine, distance_km=dist, road_density=roads,
                                population=pop[year], slope=slope, urban_threshold=thr)

    X_tr_all, names = drivers(t0)
    X_te_all, _ = drivers(v0)
    label_tr, elig_tr = ST.transition_labels(built[t0], built[t1], urban_threshold=thr)
    label_te, elig_te = ST.transition_labels(built[v0], built[v1], urban_threshold=thr)

    # ---- image model ------------------------------------------------------
    surfaces_train: dict[str, np.ndarray] = {}
    surfaces_test: dict[str, np.ndarray] = {}
    image_info: dict = {}
    comps_info: dict = {}
    X_tr, X_te, feat_names = X_tr_all, X_te_all, list(names)

    if use_image:
        from urbanintel.deep.train import ImageModel, dropout_ensemble, predict_surface

        model = ImageModel.load(ckpt)
        log.info("image model: %s encoder, %s parameters, %d date(s), source %s",
                 model.config.encoder, f"{model.n_parameters:,}", model.n_dates,
                 model.source)

        def stack_for(year: int) -> ST.TemporalStack:
            years = [year - 5, year] if model.n_dates == 2 else [year]
            return ST.driver_stack(built, fine, years=years, distance_km=dist,
                                   road_density=roads, population=pop, slope=slope,
                                   urban_threshold=thr)

        st_tr, st_te = stack_for(t0), stack_for(v0)
        surfaces_train["image"] = predict_surface(model, st_tr, device=args.device)
        surfaces_test["image"] = predict_surface(model, st_te, device=args.device)
        image_info = model.as_dict()

        feats = EM.encoder_surface(model, st_te, device=args.device)
        comps_te, comps_info = EM.pca_components(feats, k=args.components, seed=seed)
        comps_tr, _ = EM.pca_components(EM.encoder_surface(model, st_tr, device=args.device),
                                        k=args.components, seed=seed)
        log.info("image components: %d, holding %.1f%% of the feature variance",
                 comps_info["n_components"], 100 * comps_info["cumulative_variance"])
        X_tr, feat_names = EM.append_components(X_tr_all, names, comps_tr,
                                                np.ones(fine.shape, dtype=bool))
        X_te, _ = EM.append_components(X_te_all, names, comps_te,
                                       np.ones(fine.shape, dtype=bool))

    # ---- tabular models ---------------------------------------------------
    models: dict[str, object] = {}

    lr = GM.fit(built[t0], built[t1], X_tr_all, names, fine, period=train_period,
                urban_threshold=thr)
    GM.validate(lr, built, X_te_all, fine, test=test_period, urban_threshold=thr)
    models["logistic_regression"] = lr
    log.info("logistic regression   test AUC %.4f  FoM %.4f", lr.test_auc,
             lr.validation.figure_of_merit)

    rf = GM.fit_forest(built[t0], built[t1], X_tr_all, names, fine, period=train_period,
                       urban_threshold=thr, n_estimators=300, min_samples_leaf=20)
    GM.validate(rf, built, X_te_all, fine, test=test_period, urban_threshold=thr)
    models["random_forest"] = rf
    log.info("random forest         test AUC %.4f  FoM %.4f", rf.test_auc,
             rf.validation.figure_of_merit)

    Xb, yb, blk = BO.eligible_rows(built[t0], built[t1], X_tr_all, ids, urban_threshold=thr)
    xgb_plain = BO.fit_booster(Xb, yb, blk, feature_names=names, val_blocks=val_blocks,
                               period=train_period, seed=seed)
    GM.validate(xgb_plain, built, X_te_all, fine, test=test_period, urban_threshold=thr)
    xgb_plain.importance = BO.mean_absolute_shap(xgb_plain, Xb, seed=seed)
    models["xgboost"] = xgb_plain
    log.info("xgboost (8 drivers)   test AUC %.4f  FoM %.4f  (%d rounds kept)",
             xgb_plain.test_auc, xgb_plain.validation.figure_of_merit,
             xgb_plain.best_iteration + 1)

    if use_image:
        Xb2, yb2, blk2 = BO.eligible_rows(built[t0], built[t1], X_tr, ids,
                                          urban_threshold=thr)
        xgb_img = BO.fit_booster(Xb2, yb2, blk2, feature_names=feat_names,
                                 val_blocks=val_blocks, period=train_period, seed=seed)
        GM.validate(xgb_img, built, X_te, fine, test=test_period, urban_threshold=thr)
        xgb_img.importance = BO.mean_absolute_shap(xgb_img, Xb2, seed=seed)
        models["xgboost_with_image_components"] = xgb_img
        surfaces_train["tabular"] = xgb_img.suitability(X_tr, fine.shape)
        surfaces_test["tabular"] = xgb_img.suitability(X_te, fine.shape)
        log.info("xgboost + image       test AUC %.4f  FoM %.4f", xgb_img.test_auc,
                 xgb_img.validation.figure_of_merit)
    else:
        surfaces_train["tabular"] = xgb_plain.suitability(X_tr_all, fine.shape)
        surfaces_test["tabular"] = xgb_plain.suitability(X_te_all, fine.shape)

    # ---- the blend, fitted where nothing trained --------------------------
    stacker = None
    if use_image:
        fit_mask = val_mask & elig_tr
        stacker = BO.fit_stacker(surfaces_train, label_tr.astype(bool), fit_mask,
                                 fit_on=f"validation blocks, {t0}-{t1}", seed=seed)
        blend = stacker.blend(surfaces_test)
        sm = BO.SurfaceModel(surface=blend, kind="stacked_image_plus_tabular",
                             extra={"stacker": stacker.as_dict()})
        GM.validate(sm, built, None, fine, test=test_period, urban_threshold=thr)
        models["stacked"] = sm
        log.info("stacked blend         test AUC %.4f  FoM %.4f  weights %s",
                 sm.test_auc, sm.validation.figure_of_merit,
                 {k: round(v, 3) for k, v in stacker.weights.items()})

        img_sm = BO.SurfaceModel(surface=surfaces_test["image"],
                                 kind=f"image_model_{image_info.get('source', '')}")
        GM.validate(img_sm, built, None, fine, test=test_period, urban_threshold=thr)
        models["image_model"] = img_sm
        log.info("image model alone     test AUC %.4f  FoM %.4f", img_sm.test_auc,
                 img_sm.validation.figure_of_merit)

    # ---- analytics for every model ----------------------------------------
    demand = int((label_te.astype(bool) & elig_te).sum())
    observed = label_te.astype(bool)
    edge_km = X_te_all[:, names.index("distance_to_urban_edge_km")].reshape(fine.shape)
    bands = [("distance_centre_km", dist, [0, 3, 6, 9, 12, 30]),
             ("distance_to_urban_edge_km", edge_km, [0, 0.3, 0.6, 1.0, 2.0, 30])]
    baseline = AN.random_allocation_baseline(observed, elig_te, seed=seed)

    reports: dict[str, dict] = {}
    for name, m in models.items():
        surf = m.suitability(X_te if "image" in name and use_image else X_te_all,
                             fine.shape) if not isinstance(m, BO.SurfaceModel) \
            else m.surface
        pred = GM.allocate(surf, built[v0], demand, fine, urban_threshold=thr, seed=seed)
        rep = AN.summarise(name, score=surf, predicted=pred, observed=observed,
                           eligible=elig_te, folds=folds, bands=bands, seed=seed)
        rep["skill_vs_random"] = (
            round(rep["validation"]["figure_of_merit"] / baseline["mean_figure_of_merit"], 1)
            if baseline["mean_figure_of_merit"] else None)
        rep["neighbourhood_weight_sweep"] = AN.neighbourhood_weight_sweep(
            surf, built[v0], observed, elig_te, fine, demand,
            urban_threshold=thr, seed=seed)
        reports[name] = rep

    table = AN.comparison_table(reports, baseline_fom=baseline["mean_figure_of_merit"])
    best_name = table[0]["model"]
    best = models[best_name]
    best_surface = best.surface if isinstance(best, BO.SurfaceModel) else \
        best.suitability(X_te if best_name.endswith("image_components") else X_te_all,
                         fine.shape)
    log.info("best on the held-out period: %s (FoM %.4f)", best_name,
             table[0]["figure_of_merit"])

    # ---- how sure is it? ---------------------------------------------------
    uncertainty = None
    if use_image:
        from urbanintel.deep.train import ImageModel  # noqa: F811

        siblings = sorted(p for p in ckpt.parent.glob(f"{ckpt.stem}_seed*.pt"))
        mode = args.ensemble
        if mode == "auto":
            mode = "seeds" if len(siblings) >= 1 else "dropout"
        if mode == "seeds" and siblings:
            # Separately trained models disagree about more than dropout does:
            # each saw a different draw of tiles and started from different
            # weights, so their spread covers the training run itself, not
            # just the noise left in one fitted network. Dropout draws from
            # each of them fill in the rest.
            members = [ckpt] + siblings
            per = max(1, args.draws // len(members))
            draws = np.stack([predict_surface(ImageModel.load(p), st_te,
                                              device=args.device, mc_dropout=per > 1,
                                              seed=i)
                              for p in members for i in range(per)])
            how = (f"{len(members)} models trained from different seeds x {per} "
                   f"dropout draws each, one allocation per draw")
        else:
            draws = dropout_ensemble(ImageModel.load(ckpt), st_te, n=args.draws,
                                     device=args.device)
            how = ("dropout left on at prediction time, one allocation per draw")
        if stacker is not None:
            draws = np.stack([stacker.blend({"image": d, "tabular": surfaces_test["tabular"]})
                              for d in draws])
        prob, _ = EN.allocation_frequency(draws, built[v0], demand, fine,
                                          urban_threshold=thr)
        entropy = EN.binary_entropy(prob)
        consensus = EN.consensus_prediction(prob, demand, elig_te)
        uncertainty = {
            "draws": int(len(draws)),
            "method": how + "; the map is how often each cell was chosen",
            "suitability_spread": EN.spread(draws),
            "cells_chosen_every_draw": int((prob >= 0.999).sum()),
            "cells_chosen_by_most": int(((prob >= 0.6) & (prob < 0.999)).sum()),
            "cells_chosen_sometimes": int(((prob > 0) & (prob < 0.6)).sum()),
            "consensus_map_metrics": GM.change_metrics(consensus, observed,
                                                       elig_te).as_dict(),
            "mean_entropy_over_chosen_cells": round(float(entropy[prob > 0].mean()), 4),
        }
        write(rdir, "deep_conversion_probability", prob, fine.profile("float32"))
        write(rdir, "deep_conversion_entropy", entropy, fine.profile("float32"))
        log.info("uncertainty over %d draws: %d cells chosen every time, %d most "
                 "of the time, %d sometimes", uncertainty["draws"],
                 uncertainty["cells_chosen_every_draw"],
                 uncertainty["cells_chosen_by_most"],
                 uncertainty["cells_chosen_sometimes"])

    # ---- ghost growth without hand labels ---------------------------------
    ghost = None
    act_names = ["activity_nightlights", "activity_poi", "activity_population",
                 "activity_index", "new_builtup_share"]
    act = [read(rdir, n) for n in act_names]
    residual = read(rdir, "activity_residual")
    if all(a is not None for a in act) and residual is not None:
        A = np.column_stack([np.nan_to_num(a).ravel() for a in act])
        builtnow = (built[obs[-1]] >= thr).ravel()
        normal = builtnow & (np.nan_to_num(residual).ravel() >= 0)
        auto = AD.fit_autoencoder(A, normal, names=act_names, seed=seed)
        err = auto.reconstruction_error(A)
        err_map = np.where(builtnow, err, np.nan).reshape(fine.shape)
        cut = float(np.nanpercentile(err_map, 95))
        flagged = np.nan_to_num(err_map, nan=-1) >= cut
        typ = read(rdir, "typology")
        overlap = None
        if typ is not None:
            rule = typ == 4                       # TYPE_GHOST_GROWTH
            inter = int((flagged & rule).sum())
            overlap = {"rule_cells": int(rule.sum()), "anomaly_cells": int(flagged.sum()),
                       "both": inter,
                       "share_of_rule_cells_found": round(inter / max(int(rule.sum()), 1), 3)}
        ghost = {"model": auto.as_dict(), "threshold_percentile": 95,
                 "threshold_error": round(cut, 5),
                 "agreement_with_rule": overlap,
                 "note": ("An unsupervised second opinion on the activity rule. Neither "
                          "is validated against ground truth yet, so agreement is "
                          "corroboration, not accuracy.")}
        write(rdir, "ghost_anomaly_error", np.nan_to_num(err_map, nan=0.0),
              fine.profile("float32"))
        log.info("ghost anomaly: %d cells above the 95th percentile, %s",
                 int(flagged.sum()),
                 f"{overlap['share_of_rule_cells_found']:.0%} of the rule's cells"
                 if overlap else "no typology raster to compare")

    # ---- write -------------------------------------------------------------
    prof = fine.profile("float32")
    write(rdir, "growth_suitability_deep", best_surface, prof)
    if use_image:
        write(rdir, "growth_suitability_xgb", surfaces_test["tabular"], prof)

    payload = {
        "design": {
            "train_period": f"{t0}-{t1}", "test_period": f"{v0}-{v1}",
            "demand_cells": demand, "demand_km2": round(demand * cell / 1e6, 2),
            "eligible_cells": int(elig_te.sum()),
            "spatial_blocks": {"block_km": block_km, "n_blocks": int(len(np.unique(ids))),
                               "validation_blocks": len(val_blocks), "seed": seed},
            "rule": ("every model is fitted on the same cells, allocated the same demand "
                     "with the same cellular automaton, and scored on the same held-out "
                     "period"),
        },
        "image_model": image_info or None,
        "image_components": comps_info or None,
        "stacker": stacker.as_dict() if stacker else None,
        "models": {k: (m.as_dict() if hasattr(m, "as_dict") else {}) for k, m in models.items()},
        "analytics": reports,
        "comparison": table,
        "random_baseline": baseline,
        "best_model": best_name,
        "environment": versions(),
        "uncertainty": uncertainty,
        "ghost_growth": ghost,
        "runtime_s": round(time.time() - t_start, 1),
    }
    out = cfg.outputs_dir / f"{aoi.slug}_deep_system.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"DEEP SYSTEM — train {t0}-{t1}, test {v0}-{v1} (held out, scored once)")
    print("=" * 78)
    print(f"  {'model':30s} {'AUC':>7s} {'AP':>7s} {'FoM':>7s} {'FoM rank':>9s} "
          f"{'kappa':>7s} {'hits':>6s} {'xrand':>6s}")
    for r in table:
        print(f"  {r['model']:30s} {r['auc_test'] or float('nan'):7.4f} "
              f"{r['average_precision'] or float('nan'):7.4f} "
              f"{r['figure_of_merit'] or float('nan'):7.4f} "
              f"{r['figure_of_merit_rank_only'] or float('nan'):9.4f} "
              f"{r['kappa'] or float('nan'):7.4f} {r['hits'] or 0:6d} "
              f"{r['x_random'] or float('nan'):6.1f}")
    print(f"  {'random allocation':30s} {0.5:7.4f} {'':7s} "
          f"{baseline['mean_figure_of_merit']:7.4f} {'':9s} {'':7s} "
          f"{baseline['mean_hits']:6.1f} {1.0:6.1f}")
    sweep = reports[best_name]["neighbourhood_weight_sweep"]
    print(f"\n  best: {best_name}")
    print(f"  cellular automaton: neighbourhood weight {sweep['weight_in_use']} in use, "
          f"{sweep['best_weight']} best here "
          f"(FoM {sweep['best_figure_of_merit']:.4f})")
    worth = [(r["model"], (r["figure_of_merit_rank_only"] or 0)
              - (r["figure_of_merit"] or 0)) for r in table]
    hurt = [m for m, d in worth if d > 0.005]
    if hurt:
        print(f"  the automaton costs accuracy for: {', '.join(hurt)}")
    print(f"  summary  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
