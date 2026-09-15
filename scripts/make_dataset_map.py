from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402,F401
from matplotlib.colors import Normalize  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset_viewer"
IMG = OUT / "map"

# key, file, band, colormap, label, unit, transparent-below (None = keep all)
LAYERS = [
    ("truecolour",   "data/raw/gee/truecolour_2024.tif",           1, "rgb",     "True-colour satellite image", "Sentinel-2 red/green/blue", None),
    ("builtup",      "data/processed/rasters/builtup_m2_2020.tif", 1, "inferno", "Built-up surface", "m² per 100 m cell", 1.0),
    ("population",   "data/processed/rasters/population_2020.tif", 1, "viridis", "Population",       "people per 100 m cell", 0.5),
    ("nightlights",  "data/raw/gee/ntl_2024.tif",                  1, "inferno", "Nighttime lights", "nW cm⁻² sr⁻¹", 0.3),
    ("ndvi",         "data/raw/gee/ndvi_hires_2024.tif",                 1, "RdYlGn",  "Vegetation index (NDVI)", "index", None),
    ("ndbi",         "data/raw/gee/ndbi_hires_2024.tif",                 1, "RdBu_r",  "Built-up index (NDBI)",   "index", None),
    ("lst",          "data/raw/gee/lst_2024.tif",                  1, "turbo",   "Land surface temperature", "°C", None),
    ("dynamicworld", "data/raw/gee/dw_2024.tif",                   1, "magma",   "Land cover — built probability", "probability", 0.02),
    ("buildings",    "data/raw/gee/buildings_2023.tif",            2, "cividis", "Building height", "metres", 0.05),
    ("poi",          "data/processed/rasters/poi_density.tif",     1, "plasma",  "Points of interest", "count per cell", 0.5),
    ("roads",        "data/processed/rasters/road_density.tif",    1, "plasma",  "Road density", "weighted length", 1.0),
]


def export(key, rel, band, cmap_name, label, unit, cut):
    src_path = ROOT / rel
    if not src_path.exists():
        return None, f"MISSING  {rel}"

    if cmap_name == "rgb":
        return export_rgb(key, src_path, label, unit)

    with rasterio.open(src_path) as src:
        # Reproject to EPSG:4326 so the overlay is a plain lat/lon rectangle,
        # which is what a web map needs. Keep the native pixel count so no
        # detail is lost — the earlier version downsampled and looked soft.
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds)
        data = np.full((height, width), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, band),
            destination=data,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=transform, dst_crs=dst_crs,
            resampling=Resampling.nearest,
            src_nodata=src.nodata, dst_nodata=np.nan,
        )
        west, north = transform * (0, 0)
        east, south = transform * (width, height)

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return None, f"EMPTY    {rel}"

    basis = finite[finite > 0] if (finite > 0).sum() > finite.size * 0.02 else finite
    vmin, vmax = (float(x) for x in np.percentile(basis, [2, 98]))
    if vmin == vmax:
        vmin, vmax = float(finite.min()), float(finite.max())

    rgba = (matplotlib.colormaps[cmap_name](Normalize(vmin, vmax, clip=True)(data)) * 255).astype("uint8")
    # Fade the low end in gradually rather than cutting it off hard. A hard
    # cut punches speckled holes through dark areas, which looks like missing
    # data; a ramp lets the basemap show through the genuinely empty land.
    if cut is None:
        alpha = np.where(np.isfinite(data), 255.0, 0.0)
    else:
        span = max((vmax - vmin) * 0.15, 1e-9)
        ramp = np.clip((data - cut) / span, 0.0, 1.0)
        alpha = np.where(np.isfinite(data), ramp * 255.0, 0.0)
    rgba[..., 3] = alpha.astype("uint8")

    IMG.mkdir(parents=True, exist_ok=True)
    dest = IMG / f"{key}.png"
    Image.fromarray(rgba, "RGBA").save(dest, optimize=True)

    meta = {
        "key": key, "label": label, "unit": unit, "cmap": cmap_name,
        "bounds": [[south, west], [north, east]],
        "vmin": round(vmin, 4), "vmax": round(vmax, 4),
        "px": [width, height],
    }
    kb = dest.stat().st_size // 1024
    return meta, f"OK       {key}.png  {width}×{height}  {kb} KB  range {vmin:.4g}–{vmax:.4g}"


def export_rgb(key, src_path, label, unit):
    """True-colour composite: three bands, each stretched independently.

    Surface reflectance needs a contrast stretch to look like a photograph —
    raw values sit in a narrow band near the dark end and render almost black.
    """
    with rasterio.open(src_path) as src:
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds)
        chans = []
        for b in (1, 2, 3):
            buf = np.full((height, width), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(src, b), destination=buf,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata, dst_nodata=np.nan,
            )
            chans.append(buf)
        west, north = transform * (0, 0)
        east, south = transform * (width, height)

    rgba = np.zeros((height, width, 4), dtype="uint8")
    for i, c in enumerate(chans):
        fin = c[np.isfinite(c)]
        if fin.size == 0:
            continue
        lo, hi = np.percentile(fin, [2, 98])
        if hi <= lo:
            lo, hi = float(fin.min()), float(fin.max()) or 1.0
        rgba[..., i] = (np.clip((c - lo) / (hi - lo), 0, 1) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(chans[0]), 255, 0).astype("uint8")

    IMG.mkdir(parents=True, exist_ok=True)
    dest = IMG / f"{key}.png"
    Image.fromarray(rgba, "RGBA").save(dest, optimize=True)
    meta = {
        "key": key, "label": label, "unit": unit, "cmap": "rgb",
        "bounds": [[south, west], [north, east]],
        "vmin": "", "vmax": "", "px": [width, height],
        "ramp": ["#1a1a1a", "#4a4a4a", "#7a7a7a", "#aaaaaa", "#dddddd"],
    }
    kb = dest.stat().st_size // 1024
    return meta, f"OK       {key}.png  {width}x{height}  {kb} KB  true colour"


def main() -> int:
    print(f"writing to {IMG}\n")
    metas = []
    for args in LAYERS:
        meta, msg = export(*args)
        print("  " + msg)
        if meta:
            metas.append(meta)

    # Colour ramps, sampled so the page can draw a legend without a library.
    # The true-colour layer is not a colour-mapped scalar and supplies its own.
    for m in metas:
        if m["cmap"] == "rgb" or m.get("ramp"):
            continue
        ramp = matplotlib.colormaps[m["cmap"]](np.linspace(0, 1, 12))[:, :3]
        m["ramp"] = ["#%02x%02x%02x" % tuple(int(c * 255) for c in row) for row in ramp]

    (OUT / "layers.js").write_text(
        "const LAYER_DATA = " + json.dumps(metas, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    print(f"\n  wrote layers.js  ({len(metas)} layers)")
    print(f"\nopen: {OUT / 'map.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
