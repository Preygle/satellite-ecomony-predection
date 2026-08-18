# Review 1 — Guide Review (5 Marks)

**BCSE497J Project I · School of Computer Science and Engineering (SCOPE) · Fall 2026–27**

| Field | Value |
|---|---|
| Project title | Satellite-Based Urban Growth and Economic Activity Intelligence System |
| Study area | Varanasi, Uttar Pradesh, India |
| Team members | *(to be filled — name, register number, contribution)* |
| Guide | *(to be filled)* |
| Scheduled review window | 9–11 July 2026 |

> **Note on timing.** The guidelines place Review 1 in the 9–11 July 2026
> window. This document is prepared after that date, so it is written as a
> consolidated record of the Review 1 deliverables against the rubric rather
> than as an advance submission. Implementation has since progressed past the
> Review 3 threshold; the objectives and scope stated here are the *approved
> baseline* against which later progress is measured, which is what the
> Review 3 and Review 4 rubrics ask for.

---

## Rubric item 1 — Project title and technical relevance (1 mark)

**Title:** *Satellite-Based Urban Growth and Economic Activity Intelligence
System*

**Domain:** Geospatial remote sensing, urban informatics, spatial machine
learning.

**Why the title is specific rather than generic.** It names three things that
constrain the work: the data source is *satellite*, the phenomenon is *urban
growth*, and the measurement layered on top of it is *economic activity*. The
combination is the point. Mapping urban growth alone is a solved and crowded
problem; measuring economic activity from nighttime lights alone is likewise
established. Intersecting them — asking whether newly built land is actually
being *used* — is where the open question lies.

**Technical relevance.** Varanasi's built-up surface grew 23.8% between 2010 and
2020 while its population grew 10.3%. Land is being consumed at roughly 2.3
times the rate that people are being housed. Whether that gap represents
legitimate densification-in-progress or stranded development is not answerable
from the built-up map alone, and no municipal dataset records it. It is
answerable from open satellite data, and that is what this project does.

---

## Rubric item 2 — Abstract and problem definition (1 mark)

### Abstract

Indian cities are expanding faster than their populations, and municipal
authorities have no systematic way to distinguish development that is being
occupied from development that is not. This project builds an end-to-end system
that measures urban expansion, commercial activity, green-cover loss and surface
urban heat from open satellite and geospatial data, and combines them to
identify **"ghost growth"** — land that has been built on but shows economic
activity far below the level normal for comparably developed land in the same
city.

The system takes Varanasi as its study area. Built-up surface is derived from
the Global Human Settlement Layer (GHS-BUILT-S R2023A) across the observational
epochs 2010, 2015 and 2020, and each newly urbanised parcel is classified as
infill, edge expansion or leapfrog using a landscape-expansion-index method.
Economic activity is estimated from VIIRS (Visible Infrared Imaging Radiometer Suite) nighttime radiance, OpenStreetMap
point-of-interest density and gridded population, normalised per unit of
built-up area. Rather than applying a fixed radiance threshold, the system
*learns* the activity level expected at each built-up intensity for that
specific city and flags the negative residuals — which makes the method
transferable to any city without re-tuning. A logistic suitability model coupled
to a constrained cellular automaton then projects where expansion will occur
next. Results are delivered through an interactive dashboard.

The system runs end-to-end on data requiring no credentials, and folds in Earth
Engine layers automatically once authentication is available.

### Problem definition

**The problem.** Urban expansion in Indian cities is measured, when it is
measured at all, by area. Area does not distinguish a functioning new
neighbourhood from an empty one. Municipalities therefore extend water,
sewerage and transit on the basis of construction, not occupancy, and have no
instrument for detecting when that investment is stranded.

**Why it is hard.** The naive detectors both fail:

- *Low nightlights* flags every agricultural field and every unlit industrial
  estate.
- *Low population density* flags every warehouse district and every commercial
  zone.

Both mistake **different** for **empty**. A correct method has to establish what
"normal" activity looks like for a given level of development *in that
particular city*, and flag departures from it — and it has to separate
genuinely stalled development from a neighbourhood that is simply mid-occupation.

**Assumptions.**

1. Nighttime radiance, POI (Point of Interest) density and population density are jointly
   informative about economic use, none of them individually sufficient.
2. Within one city, the relationship between built-up intensity and activity is
   stable enough that a large negative residual is meaningful.
3. GHS-BUILT-S is an adequate proxy for built-up surface at 100 m.

**Constraints.**

1. **No ground truth is available.** Nothing in the output has been validated
   against observation. The system is therefore specified as a *screening tool*,
   not an occupancy census.
2. **VIIRS resolves ~460 m.** The smallest reliable unit of a finding is a
   neighbourhood, not a building.
3. **OpenStreetMap coverage is uneven**, better in the core than the periphery —
   and the periphery is where the findings concentrate.
