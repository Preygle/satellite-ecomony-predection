"""Independent satellite cross-checks of the pipeline's layers.

    python scripts/cross_checks.py

1. **Built-up definitions** — how much of the study area is "built" according
   to six datasets, and how well they agree cell by cell (Cohen's kappa).
   They measure different things (roof area, land cover, a spectral index),
   so they are not expected to match; the point is to know by how much they
   differ and where.
2. **Open Buildings on the typology classes** — do cells the typology calls
   ghost growth or emerging contain buildings in 2023, and did building
   presence and modelled height change 2016-2023? A ghost cell with no
   buildings at all is more likely a GHSL error than an empty development.
3. **Green lost to built-up, matched periods** — NDVI loss 2018-2024 against
   Dynamic World built gain over the same years, next to the Review 2 figure,
   which paired it with GHSL gain over a different period.
4. **Land surface temperature** — Landsat against MODIS on a 1 km grid
   (agreement, bias, and whether both sensors show the same urban-rural
   contrast), and the heat-island change 2013-2024 by typology class.
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from urbanintel.analysis import ghost as A_ghost  # noqa: E402
from urbanintel.analysis import validation as VAL  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("cross_checks")

CLASS_CODES = {name: code for code, name in A_ghost.TYPE_LABELS.items()
               if code != A_ghost.TYPE_UNDEVELOPED}


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def r(x, n: int = 3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    rdir, raw = cfg.processed_dir / "rasters", cfg.raw_dir / "gee"
    cell_km2 = fine.res**2 / 1e6
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    cur = cfg.epoch_current
    dw_year = cfg.get("timeseries.vegetation_end") - 1

    built_m2 = np.nan_to_num(read(rdir, f"builtup_m2_{cur}"))
    frac = np.clip(built_m2 / fine.res**2, 0, 1)
    typ = np.nan_to_num(read(rdir, "typology")).astype(int)
    out: dict = {"study_area_km2": round(aoi.area_km2(), 1), "analysis_grid_m": fine.res}

    # ------------------------------------------------ 1. built-up definitions
    log.info("built-up definitions")
    # Class masks are read with nodata=None: Earth Engine tags 0 as no-data on
    # these uint8 exports, which would drop every "not built" pixel.
    wc = gee.to_frame(raw / "worldcover_built_2021.tif", fine, nodata=None)   # share classed built
    dw_p = raw / f"dw_built_mode_{dw_year}.tif"
    dw = gee.to_frame(dw_p, fine, nodata=None) if dw_p.exists() else np.full(fine.shape, np.nan)
    ob23 = gee.to_frame(raw / "buildings_2023.tif", fine, band=1)
    ndbi = gee.to_frame(raw / "ndbi_2024.tif", fine)
    areas = {
        "GHSL 2020 built surface (roof area)": {
            "dataset": "GHS-BUILT-S R2023A", "km2": r(built_m2.sum() / 1e6, 2),
            "rule": "sum of built surface in every cell"},
        "GHSL 2020 urban extent": {
            "dataset": "GHS-BUILT-S R2023A", "km2": r((frac >= thr).sum() * cell_km2, 2),
            "rule": "cells at least 20% built"},
        "ESA WorldCover 2021 built-up class": {
            "dataset": "ESA/WorldCover/v200", "km2": r(np.nansum(wc) * cell_km2, 2),
            "rule": "10 m pixels classed built-up (class 50)"},
        f"Dynamic World {dw_year} built": {
            "dataset": "GOOGLE/DYNAMICWORLD/V1", "km2": r(np.nansum(dw) * cell_km2, 2),
            "rule": "10 m pixels whose most frequent label over the year is built"},
        "Open Buildings 2023 presence-weighted area": {
            "dataset": "GOOGLE/Research/open-buildings-temporal/v1",
            "km2": r(np.nansum(ob23) * cell_km2, 2),
            "rule": "mean building presence x cell area (an approximate roof area)"},
        "NDBI 2024 > 0": {
            "dataset": "COPERNICUS/S2_SR_HARMONIZED", "km2": r((ndbi > 0).sum() * cell_km2, 2),
            "rule": "cells whose NDBI is above zero"},
    }
    binary = {
        "GHSL urban extent": frac >= thr,
        "WorldCover": np.nan_to_num(wc) >= thr,
        "Dynamic World": np.nan_to_num(dw) >= thr,
        "Open Buildings": np.nan_to_num(ob23) >= thr,
        "NDBI > 0": np.nan_to_num(ndbi, nan=-1) > 0,
    }
    valid = np.isfinite(wc) & np.isfinite(ob23) & np.isfinite(ndbi) & np.isfinite(dw)
    names = list(binary)
    kappa = [[r(VAL.agreement(binary[a], binary[b], valid)["kappa"]) for b in names] for a in names]
    vs = {}
    for n in names[1:]:
        a = VAL.agreement(binary["GHSL urban extent"], binary[n], valid)
        vs[n] = {"kappa": r(a["kappa"]), "both_km2": r(a["both"] * cell_km2, 2),
                 "only_ghsl_km2": r(a["only_a"] * cell_km2, 2),
                 "only_other_km2": r(a["only_b"] * cell_km2, 2)}
    out["builtup_definitions"] = {
        "areas": areas,
        "binary_rule": "a cell counts as built when at least 20% of it is built (GHSL, "
                       "WorldCover, Dynamic World, Open Buildings) or when NDBI > 0",
        "kappa_matrix": {"names": names, "values": kappa},
        "vs_ghsl_urban_extent": vs,
    }

    # ------------------------------------------- 2. Open Buildings by class
    log.info("Open Buildings on the typology classes")
    ob16 = gee.to_frame(raw / "buildings_2016.tif", fine, band=1)
    h16 = gee.to_frame(raw / "buildings_2016.tif", fine, band=2)
    h23 = gee.to_frame(raw / "buildings_2023.tif", fine, band=2)
    has_bld = 0.05                     # at least ~5% of the cell covered by buildings
    per_class = {}
    for name, code in CLASS_CODES.items():
        m = typ == code
        if not m.any():
            continue
        per_class[name] = {
            "cells": int(m.sum()),
            "share_with_buildings_2023": r(float((np.nan_to_num(ob23[m]) >= has_bld).mean())),
            "presence_2016": r(np.nanmean(ob16[m])), "presence_2023": r(np.nanmean(ob23[m])),
            "presence_change": r(np.nanmean(ob23[m] - ob16[m])),
            "height_2016_m": r(np.nanmean(h16[m]), 2), "height_2023_m": r(np.nanmean(h23[m]), 2),
            "height_change_m": r(np.nanmean(h23[m] - h16[m]), 2),
        }
    ghost = typ == A_ghost.TYPE_GHOST_GROWTH
    out["open_buildings_by_class"] = {
        "dataset": "GOOGLE/Research/open-buildings-temporal/v1 (2016 and 2023)",
        "buildings_threshold": has_bld,
        "classes": per_class,
        "ghost_cells": int(ghost.sum()),
        "ghost_cells_without_buildings_2023": int((ghost & (np.nan_to_num(ob23) < has_bld)).sum()),
        "note": ("Presence is the model's per-pixel building confidence, averaged over the "
                 "cell; height is the modelled building height averaged the same way, so it "
                 "is a built-volume indicator rather than the height of any one building."),
    }

    # ------------------------------ 3. green lost to built-up, matched periods
    log.info("green lost to built-up")
    green_lost = np.nan_to_num(read(rdir, "green_lost")) > 0
    new_urban = np.nan_to_num(read(rdir, "new_urban")) > 0
    dw_gain_arr = read(rdir, "dw_built_gain")
    green = {"ndvi_period": f"{cfg.get('timeseries.vegetation_start')}-{dw_year}",
             "green_lost_km2": r(green_lost.sum() * cell_km2, 2),
             "with_ghsl_gain_km2": r((green_lost & new_urban).sum() * cell_km2, 2),
             "ghsl_gain_period": f"{cfg.epoch_baseline}-{cur} (different years)",
             "review2_value_km2": 0.05,
             "review2_basis": "GHSL gain 2010-2025, where 2025 is a GHSL projection"}
    if dw_gain_arr is not None:
        dw_gain = np.nan_to_num(dw_gain_arr) > 0
        green.update({"with_dynamic_world_gain_km2": r((green_lost & dw_gain).sum() * cell_km2, 2),
                      "dynamic_world_gain_period": f"{cfg.get('timeseries.vegetation_start')}-{dw_year} (same years)",
                      "dynamic_world_gain_km2": r(dw_gain.sum() * cell_km2, 2)})
    out["green_lost_to_builtup"] = green

    # --------------------------------------------------- 4. LST cross-checks
    log.info("land surface temperature: Landsat vs MODIS")
    lst_year = cfg.get("timeseries.thermal_end") - 1
    f1k = aoi.frame(1000)
    ls = gee.to_frame(raw / f"lst_{lst_year}.tif", f1k)
    md = gee.to_frame(raw / f"modis_lst_{lst_year}.tif", f1k)
    frac1k = np.clip(np.nan_to_num(gee.to_frame(rdir / f"builtup_m2_{cur}.tif", f1k))
                     / fine.res**2, 0, 1)
    water1k = np.nan_to_num(gee.to_frame(raw / f"dw_{dw_year}.tif", f1k, band=4))
    urban1k = frac1k >= thr
    rural1k = (frac1k < 0.02) & (water1k < 0.5)
    contrast = {}
    for name, arr in (("landsat", ls), ("modis", md)):
        contrast[name] = {
            "urban_mean_c": r(np.nanmean(arr[urban1k]), 2),
            "rural_median_c": r(np.nanmedian(arr[rural1k]), 2),
            "urban_minus_rural_c": r(np.nanmean(arr[urban1k]) - np.nanmedian(arr[rural1k]), 2),
        }
    cmp_ = VAL.paired_comparison(md, ls)
    out["lst_landsat_vs_modis"] = {
        "season": f"March-May {lst_year}",
        "grid_m": 1000,
        "datasets": ["LANDSAT/LC08/C02/T1_L2 + LANDSAT/LC09/C02/T1_L2 (ST_B10)",
                     "MODIS/061/MOD11A2 (LST_Day_1km)"],
        "comparison": {k: r(v) if isinstance(v, float) else v for k, v in cmp_.items()},
        "rank_correlation": {k: r(v) if isinstance(v, float) else v
                             for k, v in VAL.rank_correlation(md, ls).items()},
        "bias_is": "Landsat minus MODIS",
        "urban_rural_contrast": contrast,
        "urban_cells_1km": int(urban1k.sum()), "rural_cells_1km": int(rural1k.sum()),
    }

    suhi = read(rdir, "suhi_intensity")
    chg = read(rdir, "suhi_change")
    hot = np.nan_to_num(read(rdir, "suhi_hotspot")) > 0
    by_class = {}
    for name, code in CLASS_CODES.items():
        m = typ == code
        if m.any():
            by_class[name] = {"suhi_mean_c": r(np.nanmean(suhi[m]), 2),
                              "suhi_change_mean_c": None if chg is None else r(np.nanmean(chg[m]), 2)}
    out["heat_island_by_class"] = {
        "years": [cfg.get("timeseries.thermal_start"), lst_year],
        "classes": by_class,
        "hotspot_km2_by_setting": {
            "urban (>=20% built)": r((hot & (frac >= thr)).sum() * cell_km2, 2),
            "peri-urban (2-20% built)": r((hot & (frac >= 0.02) & (frac < thr)).sum() * cell_km2, 2),
            "rural (<2% built)": r((hot & (frac < 0.02)).sum() * cell_km2, 2),
        },
    }

    p = cfg.outputs_dir / f"{aoi.slug}_cross_checks.json"
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("summary -> %s", p)

    print("\n" + "=" * 70)
    print("CROSS-CHECKS")
    print("=" * 70)
    for k, v in areas.items():
        print(f"  {k:44s} {v['km2']:8.2f} km2")
    for k, v in vs.items():
        print(f"  kappa vs GHSL urban extent — {k:16s} {v['kappa']}")
    ob = out["open_buildings_by_class"]
    print(f"  ghost cells without buildings in 2023: {ob['ghost_cells_without_buildings_2023']} "
          f"of {ob['ghost_cells']}")
    print(f"  Landsat vs MODIS: R2 {out['lst_landsat_vs_modis']['comparison']['r2']}, "
          f"bias {out['lst_landsat_vs_modis']['comparison']['bias']} C")
    for k, v in contrast.items():
        print(f"  {k:8s} urban minus rural: {v['urban_minus_rural_c']} C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
