"""Export every Earth Engine layer for the configured city.

Run once, after authenticating:

    pip install earthengine-api
    earthengine authenticate
    python scripts/gee_export.py --project YOUR_GCP_PROJECT

Downloads land in ``data/raw/gee/`` and are picked up automatically by the
main pipeline on its next run. For an AOI larger than ~50x50 km use
``--drive`` instead, which submits batch tasks to Google Drive.

    python scripts/gee_export.py --project X --only nightlights
    python scripts/gee_export.py --project X --drive
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("gee_export")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--project", default=None, help="Google Cloud project for Earth Engine")
    ap.add_argument("--drive", action="store_true", help="export to Drive instead of downloading")
    ap.add_argument("--scale", type=int, default=None, help="override export scale (m)")
    ap.add_argument("--only", nargs="*", default=None,
                    choices=["nightlights", "ndvi", "ndbi", "lst", "dynamicworld", "buildings"],
                    help="export only these layers")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config(args.config)
    aoi = AOI(cfg)
    scale = args.scale or cfg.get("sources.gee.export_scale_m")
    out = cfg.raw_dir / "gee"
    out.mkdir(parents=True, exist_ok=True)

    try:
        gee.ee_init(args.project or cfg.get("sources.gee.project", None))
    except gee.GEEUnavailable as exc:
        log.error("%s", exc)
        return 2

    log.info("city=%s  scale=%dm  mode=%s", cfg.city, scale, "drive" if args.drive else "download")
    want = set(args.only) if args.only else None

    def wanted(name: str) -> bool:
        return want is None or name in want

    def emit(img, name: str):
        if args.drive:
            gee.export_to_drive(img, aoi, f"{aoi.slug}_{name}", scale=scale)
        else:
            gee.download_image(img, aoi, out / f"{name}.tif", scale=scale)

    failures: list[str] = []

    # --- nightlights: full annual series ---------------------------------
    if wanted("nightlights"):
        y0 = cfg.get("timeseries.nightlights_start")
        y1 = cfg.get("timeseries.nightlights_end")
        log.info("nightlights %d-%d (VIIRS annual)", y0, y1)
        for y in range(y0, y1 + 1):
            try:
                emit(gee.nightlights_image(cfg, aoi, y), f"ntl_{y}")
            except Exception as exc:
                log.warning("  %d failed: %s", y, exc)
                failures.append(f"ntl_{y}")
            time.sleep(0.5)

    # --- NDVI / NDBI at the analysis epochs ------------------------------
    veg_years = [cfg.get("timeseries.vegetation_start"), cfg.get("timeseries.vegetation_end") - 1]
    if wanted("ndvi"):
        for y in veg_years:
            log.info("NDVI %d (Sentinel-2, Oct-Mar)", y)
            try:
                emit(gee.ndvi_image(cfg, aoi, y), f"ndvi_{y}")
            except Exception as exc:
                log.warning("  failed: %s", exc)
                failures.append(f"ndvi_{y}")
    if wanted("ndbi"):
        for y in veg_years:
            log.info("NDBI %d", y)
            try:
                emit(gee.ndbi_image(cfg, aoi, y), f"ndbi_{y}")
            except Exception as exc:
                log.warning("  failed: %s", exc)
                failures.append(f"ndbi_{y}")

    # --- LST --------------------------------------------------------------
    if wanted("lst"):
        for y in (cfg.get("timeseries.thermal_start"), cfg.get("timeseries.thermal_end") - 1):
            log.info("LST %d (Landsat 8/9, pre-monsoon Mar-May)", y)
            try:
                emit(gee.lst_image(cfg, aoi, y, season="premonsoon"), f"lst_{y}")
            except Exception as exc:
                log.warning("  failed: %s", exc)
                failures.append(f"lst_{y}")

    # --- Dynamic World ----------------------------------------------------
    if wanted("dynamicworld"):
        for y in veg_years:
            log.info("Dynamic World %d", y)
            try:
                emit(gee.dynamicworld_image(cfg, aoi, y), f"dw_{y}")
            except Exception as exc:
                log.warning("  failed: %s", exc)
                failures.append(f"dw_{y}")

    # --- Open Buildings temporal (vertical growth) ------------------------
    if wanted("buildings"):
        for y in (2016, 2023):
            log.info("Open Buildings Temporal %d", y)
            try:
                emit(gee.building_height_image(cfg, aoi, y), f"buildings_{y}")
            except Exception as exc:
                log.warning("  failed: %s", exc)
                failures.append(f"buildings_{y}")

    if args.drive:
        log.info("Batch tasks submitted. Track them at "
                 "https://code.earthengine.google.com/tasks")
        log.info("When they finish, copy the GeoTIFFs into %s", out)
    else:
        log.info("Downloads in %s", out)

    if failures:
        log.warning("%d layer(s) failed: %s", len(failures), ", ".join(failures))
        return 1
    log.info("all exports complete — rerun `python -m urbanintel.pipeline`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