4. **GHS-BUILT-S is modelled, not measured**, and under-detects low-rise
   informal development.
5. **GHSL epochs 2025 and 2030 are the GHSL model's own projections, not
   observations.** All measured claims are restricted to 1975–2020.

**Significance.** The output is a ranked, mapped shortlist of underperforming
development zones that a planning authority can send someone to inspect. That
is a decision-support artefact that does not currently exist for Varanasi, and
the pipeline is city-agnostic — a different city is a different configuration
file.

---

## Rubric item 3 — Objectives and expected outcomes (1 mark)

### Objectives

| # | Objective | Measurable completion criterion |
|---|---|---|
| O1 | Quantify built-up expansion across observational epochs | Built-up surface and urban extent for 2010/2015/2020 at 100 m, with per-epoch change rasters |
| O2 | Classify the *form* of new development | Every newly urbanised cell labelled infill / edge expansion / leapfrog, with area shares |
| O3 | Construct a multi-signal economic-activity index | Composite of NTL, POI density and population, normalised per unit built-up area |
| O4 | Detect ghost growth without fixed thresholds | Learned expected-activity curve + residual screen; output as a six-class growth typology |
| O5 | Measure green-cover loss attributable to urbanisation | NDVI (Normalized Difference Vegetation Index) change intersected with built-up gain |
| O6 | Map surface urban heat island and heat vulnerability | LST (Land Surface Temperature) minus in-scene rural reference, water excluded; population-weighted vulnerability |
| O7 | Predict future urban expansion | Suitability model + constrained CA, validated on a held-out period against a random baseline |
| O8 | Deliver the results as usable planning intelligence | Interactive dashboard; machine-readable grid export with full provenance |

### Expected outcomes

**Software.** A reproducible pipeline (`python -m urbanintel.pipeline`), a
configuration-driven city definition, an automated test suite, and a Streamlit
dashboard.

**Data products.** Analytical raster layers at 100 m; a 500 m reporting grid as
GeoJSON and CSV; a summary JSON carrying every statistic together with its
provenance and an explicit record of any layer that was skipped and why.

**Analytical findings.** Quantified expansion rate and its ratio to population
growth; the infill/edge/leapfrog composition of new development; a ranked list
of ghost-growth zones with area, residual and location; a validated projection
of future expansion.

**Documentation.** Methodology, dataset inventory with licences, literature
review, and per-review reports.

### Success criteria

The project is successful if it (a) produces the above from data that anyone can
re-download, (b) validates the predictive component against a held-out period
with a benchmark that makes the score interpretable, and (c) states its
limitations precisely enough that a planner knows what the output cannot be used
for. Criterion (c) is deliberate: a screening tool that over-claims is worse
than none.

---

## Rubric item 4 — Scope and feasibility (1 mark)

### In scope

Varanasi, a 1,206 km² area of interest (82.80–83.15 °E, 25.15–25.45 °N) covering
the Municipal Corporation, the Ring Road corridor, the peri-urban belt and the
Babatpur airport corridor. Analysis at 100 m, reporting at 500 m, over the
observational epochs 2010, 2015 and 2020, with projection to 2030.

### Explicitly out of scope

Stated so the boundary is defensible rather than accidental:

- Building-level occupancy determination — beyond the resolution of the sensors.
- Field survey and ground validation — recorded as the primary Phase 3 gap.
- Real-time or sub-annual monitoring — the annual composites define the cadence.
- Causal attribution of why a zone underperforms — the system localises, it does
  not explain.
- Multi-city comparison — the architecture supports it; the semester does not.

### Feasibility

**Data.** Every source is open and free. GHSL, OpenStreetMap and WorldPop
require no credentials at all; VIIRS, Sentinel-2, Landsat, Dynamic World and
Open Buildings are available through Google Earth Engine's free research tier.
Total download for the credential-free path is approximately 330 MB.

**The principal feasibility risk was addressed by design.** Most projects of
this kind stall at "first, obtain Earth Engine access." This system is built on
two data paths: the open path runs end-to-end and produces the core built-up,
form-classification, activity and ghost-growth results with no account of any
kind; the Earth Engine path adds nightlights, NDVI and land surface temperature
and is folded in automatically once available. A pipeline that produces partial
results is a pipeline that produces results.

**Compute.** Standard laptop. No GPU is required, and §5 of
`docs/LITERATURE_NTL_AND_UNET.md` documents the literature basis for that
choice: U-Net-based expansion models report accuracy comparable to
cellular-automaton models, so the deep-learning route was not worth its cost in
labelled data, GPU time and interpretability for this project.

