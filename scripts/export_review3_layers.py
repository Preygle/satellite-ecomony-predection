"""Export the extra Earth Engine layers the Review 3 checks need.

    python scripts/export_review3_layers.py              # skip files already present
    python scripts/export_review3_layers.py --force-lst  # re-export LST with the stricter cloud mask

Everything lands in ``data/raw/gee`` beside the pipeline's own exports, so the
pipeline and the validation scripts read one shared cache.

| File                        | Official dataset                             | Used by                     |
|-----------------------------|----------------------------------------------|-----------------------------|
| lst_2013.tif, lst_2024.tif  | LANDSAT/LC08/C02/T1_L2 + LANDSAT/LC09/C02/T1_L2 | heat-island change (WP2, WP5) |
| dw_2018.tif                 | GOOGLE/DYNAMICWORLD/V1                        | green lost to built-up, matched 2018-2024 (WP5) |
| truecolour_2018.tif         | COPERNICUS/S2_SR_HARMONIZED                   | zone evidence cards (WP7)   |
| slope.tif                   | USGS/SRTMGL1_003                              | slope driver (WP4)          |
| worldcover_built_2021.tif   | ESA/WorldCover/v200                           | built-up definitions (WP5)  |
| dw_built_mode_2024.tif      | GOOGLE/DYNAMICWORLD/V1 (label band, mode)     | built-up definitions (WP5)  |
| modis_lst_2024.tif          | MODIS/061/MOD11A2                             | Landsat LST check (WP5)     |
| worldpop_2010/2020.tif      | WorldPop/GP/100m/pop                          | population sensitivity (WP6) |
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

log = logging.getLogger("export_r3")

TOO_LARGE = ("total request size", "must be less than", "too large", "400 client error")


def fetch(make_image, dest: Path, scales: tuple[int, ...], aoi: AOI, force: bool) -> None:
    """Download one layer, stepping to a coarser scale if Earth Engine refuses the size."""
    if dest.exists() and not force:
        log.info("cached      %s", dest.name)
        return
    img = make_image()
    for s in scales:
        try:
            t0 = time.time()
            gee.download_image(img, aoi, dest, scale=s, force=True)
            log.info("wrote       %s at %d m (%.0f s)", dest.name, s, time.time() - t0)
            return
        except Exception as exc:  # noqa: BLE001 — Earth Engine raises plain exceptions
            if any(k in str(exc).lower() for k in TOO_LARGE) and s != scales[-1]:
                log.info("too large at %d m, stepping down: %s", s, dest.name)
                continue
            raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force-lst", action="store_true",
                    help="re-export both LST composites (needed once after the cloud-mask fix)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()
    aoi = AOI(cfg)
    gee.ee_init(cfg.get("sources.gee.project", None))
    raw = cfg.raw_dir / "gee"

    lst0 = cfg.get("timeseries.thermal_start")
    lst1 = cfg.get("timeseries.thermal_end") - 1
    jobs = [
        (f"lst_{lst0}.tif", lambda: gee.lst_image(cfg, aoi, lst0), (30,), args.force_lst),
        (f"lst_{lst1}.tif", lambda: gee.lst_image(cfg, aoi, lst1), (30,), args.force_lst),
        ("dw_2018.tif", lambda: gee.dynamicworld_image(cfg, aoi, 2018), (60,), False),
        ("truecolour_2018.tif", lambda: gee.truecolour_image(cfg, aoi, 2018), (20, 30), False),
        ("slope.tif", lambda: gee.slope_image(cfg, aoi), (30, 60), False),
        ("worldcover_built_2021.tif", lambda: gee.worldcover_built_image(cfg, aoi), (10, 20), False),
        ("dw_built_mode_2024.tif", lambda: gee.dynamicworld_built_mode_image(cfg, aoi, 2024),
         (10, 20, 30), False),
        (f"modis_lst_{lst1}.tif", lambda: gee.modis_lst_image(cfg, aoi, lst1), (1000,), False),
        ("worldpop_2010.tif", lambda: gee.worldpop_density_image(cfg, aoi, 2010), (100,), False),
        ("worldpop_2020.tif", lambda: gee.worldpop_density_image(cfg, aoi, 2020), (100,), False),
    ]

    failed = []
    for name, make, scales, force in jobs:
        try:
            fetch(make, raw / name, scales, aoi, force)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            log.error("FAILED      %s: %s", name, str(exc)[:300])

    if failed:
        log.error("%d layer(s) failed: %s", len(failed), ", ".join(failed))
        return 1
    log.info("all %d layers present in %s", len(jobs), raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
