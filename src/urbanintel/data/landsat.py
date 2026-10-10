from __future__ import annotations

import calendar
import logging

from ..aoi import AOI
from . import gee

log = logging.getLogger(__name__)

# Roy et al. (2016) Table 2 OLS coefficients putting TM/ETM+ reflectance on the OLI scale (blue..swir2)
ROY_SLOPE = [0.8474, 0.8483, 0.9047, 0.8462, 0.8937, 0.9071]
ROY_INTERCEPT = [0.0003, 0.0088, 0.0061, 0.0412, 0.0254, 0.0172]

TM_BANDS = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]
OLI_BANDS = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
OUT_BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]


def collections(cfg, year: int) -> list[tuple[str, list[str], bool]]:
    a = cfg.get("sources.gee.assets")
    if year <= 2011:
        out = [(a.get("landsat5", "LANDSAT/LT05/C02/T1_L2"), TM_BANDS, True)]
        if year >= 1999:
            # Landsat 7 SLC-off gaps after May 2003 are filled by the seasonal median
            out.append((a.get("landsat7", "LANDSAT/LE07/C02/T1_L2"), TM_BANDS, True))
        return out
    out = [(a.get("landsat8", "LANDSAT/LC08/C02/T1_L2"), OLI_BANDS, False)]
    if year >= 2022:
        out.append((a.get("landsat9", "LANDSAT/LC09/C02/T1_L2"), OLI_BANDS, False))
    return out


def merged_collection(cfg, aoi: AOI, year: int, *, months: tuple[int, int] = (10, 3), seasons: int = 1):
    ee = gee.ee_init(cfg.get("sources.gee.project", None))
    geom = gee.aoi_geometry(aoi)
    # Same exclusive end date as the original Varanasi export (the month's last day), valid for every month
    windows = []
    for k in range(seasons):
        y = year - k
        last = calendar.monthrange(y, months[1])[1]
        windows.append((f"{y - 1}-{months[0]:02d}-01", f"{y}-{months[1]:02d}-{last:02d}"))
    parts = []
    for start, end in windows:
        for asset, bands, harmonise in collections(cfg, int(end[:4])):
            col = ee.ImageCollection(asset).filterDate(start, end).filterBounds(geom)

            def prep(img, bands=bands, harmonise=harmonise):
                sr = img.select(bands).multiply(0.0000275).add(-0.2)
                if harmonise:
                    sr = sr.multiply(ee.Image.constant(ROY_SLOPE)).add(ee.Image.constant(ROY_INTERCEPT))
                return (sr.rename(OUT_BANDS).updateMask(gee.landsat_clear_mask(img))
                        .copyProperties(img, ["system:time_start"]))

            parts.append(col.map(prep))
    merged = parts[0]
    for p in parts[1:]:
        merged = merged.merge(p)
    return merged, (windows[-1][0], windows[0][1])


def composite(cfg, aoi: AOI, year: int, *, months: tuple[int, int] = (10, 3)):
    merged, (start, end) = merged_collection(cfg, aoi, year, months=months)
    depth = gee.require_composite_depth(
        cfg, merged, f"Landsat {year}",
        floor=int(cfg.get("sources.gee.min_composite_dates_landsat", 4)))
    log.info("  %d: %d clear acquisition dates in %s to %s", year, depth, start, end)
    # Scaled int16 keeps the six-band export under Earth Engine's 50 MB direct-download cap
    return merged.median().rename(OUT_BANDS).multiply(10_000).toInt16().clip(gee.aoi_geometry(aoi))
