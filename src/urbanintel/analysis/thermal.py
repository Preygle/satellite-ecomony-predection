"""Surface urban heat island: intensity, hotspots, and the greening lever.

SUHI intensity here is LST minus the mean LST of *rural land cells inside the
same scene* — the standard urban-minus-rural formulation reviewed by Zhou et
al. (2019, *Remote Sensing* 11:48). Two choices matter:

* **Water is excluded from the rural reference.** The Ganga bisects the AOI
  and is several degrees cooler than rural land; leaving it in would drag the
  baseline down and inflate reported heat-island intensity city-wide.

* **The reference is taken from the same image**, not a fixed climatology, so
  the metric is insensitive to which day the scene was captured. Absolute
  LST is not comparable across dates; the urban-rural *difference* largely is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from ..aoi import AnalysisFrame


@dataclass
class SUHI:
    """Surface urban heat island for one epoch."""

    year: int
    lst: np.ndarray                 # degrees C
    rural_reference_c: float        # mean rural LST
    intensity: np.ndarray           # LST - rural reference, degrees C
    hotspots: np.ndarray            # bool mask
    threshold_c: float

    @property
    def max_intensity_c(self) -> float:
        return float(np.nanmax(self.intensity))

    @property
    def mean_urban_intensity_c(self) -> float:
        return float(np.nanmean(self.intensity[self.intensity > 0]))

    def hotspot_area_km2(self, frame: AnalysisFrame) -> float:
        return float(self.hotspots.sum()) * (frame.res**2) / 1e6


def compute_suhi(
    lst: np.ndarray,
    rural_mask: np.ndarray,
    *,
    year: int,
    hotspot_delta_c: float = 3.0,
    smooth_m: float = 0.0,
    frame: AnalysisFrame | None = None,
    min_rural_cells: int = 100,
) -> SUHI:
    """Compute SUHI intensity and hotspot mask from an LST surface."""
    t = lst.astype("float32").copy()
    if smooth_m > 0 and frame is not None:
        sigma = max(0.5, smooth_m / frame.res / 2.0)
        t = _nan_gaussian(t, sigma)

    rural_vals = t[rural_mask & np.isfinite(t)]
    if rural_vals.size < min_rural_cells:
        raise ValueError(
            f"only {rural_vals.size} valid rural reference cells "
            f"(need >={min_rural_cells}); widen the AOI or relax the rural mask"
        )
    ref = float(np.median(rural_vals))  # median: robust to residual cloud

    intensity = t - ref
    hotspots = np.nan_to_num(intensity, nan=-999.0) >= hotspot_delta_c

    return SUHI(
        year=year, lst=t, rural_reference_c=ref,
        intensity=intensity.astype("float32"),
        hotspots=hotspots, threshold_c=hotspot_delta_c,
    )


def _nan_gaussian(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smooth that ignores NaN instead of propagating it."""
    v = np.nan_to_num(arr, nan=0.0)
    w = np.isfinite(arr).astype("float32")
    vs = ndimage.gaussian_filter(v, sigma=sigma)
    ws = ndimage.gaussian_filter(w, sigma=sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(ws > 1e-6, vs / ws, np.nan)
    return out.astype("float32")


def heat_vulnerability(
    suhi: SUHI, population: np.ndarray, *, ndvi: np.ndarray | None = None,
) -> np.ndarray:
    """Population-weighted heat exposure, rank-scaled to [0, 1].

    A 5 degree hotspot over an empty industrial yard is a different planning
    problem from a 3 degree hotspot over a dense neighbourhood. Weighting by
    residents ranks the second higher, which is the correct prioritisation.
    Low NDVI raises the score further, since it marks places where tree
    planting is both possible and absent.
    """
    heat = np.clip(np.nan_to_num(suhi.intensity, nan=0.0), 0, None)
    pop = np.clip(np.nan_to_num(population, nan=0.0), 0, None)

    score = heat * pop
    if ndvi is not None:
        greenness = np.clip(np.nan_to_num(ndvi, nan=0.0) / 0.30, 0, 1)
        score = score * (1.0 + (1.0 - greenness))

    hi = float(np.nanpercentile(score, 99)) if np.isfinite(score).any() else 0.0
    if hi <= 0:
        return np.zeros_like(score, dtype="float32")
    return np.clip(score / hi, 0, 1).astype("float32")


def cooling_potential(suhi: SUHI, ndvi: np.ndarray, builtup_frac: np.ndarray) -> np.ndarray:
    """Where greening would buy the most cooling, in [0, 1].

    Highest where a cell is simultaneously hot, sparsely vegetated, and built
    enough that intervention is meaningful. This is the actionable inverse of
    the hotspot map: not "where is it hot" but "where should we plant".
    """
    heat = np.clip(np.nan_to_num(suhi.intensity, nan=0.0), 0, None)
    heat_n = heat / max(float(np.nanpercentile(heat, 95)), 1e-6)
    bare = 1.0 - np.clip(np.nan_to_num(ndvi, nan=0.0) / 0.30, 0, 1)
    built = np.clip(np.nan_to_num(builtup_frac, nan=0.0), 0, 1)
    return np.clip(heat_n * bare * built, 0, 1).astype("float32")


def summary(suhi: SUHI, frame: AnalysisFrame) -> dict[str, float]:
    return {
        "year": suhi.year,
        "rural_reference_c": round(suhi.rural_reference_c, 2),
        "max_intensity_c": round(suhi.max_intensity_c, 2),
        "mean_urban_intensity_c": round(suhi.mean_urban_intensity_c, 2),
        "hotspot_threshold_c": suhi.threshold_c,
        "hotspot_area_km2": round(suhi.hotspot_area_km2(frame), 2),
    }
