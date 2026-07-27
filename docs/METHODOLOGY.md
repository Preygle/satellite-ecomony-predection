# Methodology

Every threshold named here lives in `config/varanasi.yaml` and can be changed
without touching code.

---

## 1. Spatial frame

| | |
|---|---|
| AOI | 82.80–83.15 °E, 25.15–25.45 °N (~1,206 km²) |
| Analysis CRS | EPSG:32644 (UTM 44N) |
| Analysis grid | 100 m — GHSL native, 359 × 339 |
| Reporting grid | 500 m — 73 × 69 |

The AOI covers Varanasi Municipal Corporation, the Ring Road corridor, the
peri-urban growth belt, and the Babatpur airport corridor to the north-west —
the last two being where expansion is actually happening.

**Why two grids.** Change detection is done at GHSL-native 100 m so that
newly built cells are not smeared across coarse boundaries. Reporting is at
500 m because a 121,000-polygon web map is unusable in a browser, and because
VIIRS at ~460 m cannot support finer claims about activity. Reporting at 100 m
would be over-claiming.

**Frame construction.** Bounds are snapped outward to whole multiples of the
resolution (`aoi.py:AOI.frame`), so the 100 m and 500 m frames nest exactly
and aggregation is a clean 5 × 5 block reduce with no resampling.

---

## 2. Built-up expansion

**Source.** GHS-BUILT-S R2023A, m² of built surface per 100 m cell, epochs
2010 / 2015 / 2020 / 2025.

**Reprojection (this one matters).** GHSL is in Mollweide, an equal-area
projection; the analysis frame is UTM. Built-up m² and population are
*extensive* quantities — resampling their raw per-cell values does not
conserve totals. Both are therefore converted to density (per m²),
reprojected bilinearly, and multiplied back by the target cell area
(`data/ghsl.py:to_frame`). Class rasters use nearest-neighbour.

**Urban threshold.** A cell is urban at ≥ **20%** built surface fraction —
the GHSL-conventional urban-fabric cut.

**New development.** A cell is `new_urban` when it crosses that threshold
*and* gains ≥ 1,000 m². The second condition prevents noise-level drift in an
already-marginal cell from being reported as development.

### Urban form

New development is classified by how much already-built land surrounds it at
baseline, within a **1 km circular** neighbourhood (circular, not square, so
the measure is isotropic and does not depend on grid orientation):

| Class | Prior built density | Planning meaning |
|---|---|---|
| `infill` | ≥ 50% | Inside existing fabric — cheapest to service |
| `edge_expansion` | 5–50% | Attached accretion — normal growth |
| `leapfrog` | < 5% | Detached — expensive to service, and where under-occupancy concentrates |

This follows the landscape-expansion-index family (Liu et al. 2010,
*Landscape and Urban Planning*).

---

## 3. Economic activity

**Sources.** VIIRS annual `average_masked` radiance; OSM commercial POI
density; GHS-POP population.

**The normalisation that makes it work.** Every activity measure is divided by
the cell's built-up area before comparison. Raw radiance largely measures *how
much development there is*; radiance per km² of built-up surface measures
*how intensely it is used*. The second is the question.

Cells below **5,000 m²** built-up (2% of a 500 m cell) are excluded. Dividing
a small radiance by a near-zero built-up area produces enormous ratios in
empty countryside that would otherwise dominate every percentile downstream.

**Trend.** A per-pixel OLS slope over the annual series, computed in closed
form (`analysis/nightlights.py:trend`) — for a 359 × 339 frame over 12 years
that is milliseconds rather than the minutes a per-pixel scipy loop would take.
Two-sided p-values come from the t statistic.

**Rank normalisation, not min-max.** Radiance and POI counts are heavily
right-skewed; min-max scaling would compress the entire city into the bottom
few percent below one bright industrial pixel.

**Thresholds are fractions, never absolute areas.** `min_builtup_fraction_for_analysis`
is 0.02 — 2% of whatever the frame's cell area is. An earlier version used an
absolute 5,000 m², documented as "2% of a 500 m cell" but applied on the 100 m
frame where it means *50%*; the activity index ended up defined for 1,418 of
15,816 urban cells. Any threshold on an area-valued quantity must be
resolution-relative.

**What is not claimed.** No currency figure is produced. The light-to-output
elasticity is well below 1 and varies by sector and country (Henderson,
Storeygard & Weil 2012). Radiance and its trend are reported; GDP is not
inferred.

