from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ..aoi import AOI, AnalysisFrame
from ..config import Config

log = logging.getLogger(__name__)

_EE: Any = None


class GEEUnavailable(RuntimeError):
    """Raised when Earth Engine is not installed or not authenticated."""


def ee_init(project: str | None = None):
    """Import and initialise Earth Engine, with an actionable error if it fails."""
    global _EE
    if _EE is not None:
        return _EE
    try:
        import ee  # noqa: PLC0415
    except ImportError as exc:
        raise GEEUnavailable(
            "earthengine-api is not installed. `pip install earthengine-api`"
        ) from exc

    try:
        ee.Initialize(project=project) if project else ee.Initialize()
    except Exception as exc:  # ee raises a variety of auth errors
        raise GEEUnavailable(
            "Earth Engine is not authenticated.\n"
            "  1) pip install earthengine-api\n"
            "  2) earthengine authenticate\n"
            "  3) set gee_project in config, or pass project=...\n"
            f"underlying error: {exc}"
        ) from exc

    _EE = ee
    return ee


def aoi_geometry(aoi: AOI):
    ee = ee_init()
    lon0, lat0, lon1, lat1 = aoi.bbox_ll
    return ee.Geometry.Rectangle([lon0, lat0, lon1, lat1], proj="EPSG:4326", geodesic=False)


# --------------------------------------------------------------------------
# Per-layer server-side composites
# --------------------------------------------------------------------------

def viirs_annual_asset(cfg: Config, year: int) -> str:
    """The VNL collection that actually holds `year`.

    The Earth Engine catalogue splits the annual VNL V2 series across two
    assets: ``ANNUAL_V21`` carries 2013-2021 and ``ANNUAL_V22`` carries 2022
    onward. Querying V2.2 for 2013 returns an *empty* collection rather than
    an error, so a single hard-coded asset silently loses nine of the twelve
    configured years — and the nightlight trend, which needs the long end of
    the series most, is exactly what would be lost.

    V2.1 and V2.2 share the same core compositing algorithm, so the join is a
    version step rather than a sensor change. It is still a discontinuity and
    is recorded as such in the layer provenance.
    """
    cutover = int(cfg.get("sources.gee.assets.viirs_annual_legacy_last_year", 2021))
    if year <= cutover:
        legacy = cfg.get("sources.gee.assets.viirs_annual_legacy", None)
        if legacy:
            return legacy
    return cfg.get("sources.gee.assets.viirs_annual")


def nightlights_image(cfg: Config, aoi: AOI, year: int):
    """VIIRS annual average radiance (nW/cm^2/sr) for `year`.

    Uses the ``average_masked`` band, which nulls background/noise pixels —
    important because the raw ``average`` band's low-level noise floor would
    otherwise register as spurious activity in unlit peri-urban cells.
    """
    ee = ee_init()
    asset = viirs_annual_asset(cfg, year)
    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(aoi_geometry(aoi))
    )
    if col.size().getInfo() == 0:
        raise ValueError(
            f"no VIIRS annual image for {year} in {asset}. "
            "The VNL series is split across ANNUAL_V21 (2013-2021) and "
            "ANNUAL_V22 (2022-); check sources.gee.assets in the config."
        )
    band = "average_masked"
    img = col.select(band).mean().rename("nightlights")
    return img.unmask(0).clip(aoi_geometry(aoi))


def require_composite_depth(cfg: Config, col, label: str, *, floor: int | None = None) -> int:
    """Reject a composite built from too few distinct acquisition dates.

    A median composite over 1-2 dates is not a seasonal median — it is a
    single observation with that day's phenology, haze and view geometry baked
    in. Comparing such a composite against a full-season one measures the
    difference in *sampling*, not the difference on the ground.

    This is not hypothetical. The Sentinel-2 L2A archive is sparse before
    ~2018: the Oct-Mar 2015 window over Varanasi contains three scenes from a
    single day, against 148 scenes on 35 days for 2024. Differencing the two
    produced an apparent green-cover rise from 27.9% to 77.9% — an artefact of
    compositing depth that would otherwise have been reported as a finding.

    Returns the number of distinct dates; raises if below the configured floor.
    `floor` overrides the configured Sentinel-2 floor — Landsat revisits every
    8 days with two satellites (16 with one), so a three-month Landsat window
    can never reach the Sentinel-2 floor of 20 and needs its own.
    """
    ee = ee_init()
    if floor is None:
        floor = int(cfg.get("sources.gee.min_composite_dates", 20))
    millis_per_day = 86_400_000
    days = col.aggregate_array("system:time_start").map(
        lambda t: ee.Number(t).divide(millis_per_day).floor()
    ).distinct().size().getInfo()
    if days < floor:
        raise ValueError(
            f"{label}: composite has only {days} distinct acquisition date(s), "
            f"below the floor of {floor}. A composite this shallow is not "
            f"comparable against a full-season one. Move the epoch to a year "
            f"with dense coverage, or lower sources.gee.min_composite_dates "
            f"deliberately if you accept the bias."
        )
    log.info("  %s: %d distinct acquisition dates", label, days)
    return days


