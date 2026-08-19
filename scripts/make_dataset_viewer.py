"""Render each acquired dataset to a PNG for the dataset viewer page.

    python scripts/make_dataset_viewer.py

Reads the rasters the pipeline already produced and writes one image per
dataset into ``dataset_viewer/img``. The viewer page itself is plain HTML and
needs no server — open ``dataset_viewer/index.html`` in a browser.
"""

from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset_viewer" / "img"

# key, source file, band, colour map, colour-bar label
LAYERS = [
    ("builtup",     "data/processed/rasters/builtup_m2_2020.tif", 1, "inferno",  "Built-up surface (m² per 100 m cell)"),
    ("population",  "data/processed/rasters/population_2020.tif", 1, "viridis",  "People per 100 m cell"),
    ("nightlights", "data/raw/gee/ntl_2024.tif",                  1, "inferno",  "Radiance (nW cm⁻² sr⁻¹)"),
    ("ndvi",        "data/raw/gee/ndvi_2024.tif",                 1, "RdYlGn",   "NDVI (−1 to +1)"),
    ("ndbi",        "data/raw/gee/ndbi_2024.tif",                 1, "RdBu_r",   "NDBI (−1 to +1)"),
    ("lst",         "data/raw/gee/lst_2024.tif",                  1, "turbo",    "Land surface temperature (°C)"),
    ("dynamicworld","data/raw/gee/dw_2024.tif",                   1, "magma",    "Probability the cell is built"),
    ("buildings",   "data/raw/gee/buildings_2023.tif",            2, "cividis",  "Building height (m)"),
    ("poi",         "data/processed/rasters/poi_density.tif",     1, "plasma",   "Points of interest per cell"),
    ("roads",       "data/processed/rasters/road_density.tif",    1, "plasma",   "Road density (weighted)"),
]


def render(key: str, rel: str, band: int, cmap: str, label: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return f"MISSING  {rel}"
    with rasterio.open(path) as ds:
        arr = ds.read(band).astype("float32")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan

    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return f"EMPTY    {rel}"

    # Stretch on the 2nd-98th percentile so a few extreme cells do not wash
    # out the whole image. Zero-heavy layers are stretched on non-zero values.
    basis = finite[finite > 0] if (finite > 0).sum() > finite.size * 0.02 else finite
    vmin, vmax = np.percentile(basis, [2, 98])
    if vmin == vmax:
        vmin, vmax = float(finite.min()), float(finite.max())

    fig, ax = plt.subplots(figsize=(7.2, 6.6), dpi=110)
    fig.patch.set_facecolor("#0f1115")
    ax.set_facecolor("#0f1115")
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.041, pad=0.02)
    cb.set_label(label, color="#c9d1d9", fontsize=9)
    cb.ax.tick_params(colors="#8b949e", labelsize=8)
    cb.outline.set_edgecolor("#30363d")
    fig.tight_layout()

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{key}.png"
    fig.savefig(dest, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    kb = dest.stat().st_size // 1024
    return f"OK       {key}.png  ({kb} KB)  range {vmin:.4g} to {vmax:.4g}"


def main() -> int:
    print(f"writing to {OUT}\n")
    for args in LAYERS:
        print("  " + render(*args))
    print(f"\nopen: {ROOT / 'dataset_viewer' / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