---

## 4. Green cover

**Source.** Sentinel-2 NDVI, median composite over **October–March**.

**Why that window.** Varanasi's June–September monsoon is heavily clouded, and
a full-year median mixes post-monsoon flush with dry-season senescence, making
inter-annual change unreadable.

| Threshold | Value |
|---|---|
| Vegetated | NDVI ≥ 0.30 |
| Loss | crosses below the threshold *and* drops ≥ 0.10 |

**The attribution step.** Raw NDVI decline in the Gangetic plain mostly
measures the cropping calendar, not urbanisation. The headline figure is
therefore green loss **intersected with built-up gain** — permanent conversion.
Unqualified NDVI decline is reported separately and is not called urbanisation.

---

## 5. Urban heat island

**Source.** Landsat 8/9 Collection-2 Level-2 `ST_B10`, pre-monsoon
(March–May) median, cloud/shadow masked on `QA_PIXEL` bits 3 and 4.

SUHI intensity = LST − **median LST of rural land cells in the same scene**
(Zhou et al. 2019). Two choices:

- **Water is excluded from the rural reference.** The Ganga bisects the AOI
  and runs several degrees cooler than rural land; leaving it in would drag the
  baseline down and inflate reported heat-island intensity city-wide.
- **The reference is in-scene, not a fixed climatology**, so the metric does
  not depend on which day the scene was captured. Absolute LST is not
  comparable across dates; the urban−rural difference largely is.
- **Median, not mean**, for robustness to residual cloud.

Hotspot = intensity ≥ **+3.0 °C**.

**Heat vulnerability** weights intensity by resident population, and raises it
further where NDVI is low. A 5 °C hotspot over an empty industrial yard is a
different planning problem from a 3 °C hotspot over a dense neighbourhood; the
weighting ranks the second higher, which is the correct prioritisation.

**Cooling potential** is the actionable inverse — high where a cell is
simultaneously hot, sparsely vegetated, and built enough for intervention to
matter. Not "where is it hot" but "where should we plant".

---

## 6. Ghost growth

### The problem with the obvious approaches

- Threshold on **low nightlights** → flags every unlit field.
- Threshold on **low population** → flags every industrial estate and every
  genuinely commercial district.

Both mistake *different* for *empty*.

### What this system does

**Step 1 — composite activity index.** Rank-normalise each available
signal (nightlights, POI density, population), each already divided by
built-up area, and combine:

| Signal | Weight |
|---|---|
| Nightlights | 0.45 |
| POI density | 0.35 |
| Population | 0.20 |

Missing signals are dropped and the remaining weights renormalised, so the
pipeline degrades gracefully when Earth Engine is unavailable. The number of
contributing signals is recorded per cell.

**Step 2 — learn expected activity.** Bin all cells by built-up fraction and
take the **median activity per bin**, then interpolate. This is the crucial
step: it asks nothing of an absolute threshold and adapts to whatever this
city's own normal happens to be. A binned median rather than a fitted curve
because the real relationship is neither linear nor reliably monotonic at the
top end, and a median is unmoved by the handful of extreme-radiance industrial
cells that would drag a least-squares fit upward.

**Step 3 — residual.** actual − expected. A large negative residual means the
cell underperforms *comparably developed land in the same city*.

**Step 4 — require recency, defined relatively.** A cell is flagged only when
a large negative residual (bottom **25th percentile** *and* strictly below
expectation) coincides with new development. "New" means **≥ 50% of the cell's
current built-up appeared since the baseline**, plus an absolute floor of 2%
of cell area.

The share matters, not the absolute delta. A cell that went 0.50 → 0.56 is
mostly old development; a cell that went 0.00 → 0.25 is entirely new, and an
absolute cut cannot tell them apart. It also fails empirically: an absolute
0.15 threshold sits at the **99th percentile** of observed GHSL change in
Varanasi and flags almost nothing.

Both residual conditions are needed. The percentile alone is not enough —
where many cells sit exactly at expectation, the bottom-quartile boundary
lands on zero and `residual ≤ 0` sweeps in every perfectly normal cell tied at
the median.

Long-established low-activity areas are a different problem and are classified
`declining`, not `ghost_growth`.

