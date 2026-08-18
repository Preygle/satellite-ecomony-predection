"""WorldPop population — optional cross-check, not on the Phase 1 critical path.

GHS-POP is the primary population layer for this system because it is
multi-epoch (2010/2015/2020/2025) and built from the same modelling chain as
GHS-BUILT-S, so population and built-up area are internally consistent.

WorldPop is offered here as an *independent* 2020 estimate for validation:
where the two disagree strongly, the population-derived parts of the
ghost-growth index should be treated with caution. It is a single ~1 GB
country raster, so it is not fetched by default.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from ..aoi import AOI, AnalysisFrame
from ..config import Config
from .download import fetch, head_ok

log = logging.getLogger(__name__)


def build_url(cfg: Config) -> str:
    base = cfg.get("sources.worldpop.base_url")
    variant = cfg.get("sources.worldpop.variant")
    year = cfg.get("sources.worldpop.year")
    iso3 = cfg.get("city.country_iso3").upper()
    iso3l = iso3.lower()
    return f"{base}/{variant}/{year}/BSGM/{iso3}/{iso3l}_ppp_{year}_UNadj_constrained.tif"


def download(cfg: Config, *, force: bool = False) -> Path:
    url = build_url(cfg)
    dest = cfg.raw_dir / "worldpop" / url.rsplit("/", 1)[-1]
    if not dest.exists() and not head_ok(url):
        raise RuntimeError(f"WorldPop URL not reachable: {url}")
    return fetch(url, dest, force=force, expected_min_bytes=1_000_000)


def load_population(cfg: Config, aoi: AOI, frame: AnalysisFrame | None = None) -> np.ndarray:
    """WorldPop persons per analysis cell, density-preserving (see ghsl.to_frame)."""
    frame = frame or aoi.frame()
    path = download(cfg)

    with rasterio.open(path) as ds:
        # Windowed read: only the AOI, not the whole country.
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        b = transform_bounds(frame.crs, ds.crs, *frame.bounds, densify_pts=21)
        win = from_bounds(*b, transform=ds.transform).round_offsets().round_lengths()
        arr = ds.read(1, window=win, boundless=True, fill_value=np.nan).astype("float64")
        src_transform = ds.window_transform(win)
        src_crs = ds.crs
        src_res_x = abs(ds.transform.a)
        src_res_y = abs(ds.transform.e)
        nodata = ds.nodata

    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    arr = np.where(arr < 0, np.nan, arr)

    # persons/cell -> persons/degree^2-ish density; approximate cell area in m^2.
    # WorldPop is in EPSG:4326, so cell area varies with latitude.
    lat_mid = (aoi.bbox_ll[1] + aoi.bbox_ll[3]) / 2.0
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * np.cos(np.radians(lat_mid))
    src_cell_area = (src_res_x * m_per_deg_lon) * (src_res_y * m_per_deg_lat)
    density = arr / src_cell_area

    dst = np.full(frame.shape, np.nan, dtype="float64")
    reproject(
        source=density, destination=dst,
        src_transform=src_transform, src_crs=src_crs, src_nodata=np.nan,
        dst_transform=frame.transform, dst_crs=frame.crs, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return np.clip(dst * (frame.res * frame.res), 0, None).astype("float32")
