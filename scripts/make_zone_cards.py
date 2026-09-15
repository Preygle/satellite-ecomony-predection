from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

from urbanintel.analysis import ghost as A_ghost  # noqa: E402
from urbanintel.analysis import nightlights as A_ntl  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

OUT = ROOT / "docs" / "figures" / "zones"
MARGIN_M = 400.0


def read(rdir: Path, name: str) -> np.ndarray:
    with rasterio.open(rdir / f"{name}.tif") as ds:
        return ds.read(1)


def crop(path: Path, bounds, bands=(1,)) -> np.ndarray:
    with rasterio.open(path) as ds:
        win = from_bounds(*bounds, transform=ds.transform)
        return np.stack([ds.read(b, window=win, boundless=True, fill_value=0) for b in bands],
                        axis=-1).astype("float32")


def stretch(a: np.ndarray, b: np.ndarray):
    """Stretch two true-colour crops with the SAME limits so they compare fairly."""
    both = np.concatenate([a.reshape(-1, 3), b.reshape(-1, 3)])
    both = both[np.isfinite(both).all(axis=1) & (both.sum(axis=1) > 0)]
    if not both.size:
        return a, b
    lo, hi = np.percentile(both, 2, axis=0), np.percentile(both, 98, axis=0)
    f = lambda x: np.clip((x - lo) / np.maximum(hi - lo, 1e-6), 0, 1)  # noqa: E731
    return f(a), f(b)