**Step 5 — separate "not yet" from "never".** Where a nightlight time series
exists, dim-but-brightening cells become `emerging` rather than
`ghost_growth`. A neighbourhood mid-occupation is not a failed one. **Without
the time series this distinction cannot be made, every dim cell falls to
`ghost_growth`, and the reported ghost figure is an upper bound** — the
pipeline records this caveat in its output and the dashboard displays it.

**Step 6 — cluster by density, not contiguity.** Isolated cells are noise at
this resolution, but joining *touching* flagged cells does not work: in
Varanasi the 724 flagged cells form 342 components whose largest is 0.11 km²,
so contiguity-based grouping returns nothing above any sensible minimum size.
That would be a method artefact, not a finding.

Instead the local density of flagged cells is measured over a **600 m** window,
and areas where that density runs at **≥ 2× the citywide background rate** are
kept, then filtered to ≥ **0.25 km²**.

The threshold is a *ratio to background* rather than an absolute density
deliberately. An absolute cut has to be re-tuned per city — and tuning it
until zones appear is exactly how an artefact gets mistaken for a finding. A
ratio is self-calibrating and means the same thing in every city: "flagged
cells occur here at twice the rate they occur across this city's developed
land". For Varanasi the background rate is 4.58%, giving a threshold of 9.16%.

### Honest limits

- VIIRS at ~460 m cannot resolve one un-occupied housing block. **The unit of
  a reliable finding is a neighbourhood, not a building.**
- OSM POI coverage on Varanasi's periphery is thin, biasing peripheral cells
  toward looking inactive. This is why the index requires agreement across
  streams and reports how many signals informed each cell.
- GHS-BUILT-S is itself modelled, not measured; it can miss low-rise informal
  development and has a documented tendency to under-detect sparse rural build.
- **This is a screening tool.** It says where to look. It is not an occupancy
  census, and no cell should be acted on without ground verification.

---

## 7. Aggregation and export

100 m → 500 m by 5 × 5 block reduce, respecting variable type:

| Type | Reduction | Examples |
|---|---|---|
| Extensive | sum | built-up m², population, POI counts, road length |
| Intensive | mean | NDVI, LST, indices, scores |
| Boolean | any | new_urban, hotspots, green loss |
| **Findings** | **priority** | **typology, urban form** |

**Findings use priority, not majority.** Majority is the obvious choice for a
class raster and it is wrong here: findings are a minority of cells by nature,
so a 500 m majority vote erases them. Aggregating Varanasi's typology by
majority wiped out every ghost-growth and healthy-growth cell, leaving only
background. `priority` reports the most significant class present in the
block — the correct behaviour for a screening tool, where a planner must see a
flag that covers any part of a reporting cell. `ghost_cells` carries the count
of flagged 100 m cells so the dashboard can show how much of the cell is
actually flagged rather than implying all of it is.

Frames whose dimensions are not an exact multiple of the factor are padded
first, so no edge is silently truncated. The analysis and reporting frames are
built as a *pair* (`AOI.frame_pair`) rather than two independent calls —
independent calls each snap outward to their own resolution and do not tile
each other.

Outputs: `outputs/varanasi_grid.geojson` (EPSG:4326, for web maps),
`varanasi_grid.csv`, `varanasi_summary.json` (statistics + provenance +
skipped layers), and every layer as a 100 m GeoTIFF in
`data/processed/rasters/`.

---

## 8. Visual encoding

The categorical palette was **validated with a CVD checker**, not chosen by
eye. The obvious green-for-healthy / red-for-ghost pairing measures
ΔE 4.1 under deuteranopia (OKLab ×100, target ≥ 8) — the two most important
classes in the system would be indistinguishable to a red–green colourblind
reader.

Adopted instead (worst all-pairs CVD ΔE 9.1, normal-vision ΔE 22.9 on the
light surface):

| Class | Colour | |
|---|---|---|
| `ghost_growth` | `#d03b3b` | red |
| `emerging` | `#eda100` | yellow |
| `healthy_growth` | `#2a78d6` | blue |
| `declining` | `#1baf7a` | aqua |
| `established_active` | `#c3c2b7` | neutral |
| `undeveloped` | `#e1e0d9` | neutral |

`undeveloped` and `established_active` are deliberately grey — they are
context, not findings, and keeping them uncoloured lets the findings carry the
visual weight. Continuous layers use a single-hue blue ramp; signed layers
(built-up change, SUHI) use a blue↔red diverging ramp with a neutral grey
midpoint. Class identity is always carried by a legend and labels, never by
hue alone.
