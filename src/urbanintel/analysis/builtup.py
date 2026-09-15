from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from ..aoi import AnalysisFrame


def fraction(builtup_m2: np.ndarray, frame: AnalysisFrame) -> np.ndarray:
    """Built-up surface as a fraction of cell area, in [0, 1]."""
    return np.clip(np.nan_to_num(builtup_m2, nan=0.0) / (frame.res * frame.res), 0.0, 1.0)


@dataclass
class BuiltupChange:
    """Built-up change between two epochs, on the analysis frame."""

    year_from: int
    year_to: int
    frac_from: np.ndarray
    frac_to: np.ndarray
    delta_frac: np.ndarray          # signed change in built fraction
    delta_m2: np.ndarray            # signed change in m^2 per cell
    new_urban: np.ndarray           # bool: crossed the urban threshold
    was_urban: np.ndarray           # bool: already urban at `year_from`
    is_urban: np.ndarray            # bool: urban at `year_to`

    @property
    def years(self) -> int:
        return self.year_to - self.year_from

    @property
    def total_new_km2(self) -> float:
        """Net new built-up surface, km^2."""
        return float(np.nansum(np.clip(self.delta_m2, 0, None))) / 1e6

    @property
    def total_lost_km2(self) -> float:
        """Built-up surface lost (rare; usually demolition or model revision)."""
        return float(np.nansum(np.clip(self.delta_m2, None, 0))) / -1e6

    def urban_area_km2(self, frame: AnalysisFrame, which: str = "to") -> float:
        mask = self.is_urban if which == "to" else self.was_urban
        return float(mask.sum()) * (frame.res**2) / 1e6

    def annual_growth_rate(self, frame: AnalysisFrame) -> float:
        """Compound annual growth rate of urban extent, percent per year."""
        a0 = self.urban_area_km2(frame, "from")
        a1 = self.urban_area_km2(frame, "to")
        if a0 <= 0 or self.years <= 0:
            return float("nan")
        return (float((a1 / a0) ** (1.0 / self.years)) - 1.0) * 100.0


def change(
    builtup_from: np.ndarray,
    builtup_to: np.ndarray,
    frame: AnalysisFrame,
    *,
    year_from: int,
    year_to: int,
    urban_threshold: float = 0.20,
    min_delta_m2: float = 1000.0,
) -> BuiltupChange:
    """Difference two GHS-BUILT-S epochs.

    `new_urban` requires both crossing the urban fraction threshold *and* a
    minimum absolute gain, so that noise-level drift in an already-marginal
    cell is not reported as new development.
    """
    f0 = fraction(builtup_from, frame)
    f1 = fraction(builtup_to, frame)
    d_frac = f1 - f0
    d_m2 = d_frac * (frame.res * frame.res)

    was_urban = f0 >= urban_threshold
    is_urban = f1 >= urban_threshold
    new_urban = (~was_urban) & is_urban & (d_m2 >= min_delta_m2)

    return BuiltupChange(
        year_from=year_from, year_to=year_to,
        frac_from=f0, frac_to=f1,
        delta_frac=d_frac.astype("float32"), delta_m2=d_m2.astype("float32"),
        new_urban=new_urban, was_urban=was_urban, is_urban=is_urban,
    )


# --------------------------------------------------------------------------
# Urban form
# --------------------------------------------------------------------------

FORM_NONE = 0
FORM_INFILL = 1
FORM_EDGE = 2
FORM_LEAPFROG = 3

FORM_LABELS = {
    FORM_NONE: "none",
    FORM_INFILL: "infill",
    FORM_EDGE: "edge_expansion",
    FORM_LEAPFROG: "leapfrog",
}


