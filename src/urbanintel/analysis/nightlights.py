"""Nighttime lights: the economic-activity axis.

Nightlight radiance is the standard satellite proxy for economic activity
(Henderson, Storeygard & Weil 2012, *AER* 102:994). Two cautions shape how
it is used here.

1. **It is a proxy, not a measurement.** The elasticity of light to output is
   well below one and varies by sector and country. This module therefore
   reports radiance and its *trend*, and never converts to a currency figure.

2. **Radiance scales with built-up area.** A bright cell may simply be a
   large cell of ordinary activity. Every comparative measure here is
   normalised by built-up surface, which is what makes the ghost-growth test
   meaningful — the question is activity *per unit of development*, not
   activity in absolute terms.

VIIRS is coarse (~460 m) relative to the 100 m built-up grid. Values are used
as an intensity surface, not as a per-building attribute; `lit_fraction`
exists to make that resolution mismatch explicit rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage, stats

from ..aoi import AnalysisFrame


@dataclass
class NightlightTrend:
    """Per-pixel linear trend in radiance over a set of years."""

    years: list[int]
    slope: np.ndarray          # radiance units per year
    intercept: np.ndarray
    r_value: np.ndarray
    p_value: np.ndarray
    mean_level: np.ndarray

    def significant_growth(self, alpha: float = 0.05, min_slope: float = 0.05) -> np.ndarray:
        """Cells brightening significantly — candidate emerging activity zones."""
        return (self.slope >= min_slope) & (self.p_value <= alpha)

    def significant_decline(self, alpha: float = 0.05, max_slope: float = -0.05) -> np.ndarray:
        """Cells dimming significantly — candidate declining zones."""
        return (self.slope <= max_slope) & (self.p_value <= alpha)


def trend(stack: dict[int, np.ndarray]) -> NightlightTrend:
    """Fit a per-pixel OLS trend across ``{year: radiance_array}``.

    A vectorised closed-form OLS is used rather than looping scipy per pixel:
    for a 359x339 frame over 12 years that is the difference between
    milliseconds and minutes.
    """
    years = sorted(stack)
    if len(years) < 3:
        raise ValueError(f"need >=3 years for a trend, got {len(years)}")

    x = np.asarray(years, dtype="float64")
    cube = np.stack([np.nan_to_num(stack[y], nan=0.0) for y in years]).astype("float64")
    n = len(years)

    x_mean = x.mean()
    y_mean = cube.mean(axis=0)
    dx = x - x_mean
    sxx = float((dx**2).sum())
    sxy = np.tensordot(dx, cube - y_mean, axes=(0, 0))

    slope = sxy / sxx
    intercept = y_mean - slope * x_mean

    # Correlation and two-sided p-value from the t statistic.
    resid = cube - (slope[None, :, :] * x[:, None, None] + intercept[None, :, :])
    ss_res = (resid**2).sum(axis=0)
    ss_tot = ((cube - y_mean) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, 0.0)
        r = np.sqrt(np.clip(r2, 0, 1)) * np.sign(slope)
        se = np.sqrt(np.where(n > 2, ss_res / (n - 2) / sxx, np.nan))
        # A zero residual is a *perfect* fit, not an undefined one: the t
        # statistic diverges and the trend is maximally significant. Mapping
        # it to t=0 (p=1) would silently discard exactly the cleanest trends —
        # which is what gap-filled nightlight series often produce.
        t = np.where(
            se > 0,
            slope / np.where(se > 0, se, 1.0),
            np.where(np.abs(slope) > 0, np.inf, 0.0),
        )
    p = 2.0 * stats.t.sf(np.abs(t), df=n - 2)

    return NightlightTrend(
        years=years,
        slope=slope.astype("float32"),
        intercept=intercept.astype("float32"),
        r_value=r.astype("float32"),
        p_value=p.astype("float32"),
        mean_level=cube.mean(axis=0).astype("float32"),
    )


def log_radiance(radiance: np.ndarray, offset: float = 1.0) -> np.ndarray:
    """Natural log of (radiance + offset). The offset keeps unlit cells finite.

    On a log scale equal *proportional* changes look equal: a dim new
    neighbourhood going from 1 to 2 and a bright market going from 20 to 40
    have both doubled. On the raw scale the market's change is twenty times
    larger, so any comparison between dim and bright places favours the bright.
    """
    return np.log(np.clip(np.nan_to_num(radiance, nan=0.0), 0.0, None) + offset)


def relative_series(
    stack: dict[int, np.ndarray], reference: np.ndarray, *, offset: float = 1.0,
) -> dict[int, np.ndarray]:
    """Each cell's log radiance minus the median of the `reference` cells, per year."""
    ref = np.asarray(reference, dtype=bool)
    if int(ref.sum()) < 30:
        raise ValueError(f"reference mask has {int(ref.sum())} cells; need at least 30")
    out: dict[int, np.ndarray] = {}
    for y in sorted(stack):
        la = log_radiance(stack[y], offset)
        out[y] = (la - float(np.median(la[ref]))).astype("float32")
    return out


