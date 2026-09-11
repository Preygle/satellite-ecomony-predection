"""Extract Sentinel-2 and Landsat imagery for a date window you choose.

Used by ``app.py``, but runnable on its own:

    python mentor_task/extract.py 2024-10-01 2025-03-31

Both sensors are pulled for the same window over the same area of interest, so
the two are directly comparable. The area comes from the main project's
configuration, so this stays in step with the rest of the system.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"

# Official dataset identifiers, exactly as the providers publish them.
SENTINEL = "COPERNICUS/S2_SR_HARMONIZED"
LANDSAT8 = "LANDSAT/LC08/C02/T1_L2"
LANDSAT9 = "LANDSAT/LC09/C02/T1_L2"


def _ctx():
    cfg = load_config()
    aoi = AOI(cfg)
    gee.ee_init(cfg.get("sources.gee.project", None))
    return cfg, aoi, gee.ee_init(), gee.aoi_geometry(aoi)


def _window(ee, col) -> dict:
    """How many scenes went in, on how many distinct days, and over what span."""
    n = col.size().getInfo()
    if not n:
        return {"scenes": 0, "days": 0, "first": None, "last": None}
    times = sorted(col.aggregate_array("system:time_start").getInfo())
    fmt = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b %Y")  # noqa: E731
    return {"scenes": n, "days": len({t // 86_400_000 for t in times}),
            "first": fmt(times[0]), "last": fmt(times[-1])}


# --------------------------------------------------------------- Sentinel ---
def sentinel(start: str, end: str, max_cloud: int = 35):
    """Sentinel-2 true colour and NDVI for the window.

    Returns (images dict, availability dict). Cloud and cirrus are masked with
    the QA60 bitmask before compositing, and the median is taken so passing
    clouds and haze do not survive into the result.
    """
    cfg, aoi, ee, geom = _ctx()
    col = (ee.ImageCollection(SENTINEL)
           .filterDate(start, end)
           .filterBounds(geom)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))
    avail = _window(ee, col)
    if not avail["scenes"]:
        return {}, avail

    masked = col.map(gee._s2_cloud_mask).median()
    return {
        "sentinel_truecolour": masked.select(["B4", "B3", "B2"])
                                     .rename(["red", "green", "blue"]).clip(geom),
        "sentinel_ndvi": masked.normalizedDifference(["B8", "B4"])
                               .rename("ndvi").clip(geom),
    }, avail


# ---------------------------------------------------------------- Landsat ---
def landsat(start: str, end: str, max_cloud: int = 40):
    """Landsat 8 and 9 true colour and land surface temperature for the window.

    Collection 2 Level-2 stores scaled integers, so the optical bands and the
    thermal band are rescaled to reflectance and °C respectively before use.
    """
    cfg, aoi, ee, geom = _ctx()
    col = (ee.ImageCollection(LANDSAT8).merge(ee.ImageCollection(LANDSAT9))
           .filterDate(start, end)
           .filterBounds(geom)
           .filter(ee.Filter.lt("CLOUD_COVER", max_cloud)))
    avail = _window(ee, col)
    if not avail["scenes"]:
        return {}, avail

    def prep(img):
        # Same mask as the main pipeline: QA_PIXEL bits 1-4 (dilated cloud,
        # cirrus, cloud, cloud shadow) — see gee.LANDSAT_QA_MASK_BITS.
        clear = gee.landsat_clear_mask(img)
        optical = img.select("SR_B.").multiply(2.75e-05).add(-0.2)
        thermal = gee.landsat_lst_celsius(img)
        return optical.addBands(thermal).updateMask(clear)

    comp = col.map(prep).median()
    return {
        "landsat_truecolour": comp.select(["SR_B4", "SR_B3", "SR_B2"])
                                  .rename(["red", "green", "blue"]).clip(geom),
        "landsat_lst": comp.select("ST_B10").rename("lst_celsius").clip(geom),
    }, avail


# ---------------------------------------------------------------- download --
def download(images: dict, scale: int, tag: str) -> list[Path]:
    """Fetch each image to GeoTIFF, stepping the scale down if it is too large."""
    cfg = load_config()
    aoi = AOI(cfg)
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, img in images.items():
        dest = OUT / f"{name}_{tag}.tif"
        for s in (scale, scale * 2, scale * 3):
            try:
                gee.download_image(img, aoi, dest, scale=s)
                written.append(dest)
                break
            except Exception as exc:
                low = str(exc).lower()
                if any(k in low for k in ("total request size", "must be less than",
                                          "too large", "400 client error")):
                    continue
                raise
    return written


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    start, end = sys.argv[1], sys.argv[2]
    tag = f"{start}_{end}".replace("-", "")

    s_img, s_av = sentinel(start, end)
    print(f"Sentinel-2 : {s_av['scenes']} scenes on {s_av['days']} days "
          f"({s_av['first']} – {s_av['last']})" if s_av["scenes"] else
          "Sentinel-2 : no scenes in this window")
    if s_img:
        for p in download(s_img, 20, tag):
            print(f"   wrote {p.name}  ({p.stat().st_size/1e6:.1f} MB)")

    l_img, l_av = landsat(start, end)
    print(f"Landsat    : {l_av['scenes']} scenes on {l_av['days']} days "
          f"({l_av['first']} – {l_av['last']})" if l_av["scenes"] else
          "Landsat    : no scenes in this window")
    if l_img:
        for p in download(l_img, 30, tag):
            print(f"   wrote {p.name}  ({p.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
