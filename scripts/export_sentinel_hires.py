"""Export the Sentinel-2 layers at the finest scale Earth Engine will allow.

    python scripts/export_sentinel_hires.py

The routine export runs at 30 m, which is fine for analysis but soft on a
zoomable map — Sentinel-2 is natively 10 m. Earth Engine caps a direct download
at roughly 50 MB, and 10 m over this area exceeds that for a three-band image,
so each layer steps down through a ladder of scales until one fits.

Adds a true-colour composite, which the routine export does not produce at all.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("sentinel_hires")

# name, builder, ladder of scales to try in order
JOBS = [
    ("ndvi_hires", gee.ndvi_image,       [10, 12, 15, 20]),
    ("ndbi_hires", gee.ndbi_image,       [10, 12, 15, 20]),
]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    gee.ee_init(cfg.get("sources.gee.project", None))

    year = cfg.get("timeseries.vegetation_end") - 1   # same epoch as the map layers
    out = cfg.raw_dir / "gee"
    out.mkdir(parents=True, exist_ok=True)

    failures = []
    for name, build, ladder in JOBS:
        img = build(cfg, aoi, year)
        for scale in ladder:
            dest = out / f"{name}_{year}.tif"
            try:
                log.info("%s at %d m ...", name, scale)
                gee.download_image(img, aoi, dest, scale=scale)
                mb = dest.stat().st_size / 1e6
                log.info("  OK  %s  %.1f MB at %d m", dest.name, mb, scale)
                break
            except Exception as exc:
                msg = str(exc)
                low = msg.lower()
                # Earth Engine signals "too big" in more than one way: a
                # byte-size message from the download endpoint, and a bare 400
                # from the thumbnail endpoint when the pixel count is too high.
                too_big = ("total request size" in low or "exceed" in low
                           or "must be less than or equal to" in low
                           or "too large" in low or "400 client error" in low)
                if too_big:
                    log.warning("  %d m too large, stepping down", scale)
                    continue
                log.error("  failed: %s", msg[:160])
                failures.append(name)
                break
        else:
            log.error("  %s did not fit at any scale in %s", name, ladder)
            failures.append(name)

    if failures:
        log.warning("failed: %s", ", ".join(failures))
        return 1
    log.info("done — now run: python scripts/make_dataset_map.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
