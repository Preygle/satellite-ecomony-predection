"""Record when each layer's imagery was actually acquired.

    python scripts/collect_layer_dates.py

Writes ``dataset_viewer/dates.js``. For the Earth Engine layers the dates are
queried from the image collections themselves — the first and last acquisition
that went into each composite, and how many distinct days contributed — rather
than assumed from the year in the filename. For the open-path datasets the
epoch is fixed by the product, and the download date is taken from the file.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("layer_dates")
ROOT = Path(__file__).resolve().parents[1]


def window(ee, col):
    """First and last acquisition, and the number of distinct days."""
    n = col.size().getInfo()
    if not n:
        return None
    times = sorted(col.aggregate_array("system:time_start").getInfo())
    fmt = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b %Y")  # noqa: E731
    days = len({t // 86_400_000 for t in times})
    return {"first": fmt(times[0]), "last": fmt(times[-1]), "scenes": n, "days": days}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    cfg = load_config()
    aoi = AOI(cfg)
    ee = gee.ee_init(cfg.get("sources.gee.project", None))
    geom = gee.aoi_geometry(aoi)
    s2 = cfg.get("sources.gee.assets.s2_sr")
    max_cloud = cfg.get("sources.gee.max_cloud_pct")
    veg_year = cfg.get("timeseries.vegetation_end") - 1

    out: dict[str, dict] = {}

    # Official identifiers, written exactly as the provider publishes them.
    IDENT = {
        "truecolour":   ("COPERNICUS/S2_SR_HARMONIZED", "ESA / Copernicus", "True-colour satellite image"),
        "ndvi":         ("COPERNICUS/S2_SR_HARMONIZED", "ESA / Copernicus", "Vegetation index (NDVI)"),
        "ndbi":         ("COPERNICUS/S2_SR_HARMONIZED", "ESA / Copernicus", "Built-up index (NDBI)"),
        "nightlights":  ("NOAA/VIIRS/DNB/ANNUAL_V21 (2013-2021) + NOAA/VIIRS/DNB/ANNUAL_V22 (2022-)",
                         "NOAA", "Nighttime lights"),
        "lst":          ("LANDSAT/LC08/C02/T1_L2 + LANDSAT/LC09/C02/T1_L2", "USGS",
                         "Land surface temperature"),
        "dynamicworld": ("GOOGLE/DYNAMICWORLD/V1", "Google", "Land cover"),
        "buildings":    ("GOOGLE/Research/open-buildings-temporal/v1", "Google", "Building height"),
        "builtup":      ("GHS-BUILT-S R2023A", "European Commission Joint Research Centre", "Built-up surface"),
        "population":   ("GHS-POP R2023A", "European Commission Joint Research Centre", "Population"),
        "poi":          ("OpenStreetMap, via the Overpass API", "OpenStreetMap contributors", "Points of interest"),
        "roads":        ("OpenStreetMap, via the Overpass API", "OpenStreetMap contributors", "Road network"),
    }

    # --- Sentinel-2 composites (true colour, NDVI, NDBI share one window) ---
    s2col = (ee.ImageCollection(s2)
             .filterDate(f"{veg_year}-10-01", f"{veg_year + 1}-03-31")
             .filterBounds(geom)
             .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))
    w = window(ee, s2col)
    if w:
        for key, res in [("truecolour", "20 m"), ("ndvi", "20 m"), ("ndbi", "15 m")]:
            out[key] = {
                "composite": f"Median of {w['scenes']} Sentinel-2 scenes on {w['days']} separate days",
                "window": f"{w['first']} – {w['last']}",
                "season": "Post-monsoon to dry season (October–March), chosen to avoid monsoon cloud",
                "export": f"Exported at {res}",
            }
    log.info("Sentinel-2 window: %s", w)

    # --- VIIRS nighttime lights: one annual composite -----------------------
    ntl_year = cfg.get("timeseries.nightlights_end")
    asset = gee.viirs_annual_asset(cfg, ntl_year)
    out["nightlights"] = {
        "composite": f"Annual composite for {ntl_year}, cloud- and moonlight-filtered by the provider",
        "window": f"01 Jan {ntl_year} – 31 Dec {ntl_year}",
        "season": f"Full year. Series held covers 2013–{ntl_year}, twelve annual composites",
        "export": f"From {asset.rsplit('/', 1)[-1]}, 463 m",
    }

    # --- Landsat land surface temperature -----------------------------------
    # Landsat 8 AND 9 — the composite uses both, so the record must count both.
    lst_year = cfg.get("timeseries.thermal_end") - 1
    lcol = None
    for key in ("landsat8", "landsat9"):
        asset = cfg.get(f"sources.gee.assets.{key}", None)
        if asset:
            c = (ee.ImageCollection(asset)
                 .filterDate(f"{lst_year}-03-01", f"{lst_year}-05-31")
                 .filterBounds(geom))
            lcol = c if lcol is None else lcol.merge(c)
    w = window(ee, lcol)
    out["lst"] = {
        "composite": (f"Median of {w['scenes']} Landsat 8 and 9 scenes on {w['days']} separate days"
                      if w else f"Landsat 8 and 9, pre-monsoon {lst_year}"),
        "window": f"{w['first']} – {w['last']}" if w else f"Mar–May {lst_year}",
        "season": "Pre-monsoon (March–May), the hottest, clearest part of the year",
        "export": "30 m",
    }
    log.info("Landsat window: %s", w)

    # --- Dynamic World -------------------------------------------------------
    # The pipeline uses the Jan-Dec annual MEAN of the class probabilities
    # (gee.dynamicworld_image), so that is the window recorded here.
    dw = cfg.get("sources.gee.assets.dynamic_world")
    dcol = (ee.ImageCollection(dw)
            .filterDate(f"{veg_year}-01-01", f"{veg_year}-12-31")
            .filterBounds(geom))
    w = window(ee, dcol)
    out["dynamicworld"] = {
        "composite": (f"Mean class probability of {w['scenes']} classifications on {w['days']} "
                      f"separate days" if w else f"Dynamic World {veg_year}"),
        "window": f"{w['first']} – {w['last']}" if w else f"Jan – Dec {veg_year}",
        "season": ("Full calendar year. Used for water (heat-island rural reference) and for "
                   "built-up gain 2018-2024, matched to the NDVI years"),
        "export": "60 m",
    }
    log.info("Dynamic World window: %s", w)

    # --- Open Buildings Temporal --------------------------------------------
    out["buildings"] = {
        "composite": "Annual mosaic for 2023",
        "window": "01 Jan 2023 – 31 Dec 2023",
        "season": "Full year. Product covers 2016–2023",
        "export": "30 m, from 4 m native",
    }

    # --- Open-path datasets: fixed product epochs, plus our download date ----
    def downloaded(rel: str) -> str:
        p = ROOT / rel
        if not p.exists():
            return "unknown"
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %Y")

    ghsl_dl = downloaded("data/processed/rasters/builtup_m2_2020.tif")
    for key, label in [("builtup", "built-up surface"), ("population", "population")]:
        out[key] = {
            "composite": f"GHSL {label} for the 2020 epoch",
            "window": "2020 epoch (product covers 1975–2020 observed, five-yearly)",
            "season": "Not seasonal — a modelled annual product",
            "export": f"100 m. Downloaded {ghsl_dl}",
        }

    osm_dl = downloaded("data/processed/rasters/poi_density.tif")
    for key, label in [("poi", "points of interest"), ("roads", "roads")]:
        out[key] = {
            "composite": f"OpenStreetMap {label}, as mapped at the time of download",
            "window": f"Snapshot taken {osm_dl}",
            "season": "Not seasonal — a live database, so this is a point-in-time extract",
            "export": "Vector, gridded to 100 m",
        }

    for key, rec in out.items():
        ident = IDENT.get(key)
        if ident:
            rec["dataset"], rec["provider"], rec["label"] = ident

    viewer = ROOT / "dataset_viewer" / "dates.js"
    viewer.write_text("const LAYER_DATES = " + json.dumps(out, indent=2, ensure_ascii=False) + ";\n",
                      encoding="utf-8")

    # A plain JSON copy, so the Streamlit dashboard reads the same record
    # rather than keeping a second, drifting copy of these dates.
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "layer_dates.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("wrote %s and outputs/layer_dates.json (%d layers)", viewer, len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
