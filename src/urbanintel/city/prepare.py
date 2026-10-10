from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio

from ..aoi import AOI, AnalysisFrame, distance_to_centre
from ..config import Config
from ..data import gee, ghsl, osm
from .fetch import GHSL_EPOCHS, WATER_YEAR

log = logging.getLogger(__name__)

COMMERCIAL = ["retail", "food_hospitality", "finance_office"]


def write(path: Path, arr: np.ndarray, frame: AnalysisFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **frame.profile("float32")) as ds:
        ds.write(np.asarray(arr, dtype="float32"), 1)


def read(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    with rasterio.open(path) as ds:
        return ds.read(1)


def prepare(cfg: Config, aoi: AOI, fine: AnalysisFrame, *,
            on_step: Callable[[str, str], None] | None = None) -> dict:
    step = on_step or (lambda module, msg: None)
    rdir = cfg.processed_dir / "rasters"
    raw = cfg.raw_dir
    thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
    stats: dict = {"urban_km2": {}, "built_km2": {}, "population": {}}

    for y in GHSL_EPOCHS:
        bp, pp = raw / "ghsl_ee" / f"built_{y}.tif", raw / "ghsl_ee" / f"pop_{y}.tif"
        if bp.exists():
            step("urbanintel.data.ghsl.to_frame", f"GHS-BUILT-S {y} onto the 100 m grid")
            b = np.clip(ghsl.to_frame([bp], fine, extensive=True), 0.0, fine.res ** 2)
            write(rdir / f"builtup_m2_{y}.tif", b, fine)
            frac = np.nan_to_num(b / fine.res ** 2)
            stats["urban_km2"][y] = round(float((frac >= thr).sum()) * fine.res ** 2 / 1e6, 2)
            stats["built_km2"][y] = round(float(np.nansum(b)) / 1e6, 2)
        if pp.exists():
            step("urbanintel.data.ghsl.to_frame", f"GHS-POP {y} onto the 100 m grid")
            p = np.clip(ghsl.to_frame([pp], fine, extensive=True), 0.0, None)
            write(rdir / f"population_{y}.tif", p, fine)
            stats["population"][y] = int(round(float(np.nansum(p))))

    step("urbanintel.aoi.distance_to_centre", "distance to the city centre")
    write(rdir / "distance_km.tif", distance_to_centre(aoi, fine), fine)

    roads = json.loads((raw / "osm" / "roads.json").read_text(encoding="utf-8"))
    step("urbanintel.data.osm.road_density", f"road density from {len(roads['features']):,} ways")
    write(rdir / "road_density.tif", osm.road_density(aoi, roads, fine, weighted=True), fine)
    stats["road_ways"] = len(roads["features"])

    pp = raw / "osm" / "pois.json"
    if pp.exists():
        pois = json.loads(pp.read_text(encoding="utf-8"))
        step("urbanintel.data.osm.poi_density", "points of interest per cell")
        write(rdir / "poi_density.tif", osm.poi_density(aoi, pois, fine), fine)
        write(rdir / "poi_commercial.tif", osm.poi_density(aoi, pois, fine, groups=COMMERCIAL), fine)
        stats["pois"] = {g: len(v) for g, v in pois.items()}

    wp = raw / "gee" / f"dw_water_{WATER_YEAR}.tif"
    step("urbanintel.data.gee.to_frame", f"Dynamic World water probability {WATER_YEAR}")
    water = gee.to_frame(wp, fine, nodata=255) / 100.0
    write(rdir / f"dw_water_{WATER_YEAR}.tif", np.nan_to_num(water, nan=0.0), fine)

    years = []
    for p in sorted((raw / "gee").glob("ntl_*.tif")):
        y = int(p.stem.split("_")[1])
        step("urbanintel.data.gee.to_frame", f"VIIRS {y} onto the 100 m grid")
        write(rdir / f"ntl_{y}.tif", np.nan_to_num(gee.to_frame(p, fine), nan=0.0), fine)
        years.append(y)
    stats["nightlight_years"] = years
    stats["landsat_years"] = sorted(int(p.stem.split("_")[1]) for p in (raw / "gee").glob("landsat_*.tif"))
    stats["cells"] = int(fine.width * fine.height)
    stats["area_km2"] = round(fine.width * fine.height * fine.res ** 2 / 1e6, 1)
    return stats