def main() -> int:
    cfg = load_config()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    rdir, raw = cfg.processed_dir / "rasters", cfg.raw_dir / "gee"
    summary = json.loads((cfg.outputs_dir / f"{aoi.slug}_summary.json").read_text(encoding="utf-8"))
    zones = summary["stats"]["ghost"]["zones"]
    if not zones:
        print("no ghost zones in the summary")
        return 0

    zone_id = read(rdir, "ghost_zone_id").astype(int)
    typ = read(rdir, "typology").astype(int)
    poi = np.nan_to_num(read(rdir, "poi_density"))
    new_share = read(rdir, "new_builtup_share")
    frac0 = np.nan_to_num(read(rdir, f"builtup_m2_{cfg.epoch_baseline}")) / fine.res**2
    ob23_fine = gee.to_frame(raw / "buildings_2023.tif", fine, band=1)

    years = range(cfg.get("timeseries.nightlights_start"), cfg.get("timeseries.nightlights_end") + 1)
    stack = {y: gee.to_frame(raw / f"ntl_{y}.tif", fine) for y in years if (raw / f"ntl_{y}.tif").exists()}
    rel = A_ntl.relative_series(stack, frac0 >= cfg.get("thresholds.builtup.surface_fraction_urban"))
    yrs = sorted(rel)

    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for z in zones:
        k = z["zone_id"]
        mask = zone_id == k
        flagged = mask & (typ == A_ghost.TYPE_GHOST_GROWTH)
        rows, cols = np.where(mask)
        x0 = fine.minx + cols.min() * fine.res - MARGIN_M
        x1 = fine.minx + (cols.max() + 1) * fine.res + MARGIN_M
        y1 = fine.maxy - rows.min() * fine.res + MARGIN_M
        y0 = fine.maxy - (rows.max() + 1) * fine.res - MARGIN_M
        bounds = (x0, y0, x1, y1)
        extent = (0, (x1 - x0) / 1000, 0, (y1 - y0) / 1000)

        tc18, tc24 = stretch(crop(raw / "truecolour_2018.tif", bounds, (1, 2, 3)),
                             crop(raw / "truecolour_2024.tif", bounds, (1, 2, 3)))
        ob16 = crop(raw / "buildings_2016.tif", bounds)[..., 0]
        ob23 = crop(raw / "buildings_2023.tif", bounds)[..., 0]
        series_zone = [float(np.nanmean(rel[y][mask])) for y in yrs]
        series_flag = [float(np.nanmean(rel[y][flagged])) if flagged.any() else np.nan for y in yrs]

        fig, axes = plt.subplots(2, 3, figsize=(13, 8.2))
        fr, fc = np.where(flagged)
        for ax, im, title in ((axes[0, 0], tc18, "Sentinel-2 true colour, Oct 2018 - Mar 2019"),
                              (axes[0, 1], tc24, "Sentinel-2 true colour, Oct 2024 - Mar 2025")):
            ax.imshow(im, extent=extent)
            for r_, c_ in zip(fr, fc):
                ax.add_patch(Rectangle(((fine.minx + c_ * fine.res - x0) / 1000,
                                        (fine.maxy - (r_ + 1) * fine.res - y0) / 1000),
                                       0.1, 0.1, fill=False, ec="#ff3b3b", lw=0.9))
            ax.set_title(title, fontsize=9.5)
        for ax, im, title in ((axes[1, 0], ob16, "Open Buildings presence, 2016"),
                              (axes[1, 1], ob23, "Open Buildings presence, 2023")):
            ax.imshow(im, extent=extent, cmap="magma", vmin=0, vmax=0.8)
            ax.set_title(title, fontsize=9.5)
        for ax in (axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]):
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
        ax = axes[0, 2]
        ax.axhline(0, color="#898781", lw=1, label="established city (median)")
        ax.plot(yrs, series_zone, marker="o", color="#2a78d6", lw=2, label="whole zone")
        ax.plot(yrs, series_flag, marker="s", color="#d03b3b", lw=1.5, label="flagged cells")
        ax.axvline(2021.5, color="#c3c2b7", ls="--", lw=1)
        ax.set_title("Night-time light relative to the city (log)", fontsize=9.5)
        ax.legend(fontsize=7.5)
        ax.tick_params(labelsize=8)

        with_bld = float((np.nan_to_num(ob23_fine[flagged]) >= 0.05).mean()) if flagged.any() else float("nan")
        facts = {
            "zone_id": k, "lat": z.get("lat"), "lon": z.get("lon"),
            "zone_area_km2": z["area_km2"], "flagged_km2": z["flagged_km2"],
            "flagged_cells": int(flagged.sum()),
            "mean_new_share": z.get("mean_new_share"), "mean_activity": z.get("mean_activity"),
            "mean_residual": z.get("mean_residual"),
            "points_of_interest": int(round(float(poi[mask].sum()))),
            "flagged_cells_with_buildings_2023": None if np.isnan(with_bld) else round(with_bld, 2),
            "relative_light_change_2013_2024": round(series_zone[-1] - series_zone[0], 3),
        }
        ax = axes[1, 2]
        ax.axis("off")
        lines = [
            f"Zone {k}   ({z.get('lat')}, {z.get('lon')})",
            "",
            f"Zone area                {z['area_km2']:.2f} km2",
            f"Flagged (ghost growth)   {z['flagged_km2']:.2f} km2  ({facts['flagged_cells']} cells)",
            f"New since 2010           {100 * (z.get('mean_new_share') or 0):.0f}% of built-up",
            f"Activity index           {z.get('mean_activity')}  (residual {z.get('mean_residual')})",
            f"Points of interest       {facts['points_of_interest']}",
            f"Flagged cells with       {'n/a' if facts['flagged_cells_with_buildings_2023'] is None else format(facts['flagged_cells_with_buildings_2023'], '.0%')}",
            "buildings in 2023",
            f"Light vs city, 2013-24   {facts['relative_light_change_2013_2024']:+.2f} (log)",
            "",
            "Evidence for a human reader, not a validation:",
            "the precision of the ghost flag is unmeasured",
            "until ground or image labels exist.",
        ]
        ax.text(0.0, 1.0, "\n".join(lines), va="top", family="monospace", fontsize=8.6)
        fig.suptitle(f"Ghost-growth zone {k} — evidence card", fontsize=13, fontweight="bold",
                     x=0.02, ha="left")
        fig.tight_layout()
        p = OUT / f"zone_{k:02d}.png"
        fig.savefig(p, dpi=130, facecolor="white")
        plt.close(fig)
        index.append(facts)
        print(f"  wrote {p.relative_to(ROOT)}")

    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"{len(index)} zone cards -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
