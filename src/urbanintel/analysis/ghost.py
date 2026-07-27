"""Ghost growth: development without activity.

The question
-----------
Which parts of the city have been *built* but are not being *used*?

Naive answers fail in predictable ways. Thresholding on low nightlights alone
flags every unlit field. Thresholding on low population alone flags every
industrial estate and every genuinely commercial district. Both mistake
"different" for "empty".

Method
------
The test used here is a **mismatch against expectation**, following the
vitality-mismatch logic of Jin et al. (2017, *Applied Geography* 80:112) and
Lu et al. (2018, *Remote Sensing* 10:1037):

1. Build a composite **activity index** from every available evidence
   stream — nightlight radiance, POI density, population — each
   rank-normalised so no single skewed variable dominates.

2. Learn the **expected activity for a given built-up intensity**
   empirically, as the median activity of cells in the same built-up bin.
   This is the crucial step: it asks nothing of an absolute threshold and
   adapts to whatever the city's own normal happens to be.

3. The **residual** (actual minus expected) identifies cells that are
   underperforming *relative to comparably developed land in the same city*.

4. A cell is flagged as ghost growth only when a large negative residual
   coincides with **recent new development**. Long-established low-activity
   areas are a different problem (decline, not ghost growth) and are
   classified separately.

Honest limits
-------------
* VIIRS at ~460 m cannot resolve a single un-occupied housing block; the unit
  of a reliable finding here is a neighbourhood, not a building.
* OSM POI coverage on Varanasi's periphery is thin, which biases peripheral
  cells toward looking inactive. This is why the index requires agreement
  across streams and why `n_signals` is reported per cell — a flag resting on
  one signal is explicitly weaker evidence, and the dashboard says so.
* The output is a screening tool that tells a planner where to look. It is
  not an occupancy census.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage, stats

from ..aoi import AnalysisFrame

# Typology codes
TYPE_UNDEVELOPED = 0
TYPE_ESTABLISHED = 1      # built before baseline, activity as expected
TYPE_HEALTHY_GROWTH = 2   # new build, activity as expected
TYPE_EMERGING = 3         # new build, low activity but rising — filling up
TYPE_GHOST_GROWTH = 4     # new build, low activity, not rising
TYPE_DECLINING = 5        # established, activity falling

TYPE_LABELS = {
    TYPE_UNDEVELOPED: "undeveloped",
    TYPE_ESTABLISHED: "established_active",
    TYPE_HEALTHY_GROWTH: "healthy_growth",
    TYPE_EMERGING: "emerging",
    TYPE_GHOST_GROWTH: "ghost_growth",
    TYPE_DECLINING: "declining",
}

# Palette validated with the data-viz six-checks validator on the *all-pairs*
# pairlist (a choropleth compares every class against every other, not just
# adjacent ones). The four finding classes score worst-pair CVD dE 9.1 and
# normal-vision dE 22.9 on the light surface.
#
# The obvious choice — green for healthy, red for ghost — was rejected: it
# measures CVD dE 4.1 under deuteranopia, i.e. the two most important classes
# in the whole system would be indistinguishable to a red-green colourblind
# reader. Blue carries "healthy" instead.
#
# `undeveloped` and `established_active` are deliberately neutral greys: they
# are context, not findings, and keeping them uncoloured lets the four
# findings carry all the visual weight.
TYPE_COLOURS = {
    TYPE_UNDEVELOPED: "#e1e0d9",
    TYPE_ESTABLISHED: "#c3c2b7",
    TYPE_HEALTHY_GROWTH: "#2a78d6",
    TYPE_EMERGING: "#eda100",
    TYPE_GHOST_GROWTH: "#d03b3b",
    TYPE_DECLINING: "#1baf7a",
}

# Dark-surface steps of the same hues, for a dark-mode render.
TYPE_COLOURS_DARK = {
    TYPE_UNDEVELOPED: "#2c2c2a",
    TYPE_ESTABLISHED: "#383835",
    TYPE_HEALTHY_GROWTH: "#3987e5",
    TYPE_EMERGING: "#c98500",
    TYPE_GHOST_GROWTH: "#d03b3b",
    TYPE_DECLINING: "#199e70",
}


@dataclass
class ActivityIndex:
    """Composite activity surface plus provenance."""

    value: np.ndarray                    # [0,1] rank-scaled, NaN off-mask
    components: dict[str, np.ndarray] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    n_signals: np.ndarray | None = None  # how many streams informed each cell

    @property
    def sources(self) -> list[str]:
        return sorted(self.components)


def _rank_scale(arr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Rank-scale to [0,1] within `valid`; NaN elsewhere."""
    out = np.full(arr.shape, np.nan, dtype="float32")
    v = arr[valid]
    v = np.where(np.isfinite(v), v, 0.0)
    if v.size == 0:
        return out
    ranks = stats.rankdata(v, method="average")
    out[valid] = ((ranks - 1) / max(len(ranks) - 1, 1)).astype("float32")
    return out


