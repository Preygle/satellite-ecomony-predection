from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np

from ..analysis import growth_model as GM
from ..aoi import AnalysisFrame
from ..config import REPO_ROOT, Config
from ..data import gee
from ..deep import analytics as AN
from ..deep import ensemble as EN
from ..deep import tiles as TL
from ..deep.boost import SurfaceModel
from .prepare import read, write

TRAINER = REPO_ROOT / "scripts" / "train_image_v2.py"
# The exact Review 4 (v5) recipe; only the city configuration changes
RECIPE = ["--factor", "1", "--with-drivers", "--epochs", "250", "--patience", "40",
          "--steps", "20", "--widths", "16", "32", "--dropout", "0.5"]
PATIENCE = 40
EXPECTED_CHANNELS = 45
TEST = (2015, 2020)
FORECAST_FROM = 2020
FORECAST_TO = 2025
EPOCH_LINE = re.compile(r"epoch\s+(\d+)/(\d+)\s+loss\s+([\d.]+)\s+stop AP\s+([\d.na]+)")


class TrainingError(RuntimeError):
    pass


def usable_transitions(cfg: Config) -> list[tuple[int, int]]:
    rdir, gdir = cfg.processed_dir / "rasters", cfg.raw_dir / "gee"
    img = {y for y in range(1975, 2026, 5) if (gdir / f"landsat_{y}.tif").exists()}
    lab = [y for y in range(1975, 2021, 5) if (rdir / f"builtup_m2_{y}.tif").exists()]
    return [(a, a + 5) for a in lab if a + 5 in lab and a in img and a - 5 in img]


def check_design(cfg: Config) -> dict:
    usable = usable_transitions(cfg)
    before = sorted(p for p in usable if p[1] <= TEST[0])
    if TEST not in usable:
        raise TrainingError(f"the test period {TEST[0]}-{TEST[1]} cannot be labelled with the data found")
    if len(before) < 2:
        raise TrainingError("need two labelled transitions before 2015 (one to train on, an older one "
                            f"to stop on); found {before}")
    return {"train": f"{before[-1][0]}-{before[-1][1]}", "stop": f"{before[0][0]}-{before[0][1]}",
            "test": f"{TEST[0]}-{TEST[1]}", "usable": [f"{a}-{b}" for a, b in usable]}