def expansion_form(
    chg: BuiltupChange,
    frame: AnalysisFrame,
    *,
    neighbourhood_m: float = 1000.0,
    infill_min: float = 0.50,
    edge_min: float = 0.05,
) -> np.ndarray:
    """Classify each new-urban cell as infill / edge expansion / leapfrog.

    For every newly urban cell, the fraction of already-urban land within
    `neighbourhood_m` at the baseline epoch decides the class. A circular
    kernel is used rather than a square so the measure is isotropic and the
    classification does not depend on grid orientation.
    """
    radius_px = max(1, int(round(neighbourhood_m / frame.res)))
    yy, xx = np.mgrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    kernel = ((xx**2 + yy**2) <= radius_px**2).astype("float32")
    kernel /= kernel.sum()

    prior_density = ndimage.convolve(
        chg.was_urban.astype("float32"), kernel, mode="constant", cval=0.0
    )

    out = np.full(chg.new_urban.shape, FORM_NONE, dtype="uint8")
    out[chg.new_urban & (prior_density >= infill_min)] = FORM_INFILL
    out[chg.new_urban & (prior_density < infill_min) & (prior_density >= edge_min)] = FORM_EDGE
    out[chg.new_urban & (prior_density < edge_min)] = FORM_LEAPFROG
    return out


def form_summary(form: np.ndarray, frame: AnalysisFrame) -> dict[str, dict[str, float]]:
    """Area and share of new development by urban form."""
    cell_km2 = (frame.res**2) / 1e6
    total = float((form != FORM_NONE).sum()) * cell_km2
    out: dict[str, dict[str, float]] = {}
    for code, label in FORM_LABELS.items():
        if code == FORM_NONE:
            continue
        km2 = float((form == code).sum()) * cell_km2
        out[label] = {
            "area_km2": round(km2, 3),
            "share_pct": round(100.0 * km2 / total, 1) if total > 0 else 0.0,
        }
    out["_total_new_km2"] = round(total, 3)
    return out


# --------------------------------------------------------------------------
# Growth intensity / hotspots
# --------------------------------------------------------------------------

def growth_hotspots(
    chg: BuiltupChange,
    frame: AnalysisFrame,
    *,
    smooth_m: float = 1500.0,
    percentile: float = 90.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed growth-intensity surface and its top-percentile hotspot mask.

    Smoothing turns a speckled per-cell difference into contiguous zones a
    planner can act on; the threshold is a percentile of *positive growth*
    cells only, so the hotspot definition does not drift with how much
    empty land happens to be inside the AOI.
    """
    sigma_px = max(1.0, smooth_m / frame.res / 2.0)
    gain = np.clip(np.nan_to_num(chg.delta_m2, nan=0.0), 0, None)
    intensity = ndimage.gaussian_filter(gain.astype("float32"), sigma=sigma_px)

    positive = intensity[intensity > 0]
    if positive.size == 0:
        return intensity, np.zeros_like(intensity, dtype=bool)
    cut = float(np.percentile(positive, percentile))
    return intensity, intensity >= cut


def radial_profile(
    values: np.ndarray, dist_km: np.ndarray, *, bin_km: float = 1.0, max_km: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean of `values` in concentric rings around the city centre.

    Returns (ring_centre_km, mean, count). The urban gradient this produces
    is the clearest single view of whether a city is spreading outward or
    densifying inward.
    """
    d = np.nan_to_num(dist_km, nan=np.inf)
    hi = float(max_km if max_km is not None else np.nanpercentile(d[np.isfinite(d)], 99))
    edges = np.arange(0.0, hi + bin_km, bin_km)
    centres = (edges[:-1] + edges[1:]) / 2.0

    means = np.full(centres.shape, np.nan, dtype="float64")
    counts = np.zeros(centres.shape, dtype="int64")
    v = np.nan_to_num(values, nan=np.nan)
    for i in range(len(centres)):
        sel = (d >= edges[i]) & (d < edges[i + 1])
        counts[i] = int(sel.sum())
        if counts[i]:
            means[i] = float(np.nanmean(v[sel]))
    return centres, means, counts