def _s2_cloud_mask(img):
    """Mask cloud and cirrus using the QA60 bitmask."""
    ee = ee_init()
    qa = img.select("QA60")
    cloud_bit = 1 << 10
    cirrus_bit = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0))
    return img.updateMask(mask).divide(10000).copyProperties(img, ["system:time_start"])


def truecolour_image(cfg: Config, aoi: AOI, year: int):
    """Sentinel-2 true-colour composite — what the ground actually looks like.

    Red, Green and Blue surface reflectance (bands B4, B3, B2), median over the
    same October-March window used for the vegetation indices so the scene is
    directly comparable with them.

    Every other Earth Engine layer in this project is a derived index. This one
    is the plain photograph, and it is what makes the rest legible to someone
    seeing the study area for the first time.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)
    asset = cfg.get("sources.gee.assets.s2_sr")
    max_cloud = cfg.get("sources.gee.max_cloud_pct")

    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-10-01", f"{year + 1}-03-31")
        .filterBounds(geom)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    )
    require_composite_depth(cfg, col, f"true colour {year}")
    comp = col.map(_s2_cloud_mask).median()
    return comp.select(["B4", "B3", "B2"]).rename(["red", "green", "blue"]).clip(geom)


def ndvi_image(cfg: Config, aoi: AOI, year: int):
    """Sentinel-2 NDVI, growing-season median.

    Restricted to Oct-Mar: Varanasi's Jun-Sep monsoon is heavily clouded, and
    a full-year median would mix post-monsoon flush with dry-season senescence,
    making inter-annual green-cover change unreadable.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)
    asset = cfg.get("sources.gee.assets.s2_sr")
    max_cloud = cfg.get("sources.gee.max_cloud_pct")

    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-10-01", f"{year + 1}-03-31")
        .filterBounds(geom)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    )
    require_composite_depth(cfg, col, f"NDVI {year}")
    comp = col.map(_s2_cloud_mask).median()
    return comp.normalizedDifference(["B8", "B4"]).rename("ndvi").clip(geom)


def ndbi_image(cfg: Config, aoi: AOI, year: int):
    """Sentinel-2 NDBI (built-up index), same seasonal window as NDVI."""
    ee = ee_init()
    geom = aoi_geometry(aoi)
    asset = cfg.get("sources.gee.assets.s2_sr")
    max_cloud = cfg.get("sources.gee.max_cloud_pct")
    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-10-01", f"{year + 1}-03-31")
        .filterBounds(geom)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    )
    require_composite_depth(cfg, col, f"NDBI {year}")
    comp = col.map(_s2_cloud_mask).median()
    return comp.normalizedDifference(["B11", "B8"]).rename("ndbi").clip(geom)