**Skills.** Python, geospatial raster processing (rasterio, numpy, geopandas),
scikit-learn, Streamlit. All within the scope of the programme.

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Earth Engine authentication unavailable | Medium | Medium | Dual-path architecture; open path is self-sufficient. Realised — Phase 1 completed without it |
| Sparse OSM coverage in the periphery biases the activity index | High | Medium | Require agreement across signals; state the bias explicitly in every report |
| No ground truth to validate against | Certain | High | Specify the deliverable as a screening tool; treat ground validation as Phase 3 |
| Products confused with observations | Medium | High | Restrict measured claims to observational epochs; label projections as such |
| Threshold choices unintentionally determine the result | High | High | Learned expected-activity curve instead of fixed thresholds; regression tests on synthetic data with known answers |
| Disk / bandwidth limits during bulk download | Medium | Low | Resumable downloads, parallel fetch, prefetch script |

The fourth risk was realised: GHSL supplies epochs to 2030, and 2025/2030 were
initially treated as measurements. They are the GHSL model's own projections.
The error was found during Phase 2 validation and corrected across all reports.

---

## Rubric item 5 — Preliminary work plan (1 mark)

### Milestones against the review schedule

| Phase | Target | Deliverable | Aligned review | Date |
|---|---|---|---|---|
| Setup | — | AOI (Area of Interest) definition, data inventory, literature survey | Review 1 | 9–11 Jul 2026 |
| Phase 1 | ~50% | Built-up expansion, urban form, activity index, ghost-growth detection, dashboard | Review 2 | 19 Aug 2026 |
| Phase 2 | ~80% | Predictive expansion model, validation against a held-out period, corrections | Review 3 | 16 Sep 2026 |
| Phase 3 | 100% | Ground validation, ward-level reporting, investment corridors, master-plan comparison | Review 4 | 12–16 Oct 2026 |
| Report | — | Chapters 1–5, publication/patent evidence | Draft + Review 5 | 12–21 Oct 2026 |

### Work breakdown

**Phase 1 — foundation.** Configuration and AOI framing; GHSL acquisition with
density-preserving reprojection; OpenStreetMap acquisition; built-up change
detection; landscape-expansion-index form classification; activity index;
ghost-growth screen; zonal aggregation and export; dashboard; test suite.

**Phase 2 — prediction.** Driver construction; logistic suitability model;
constrained cellular-automaton allocation; validation on a held-out period
against a random-allocation baseline; projection.

**Phase 3 — validation and delivery.** Earth Engine layers; ward-level
aggregation to Census 2011 boundaries; building height from Open Buildings
Temporal; master-plan overlay; ground validation of the flagged zones;
investment-corridor identification; deployment.

### Allocation of responsibilities

*(To be completed with team member names. The natural division follows the
module boundaries: data acquisition and preprocessing; analysis and modelling;
dashboard, documentation and validation. Every member's contribution must be
demonstrable at each review and stated in the individual final report, per §2 of
the guidelines.)*

### Dependencies and the critical path

Earth Engine authentication gates objectives O5, O6 and the nightlight component
of O3, and therefore also gates the refinement of the O4 ghost-growth figure —
without a nightlight time series, neighbourhoods that are dim but *brightening*
cannot be separated from those that are dim and staying dim, so the reported
ghost figure is an upper bound. It is the single highest-value unblocking
action in the project and does not depend on anything else. It should be
completed first in Phase 3.

Digitising the Varanasi Development Authority master plan is the longest-lead
Phase 3 item and has no software dependency, so it can proceed in parallel from
the start of the phase.

---

## Appendix — Review 1 comments and action taken

Per §2 of the guidelines, all review comments must be recorded and the action
taken presented at the following review. Review 3 allocates 1 mark and Review 4
allocates 2 marks specifically to this.

| # | Comment received | Date | Action taken | Evidence |
|---|---|---|---|---|
| 1 | *(record verbatim)* | | | |
| 2 | | | | |

**Guide's remarks recorded to date**

| # | Remark | Action taken | Evidence |
|---|---|---|---|
| 1 | Identify at least five VIIRS papers with a similar model implementation and comparable outputs, and derive a central common trend | Five cross-sensor calibration implementations selected against a stated criterion; outputs compared in a single table; common trend derived in four ranked findings | `docs/LITERATURE_NTL_AND_UNET.md` §2–3 |
| 2 | Selected papers must be concrete implementations, not conceptual studies | Selection criterion requires a released product and reported quantitative validation; reviews and application papers excluded | `docs/LITERATURE_NTL_AND_UNET.md` §2.1 |
| 3 | Find five papers using U-Net or a closely related architecture | Six identified spanning the foundational architecture, nighttime-light calibration, building segmentation and urban-expansion simulation; common trend derived | `docs/LITERATURE_NTL_AND_UNET.md` §4–5 |

---

*Prepared with AI assistance (Claude), in line with §2 of the BCSE497J
guidelines.*