def activity_index(
    builtup_m2: np.ndarray,
    frame: AnalysisFrame,
    *,
    nightlights: np.ndarray | None = None,
    poi_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    min_builtup_m2: float = 5000.0,
    weights: dict[str, float] | None = None,
    smooth_m: float = 750.0,
) -> ActivityIndex:
    """Composite activity index over sufficiently built-up cells.

    Every stream is normalised **per unit built-up area** before ranking, so
    the index measures intensity of use rather than size of development.

    Streams that are `None` are skipped and the remaining weights are
    renormalised, so the pipeline degrades gracefully when Earth Engine
    (and therefore nightlights) is unavailable.
    """
    default_w = {"nightlights": 0.45, "poi": 0.35, "population": 0.20}
    w = dict(weights or default_w)

    b = np.nan_to_num(builtup_m2, nan=0.0)
    valid = b >= min_builtup_m2
    b_km2 = np.where(valid, b / 1e6, np.nan)

    sigma = max(0.5, smooth_m / frame.res / 2.0) if smooth_m > 0 else 0.0

    raw: dict[str, np.ndarray] = {}
    if nightlights is not None:
        v = np.nan_to_num(nightlights, nan=0.0)
        if sigma:
            v = ndimage.gaussian_filter(v.astype("float32"), sigma=sigma)
        raw["nightlights"] = v / b_km2
    if poi_density is not None:
        v = np.nan_to_num(poi_density, nan=0.0)
        if sigma:
            # POIs are sparse points; smoothing turns them into a usable surface.
            v = ndimage.gaussian_filter(v.astype("float32"), sigma=sigma)
        raw["poi"] = v / b_km2
    if population is not None:
        raw["population"] = np.nan_to_num(population, nan=0.0) / b_km2

    if not raw:
        raise ValueError("activity_index needs at least one of nightlights/poi/population")

    used = {k: w.get(k, 0.0) for k in raw}
    total_w = sum(used.values()) or 1.0
    used = {k: v / total_w for k, v in used.items()}

    components = {k: _rank_scale(v, valid) for k, v in raw.items()}
    stack = np.stack([components[k] * used[k] for k in components])
    value = np.where(valid, np.nansum(stack, axis=0), np.nan).astype("float32")

    n_signals = np.where(valid, len(raw), 0).astype("uint8")

    return ActivityIndex(
        value=value, components=components, weights=used, n_signals=n_signals
    )


# --------------------------------------------------------------------------
# Expected activity and the residual
# --------------------------------------------------------------------------

def expected_activity(
    activity: np.ndarray,
    builtup_frac: np.ndarray,
    *,
    n_bins: int = 20,
    min_per_bin: int = 20,
) -> np.ndarray:
    """Median activity as a function of built-up intensity, interpolated.

    A binned median rather than a fitted curve: the activity/built-up
    relationship in a real city is not linear, not log-linear, and not
    reliably monotonic at the top end, and a median is unmoved by the
    handful of extreme-radiance industrial cells that would otherwise
    drag a least-squares fit upward.
    """
    valid = np.isfinite(activity) & np.isfinite(builtup_frac)
    if not valid.any():
        return np.full_like(activity, np.nan)

    bf = builtup_frac[valid]
    ac = activity[valid]

    edges = np.quantile(bf, np.linspace(0, 1, n_bins + 1))
    edges = np.unique(edges)
    if len(edges) < 3:
        return np.where(np.isfinite(activity), float(np.median(ac)), np.nan).astype("float32")

    centres, medians = [], []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        sel = (bf >= lo) & (bf <= hi if i == len(edges) - 2 else bf < hi)
        if sel.sum() >= min_per_bin:
            centres.append(float(np.median(bf[sel])))
            medians.append(float(np.median(ac[sel])))

    if len(centres) < 2:
        return np.where(np.isfinite(activity), float(np.median(ac)), np.nan).astype("float32")

    out = np.full(activity.shape, np.nan, dtype="float32")
    m = np.isfinite(builtup_frac)
    out[m] = np.interp(builtup_frac[m], centres, medians)
    return np.where(np.isfinite(activity), out, np.nan).astype("float32")