def lst_image(cfg: Config, aoi: AOI, year: int, *, season: str = "premonsoon"):
    """Landsat 8/9 land surface temperature in degrees Celsius.

    `season` = "premonsoon" (Mar-May) targets the period when the surface
    urban heat island in the Indo-Gangetic plain is strongest and most
    policy-relevant; "annual" averages all clear scenes.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)

    if season == "premonsoon":
        start, end = f"{year}-03-01", f"{year}-05-31"
    else:
        start, end = f"{year}-01-01", f"{year}-12-31"

    def prep(img):
        return (landsat_lst_celsius(img).updateMask(landsat_clear_mask(img))
                .rename("lst").copyProperties(img, ["system:time_start"]))

    cols = []
    for key in ("landsat8", "landsat9"):
        asset = cfg.get(f"sources.gee.assets.{key}", None)
        if not asset:
            continue
        cols.append(ee.ImageCollection(asset).filterDate(start, end).filterBounds(geom))
    if not cols:
        raise ValueError("no Landsat assets configured")

    merged = cols[0]
    for c in cols[1:]:
        merged = merged.merge(c)
    require_composite_depth(
        cfg, merged, f"LST {year}",
        floor=int(cfg.get("sources.gee.min_composite_dates_landsat", 4)),
    )
    return merged.map(prep).median().rename("lst").clip(geom)


# Collection 2 Level-2 QA_PIXEL bits that mark a pixel as unusable:
# 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow. Masking only 3 and 4
# lets cloud edges and thin cirrus through, and both read several degrees
# cooler than the ground beneath them.
LANDSAT_QA_MASK_BITS = (1, 2, 3, 4)


def landsat_clear_mask(img):
    """True where none of the cloud-related QA_PIXEL bits is set."""
    qa = img.select("QA_PIXEL")
    bad = 0
    for bit in LANDSAT_QA_MASK_BITS:
        bad |= 1 << bit
    return qa.bitwiseAnd(bad).eq(0)


def landsat_lst_celsius(img):
    """ST_B10 to degrees Celsius, using the published Collection 2 scale/offset."""
    return img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)


def dynamicworld_image(cfg: Config, aoi: AOI, year: int):
    """Dynamic World class probabilities, annual mean (built / trees / grass)."""
    ee = ee_init()
    geom = aoi_geometry(aoi)
    asset = cfg.get("sources.gee.assets.dynamic_world")
    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(geom)
        .select(["built", "trees", "grass", "water", "crops"])
    )
    return col.mean().clip(geom)


def dynamicworld_built_mode_image(cfg: Config, aoi: AOI, year: int):
    """1 where Dynamic World's most frequent label over `year` is built (class 6).

    Each Dynamic World image carries a ``label`` band — the most likely class
    on that date. The most frequent label over the year gives one land-cover
    map, comparable with ESA WorldCover's classes. The annual-mean
    probabilities (`dynamicworld_image`) cannot do this: without the bare,
    shrub and flooded-vegetation bands, "built is the largest of the five
    exported probabilities" is true over much of the dry-season farmland.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)
    col = (ee.ImageCollection(cfg.get("sources.gee.assets.dynamic_world"))
           .filterDate(f"{year}-01-01", f"{year}-12-31")
           .filterBounds(geom)
           .select("label"))
    return col.mode().eq(6).unmask(0).toUint8().rename("dw_built_mode").clip(geom)