def relative_trend(
    stack: dict[int, np.ndarray], reference: np.ndarray, *, offset: float = 1.0,
) -> NightlightTrend:
    """Trend of log radiance *relative to the established city*.

    Why relative: between 2013 and 2024 almost every urban cell in the study
    area brightened, so a positive raw slope says nothing about a particular
    place. The series also switches product version between 2021
    (ANNUAL_V21) and 2022 (ANNUAL_V22), and a version change can shift the
    whole scene at once. Subtracting, year by year, the median of the
    established city (`reference`, e.g. cells already urban in 2010) cancels
    both. A positive relative slope therefore means "brightening faster than
    the established city", and its p-value tests exactly that.
    """
    return trend(relative_series(stack, reference, offset=offset))


def relative_level(
    stack: dict[int, np.ndarray], reference: np.ndarray, years, *, offset: float = 1.0,
) -> np.ndarray:
    """Mean relative log radiance over `years` (see `relative_series`)."""
    rel = relative_series({y: stack[y] for y in years}, reference, offset=offset)
    return np.mean(np.stack([rel[y] for y in sorted(rel)]), axis=0).astype("float32")


def window_mean(stack: dict[int, np.ndarray], years) -> np.ndarray:
    """Mean radiance over `years` — a steadier activity level than any one year."""
    missing = [y for y in years if y not in stack]
    if missing:
        raise ValueError(f"years missing from the night-light stack: {missing}")
    return np.mean(np.stack([np.nan_to_num(stack[y], nan=0.0) for y in years]),
                   axis=0).astype("float32")


def sum_of_lights(radiance: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Sum of Lights over the AOI — the standard city-level activity aggregate."""
    v = np.nan_to_num(radiance, nan=0.0)
    if mask is not None:
        v = np.where(mask, v, 0.0)
    return float(v.sum())


def lit_fraction(radiance: np.ndarray, unlit_threshold: float = 0.5) -> float:
    """Share of AOI cells above the unlit noise floor."""
    v = np.nan_to_num(radiance, nan=0.0)
    return float((v > unlit_threshold).mean())


def activity_per_builtup(
    radiance: np.ndarray,
    builtup_m2: np.ndarray,
    *,
    min_builtup_m2: float = 5000.0,
    smooth_px: float = 0.0,
) -> np.ndarray:
    """Radiance per km^2 of built-up surface. NaN where too little is built.

    This is the core normalisation of the whole system. Masking sparsely
    built cells is essential: dividing a small radiance by a near-zero
    built-up area produces enormous ratios in empty countryside that would
    otherwise dominate every percentile calculation downstream.
    """
    r = np.nan_to_num(radiance, nan=0.0)
    if smooth_px > 0:
        r = ndimage.gaussian_filter(r.astype("float32"), sigma=smooth_px)
    b = np.nan_to_num(builtup_m2, nan=0.0)
    out = np.full(r.shape, np.nan, dtype="float32")
    ok = b >= min_builtup_m2
    out[ok] = r[ok] / (b[ok] / 1e6)
    return out


def commercial_intensity(
    radiance: np.ndarray,
    poi_density: np.ndarray,
    builtup_m2: np.ndarray,
    frame: AnalysisFrame,
    *,
    min_builtup_m2: float = 5000.0,
) -> np.ndarray:
    """Composite commercial-activity surface in [0, 1].

    Radiance alone cannot distinguish a lit arterial road from a market, and
    POI density alone is biased by OSM mapping effort. Their *product* (after
    rank-normalising each) requires both kinds of evidence to agree, which
    suppresses both failure modes.
    """
    b = np.nan_to_num(builtup_m2, nan=0.0)
    valid = b >= min_builtup_m2

    r_norm = _rank_normalise(radiance, valid)
    p_norm = _rank_normalise(poi_density, valid)

    out = np.full(radiance.shape, np.nan, dtype="float32")
    out[valid] = np.sqrt(r_norm[valid] * p_norm[valid])  # geometric mean
    return out


def _rank_normalise(arr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Map values to [0, 1] by rank within `valid` cells.

    Rank rather than min-max because both radiance and POI counts are heavily
    right-skewed; a single bright industrial pixel would otherwise compress
    the entire rest of the city into the bottom few percent of the scale.
    """
    out = np.zeros(arr.shape, dtype="float32")
    v = np.nan_to_num(arr, nan=0.0)[valid]
    if v.size == 0:
        return out
    ranks = stats.rankdata(v, method="average")
    out[valid] = ((ranks - 1) / max(len(ranks) - 1, 1)).astype("float32")
    return out
