"""Fit, validate and project the urban expansion model.

    python scripts/run_growth_model.py

Reads the Phase 1 processed rasters, fits the transition model on observed
conversions, validates it on a held-out later period, benchmarks it against
a random-allocation baseline, and projects future expansion.

Epoch discipline
----------------
GHS-BUILT-S R2023A supplies epochs to 2030, but **only 1975-2020 are
observational; 2025 and 2030 are the GHSL model's own projections.**
Training or validating against them would be fitting one model to another
model's output. This script therefore uses only 2010/2015/2020 for fitting
and validation, and treats GHSL 2025 purely as an independent projection to
compare against — never as ground truth.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from urbanintel.analysis import growth_model as GM  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402

log = logging.getLogger("growth_model")

OBSERVATIONAL_EPOCHS = (2010, 2015, 2020)
PROJECTED_EPOCHS = (2025, 2030)


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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    fine, coarse = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")

    rdir = cfg.processed_dir / "rasters"
    if not rdir.exists():
        log.error("no processed rasters; run the pipeline first")
        return 2
    L = {os.path.basename(p)[:-4]: rasterio.open(p).read(1) for p in glob.glob(str(rdir / "*.tif"))}

    cell = fine.res**2
    built = {y: L[f"builtup_m2_{y}"] / cell for y in OBSERVATIONAL_EPOCHS}
    pop = {y: L[f"population_{y}"] for y in OBSERVATIONAL_EPOCHS}
    dist = L["distance_km"]
    roads = L.get("road_density")

    log.info("observational epochs: %s", OBSERVATIONAL_EPOCHS)
    for y in OBSERVATIONAL_EPOCHS:
        log.info("  %d urban cells: %d", y, int((built[y] >= thr).sum()))

    # ---- fit and validate ------------------------------------------------
    log.info("fitting 2010-2015, validating 2015-2020")
    model = GM.fit_and_validate(
        built, fine, distance_km=dist, road_density=roads, population=pop,
        train=(2010, 2015), test=(2015, 2020), urban_threshold=thr,
    )

    urban_15 = built[2015] >= thr
    urban_20 = built[2020] >= thr
    observed = urban_20 & ~urban_15
    baseline = random_baseline(observed, ~urban_15)

    v = model.validation.as_dict()
    skill = (v["figure_of_merit"] / baseline["mean_figure_of_merit"]
             if baseline["mean_figure_of_merit"] > 0 else float("nan"))

    log.info("  AUC (train)        %.4f", model.auc)
    log.info("  Figure of Merit    %.4f", v["figure_of_merit"])
    log.info("  random baseline    %.5f", baseline["mean_figure_of_merit"])
    log.info("  skill vs random    %.1fx", skill)
    log.info("  Kappa              %.4f", v["kappa"])

    # ---- projection ------------------------------------------------------
    demand_2030 = GM.extrapolate_demand(built, fine, target_year=2030, urban_threshold=thr)
    log.info("projecting 2020 -> 2030, demand %d cells (%.2f km2)",
             demand_2030, demand_2030 * cell / 1e6)

    suit, new_2030 = GM.project(
        model, built[2020], fine, distance_km=dist, road_density=roads,
        population=pop[2020], demand_cells=demand_2030, urban_threshold=thr,
    )

    # ---- independent cross-check against the GHSL projection -------------
    cross = None
    ghsl_2025_path = rdir / "builtup_m2_2025.tif"
    if ghsl_2025_path.exists():
        ghsl25 = rasterio.open(ghsl_2025_path).read(1) / cell
        ghsl_new = (ghsl25 >= thr) & ~urban_20
        our_new_25 = GM.allocate(suit, built[2020], int(ghsl_new.sum()), fine,
                                 urban_threshold=thr)
        agree = GM.change_metrics(our_new_25, ghsl_new, ~urban_20)
        cross = agree.as_dict()
        log.info("agreement with GHSL's own 2025 projection: FoM %.4f", cross["figure_of_merit"])

    # ---- write outputs ---------------------------------------------------
    out = cfg.outputs_dir
    prof = fine.profile("float32")
    for name, arr in [("growth_suitability", suit),
                      ("predicted_new_urban_2030", new_2030.astype("float32"))]:
        with rasterio.open(rdir / f"{name}.tif", "w", **prof) as ds:
            ds.write(arr.astype("float32"), 1)
    log.info("wrote suitability and 2030 projection rasters")

    payload = {
        "epoch_discipline": {
            "observational_epochs": list(OBSERVATIONAL_EPOCHS),
            "projected_epochs_excluded_from_fitting": list(PROJECTED_EPOCHS),
            "reason": (
                "GHS-BUILT-S R2023A epochs 2025 and 2030 are the GHSL model's own "
                "projections, not observations. Fitting or validating against them "
                "would measure agreement between two models rather than accuracy "
                "against reality."
            ),
        },
        "model": model.as_dict(),
        "random_baseline": baseline,
        "skill_vs_random": round(skill, 2) if np.isfinite(skill) else None,
        "projection_2030": {
            "demand_cells": demand_2030,
            "demand_km2": round(demand_2030 * cell / 1e6, 2),
            "method": "compound annual growth of urban extent, 2010-2020, extrapolated",
        },
        "cross_check_vs_ghsl_2025_projection": cross,
    }
    (out / f"{aoi.slug}_growth_model.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    log.info("summary -> %s", out / f"{aoi.slug}_growth_model.json")

    print("\n" + "=" * 66)
    print("GROWTH MODEL — fitted on observational epochs only")
    print("=" * 66)
    print(f"  Train 2010-2015 · validate 2015-2020 (held out)")
    print(f"  AUC (train)         {model.auc:.4f}")
    print(f"  Figure of Merit     {v['figure_of_merit']:.4f}")
    print(f"  Random baseline     {baseline['mean_figure_of_merit']:.5f}")
    print(f"  Skill vs random     {skill:.1f}x")
    print(f"  Kappa               {v['kappa']:.4f}")
    print(f"  Hits / observed     {v['hits']} / {v['hits'] + v['misses']}")
    print(f"\n  2030 projection     +{demand_2030 * cell / 1e6:.2f} km2 urban extent")
    if cross:
        print(f"  Agreement w/ GHSL   FoM {cross['figure_of_merit']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
