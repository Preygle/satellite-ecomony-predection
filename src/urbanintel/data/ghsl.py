"""GHSL (Global Human Settlement Layer) acquisition — open, no credentials.

Products used
-------------
GHS-BUILT-S  built-up *surface* in m^2 per cell (100 m)  -> urban expansion
GHS-POP      residential population per cell (100 m)     -> activity denominator
GHS-SMOD     settlement class (1 km, categorical)        -> urban/rural reference

Why GHSL is the backbone: it is the only multi-epoch, globally consistent
built-up product that is bulk-downloadable without an account, and its
5-yearly epochs (1975..2030) line up exactly with the analysis years.

Reprojection note
-----------------
GHSL ships in Mollweide (ESRI:54009), an equal-area projection; the analysis
frame is UTM 44N. BUILT_S and POP are *extensive* quantities (m^2 and persons
per cell), so resampling their raw values would not conserve totals. Both are
therefore converted to an intensive density, reprojected bilinearly, and
multiplied back by the target cell area. SMOD is categorical and uses nearest.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject

from ..aoi import AOI, AnalysisFrame
from ..config import Config
from .download import DownloadError, fetch, head_ok, unzip_one

log = logging.getLogger(__name__)

# GHSL Mollweide tiling grid: 1,000,000 m square tiles.
_TILE_M = 1_000_000.0
_GRID_X0 = -18_041_000.0
_GRID_Y0 = 9_020_048.0

# Products whose R2023A release is only published at 1 km.
_RES_OVERRIDE = {"GHS_SMOD": 1000}
# Product version strings differ between products.
_VERSION = {"GHS_BUILT_S": "V1-0", "GHS_POP": "V1-0", "GHS_SMOD": "V2-0"}
# SMOD is published as a single global file, not tiles.
_UNTILED = {"GHS_SMOD"}


@dataclass(frozen=True)
class Tile:
    row: int
    col: int

    def __str__(self) -> str:
        return f"R{self.row}_C{self.col}"


def tile_for(lon: float, lat: float) -> Tile:
    """Return the GHSL Mollweide tile containing a geographic point."""
    t = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    x, y = t.transform(lon, lat)
    col = int(math.floor((x - _GRID_X0) / _TILE_M)) + 1
    row = int(math.floor((_GRID_Y0 - y) / _TILE_M)) + 1
    return Tile(row=row, col=col)


def tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[Tile]:
    """All GHSL tiles intersecting a geographic bbox (usually one for a city)."""
    lon0, lat0, lon1, lat1 = bbox
    corners = [(lon0, lat0), (lon0, lat1), (lon1, lat0), (lon1, lat1)]
    seen: dict[tuple[int, int], Tile] = {}
    for lon, lat in corners:
        t = tile_for(lon, lat)
        seen[(t.row, t.col)] = t
    # Fill any interior tiles spanned by a large bbox.
    rows = [t.row for t in seen.values()]
    cols = [t.col for t in seen.values()]
    out = []
    for r in range(min(rows), max(rows) + 1):
        for c in range(min(cols), max(cols) + 1):
            out.append(Tile(r, c))
    return out


def _product_dirname(product: str, epoch: int, release: str, res: int) -> str:
    return f"{product}_E{epoch}_GLOBE_{release}_54009_{res}"


def build_url(cfg: Config, product: str, epoch: int, tile: Tile | None) -> str:
    """Compose the JRC open-data URL for one GHSL product/epoch/tile."""
    base = cfg.get("sources.ghsl.base_url")
    release = cfg.get("sources.ghsl.release")
    res = _RES_OVERRIDE.get(product, cfg.get("sources.ghsl.resolution_m"))
    version = _VERSION[product]
    vflat = version.replace("-", "_")
    stem = _product_dirname(product, epoch, release, res)

    if product in _UNTILED or tile is None:
        return f"{base}/{product}_GLOBE_{release}/{stem}/{version}/{stem}_{vflat}.zip"
    return (
        f"{base}/{product}_GLOBE_{release}/{stem}/{version}/tiles/"
        f"{stem}_{vflat}_{tile}.zip"
    )


def download_product(cfg: Config, product: str, epoch: int, *, force: bool = False) -> list[Path]:
    """Download and extract every tile of one GHSL product/epoch. Returns GeoTIFFs."""
    raw = cfg.raw_dir / "ghsl"
    tiles: list[Tile | None]
    tiles = [None] if product in _UNTILED else tiles_for_bbox(cfg.bbox)

    out: list[Path] = []
    for tile in tiles:
        url = build_url(cfg, product, epoch, tile)
        name = url.rsplit("/", 1)[-1]
        zip_path = raw / name
        if not zip_path.exists() and not head_ok(url):
            raise DownloadError(f"GHSL URL not reachable: {url}")
        fetch(url, zip_path, force=force, expected_min_bytes=10_000)
        tif = unzip_one(zip_path, ".tif", raw, force=force)
        out.append(tif)
        log.info("%s %s %s -> %s", product, epoch, tile or "global", tif.name)
    return out


# --------------------------------------------------------------------------
# Reprojection onto the analysis frame
# --------------------------------------------------------------------------

def _read_mosaic(paths: list[Path]) -> tuple[np.ndarray, object, object, float]:
    """Read one or more same-CRS tiles into a single array + transform."""
    if len(paths) == 1:
        with rasterio.open(paths[0]) as ds:
            return ds.read(1).astype("float64"), ds.transform, ds.crs, abs(ds.transform.a)
    from rasterio.merge import merge

    srcs = [rasterio.open(p) for p in paths]
    try:
        arr, transform = merge(srcs)
        return arr[0].astype("float64"), transform, srcs[0].crs, abs(srcs[0].transform.a)
    finally:
        for s in srcs:
            s.close()


def to_frame(
    paths: list[Path],
    frame: AnalysisFrame,
    *,
    extensive: bool,
    categorical: bool = False,
    nodata_in: float | None = None,
) -> np.ndarray:
    """Reproject GHSL tiles onto the analysis frame.

    Parameters
    ----------
    extensive
        True for per-cell totals (m^2 built, persons) — converted to density
        before resampling and rescaled to the target cell area afterwards,
        so area/headcount totals are preserved.
    categorical
        True for class rasters — uses nearest-neighbour and skips the
        density conversion.
    """
    src, src_transform, src_crs, src_res = _read_mosaic(paths)

    if nodata_in is not None:
        src = np.where(src == nodata_in, np.nan, src)
    # GHSL uses large negative sentinels for no-data / water in some products.
    src = np.where(src < -1e29, np.nan, src)

    src_cell_area = src_res * src_res
    if extensive and not categorical:
        src = src / src_cell_area  # -> per m^2

    dst = np.full(frame.shape, np.nan, dtype="float64")
    reproject(
        source=src,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=frame.transform,
        dst_crs=frame.crs,
        dst_nodata=np.nan,
        resampling=Resampling.nearest if categorical else Resampling.bilinear,
    )

    if extensive and not categorical:
        dst = dst * (frame.res * frame.res)  # -> per target cell
    return dst.astype("float32")


def load_builtup(cfg: Config, aoi: AOI, epoch: int, frame: AnalysisFrame | None = None) -> np.ndarray:
    """Built-up surface in m^2 per analysis cell, for one epoch."""
    frame = frame or aoi.frame()
    tifs = download_product(cfg, cfg.get("sources.ghsl.products.built_surface"), epoch)
    arr = to_frame(tifs, frame, extensive=True)
    # Built surface cannot exceed the cell area, nor be negative.
    return np.clip(arr, 0.0, frame.res * frame.res).astype("float32")


def load_population(cfg: Config, aoi: AOI, epoch: int, frame: AnalysisFrame | None = None) -> np.ndarray:
    """Residential population per analysis cell, for one epoch."""
    frame = frame or aoi.frame()
    tifs = download_product(cfg, cfg.get("sources.ghsl.products.population"), epoch)
    arr = to_frame(tifs, frame, extensive=True)
    return np.clip(arr, 0.0, None).astype("float32")


def load_smod(cfg: Config, aoi: AOI, epoch: int, frame: AnalysisFrame | None = None) -> np.ndarray:
    """GHS-SMOD settlement class per analysis cell (categorical).

    Classes: 30 urban centre, 23/22/21 dense/semi-dense/suburban cluster,
    13/12/11 village/dispersed/mostly-uninhabited rural, 10 water.
    """
    frame = frame or aoi.frame()
    tifs = download_product(cfg, cfg.get("sources.ghsl.products.settlement_model"), epoch)
    return to_frame(tifs, frame, extensive=False, categorical=True)


# SMOD class codes worth naming rather than repeating as magic numbers.
SMOD_URBAN_CENTRE = 30
SMOD_DENSE_CLUSTER = 23
SMOD_SEMI_DENSE = 22
SMOD_SUBURBAN = 21
SMOD_RURAL_MAX = 13  # anything <= 13 is rural or water
SMOD_WATER = 10


def urban_mask(smod: np.ndarray) -> np.ndarray:
    """Boolean mask of urban-cluster-or-denser cells."""
    return smod >= SMOD_SUBURBAN


def rural_reference_mask(smod: np.ndarray) -> np.ndarray:
    """Rural land cells — the reference population for SUHI intensity.

    Water is excluded: including the Ganga would bias the rural baseline
    cold and inflate apparent heat-island intensity across Varanasi.
    """
    return (smod > SMOD_WATER) & (smod <= SMOD_RURAL_MAX)


# --------------------------------------------------------------------------
# SMOD-free masks
# --------------------------------------------------------------------------
# GHS-SMOD is a 1 km *global* single file (a large download for one city) and
# is itself derived from BUILT_S + POP by thresholding. Deriving the two masks
# we actually need directly from BUILT_S/POP therefore costs no fidelity,
# removes ~1 GB of transfer, and keeps every mask on the 100 m analysis grid
# instead of forcing a 1 km floor onto the thermal analysis.
#
# Set `sources.ghsl.use_smod: true` in config to use the official product
# instead (load_smod above); the class codes are kept for that path.

def urban_mask_from_builtup(
    builtup_m2: np.ndarray, frame: AnalysisFrame, threshold: float = 0.20
) -> np.ndarray:
    """Urban cells: built-up surface fraction at or above `threshold`.

    0.20 is the GHSL-conventional urban-fabric cut and matches the
    `thresholds.builtup.surface_fraction_urban` config value.
    """
    frac = builtup_m2 / (frame.res * frame.res)
    return np.nan_to_num(frac, nan=0.0) >= threshold


def rural_reference_mask_from_builtup(
    builtup_m2: np.ndarray,
    frame: AnalysisFrame,
    *,
    upper_fraction: float = 0.02,
    water: np.ndarray | None = None,
) -> np.ndarray:
    """Rural land cells — the SUHI reference population.

    Cells with under 2% built surface, excluding water. Water must be
    excluded explicitly: the Ganga runs through the AOI and a water-
    contaminated rural baseline reads cold, inflating apparent heat-island
    intensity across the whole city. Pass `water` (e.g. the Dynamic World
    water probability > 0.5) when available.
    """
    frac = np.nan_to_num(builtup_m2 / (frame.res * frame.res), nan=0.0)
    mask = frac < upper_fraction
    if water is not None:
        mask &= ~np.nan_to_num(water, nan=0.0).astype(bool)
    return mask