def train_seeds(cfg_path: Path, seeds: list[int], *,
                on_line: Callable[[int, int, str, dict | None], None] | None = None) -> None:
    env = dict(os.environ, URBANINTEL_CONFIG=str(cfg_path), PYTHONUNBUFFERED="1",
               PYTHONIOENCODING="utf-8")
    for i, seed in enumerate(seeds):
        cmd = [sys.executable, "-u", str(TRAINER), *RECIPE, "--forecast-from", str(FORECAST_FROM),
               "--seed", str(seed), "--tag", f"v5_s{seed}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env, cwd=str(REPO_ROOT))
        best, best_epoch, tail = -1.0, 0, []
        for line in proc.stdout:
            line = line.rstrip()
            tail.append(line)
            tail = tail[-40:]
            m = EPOCH_LINE.search(line)
            info = None
            if m:
                epoch, ap = int(m.group(1)), float(m.group(4)) if m.group(4) != "nan" else float("nan")
                if ap == ap and ap > best + 1e-5:
                    best, best_epoch = ap, epoch
                info = {"epoch": epoch, "max_epochs": int(m.group(2)), "loss": float(m.group(3)),
                        "stop_ap": ap, "best_ap": best, "best_epoch": best_epoch,
                        "stops_by": best_epoch + PATIENCE}
            if on_line:
                on_line(i, seed, line, info)
        if proc.wait() != 0:
            raise TrainingError(f"seed {seed} failed:\n" + "\n".join(tail[-12:]))


def _built(cfg: Config, fine: AnalysisFrame) -> dict[int, np.ndarray]:
    rdir = cfg.processed_dir / "rasters"
    out = {}
    for y in range(1975, 2021, 5):
        a = read(rdir / f"builtup_m2_{y}.tif")
        if a is not None:
            out[y] = a / fine.res ** 2
    return out


def _seed_summary(cfg: Config, seed: int) -> dict:
    p = cfg.outputs_dir / f"{cfg.city_slug}_image_model_v5_s{seed}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    a = d["analytics"]
    return {"seed": seed, "figure_of_merit": a["validation"]["figure_of_merit"],
            "kappa": a["validation"].get("kappa"),
            "auc": a["auc_test"], "average_precision": a["average_precision"],
            "best_epoch": d["design"]["best_epoch"], "epochs_run": d["design"]["epochs_run"],
            "parameters": d["design"]["parameters"], "channels": len(d["design"]["channels"]),
            "runtime_s": d["runtime_s"], "train": d["design"]["train"], "stop": d["design"]["stop"]}


def evaluate(cfg: Config, fine: AnalysisFrame, seeds: list[int]) -> dict:
    rdir = cfg.processed_dir / "rasters"
    thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
    built = _built(cfg, fine)
    surfaces = np.stack([read(rdir / f"growth_suitability_image_v5_s{s}.tif") for s in seeds])
    ens = surfaces.mean(axis=0).astype("float32")
    write(rdir / "growth_suitability_image_v5_ensemble.tif", ens, fine)

    sm = SurfaceModel(surface=ens, kind="image_v5_ensemble")
    _, predicted, observed, eligible = GM.validate(sm, built, None, fine, test=TEST,
                                                   urban_threshold=thr)
    folds = TL.block_folds(TL.block_ids(fine.shape, fine, block_m=16_000.0), n_folds=5, seed=0)
    rep = AN.summarise("image_v5_ensemble", score=ens, predicted=predicted, observed=observed,
                       eligible=eligible, folds=folds, seed=0)
    rep["validation"]["kappa"] = round(sm.validation.kappa, 4)
    base = AN.random_allocation_baseline(observed, eligible, seed=0)

    outcome = np.zeros(fine.shape, dtype="float32")
    outcome[built[TEST[0]] >= thr] = 1
    outcome[predicted & observed] = 2
    outcome[~predicted & observed] = 3
    outcome[predicted & ~observed] = 4
    write(rdir / "test_outcome_2015_2020.tif", outcome, fine)

    dist = read(rdir / "distance_km.tif")
    roads = read(rdir / "road_density.tif")
    pop = {y: read(rdir / f"population_{y}.tif") for y in (2010, 2015)}
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0) if slope_p.exists() else None
    lr = GM.fit_and_validate(built, fine, distance_km=dist, road_density=roads, population=pop,
                             slope=slope, train=(2010, 2015), test=TEST, urban_threshold=thr)
    v = rep["validation"]
    fom = v["figure_of_merit"]
    seed_rows = [_seed_summary(cfg, s) for s in seeds]
    channels = sorted({r["channels"] for r in seed_rows})
    # The Review 4 design has 45 channels; fewer means a driver could not be built for every period
    design_note = (None if channels == [EXPECTED_CHANNELS] else
                   f"model trained on {channels} channels instead of {EXPECTED_CHANNELS}; "
                   "a driver was missing for at least one period")
    rand = base["mean_figure_of_merit"]
    return {
        "test_period": f"{TEST[0]}-{TEST[1]}",
        "conversions": int((observed & eligible).sum()), "eligible": int(eligible.sum()),
        "ensemble": {"figure_of_merit": fom, "auc": rep["auc_test"],
                     "average_precision": rep["average_precision"],
                     "average_precision_lift": rep["average_precision_lift"],
                     "kappa": v["kappa"], "hits": v["hits"], "misses": v["misses"],
                     "false_alarms": v["false_alarms"],
                     "producers_accuracy": v["producers_accuracy"],
                     "users_accuracy": v["users_accuracy"]},
        "seeds": seed_rows, "channels": channels, "design_note": design_note,
        "random_baseline": {"figure_of_merit": rand, "hits": base["mean_hits"]},
        "skill_vs_random": round(fom / rand, 1) if rand else None,
        "logistic_regression": {"figure_of_merit": round(lr.validation.figure_of_merit, 4),
                                "auc": round(lr.test_auc, 4), "kappa": round(lr.validation.kappa, 4),
                                "drivers": lr.driver_names},
        "toc": rep.get("toc"), "calibration": rep.get("calibration"),
        "precision_at_k": rep.get("precision_at_k"), "block_stability": rep.get("block_stability"),
    }


def forecast(cfg: Config, fine: AnalysisFrame, seeds: list[int]) -> dict:
    rdir = cfg.processed_dir / "rasters"
    thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
    built = _built(cfg, fine)
    surfaces = np.stack([read(rdir / f"growth_suitability_image_v5_s{s}_from{FORECAST_FROM}.tif")
                         for s in seeds])
    ens = surfaces.mean(axis=0).astype("float32")
    write(rdir / f"growth_forecast_{FORECAST_FROM}_{FORECAST_TO}.tif", ens, fine)
    obs = {y: built[y] for y in (2010, 2015, 2020) if y in built}
    demand = GM.extrapolate_demand(obs, fine, target_year=FORECAST_TO, urban_threshold=thr)
    new = GM.allocate(ens, built[FORECAST_FROM], demand, fine, urban_threshold=thr)
    agree, _ = EN.allocation_frequency(surfaces, built[FORECAST_FROM], demand, fine,
                                       urban_threshold=thr, seeds=list(seeds))
    write(rdir / f"predicted_new_urban_{FORECAST_TO}.tif", new.astype("float32"), fine)
    write(rdir / f"allocation_agreement_{FORECAST_TO}.tif", agree, fine)
    cell_km2 = fine.res ** 2 / 1e6
    urban = {y: round(float((built[y] >= thr).sum()) * cell_km2, 2) for y in obs}
    urban[FORECAST_TO] = round(urban[FORECAST_FROM] + float(new.sum()) * cell_km2, 2)
    placed = new & (agree > 0)
    return {"from": FORECAST_FROM, "to": FORECAST_TO, "demand_cells": int(demand),
            "new_urban_km2": round(float(new.sum()) * cell_km2, 2),
            "urban_extent_km2": urban,
            "demand_rule": "compound growth of the observed urban extent 2010-2020, carried to 2025",
            "seed_agreement": {
                "all_seeds": round(float((agree[new] >= 0.999).mean()), 3) if new.any() else None,
                "majority": round(float((agree[new] > 0.5).mean()), 3) if new.any() else None,
                "any_seed": round(float(placed.sum() / max(new.sum(), 1)), 3)}}
