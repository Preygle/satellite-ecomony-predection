from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402

from ..aoi import AnalysisFrame  # noqa: E402

OUTCOME = {1: ("#d9d9d9", "already urban in 2015"), 2: ("#009e73", "hit: predicted and observed"),
           3: ("#d55e00", "miss: observed, not predicted"), 4: ("#0072b2", "false alarm: predicted, not observed")}
PROB_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "probability", ["#ffffff"] + [mcolors.to_hex(matplotlib.colormaps["magma_r"](v))
                                  for v in np.linspace(0.12, 1.0, 9)])
SEQ_BLUE = mcolors.LinearSegmentedColormap.from_list(
    "seq_blue", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIVERGING = mcolors.LinearSegmentedColormap.from_list(
    "diverging", ["#b2302f", "#e34948", "#f19a99", "#f0efec", "#86b6ef", "#2a78d6", "#184f95"])


def to_wgs84(arr: np.ndarray, frame: AnalysisFrame, *, categorical: bool) -> tuple[np.ndarray, list]:
    src = np.where(np.isfinite(arr), arr, np.nan).astype("float32")
    t, w, h = calculate_default_transform(frame.crs, "EPSG:4326", frame.width, frame.height,
                                          *frame.bounds)
    dst = np.full((h, w), np.nan, dtype="float32")
    reproject(src, dst, src_transform=frame.transform, src_crs=frame.crs, src_nodata=np.nan,
              dst_transform=t, dst_crs="EPSG:4326", dst_nodata=np.nan,
              resampling=Resampling.nearest if categorical else Resampling.bilinear)
    lon0, lat1 = t.c, t.f
    lon1, lat0 = lon0 + t.a * w, lat1 + t.e * h
    return dst, [[lat0, lon0], [lat1, lon1]]


def _png(rgba: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype("uint8"), mode="RGBA")
    if max(img.size) < 900:
        k = int(np.ceil(900 / max(img.size)))
        img = img.resize((img.size[0] * k, img.size[1] * k), Image.NEAREST)
    img.save(path, optimize=True)


def continuous(arr, frame, path, *, cmap, vmin, vmax, gamma=1.0, alpha=0.85) -> dict:
    a, bounds = to_wgs84(arr, frame, categorical=False)
    norm = mcolors.PowerNorm(gamma, vmin, vmax) if gamma != 1.0 else mcolors.Normalize(vmin, vmax)
    rgba = cmap(norm(np.nan_to_num(a, nan=vmin)))
    rgba[..., 3] = np.where(np.isfinite(a), alpha, 0.0)
    _png(rgba, path)
    return {"file": path.name, "bounds": bounds, "kind": "continuous", "vmin": float(vmin),
            "vmax": float(vmax), "gamma": gamma,
            "colors": [mcolors.to_hex(cmap(x)) for x in np.linspace(0, 1, 7)]}


def categorical(arr, frame, path, classes: dict[int, tuple[str, str]], *, alpha=0.9) -> dict:
    a, bounds = to_wgs84(arr, frame, categorical=True)
    rgba = np.zeros(a.shape + (4,), dtype="float32")
    for code, (hexc, _) in classes.items():
        m = a == code
        rgba[m, :3] = mcolors.to_rgb(hexc)
        rgba[m, 3] = alpha
    _png(rgba, path)
    return {"file": path.name, "bounds": bounds, "kind": "categorical",
            "classes": [{"code": k, "color": c, "label": lbl} for k, (c, lbl) in classes.items()]}


def _read(p: Path) -> np.ndarray | None:
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def build_overlays(rdir: Path, out: Path, fine: AnalysisFrame, coarse: AnalysisFrame, thr: float,
                   econ_last: int | None) -> dict:
    o: dict[str, dict] = {}
    b15, b20 = _read(rdir / "builtup_m2_2015.tif"), _read(rdir / "builtup_m2_2020.tif")
    cell = fine.res ** 2
    if b15 is not None and b20 is not None:
        ctx = np.full(fine.shape, np.nan, dtype="float32")
        ctx[b15 / cell >= thr] = 1
        ctx[(b20 / cell >= thr) & (b15 / cell < thr)] = 2
        o["urban_change"] = {**categorical(ctx, fine, out / "urban_change.png",
                                           {1: ("#c3c2b7", "urban in 2015"),
                                            2: ("#eb6834", "became urban 2015-2020 (observed)")}),
                             "title": "Observed urban growth, 2015 to 2020 (GHS-BUILT-S)"}
    oc = _read(rdir / "test_outcome_2015_2020.tif")
    if oc is not None:
        oc = np.where(oc == 0, np.nan, oc)
        o["test_outcome"] = {**categorical(oc, fine, out / "test_outcome.png", OUTCOME),
                             "title": "Held-out test 2015 to 2020: where the model was right and wrong"}
    fc = _read(rdir / "growth_forecast_2020_2025.tif")
    if fc is not None and b20 is not None:
        fc = np.where(b20 / cell >= thr, np.nan, fc)
        vmax = float(np.nanpercentile(fc, 99.5)) or 1.0
        o["forecast"] = {**continuous(fc, fine, out / "forecast.png", cmap=PROB_CMAP, vmin=0,
                                      vmax=vmax, gamma=0.5),
                         "title": "Probability of becoming urban, 2020 to 2025 (prediction)"}
    nu, ag = _read(rdir / "predicted_new_urban_2025.tif"), _read(rdir / "allocation_agreement_2025.tif")
    if nu is not None and ag is not None and b20 is not None:
        cls = np.full(fine.shape, np.nan, dtype="float32")
        cls[b20 / cell >= thr] = 1
        cls[(nu > 0) & (ag < 0.5)] = 2
        cls[(nu > 0) & (ag >= 0.5)] = 3
        o["new_urban_2025"] = {**categorical(cls, fine, out / "new_urban_2025.png",
                                             {1: ("#c3c2b7", "urban in 2020"),
                                              2: ("#f0b48a", "predicted new urban, fewer than half of seeds agree"),
                                              3: ("#b2302f", "predicted new urban, most seeds agree")}),
                               "title": "Predicted new urban area by 2025 (prediction)"}
    if econ_last:
        lv = _read(rdir / f"econ_level_{econ_last}.tif")
        if lv is not None:
            o["night_lights"] = {**continuous(np.where(lv > 0.05, lv, np.nan), coarse,
                                              out / "night_lights.png", cmap=SEQ_BLUE, vmin=0,
                                              vmax=float(np.nanpercentile(lv, 99))),
                                 "title": f"Night-light level {econ_last - 1}-{econ_last}, log(1 + radiance)"}
        g = sorted(rdir.glob("econ_growth_forecast_*.tif"))
        if g:
            gv = _read(g[-1])
            lim = float(np.nanpercentile(np.abs(gv), 98)) or 0.1
            o["activity_growth"] = {**continuous(gv, coarse, out / "activity_growth.png",
                                                 cmap=DIVERGING, vmin=-lim, vmax=lim),
                                    "title": "Forecast night-light growth relative to the established core "
                                             f"({g[-1].stem.split('_')[-2]}-{g[-1].stem.split('_')[-1]})"}
    op = _read(rdir / "opportunity_score.tif")
    if op is not None:
        o["opportunity"] = {**continuous(op, coarse, out / "opportunity.png", cmap=SEQ_BLUE,
                                         vmin=float(np.nanmin(op)), vmax=float(np.nanmax(op))),
                            "title": "Expansion opportunity score (satellite and census evidence)"}
    nw = _read(rdir / "news_index.tif")
    if nw is not None and np.nanmax(np.abs(nw)) > 0:
        o["news"] = {**continuous(nw, coarse, out / "news.png", cmap=DIVERGING, vmin=-1, vmax=1,
                                  alpha=0.7),
                     "title": "News development index (qualitative, not validated)"}
    (out / "overlays.json").write_text(json.dumps(o, indent=1), encoding="utf-8")
    return o