def building_height_image(cfg: Config, aoi: AOI, year: int):
    """Open Buildings Temporal: building presence + height for `year` (2016-2023).

    This is the vertical dimension the other layers miss. A cell whose
    built-up *area* is flat but whose mean building height is rising is
    densifying, not expanding — a distinction that matters for both the
    growth typology and the ghost-growth test.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)
    asset = cfg.get("sources.gee.assets.open_buildings_temporal")
    if not (2016 <= year <= 2023):
        raise ValueError(f"Open Buildings Temporal covers 2016-2023, got {year}")
    col = (
        ee.ImageCollection(asset)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(geom)
        .select(["building_presence", "building_height", "building_fractional_count"])
    )
    return col.mosaic().clip(geom)


def slope_image(cfg: Config, aoi: AOI):
    """Terrain slope in degrees from the SRTM 1 arc-second DEM (USGS/SRTMGL1_003)."""
    ee = ee_init()
    dem = ee.Image(cfg.get("sources.gee.assets.srtm"))
    return ee.Terrain.slope(dem).rename("slope_deg").clip(aoi_geometry(aoi))


def worldcover_built_image(cfg: Config, aoi: AOI):
    """1 where ESA WorldCover 2021 (v200) classes the 10 m pixel as built-up (class 50)."""
    ee = ee_init()
    wc = ee.ImageCollection(cfg.get("sources.gee.assets.esa_worldcover")).first()
    # uint8 keeps a 10 m export of the AOI near 12 MB, well inside the direct
    # download cap; a default integer type would be four times that.
    return wc.select("Map").eq(50).toUint8().rename("wc_built").clip(aoi_geometry(aoi))


def modis_lst_image(cfg: Config, aoi: AOI, year: int):
    """MODIS/061/MOD11A2 daytime LST in degrees Celsius, mean over March-May.

    An independent sensor for checking the Landsat LST. Only pixels whose
    quality flag (QC_Day bits 0-1) reports the LST as produced are kept.
    """
    ee = ee_init()
    geom = aoi_geometry(aoi)

    def prep(img):
        good = img.select("QC_Day").bitwiseAnd(3).lte(1)
        lst = img.select("LST_Day_1km").multiply(0.02).subtract(273.15)
        return lst.updateMask(good).copyProperties(img, ["system:time_start"])

    col = (ee.ImageCollection(cfg.get("sources.gee.assets.modis_lst"))
           .filterDate(f"{year}-03-01", f"{year}-05-31").filterBounds(geom))
    return col.map(prep).mean().rename("modis_lst").clip(geom)


def worldpop_density_image(cfg: Config, aoi: AOI, year: int):
    """WorldPop/GP/100m/pop for India as persons per hectare.

    WorldPop stores persons *per pixel* on a 3 arc-second grid (~84 x 92 m at
    Varanasi). Downloading that on a 100 m grid samples pixel counts as if
    each covered a full hectare and understates the total by roughly a fifth.
    Dividing by the native pixel area first turns it into a density, which
    survives the change of grid; persons per 100 m cell is then the density
    itself (1 ha = one cell).
    """
    ee = ee_init()
    col = (ee.ImageCollection(cfg.get("sources.gee.assets.worldpop_gp"))
           .filter(ee.Filter.eq("country", "IND"))
           .filter(ee.Filter.eq("year", year)))
    img = col.first()
    native_area = ee.Image.pixelArea().reproject(img.projection())
    return (img.divide(native_area).multiply(1e4)
            .rename("pop_per_ha").clip(aoi_geometry(aoi)))


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def download_image(
    img, aoi: AOI, dest: Path, *, scale: int = 30, force: bool = False,
) -> Path:
    """Fetch a server-side image to a local GeoTIFF via getDownloadURL.

    Suitable for a city-sized AOI (Varanasi at 30 m is ~1300x1100 px, a few
    MB). For larger areas use `export_to_drive` instead — EE caps direct
    downloads at 32 MB / 262144 pixels per band per request.
    """
    import requests

    dest = Path(dest)
    if dest.exists() and not force:
        log.info("cached: %s", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    url = img.getDownloadURL({
        "region": aoi_geometry(aoi),
        "scale": scale,
        "crs": aoi.crs_m,
        "format": "GEO_TIFF",
    })
    log.info("downloading EE image -> %s", dest.name)
    r = requests.get(url, stream=True, timeout=600)
    r.raise_for_status()
    tmp = dest.with_suffix(".part")
    with tmp.open("wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    tmp.replace(dest)
    return dest


def export_to_drive(img, aoi: AOI, description: str, *, scale: int = 30, folder: str = "urbanintel"):
    """Start a Drive export task — the route for AOIs too large to download directly."""
    ee = ee_init()
    task = ee.batch.Export.image.toDrive(
        image=img,
        description=description,
        folder=folder,
        region=aoi_geometry(aoi),
        scale=scale,
        crs=aoi.crs_m,
        maxPixels=1e10,
        fileFormat="GeoTIFF",
    )
    task.start()
    log.info("started Drive export task: %s", description)
    return task


def to_frame(path: Path, frame: AnalysisFrame, *, categorical: bool = False,
             band: int = 1, nodata: float | str | None = "file") -> np.ndarray:
    """Reproject one band of a downloaded EE GeoTIFF onto the analysis frame.

    `band` is 1-based, as in rasterio. Multi-band exports keep the band order
    of the Earth Engine image — e.g. Dynamic World is built, trees, grass,
    water, crops (see `dynamicworld_image`).

    `nodata` = "file" uses the no-data value recorded in the GeoTIFF; None
    ignores it. Earth Engine records 0 as no-data on some integer exports.
    For a 0/1 class mask that silently drops every "0 = not this class"
    pixel, and the cell average becomes 1 wherever the class appears at all —
    so class masks must be read with ``nodata=None``.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    with rasterio.open(path) as ds:
        src = ds.read(band).astype("float64")
        nd = ds.nodata if nodata == "file" else nodata
        if nd is not None:
            src = np.where(src == nd, np.nan, src)
        dst = np.full(frame.shape, np.nan, dtype="float64")
        reproject(
            source=src, destination=dst,
            src_transform=ds.transform, src_crs=ds.crs, src_nodata=np.nan,
            dst_transform=frame.transform, dst_crs=frame.crs, dst_nodata=np.nan,
            resampling=Resampling.nearest if categorical else Resampling.average,
        )
    return dst.astype("float32")
