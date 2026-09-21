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
from urbanintel.data import gee, osm  # noqa: E402
from urbanintel.deep import analytics as AN  # noqa: E402
from urbanintel.deep import boost as BO  # noqa: E402
from urbanintel.deep import features as FE  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402
from urbanintel.deep import tiles as TL  # noqa: E402

log = logging.getLogger("feature_model")


def usage() -> str:
    return ("Fit the growth models on the extended driver set and sweep the "
            "allocation, reporting the Figure of Merit for each combination.")


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--no-poi", action="store_true",
                    help="drop points of interest, which are a present-day snapshot")
    ap.add_argument("--no-roads", action="store_true",
                    help="drop everything derived from OpenStreetMap roads")
    ap.add_argument("--all-transitions", action="store_true",
                    help="train on every labelled transition before the test "
                         "period, not just the configured one")
    ap.add_argument("--block-km", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=0)
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
    train_period = tuple(int(y) for y in cfg.get("growth_model.train", [2010, 2015]))
    test_period = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))
    t0, t1 = train_period
    v0, v1 = test_period
    rdir = cfg.processed_dir / "rasters"

    epochs = [y for y in range(1975, 2026, 5) if (rdir / f"builtup_m2_{y}.tif").exists()]
    built = {y: read(rdir, f"builtup_m2_{y}") / fine.res**2 for y in epochs}
    pop = {y: read(rdir, f"population_{y}") for y in epochs
           if (rdir / f"population_{y}.tif").exists()}
    dist = read(rdir, "distance_km")
    roads_r = read(rdir, "road_density")
    slope = None
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    if slope_p.exists():
        slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0)

    roads = None if args.no_roads else osm.fetch_roads(cfg)
    water = read(rdir, "dw_water_2024")
    poi = None if args.no_poi else read(rdir, "poi_density")

    def ntl(year: int) -> np.ndarray | None:
        p = cfg.raw_dir / "gee" / f"ntl_{year}.tif"
        return gee.to_frame(p, fine) if p.exists() else None

    def design(year: int) -> tuple[np.ndarray, list[str]]:
        return FE.extended_drivers(
            built, fine, year=year, aoi=aoi, distance_km=dist,
            road_density=roads_r if not args.no_roads else None,
            population=pop, slope=slope, roads=roads, water=water,
            nightlights=ntl(year), poi_density=poi, urban_threshold=thr)

    ids = TL.block_ids(fine.shape, fine, block_m=args.block_km * 1000.0)
    log.info("building features for %d and %d ...", t0, v0)
    X_tr, names = design(t0)
    X_te, names_te = design(v0)
    # A feature has to exist at both dates or it cannot be used: night lights
    # start in 2013 and growth momentum needs the epoch before, so the two
    # dates do not automatically offer the same columns. Keeping the
    # intersection is the only honest option -- a column present at one date
    # and zero at the other would teach the model the date, not the place.
    if names != names_te:
        keep = [n for n in names if n in set(names_te)]
        dropped = [n for n in names + names_te if n not in set(keep)]
        X_tr = X_tr[:, [names.index(n) for n in keep]]
        X_te = X_te[:, [names_te.index(n) for n in keep]]
        log.info("dropped %d feature(s) not available at both dates: %s",
                 len(set(dropped)), ", ".join(sorted(set(dropped))))
        names = keep
    base_names = GM.DRIVER_NAMES
    added = [n for n in names if n not in base_names]
    log.info("%d features: %d published + %d new (%s)", len(names),
             len(names) - len(added), len(added), ", ".join(added))

    # Which transitions can supply every feature and a label?
    usable = []
    for a in epochs:
        b = a + 5
        if b in built and b <= v0:
            try:
                _, nm = design(a)
            except Exception:                                   # noqa: BLE001
                continue
            if set(names).issubset(nm):
                usable.append((a, b))
    train_periods = usable if args.all_transitions else [train_period]
    log.info("training transitions: %s",
             ", ".join(f"{a}-{b}" for a, b in train_periods))

    def rows_for(periods):
        Xs, ys, bs = [], [], []
        for a, b in periods:
            Xa, nm = design(a)
            Xa = Xa[:, [nm.index(n) for n in names]]
            xr, yr, br = BO.eligible_rows(built[a], built[b], Xa, ids,
                                          urban_threshold=thr)
            Xs.append(xr), ys.append(yr), bs.append(br)
        return (np.vstack(Xs), np.concatenate(ys), np.concatenate(bs))

    label_te, elig_te = ST.transition_labels(built[v0], built[v1], urban_threshold=thr)
    observed = label_te.astype(bool)
    demand = int((observed & elig_te).sum())
    _, val_blocks = TL.block_split(ids, val_fraction=0.25, seed=args.seed)
    folds = TL.block_folds(ids, n_folds=5, seed=args.seed)
    baseline = AN.random_allocation_baseline(observed, elig_te, seed=args.seed)

    results: dict[str, dict] = {}
    surfaces: dict[str, np.ndarray] = {}

    def score(name: str, surface: np.ndarray) -> None:
        surfaces[name] = surface
        rep = AN.summarise(name, score=surface,
                           predicted=GM.allocate(surface, built[v0], demand, fine,
                                                 urban_threshold=thr, seed=args.seed),
                           observed=observed, eligible=elig_te, folds=folds,
                           seed=args.seed)
        rep["neighbourhood_weight_sweep"] = AN.neighbourhood_weight_sweep(
            surface, built[v0], observed, elig_te, fine, demand,
            urban_threshold=thr, seed=args.seed)
        rep["skill_vs_random"] = round(
            rep["validation"]["figure_of_merit"] / baseline["mean_figure_of_merit"], 1)
        results[name] = rep
        sw = rep["neighbourhood_weight_sweep"]
        log.info("%-28s AUC %.4f  AP %.4f  FoM %.4f  best-weight FoM %.4f (w=%s)",
                 name, rep["auc_test"], rep["average_precision"],
                 rep["validation"]["figure_of_merit"], sw["best_figure_of_merit"],
                 sw["best_weight"])

    # ---- the published eight, as the reference -----------------------------
    Xb_tr, names_b = GM.build_drivers(built[t0], fine, distance_km=dist,
                                      road_density=roads_r, population=pop.get(t0),
                                      slope=slope, urban_threshold=thr)
    Xb_te, _ = GM.build_drivers(built[v0], fine, distance_km=dist,
                                road_density=roads_r, population=pop.get(v0),
                                slope=slope, urban_threshold=thr)
    rf = GM.fit_forest(built[t0], built[t1], Xb_tr, names_b, fine, period=train_period,
                       urban_threshold=thr, n_estimators=300, min_samples_leaf=20)
    score("random_forest_8_drivers", rf.suitability(Xb_te, fine.shape))

    rows_b, y_b, blk_b = BO.eligible_rows(built[t0], built[t1], Xb_tr, ids,
                                          urban_threshold=thr)
    xgb_b = BO.fit_booster(rows_b, y_b, blk_b, feature_names=names_b,
                           val_blocks=val_blocks, period=train_period, seed=args.seed)
    score("xgboost_8_drivers", xgb_b.suitability(Xb_te, fine.shape))

    # ---- the extended set --------------------------------------------------
    from sklearn.ensemble import RandomForestClassifier

    rows_x, y_x, blk_x = rows_for(train_periods)
    log.info("extended sample: %d rows, %d conversions (%.2f%%)", len(y_x),
             int(y_x.sum()), 100 * y_x.mean())
    forest = RandomForestClassifier(n_estimators=300, min_samples_leaf=20,
                                    class_weight="balanced_subsample",
                                    random_state=args.seed, n_jobs=-1)
    forest.fit(rows_x, y_x)
    score("random_forest_extended",
          forest.predict_proba(X_te)[:, 1].reshape(fine.shape).astype("float32"))
    xgb_x = BO.fit_booster(rows_x, y_x, blk_x, feature_names=names,
                           val_blocks=val_blocks, period=train_period, seed=args.seed)
    xgb_x.importance = BO.mean_absolute_shap(xgb_x, rows_x, seed=args.seed)
    score("xgboost_extended", xgb_x.suitability(X_te, fine.shape))

    # ---- what each new feature is worth ------------------------------------
    top = sorted(xgb_x.importance.items(), key=lambda kv: -kv[1])
    log.info("strongest features: %s",
             ", ".join(f"{k} {v:.3f}" for k, v in top[:8]))

    best_name = max(results, key=lambda k: max(
        r["figure_of_merit"] for r in results[k]["neighbourhood_weight_sweep"]["sweep"]))
    best_sweep = results[best_name]["neighbourhood_weight_sweep"]

    prof = fine.profile("float32")
    with rasterio.open(rdir / "growth_suitability_extended.tif", "w", **prof) as ds:
        ds.write(surfaces[best_name].astype("float32"), 1)

    payload = {
        "design": {"train_period": f"{t0}-{t1}", "test_period": f"{v0}-{v1}",
                   "demand_cells": demand, "eligible_cells": int(elig_te.sum()),
                   "features": names, "new_features": added,
                   "points_of_interest_used": not args.no_poi,
                   "roads_used": not args.no_roads},
        "results": results,
        "feature_importance_mean_absolute_shap": xgb_x.importance,
        "random_baseline": baseline,
        "best": {"model": best_name,
                 "figure_of_merit": best_sweep["best_figure_of_merit"],
                 "neighbourhood_weight": best_sweep["best_weight"]},
        "runtime_s": round(time.time() - t_start, 1),
    }
    out = cfg.outputs_dir / f"{aoi.slug}_feature_model.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 96)
    print(f"EXTENDED FEATURES - train {t0}-{t1}, test {v0}-{v1} (held out)")
    print("=" * 96)
    print(f"  {'model':28s} {'AUC':>7s} {'AP':>7s} {'FoM@0.35':>9s} {'best FoM':>9s} "
          f"{'w':>5s} {'hits':>6s}")
    for name, r in results.items():
        sw = r["neighbourhood_weight_sweep"]
        print(f"  {name:28s} {r['auc_test']:7.4f} {r['average_precision']:7.4f} "
              f"{r['validation']['figure_of_merit']:9.4f} "
              f"{sw['best_figure_of_merit']:9.4f} {sw['best_weight']:5.2f} "
              f"{r['validation']['hits']:6d}")
    print(f"  {'random forest, Review 3':28s} {0.8331:7.4f} {0.1270:7.4f} "
          f"{0.1016:9.4f} {0.1097:9.4f} {0.10:5.2f} {224:6d}")
    print(f"\n  best: {best_name} at neighbourhood weight "
          f"{best_sweep['best_weight']} -> Figure of Merit "
          f"{best_sweep['best_figure_of_merit']:.4f}")
    print(f"  summary  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
