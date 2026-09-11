"""Is the emerging / ghost-growth split real? A temporal hold-out test.

    python scripts/validate_typology.py

The typology separates low-activity new development into ``emerging``
(night-time lights rising faster than the established city — filling up) and
``ghost_growth`` (not rising). There are no ground labels for Varanasi, so the
strongest available check is a hold-out in time:

1. Re-run the classification using ONLY the 2013-2020 night-light record —
   all of it from ``NOAA/VIIRS/DNB/ANNUAL_V21``, so there is no product-version
   change inside it. Activity level = mean of 2018-2020; trend = 2013-2020.
2. Measure what happened NEXT, which the classifier never saw: each cell's
   change in brightness relative to the established city, from 2018-2020 to
   2022-2024.
3. If the split means something, cells called ``emerging`` should have kept
   catching up — brightened relative to the city more than cells called
   ``ghost_growth``. A one-sided Mann-Whitney U test says whether the
   difference could be chance.

VIIRS pixels are about 463 m across, so neighbouring 100 m cells share one
measurement and are not independent. The test is therefore repeated on 500 m
blocks (the mean outcome of each class within each block), which is close to
one observation per VIIRS pixel. All four definitions of "rising" are tested,
with the configured one reported first.
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from urbanintel.analysis import ghost as A_ghost  # noqa: E402
from urbanintel.analysis import nightlights as A_ntl  # noqa: E402
from urbanintel.analysis import validation as VAL  # noqa: E402
from urbanintel.analysis import zonal as A_zonal  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

log = logging.getLogger("typology_holdout")

CLASSES = {
    A_ghost.TYPE_ESTABLISHED: "established_active",
    A_ghost.TYPE_HEALTHY_GROWTH: "healthy_growth",
    A_ghost.TYPE_EMERGING: "emerging",
    A_ghost.TYPE_GHOST_GROWTH: "ghost_growth",
    A_ghost.TYPE_DECLINING: "declining",
}


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def quantiles(x: np.ndarray) -> dict | None:
    x = x[np.isfinite(x)]
    if x.size == 0:
        return None
    p5, q1, med, q3, p95 = np.percentile(x, [5, 25, 50, 75, 95])
    return {"n": int(x.size), "p5": round(float(p5), 4), "q1": round(float(q1), 4),
            "median": round(float(med), 4), "q3": round(float(q3), 4),
            "p95": round(float(p95), 4), "mean": round(float(x.mean()), 4)}


def block_means(values: np.ndarray, mask: np.ndarray, factor: int) -> np.ndarray:
    """Mean of `values` over the cells in `mask`, per factor x factor block."""
    s = A_zonal.block_reduce(np.where(mask, values, 0.0), factor, "sum")
    n = A_zonal.block_reduce(mask.astype("float64"), factor, "sum")
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.where(n > 0, s / n, np.nan)
    return m[np.isfinite(m)]


def rounded(d: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    fine, coarse = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    factor = int(round(coarse.res / fine.res))
    rdir = cfg.processed_dir / "rasters"
    raw = cfg.raw_dir / "gee"
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    y0, y1 = cfg.epoch_baseline, cfg.epoch_current
    cell = fine.res**2

    b0, b1 = read(rdir, f"builtup_m2_{y0}"), read(rdir, f"builtup_m2_{y1}")
    if b0 is None or b1 is None:
        log.error("processed rasters missing; run the pipeline first")
        return 2
    frac0 = np.clip(np.nan_to_num(b0) / cell, 0, 1)
    frac1 = np.clip(np.nan_to_num(b1) / cell, 0, 1)
    new_frac = np.clip(np.nan_to_num(read(rdir, "builtup_delta_frac")), 0, None)
    pop = read(rdir, f"population_{y1}")
    poi = read(rdir, "poi_density")
    typ_full = read(rdir, "typology")

    n0, n1 = cfg.get("timeseries.nightlights_start"), cfg.get("timeseries.nightlights_end")
    split = int(cfg.get("timeseries.nightlights_holdout_split", 2020))
    stack = {y: gee.to_frame(raw / f"ntl_{y}.tif", fine)
             for y in range(n0, n1 + 1) if (raw / f"ntl_{y}.tif").exists()}
    hold_years = [y for y in sorted(stack) if y <= split]
    after_years = [y for y in sorted(stack) if y > split]
    if len(hold_years) < 5 or len(after_years) < 3:
        log.error("need >=5 years up to %d and >=3 after it; have %s", split, sorted(stack))
        return 2
    level_years = hold_years[-3:]
    outcome_years = after_years[-3:]
    ref = frac0 >= thr                              # established city: urban at the baseline
    log.info("classify with %d-%d (level %s); outcome %s vs %s",
             hold_years[0], hold_years[-1], level_years, outcome_years, level_years)

    # --- classification from the hold-out years only -----------------------
    level = A_ntl.window_mean(stack, level_years)
    sub = {y: stack[y] for y in hold_years}
    tr = A_ntl.trend(sub)
    rt = A_ntl.relative_trend(sub, ref)
    ev = A_ghost.TrendEvidence(slope=tr.slope, p_value=tr.p_value,
                               rel_slope=rt.slope, rel_p_value=rt.p_value)
    min_built = cfg.get("grid.min_builtup_fraction_for_analysis") * cell
    act = A_ghost.activity_index(b1, fine, nightlights=level, poi_density=poi,
                                 population=pop, min_builtup_m2=min_built)
    common = dict(
        min_new_share=cfg.get("thresholds.ghost_growth.min_new_share"),
        min_new_builtup_frac=cfg.get("thresholds.ghost_growth.min_new_builtup_fraction"),
        residual_percentile=cfg.get("thresholds.ghost_growth.max_activity_percentile"),
        urban_threshold=thr,
    )
    alpha = float(cfg.get("thresholds.ghost_growth.trend_alpha", 0.10))
    primary = cfg.get("thresholds.ghost_growth.trend_rule", "relative_significant")

    # --- the outcome the classifier never saw ------------------------------
    outcome = (A_ntl.relative_level(stack, ref, outcome_years)
               - A_ntl.relative_level(stack, ref, level_years))

    results: dict[str, dict] = {}
    for rule in [primary] + [r for r in A_ghost.RISING_RULES if r != primary]:
        g = A_ghost.analyse(act, frac1, new_frac, fine, activity_trend=ev,
                            rising_rule=rule, trend_alpha=alpha, **common)
        per_class = {}
        for code, name in CLASSES.items():
            m = g.typology == code
            per_class[name] = {"area_km2": round(float(m.sum()) * cell / 1e6, 3),
                               "outcome": quantiles(outcome[m])}
        em = g.typology == A_ghost.TYPE_EMERGING
        gh = g.typology == A_ghost.TYPE_GHOST_GROWTH
        res = {
            "classes": per_class,
            "emerging_vs_ghost_cells": rounded(VAL.mann_whitney_greater(outcome[em], outcome[gh])),
            "emerging_vs_ghost_500m_blocks": rounded(VAL.mann_whitney_greater(
                block_means(outcome, em, factor), block_means(outcome, gh, factor))),
        }
        if rule == primary and typ_full is not None:
            # How far the hold-out labels agree with the full-period labels.
            cons = {}
            for code, name in ((A_ghost.TYPE_EMERGING, "emerging"),
                               (A_ghost.TYPE_GHOST_GROWTH, "ghost_growth")):
                m = g.typology == code
                if m.any():
                    full = typ_full[m].astype(int)
                    cons[name] = {A_ghost.TYPE_LABELS[c]: round(float((full == c).mean()), 3)
                                  for c in np.unique(full)}
            res["same_cells_in_full_period_classification"] = cons
        results[rule] = res
        t = res["emerging_vs_ghost_cells"]
        log.info("%-22s emerging %5.2f km2  ghost %5.2f km2  median outcome %+.3f vs %+.3f  p=%s",
                 rule, per_class["emerging"]["area_km2"], per_class["ghost_growth"]["area_km2"],
                 t["median_x"] if t["median_x"] is not None else float("nan"),
                 t["median_y"] if t["median_y"] is not None else float("nan"),
                 "n/a" if t["p_value"] is None else f"{t['p_value']:.3g}")

    payload = {
        "question": ("Do cells classified as 'emerging' from 2013-2020 night lights alone keep "
                     "brightening relative to the established city afterwards, more than cells "
                     "classified as 'ghost_growth'?"),
        "classification_years": [hold_years[0], hold_years[-1]],
        "classification_level_years": level_years,
        "outcome": (f"change in log radiance relative to the established city (median of cells "
                    f"urban in {y0}), mean {outcome_years[0]}-{outcome_years[-1]} minus mean "
                    f"{level_years[0]}-{level_years[-1]}"),
        "product_versions": ("classification uses NOAA/VIIRS/DNB/ANNUAL_V21 only; the outcome "
                             "spans the change to ANNUAL_V22, which the relative measure cancels "
                             "wherever it shifts the whole scene alike"),
        "primary_rule": primary,
        "alpha": alpha,
        "results": results,
        "caveats": [
            "Neighbouring 100 m cells share one ~463 m VIIRS pixel, so cell-level p-values are "
            "optimistic; the 500 m block test is the more conservative one.",
            "OpenStreetMap points of interest are a present-day snapshot, so the activity index "
            "is not fully free of post-2020 information.",
            "This validates the emerging / ghost split against later brightening. It does not "
            "measure how often a flagged area is truly vacant: that needs ground or image "
            "labels, which were deferred to Review 4.",
        ],
    }
    out = cfg.outputs_dir / f"{aoi.slug}_typology_validation.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("summary -> %s", out)

    r = results[primary]
    c, b = r["emerging_vs_ghost_cells"], r["emerging_vs_ghost_500m_blocks"]
    print("\n" + "=" * 70)
    print(f"TYPOLOGY HOLD-OUT — classify {hold_years[0]}-{hold_years[-1]}, "
          f"check {outcome_years[0]}-{outcome_years[-1]} (rule: {primary})")
    print("=" * 70)
    for name, v in r["classes"].items():
        q = v["outcome"]
        print(f"  {name:20s} {v['area_km2']:7.2f} km2   median later change "
              f"{(q['median'] if q else float('nan')):+.3f}")
    print(f"\n  emerging > ghost, cells:  n={c['n_x']}/{c['n_y']}  p={c['p_value']}  "
          f"P(emerging brighter)={c['prob_superiority']}")
    print(f"  emerging > ghost, blocks: n={b['n_x']}/{b['n_y']}  p={b['p_value']}  "
          f"P(emerging brighter)={b['prob_superiority']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