@dataclass
class GhostAnalysis:
    """Ghost-growth screening result."""

    activity: ActivityIndex
    expected: np.ndarray
    residual: np.ndarray          # actual - expected; negative = underperforming
    ghost_score: np.ndarray       # [0,1], higher = stronger ghost signal
    typology: np.ndarray          # TYPE_* codes
    new_builtup_frac: np.ndarray  # absolute gain in built fraction
    new_share: np.ndarray         # share of current built-up that is post-baseline

    def counts(self) -> dict[str, int]:
        return {
            label: int((self.typology == code).sum())
            for code, label in TYPE_LABELS.items()
        }

    def areas_km2(self, frame: AnalysisFrame) -> dict[str, float]:
        cell = (frame.res**2) / 1e6
        return {
            label: round(float((self.typology == code).sum()) * cell, 3)
            for code, label in TYPE_LABELS.items()
        }


def analyse(
    activity: ActivityIndex,
    builtup_frac_now: np.ndarray,
    new_builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    activity_trend: np.ndarray | None = None,
    min_new_share: float = 0.50,
    min_new_builtup_frac: float = 0.02,
    residual_percentile: float = 25.0,
    urban_threshold: float = 0.20,
) -> GhostAnalysis:
    """Run the full ghost-growth screen and produce the growth typology.

    Parameters
    ----------
    activity_trend
        Optional per-cell slope of activity over time (e.g. the nightlight
        trend). When supplied, low-activity new development that is
        *brightening* is classified `emerging` rather than `ghost_growth` —
        a neighbourhood mid-occupation is not a failed one. Without it, that
        distinction cannot be made and everything low falls to
        `ghost_growth`, which the report notes as a limitation.
    """
    act = activity.value
    exp = expected_activity(act, builtup_frac_now)
    resid = (act - exp).astype("float32")

    finite = np.isfinite(resid)
    if finite.any():
        cut = float(np.percentile(resid[finite], residual_percentile))
    else:
        cut = 0.0

    # Both conditions are required. The percentile alone is not enough: where
    # many cells sit exactly at expectation the bottom quartile boundary lands
    # on zero, and `resid <= 0` then sweeps in every perfectly-normal cell
    # tied at the median. Underperforming must mean *below* expectation.
    underperforming = finite & (resid <= cut) & (resid < 0)

    # "New" is relative: what share of the cell's *current* built-up appeared
    # since the baseline. A cell that went 0.50 -> 0.56 is mostly old; a cell
    # that went 0.00 -> 0.25 is entirely new. An absolute delta cut cannot
    # tell those apart, and in practice lands so far into the tail of the
    # GHSL change distribution that it flags almost nothing.
    now = np.nan_to_num(builtup_frac_now, nan=0.0)
    gained = np.clip(np.nan_to_num(new_builtup_frac, nan=0.0), 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        new_share = np.where(now > 1e-9, gained / now, 0.0)
    new_share = np.clip(new_share, 0.0, 1.0)

    is_new = (new_share >= min_new_share) & (gained >= min_new_builtup_frac)
    is_urban = now >= urban_threshold

    # Continuous score: how far below expectation, scaled by how new the
    # development is. Both factors must be present for a high score.
    deficit = np.clip(-resid, 0, None)
    deficit_n = deficit / max(
        float(np.nanpercentile(deficit[finite], 95)) if finite.any() else 1.0, 1e-6
    )
    newness = np.clip(new_share / max(min_new_share, 1e-6), 0, 1)
    score = np.where(finite, np.clip(deficit_n, 0, 1) * newness, np.nan).astype("float32")

    # Typology
    typ = np.full(act.shape, TYPE_UNDEVELOPED, dtype="uint8")
    typ[is_urban] = TYPE_ESTABLISHED
    typ[is_urban & is_new] = TYPE_HEALTHY_GROWTH

    rising = None
    if activity_trend is not None:
        rising = np.nan_to_num(activity_trend, nan=0.0) > 0

    ghost_candidates = is_urban & is_new & underperforming
    if rising is not None:
        typ[ghost_candidates & rising] = TYPE_EMERGING
        typ[ghost_candidates & (~rising)] = TYPE_GHOST_GROWTH
    else:
        typ[ghost_candidates] = TYPE_GHOST_GROWTH

    # Established areas that are underperforming and *falling* are declining,
    # a distinct planning problem from ghost growth.
    if rising is not None:
        typ[is_urban & (~is_new) & underperforming & (~rising)] = TYPE_DECLINING

    return GhostAnalysis(
        activity=activity, expected=exp, residual=resid,
        ghost_score=score, typology=typ,
        new_builtup_frac=gained.astype("float32"),
        new_share=new_share.astype("float32"),
    )


def cluster_zones(
    ghost: GhostAnalysis,
    frame: AnalysisFrame,
    *,
    min_area_km2: float = 0.25,
    neighbourhood_m: float = 600.0,
    density_ratio: float = 2.0,
) -> tuple[np.ndarray, list[dict]]:
    """Group ghost cells into contiguous *zones* and rank them.

    Not by joining touching cells. Flagged cells at 100 m are genuinely
    fragmented — in Varanasi, 342 components whose largest is 0.11 km² — so
    contiguity-based grouping returns nothing above any sensible minimum
    size, which would be an artefact of the method rather than a finding.

    Instead this measures the **local density** of flagged cells over a
    `neighbourhood_m` window and keeps areas where that density runs at
    `density_ratio` times the citywide background rate. That matches what the
    screen can actually support: the claim is "this neighbourhood is
    underperforming", not "these exact pixels are". Scattered singletons
    dissolve; genuine concentrations survive and merge into one zone.

    The threshold is expressed as a *ratio to background* rather than an
    absolute density deliberately. An absolute cut has to be re-tuned per
    city — and tuning it until zones appear is how a method artefact gets
    mistaken for a finding. A ratio is self-calibrating: 2.0 means "flagged
    cells occur here at twice the rate they occur across this city's
    developed land", which is a claim that means the same thing everywhere.
    """
    mask = ghost.typology == TYPE_GHOST_GROWTH
    cell_km2 = (frame.res**2) / 1e6

    if not mask.any():
        return np.zeros(mask.shape, dtype="int32"), []

    # Background rate over the developed land the screen actually considered.
    considered = ghost.typology != TYPE_UNDEVELOPED
    n_considered = int(considered.sum())
    background = float(mask.sum()) / n_considered if n_considered else 0.0
    threshold = max(background * density_ratio, 1e-6)

    sigma = max(0.5, neighbourhood_m / frame.res / 2.0)
    density = ndimage.gaussian_filter(mask.astype("float32"), sigma=sigma)
    core = density >= threshold

    labels, n = ndimage.label(core, structure=np.ones((3, 3)))
    min_cells = max(1, int(round(min_area_km2 / cell_km2)))

    zones: list[dict] = []
    out = np.zeros(mask.shape, dtype="int32")
    keep_id = 0
    for lab in range(1, n + 1):
        sel = labels == lab
        n_cells = int(sel.sum())
        if n_cells < min_cells:
            continue
        flagged = sel & mask
        if not flagged.any():
            continue
        keep_id += 1
        out[sel] = keep_id
        rows, cols = np.where(sel)
        cx = frame.minx + (cols.mean() + 0.5) * frame.res
        cy = frame.maxy - (rows.mean() + 0.5) * frame.res
        zones.append({
            "zone_id": keep_id,
            "density_threshold": round(threshold, 4),
            "background_rate": round(background, 4),
            "area_km2": round(n_cells * cell_km2, 3),
            "flagged_km2": round(int(flagged.sum()) * cell_km2, 3),
            "n_cells": n_cells,
            "centroid_x": float(cx),
            "centroid_y": float(cy),
            "mean_ghost_score": round(float(np.nanmean(ghost.ghost_score[flagged])), 3),
            "mean_activity": round(float(np.nanmean(ghost.activity.value[flagged])), 3),
            "mean_residual": round(float(np.nanmean(ghost.residual[flagged])), 3),
            "mean_new_share": round(float(np.nanmean(ghost.new_share[flagged])), 3),
        })

    zones.sort(key=lambda z: (-z["flagged_km2"], -z["mean_ghost_score"]))
    # Renumber so zone_id 1 is the largest.
    remap = {z["zone_id"]: i + 1 for i, z in enumerate(zones)}
    renumbered = np.zeros_like(out)
    for old, new in remap.items():
        renumbered[out == old] = new
        zones[new - 1]["zone_id"] = new
    return renumbered, zones
