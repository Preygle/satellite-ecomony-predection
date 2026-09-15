from __future__ import annotations

import warnings
from typing import Literal

import numpy as np

from ..aoi import AOI, AnalysisFrame

AggHow = Literal["sum", "mean", "max", "majority", "any", "priority"]


def block_reduce(
    arr: np.ndarray,
    factor: int,
    how: AggHow = "mean",
    *,
    n_classes: int | None = None,
    priority: list[int] | None = None,
) -> np.ndarray:
    """Reduce `arr` by an integer `factor` in both dimensions.

    The array is padded with NaN (or 0 for counts) so that a frame whose
    dimensions are not an exact multiple of `factor` still reduces cleanly
    rather than silently truncating its right/bottom edge.
    """
    if factor == 1:
        return arr

    h, w = arr.shape
    ph = (-h) % factor
    pw = (-w) % factor
    if ph or pw:
        fill = 0.0 if how in ("sum", "any") else np.nan
        arr = np.pad(arr.astype("float64"), ((0, ph), (0, pw)),
                     mode="constant", constant_values=fill)

    H, W = arr.shape
    blocks = arr.reshape(H // factor, factor, W // factor, factor)

    if how == "sum":
        return np.nansum(blocks, axis=(1, 3)).astype("float32")
    # An all-NaN block is a legitimate result (a cell where the layer is
    # undefined, e.g. activity over unbuilt land), not a problem — suppress
    # the warning rather than letting it flood the log once per layer.
    if how == "mean":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(blocks, axis=(1, 3)).astype("float32")
    if how == "max":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmax(blocks, axis=(1, 3)).astype("float32")
    if how == "any":
        return (np.nansum(blocks, axis=(1, 3)) > 0).astype("float32")
    if how == "majority":
        flat = blocks.transpose(0, 2, 1, 3).reshape(H // factor, W // factor, factor * factor)
        k = int(n_classes if n_classes is not None else (np.nanmax(arr) + 1))
        counts = np.zeros((*flat.shape[:2], k), dtype="int32")
        valid = np.isfinite(flat)
        codes = np.where(valid, flat, 0).astype("int32")
        for c in range(k):
            counts[:, :, c] = ((codes == c) & valid).sum(axis=2)
        return counts.argmax(axis=2).astype("float32")

    if how == "priority":
        # For a *findings* raster, majority is the wrong reducer: findings are
        # by nature a minority of cells, so a majority vote erases them —
        # aggregating Varanasi's typology by majority wiped out every
        # ghost-growth and healthy-growth cell, leaving only background.
        # Priority instead reports the most significant class present, which
        # is what a screening tool must do: if any part of the reporting cell
        # is flagged, the planner has to see it.
        if not priority:
            raise ValueError("how='priority' requires a `priority` class list")
        flat = blocks.transpose(0, 2, 1, 3).reshape(H // factor, W // factor, factor * factor)
        valid = np.isfinite(flat)
        codes = np.where(valid, flat, -1).astype("int32")
        out = np.full(flat.shape[:2], float(priority[-1]), dtype="float32")
        # Assign lowest priority first so higher-priority classes overwrite.
        for cls in reversed(priority):
            present = ((codes == int(cls)) & valid).any(axis=2)
            out[present] = float(cls)
        return out

    raise ValueError(f"unknown aggregation: {how}")


def to_grid(
    aoi: AOI,
    layers: dict[str, tuple[np.ndarray, AggHow]],
    fine: AnalysisFrame,
    coarse: AnalysisFrame,
    *,
    priorities: dict[str, list[int]] | None = None,
):
    """Aggregate named layers onto the reporting grid, as a GeoDataFrame.

    `layers` maps name -> (array_on_fine_frame, how).
    `priorities` maps layer name -> class order for how='priority'.
    """
    priorities = priorities or {}
    import geopandas as gpd

    if fine.res > coarse.res:
        raise ValueError("`fine` must be the higher-resolution frame")
    ratio = coarse.res / fine.res
    factor = int(round(ratio))
    if abs(ratio - factor) > 1e-9:
        raise ValueError(
            f"coarse resolution ({coarse.res}) must be an integer multiple "
            f"of fine ({fine.res})"
        )

    gdf = aoi.grid_gdf(coarse.res)

    for name, (arr, how) in layers.items():
        if arr.shape != fine.shape:
            raise ValueError(
                f"layer {name!r} has shape {arr.shape}, expected {fine.shape}"
            )
        n_classes = None
        if how == "majority":
            finite = arr[np.isfinite(arr)]
            n_classes = int(finite.max()) + 1 if finite.size else 1
        red = block_reduce(
            arr.astype("float64"), factor, how,
            n_classes=n_classes, priority=priorities.get(name),
        )
        red = red[: coarse.height, : coarse.width]
        gdf[name] = red.reshape(-1)

    return gdf


def summarise(gdf, columns: list[str] | None = None) -> dict[str, dict[str, float]]:
    """Descriptive statistics per column, for the report and dashboard header."""
    import pandas as pd

    cols = columns or [
        c for c in gdf.columns
        if c not in ("geometry", "cell_id", "row", "col", "x", "y", "lon", "lat")
        and pd.api.types.is_numeric_dtype(gdf[c])
    ]
    out: dict[str, dict[str, float]] = {}
    for c in cols:
        s = gdf[c].replace([np.inf, -np.inf], np.nan).dropna()
        if s.empty:
            continue
        out[c] = {
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "p90": round(float(s.quantile(0.90)), 4),
            "max": round(float(s.max()), 4),
            "sum": round(float(s.sum()), 2),
            "n_nonzero": int((s != 0).sum()),
        }
    return out


def export(gdf, path, *, to_wgs84: bool = True) -> None:
    """Write the reporting grid to GeoJSON for the dashboard.

    Reprojected to EPSG:4326 because folium/leaflet expect geographic
    coordinates; cells carrying no signal at all are dropped to keep the
    payload small.
    """
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = gdf.to_crs("EPSG:4326") if to_wgs84 else gdf
    out.to_file(path, driver="GeoJSON")
