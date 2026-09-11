# Review 2 — Project Documentation

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
BCSE497J Project I · School of Computer Science and Engineering · Fall 2026–27
Study area: Varanasi, Uttar Pradesh, India

> **Correction notice (Review 3, 11 September 2026).** This document is kept as
> it was presented at Review 2. An audit for Review 3 found that several of its
> figures were computed against GHSL's 2025 epoch (a model projection), and that
> some method statements did not match the code — the LST emissivity step, the
> water exclusion, and the slope driver. The corrected figures and every change
> are in [`REVIEW3_REPORT.md`](REVIEW3_REPORT.md) (corrections log, §6).

---

## Contents

| § | Section |
|---|---|
| 1 | [Abstract](#1-abstract) |
| 2 | [Literature Review](#2-literature-review) |
| 3 | [Methodology](#3-methodology) |
| 4 | [Dataset Exploration](#4-dataset-exploration) |
| 5 | [System Architecture](#5-system-architecture) |
| 6 | [Proposed Solution](#6-proposed-solution) |
| 7 | [Results Obtained So Far](#7-results-obtained-so-far) |
| 8 | [Technical Challenges and Corrective Action](#8-technical-challenges-and-corrective-action) |
| 9 | [Limitations and Future Work](#9-limitations-and-future-work) |
| 10 | [References](#10-references) |

Abbreviations and official dataset identifiers are listed in
[`CONVENTIONS.md`](CONVENTIONS.md). Every figure in this document comes from an
actual pipeline run recorded in `outputs/varanasi_summary.json`.

---

# 1. Abstract

Indian cities are expanding faster than their populations, and municipal
authorities have no systematic way to tell development that is being occupied
from development that is not. In Varanasi, built-up surface grew **23.8%**
between 2010 and 2020 while population grew **10.3%** — land consumed roughly
**2.3 times faster** than people were housed. Expansion is normally measured by
area alone, and area cannot distinguish a functioning new neighbourhood from an
empty one. Municipalities therefore extend water, sewerage and transport on the
basis of construction rather than occupancy, with no instrument for detecting
when that investment is stranded.

This project builds an end-to-end system that measures urban expansion,
commercial activity, green-cover loss and surface urban heat from open satellite
and geospatial data, and combines them to identify **ghost growth** — land that
has been built on but shows economic activity far below the level normal for
comparably developed land in the same city.

Built-up surface is taken from `GHS-BUILT-S R2023A` across the observational
epochs 2010, 2015 and 2020, and every newly urbanised cell is classified as
infill, edge expansion or leapfrog using a landscape-expansion-index method.
Economic activity is estimated from three independent signals — VIIRS nighttime
radiance, OpenStreetMap point-of-interest density, and gridded population — each
normalised per unit of built-up area. Rather than applying a fixed radiance
threshold, the system **learns the activity level expected at each built-up
intensity for that specific city** and flags the negative residuals, which makes
the method transferable to any city without re-tuning. A logistic suitability
model coupled to a constrained cellular automaton then projects where expansion
will occur next, trained on one period and validated on a later period it has
never seen.

The distinction that matters most is between development that has stalled and
development still filling up. Without a nighttime-light time series the system
flagged **7.24 km²** as underused; adding the 2013–2024 series split that almost
exactly into **0.35 km² genuinely stalled** and **6.88 km² still being
occupied**. A method that cannot draw this distinction overstates the problem
roughly twentyfold.

The system runs end-to-end on data requiring no credentials, and folds in Google
Earth Engine layers automatically once authentication is available. Results are
delivered through an interactive dashboard and a machine-readable grid export
carrying full provenance.

**Keywords** — remote sensing, urban growth, nighttime lights, machine learning,
cellular automata, Google Earth Engine, land-change modelling.

---

# 2. Literature Review

Twenty papers were reviewed, **nineteen of them published in 2020 or later**.
Each had to implement a model, release or report a product, and give quantitative
validation; reviews and papers that merely consume such products were excluded.
Per-paper summaries are in [`PAPER_SUMMARIES.md`](PAPER_SUMMARIES.md) and the
full thematic treatment is in [`LITERATURE_REVIEW.md`](LITERATURE_REVIEW.md).

## 2.1 Theme A — Nighttime light as a proxy for human activity

Nighttime light radiance is the most widely used indirect indicator of human and
economic activity. The difficulty is that the long historical record comes from
two incompatible sensors: DMSP-OLS (Defense Meteorological Satellite Program —
Operational Linescan System), covering 1992–2013 but saturating in bright cores
and spreading light beyond its true source, and
VIIRS (Visible Infrared Imaging Radiometer Suite), covering 2012 onward with
better calibration and a far wider measurable range.

| Study | Year | Method | Reported result |
|---|---|---|---|
| Li, X. et al. | 2020 | Sigmoid function | The standard harmonised global series, 1992–2018 |
| Chen, Z. et al. | 2021 | Auto-encoder network plus a vegetation index | R² 0.87 per pixel, 0.95 per city |
| Nechaev, D. et al. | 2021 | Residual U-Net | R² 0.94–0.99 |
| Chen, X. et al. | 2024 | U-Net as image super-resolution | R² 0.617 per pixel rising to 0.964 per country |
| Zhang, L. et al. | 2024 | Convolutional Long Short-Term Memory network | RMSE 0.73, R² 0.95 per pixel |
| Tian, Y. et al. | 2026 | Two-stage deep model guided by impervious surface | R² 0.8088, beating both earlier products |

**Finding 1 — accuracy depends on scale, not on the model.** Chen, X. et al.
report R² rising 0.617 → 0.747 → 0.874 → 0.964 from pixel to city to province to
country. Chen, Z. et al. show the same pattern. Six studies span sigmoid
functions, auto-encoders, U-Nets, Long Short-Term Memory networks and two-stage
deep models, and within a fixed transform direction they land in the same
accuracy band. Chen, X. et al. describe their own network as performing "closely
to" an auto-encoder.

**Finding 2 — the difficulty lies in the direction, not the architecture.**
Converting VIIRS down to look like DMSP-OLS is a monotone mapping plus a blur, so
a sigmoid suffices. Rebuilding VIIRS-like detail *from* DMSP-OLS is
under-determined, because the detail was never recorded. Both studies that
succeed at the hard direction add a **daytime** channel — a vegetation index in
Chen, Z. et al., Landsat NDVI in Chen, X. et al., impervious surface in Tian et
al. The auxiliary data, not the network, is the enabling ingredient.

**Finding 3 — residual error concentrates at the urban fringe.** Chen, X. et al.
document that their product underestimates radiance at the city edge, because
the network pulls bright pixels toward darker neighbours, while the competing
ChenVNL product overestimates cores and underestimates peri-urban land. Two
networks, two bias signs, both worst at the fringe.

## 2.2 Theme B — Measuring built-up extent

| Study | Year | Data | Result |
|---|---|---|---|
| Goldblatt, R. et al. | 2018 | Landsat + nighttime light | 80.8% balanced accuracy for India |
| Marconcini, M. et al. | 2020 | Landsat + Sentinel-1 radar | Kappa 0.6885; +0.23 over GHSL |
| Tang, Y. et al. | 2021 | Nighttime light + MODIS | R² 0.9239 for sealed-surface percentage |
| Sirko, W. et al. | 2021 | U-Net on 50 cm imagery | 516 million building footprints |
| Brown, C. F. et al. | 2022 | Deep learning on Sentinel-2 | First near-real-time global land cover |

Goldblatt et al. is the methodological ancestor of this project: it uses
nighttime light to label training data automatically, avoiding hand-drawn
training areas, and was validated on India. Sirko et al. found that **deeper
encoders gave no accuracy gain** — improvements came from training technique
rather than architecture. Marconcini et al. quantify where GHSL is weakest,
namely small and scattered settlements, which is a documented limitation of the
dataset this project relies on.

**What this theme leaves open.** All five produce a map of *where buildings are*.
None says anything about whether those buildings are used.

## 2.3 Theme C — Inferring activity and vacancy

**Zhang, Y., Tu, T. & Long, Y. (2024)** is the closest published work. Across
8,841 cities worldwide they split each into areas developed before and after
2005 and measured urban vitality from road density, point-of-interest density and
population density. New areas showed only **7.69%** of the vitality of older
areas, and the worst-scoring 5% — 442 cities — were labelled ghost cities.

**Yeh, C. et al. (2020)** trained deep networks on public satellite imagery
across about 20,000 African villages and explained **70%** of the variation in
ground-measured wealth in countries the model had never seen. Their targeting
accuracy was 81% using multispectral imagery plus nighttime light against 62%
using nighttime light alone — direct evidence for combining signals.

**Anucharn, T. et al. (2025)** provide a working Google Earth Engine template,
reporting overall accuracy of 0.80–0.82 against 0.73–0.76 for traditional
classification, and R² 0.9744 between nighttime light and electricity
consumption. That correlation is between **provincial totals**, not pixels, and
treating an aggregate correlation as evidence about individual pixels is a
common error this project explicitly avoids.

## 2.4 Theme D — Predicting future urban expansion

| Study | Year | Method | Result |
|---|---|---|---|
| Chen, G. et al. | 2020 | Scenario projection to 2100 | 50–63% of new urban land falls on cropland |
| Liang, X. et al. | 2021 | Random forest + patch-based cellular automaton | **Figure of Merit 0.2642** |
| Shojaei, H. et al. | 2022 | Modified U-Net | AUC 0.87 against random forest 0.82 |
| Zhang, A. et al. | 2025 | Earth Engine + cellular automaton with neural network | Classification accuracy above 92% |

Liang et al. established the pattern this project follows — learn where growth is
likely, then use a cellular automaton so new development appears in connected
patches. Their Figure of Merit of 0.2642 is the benchmark our own result is
measured against. Chen, G. et al. chose the Figure of Merit explicitly because
conventional measures such as the Kappa coefficient overstate accuracy in land
change, which is the same argument this project makes.

Shojaei et al. is the closest analogue to our prediction module: almost the same
driver variables (altitude, slope, distance to roads and urban areas) and the
same decade-scale epoch spacing.

**Finding 4 — deep learning buys automation, not accuracy.** Wang et al. (2022)
report U-Net at parity with cellular-automaton models. Shojaei et al. beat a
random forest by 0.05 in area under the curve — and a random forest has no view
of a cell's surroundings at all, so much of that gap reflects spatial context
rather than deep learning as such. Sirko et al. found deeper networks gave
nothing. What a U-Net buys is automation and transferability; what it costs is
labelled data, a graphics processing unit, and interpretability.

## 2.5 Theme E — Environmental consequences

**Ermida, S. L. et al. (2020)** published open Google Earth Engine code for
computing LST (Land Surface Temperature) from Landsat, validated against ground
radiometers at RMSE 1.0–1.3 K. This is the reference method behind our thermal
layer, and it tells us how large a heat-island difference must be before it is
worth reporting.

**Ramachandra, T. V. et al. (2025)** map urban heat islands against landscape
morphology for an Indian city, finding 15.41 km² at very high temperature and a
relationship between land cover and temperature of R² 0.49 — a useful reminder
that land cover explains only part of surface temperature.

## 2.6 Research gap

| What exists | What it does | What it does not do |
|---|---|---|
| Nighttime-light series (A) | Long, consistent activity records | Say nothing about whether construction is occupied |
| Built-up mapping (B) | Show precisely where buildings are | Show whether those buildings are used |
| Ghost-city studies (C) | Compare new against old, or use a fixed cut-off | Adapt to each city's own norm; separate stalled from filling-up |
| Expansion models (D) | Predict *where* a city grows | Ask whether that growth will be used |

> **The gap.** No existing study learns the activity level normal for a given
> level of development *within a city* and uses it to separate development that
> has stalled from development that is still being occupied.

This is not a theoretical gap. Section 7.4 shows that on our own data the
distinction is the difference between 7.24 km² and 0.35 km².

---

# 3. Methodology

## 3.1 Problem framing

The two obvious detectors both fail:

| Detector | What it actually flags |
|---|---|
| Low nighttime light | Every agricultural field, every unlit industrial estate |
| Low population density | Every warehouse district, every commercial zone |

Both mistake **different** for **empty**. A correct method must (i) learn what
normal activity is *for that city* at each level of development, (ii) flag
departures from that norm rather than from a global threshold, and (iii)
separate stalled development from development mid-occupation.

## 3.2 Spatial frame

Two grids are constructed together from a single origin.

| Grid | Cell size | Dimensions | Used for |
|---|---|---|---|
| Fine | 100 m | 365 × 345 | All analysis |
| Coarse | 500 m | 73 × 69 → 4,765 cells with signal | All reporting and display |

Exactly 25 fine cells nest inside one coarse cell. Analysis runs at 100 m
because that is the native resolution of `GHS-BUILT-S R2023A` and change
detection works best at the finest resolution available. Reporting runs at 500 m
because a map of the study area at 100 m has more than 121,000 cells, which is
unusable in a browser and would imply more precision than the sensors support —
the nighttime-light sensor resolves about 460 m at best.

**Both grids must be created together.** If each were snapped independently to
its own cell size, they would not tile one another and every aggregate would be
silently shifted. This is implemented in `AOI.frame_pair()`.

## 3.3 Density-preserving reprojection

GHSL products ship in Mollweide (ESRI:54009), an equal-area projection; the
analysis frame is UTM zone 44N (EPSG:32644). Built-up surface in m² and
population counts are **extensive** quantities — they scale with cell area — so
each is converted to a density, reprojected, and rescaled by the destination
cell area. Reprojecting the raw counts directly would not conserve totals.

## 3.4 Built-up expansion and urban form

**Source.** `GHS-BUILT-S R2023A`, observational epochs 2010, 2015 and 2020.

Change is computed by differencing epochs. Each cell that newly crosses the 20%
built-up threshold is then classified by its spatial relationship to the
existing urban fabric, following the landscape expansion index of Liu et al.
(2010):

| Class | Definition | Why it matters |
|---|---|---|
| **Infill** | New development inside the existing urban area | Cheapest to service |
| **Edge expansion** | New development touching the existing edge | Moderate cost |
| **Leapfrog** | New development detached from existing fabric | Most expensive to service, most associated with under-occupancy |

Leapfrog share is the leading indicator for ghost growth: detached development
is exactly where built-but-inactive land should concentrate.

## 3.5 The activity index

Three independent signals are combined, each normalised **per unit of built-up
area** so the value reflects intensity of use rather than size of settlement.

| Signal | Weight | Source |
|---|---|---|
| Nighttime light radiance | 0.45 | `NOAA/VIIRS/DNB/ANNUAL_V21` and `_V22` |
| Point-of-interest density | 0.35 | OpenStreetMap via the Overpass API |
| Population density | 0.20 | `GHS-POP R2023A` |

Normalisation is essential: raw radiance mostly measures how large a place is.
Three signals are used rather than one because each fails differently — light
misses unlit but occupied areas, points of interest are unevenly mapped, and
population misses commercial districts. Requiring agreement across signals is
what makes a low reading meaningful.

## 3.6 The ghost-growth method — the project's differentiator

### Step 1 — learn the city's own norm

Instead of a fixed threshold, the system computes a **binned median of activity
against built-up intensity** across the whole city. This produces an
*expected-activity curve* describing what activity level is normal for each
level of development **in Varanasi specifically**.

This is the core methodological contribution. A fixed brightness cut-off has to
be re-tuned for every city and every sensor version. A learned norm transfers to
any city unchanged, because it is derived from that city's own data.

### Step 2 — residual and recency screen

A cell is flagged when **both** hold:

- its activity falls far below the expected curve (a large negative residual),
  and
- the development is recent — measured by `new_share`, the proportion of the
  cell's current built-up area that appeared after the 2010 baseline.

The recency condition prevents long-standing low-activity land (an old
industrial estate) from being confused with new development that never filled.

### Step 3 — the trend test that separates stalled from filling-up

Where a nighttime-light time series exists, each cell's radiance trend is fitted
over 2013–2024. Cells that are dim **but measurably brightening** are classified
`emerging` rather than `ghost_growth`.

This single test is what §2.6 identifies as missing from the literature, and
§7.4 shows it accounts for 95% of what would otherwise be reported as a problem.

### Step 4 — the six-class growth typology

| Class | Meaning |
|---|---|
| `ghost_growth` | New development, activity far below expectation, **not** rising |
| `emerging` | New development, low activity but **rising** — filling up |
| `healthy_growth` | New development performing normally |
| `established_active` | Built before the baseline, performing normally |
| `declining` | Established, underperforming **and falling** |
| `undeveloped` | Below the built-up threshold |

### Step 5 — zone clustering

Individual flagged cells are grouped into contiguous zones using a
**density-ratio-to-background** rule: a neighbourhood qualifies when its local
density of flagged cells exceeds the citywide background rate by a set factor.
This produces zones a planner can inspect, rather than scattered single cells.

## 3.7 Green cover and surface heat

**Green cover.** NDVI (Normalized Difference Vegetation Index) is computed from
`COPERNICUS/S2_SR_HARMONIZED` over an October–March window, avoiding the heavily
clouded June–September monsoon. Only NDVI decline that **coincides with built-up
gain** is counted as urbanisation-driven, because most vegetation change across
this largely agricultural area is the *rabi* cropping calendar rather than
construction.

**Surface heat.** LST is computed from `LANDSAT/LC08/C02/T1_L2` and
`LANDSAT/LC09/C02/T1_L2` band `ST_B10` over the pre-monsoon March–May window.
Heat-island intensity is LST minus the median LST of rural land **in the same
scene, with water excluded**. Excluding water matters: the Ganga would otherwise
drag the rural baseline down and inflate apparent heat-island intensity across
the whole city.

## 3.8 The predictive expansion model

### Drivers

Seven variables are computed per cell:

| Driver | Rationale |
|---|---|
| Distance from the city centre | Growth concentrates nearer the centre |
| Distance from the existing built-up edge | New building appears beside old building |
| Current built-up fraction | Partly built cells fill in further |
| Road density | Roads precede buildings |
| Population | People attract construction |
| Neighbourhood built-up | Local context drives conversion |
| Slope | Steep land is harder to build on |

### Model

**Logistic Regression** estimates, for each currently non-urban cell, the
probability that it becomes built-up. Class weights are balanced, because
conversion is a rare event.

A **constrained cellular automaton** then allocates the expected quantity of new
development to the highest-suitability cells, with each cell also weighted by
its neighbourhood (300 m neighbourhood, neighbourhood weight 0.35, eight
iterations). Without this step the model scatters predicted growth as isolated
cells; with it, development appears in connected patches, which is how cities
actually grow.

### Why not deep learning

Per §2.4: published work reports U-Net at parity with cellular-automaton models
for this task, the gain over a random forest is around 0.05 in area under the
curve, and deeper networks gave no gain at all in Sirko et al. A U-Net needs a
large labelled training set and a graphics processing unit, and produces a model
whose reasoning cannot be shown to a planner. Logistic Regression needs neither
and yields coefficients that can be read directly. Deep learning is recorded as
a possible later upgrade, not dismissed.

### Validation discipline

- **Train** on 2010→2015. **Test** on 2015→2020, a period the model never saw.
- **Benchmark** against random allocation of the same demand, repeated 20 times.
- **Epoch discipline.** `GHS-BUILT-S R2023A` supplies epochs to 2030, but only
  1975–2020 are observational; 2025 and 2030 are the GHSL model's own
  projections. Fitting or validating against them would measure agreement
  between two models rather than accuracy against reality, so they are excluded
  from all fitting.

### Why Figure of Merit rather than accuracy

```
Figure of Merit  =  hits / (hits + misses + false alarms)
```

Overall accuracy is actively misleading for land change. On this data a **null
model predicting no change at all scores 98.91%** — better than our model's
98.1%. Persistence dominates every cell count. The Figure of Merit ignores
correct rejections and measures only the change class, which is what is being
predicted. Chen, G. et al. (2020) give the same justification.

---

# 4. Dataset Exploration

## 4.1 Datasets requiring no account

| Official product | Provider | Resolution | Coverage used |
|---|---|---|---|
| `GHS-BUILT-S R2023A` | European Commission Joint Research Centre | 100 m | 1975–2020 observed, five-yearly |
| `GHS-POP R2023A` | European Commission Joint Research Centre | 100 m | 1975–2020, five-yearly |
| OpenStreetMap via the Overpass API | OpenStreetMap contributors | vector | Current snapshot |

`GHS-BUILT-S R2023A` is the backbone because it is the only multi-epoch,
globally consistent built-up product downloadable in bulk **without an account**,
and its five-yearly epochs land exactly on the years we want. It is distributed
on a 1,000,000 m Mollweide grid; Varanasi falls entirely inside tile `R6_C26`,
computed from the area of interest rather than hard-coded.

## 4.2 Datasets requiring Google Earth Engine

| Official asset identifier | Provider | Resolution | Imagery dates |
|---|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` | NOAA | 463 m | 2013–2021 |
| `NOAA/VIIRS/DNB/ANNUAL_V22` | NOAA | 463 m | 2022 onward |
| `COPERNICUS/S2_SR_HARMONIZED` | ESA / Copernicus | 10 m native | 01 Oct 2024 – 30 Mar 2025 |
| `LANDSAT/LC08/C02/T1_L2` | USGS | 30 m | 12 Mar – 15 May 2024 |
| `LANDSAT/LC09/C02/T1_L2` | USGS | 30 m | 2021 onward |
| `GOOGLE/DYNAMICWORLD/V1` | Google | 10 m | 01 Oct 2024 – 30 Mar 2025 |
| `GOOGLE/Research/open-buildings-temporal/v1` | Google | 4 m | 2023 |
| `USGS/SRTMGL1_003` | NASA / USGS | 30 m | Single epoch |

Acquisition dates were **read back from the image collections themselves**, not
assumed from filenames. The Sentinel-2 composite is a median of **116 scenes
across 29 separate days**; the Landsat thermal composite is **10 scenes on 5
days**; Dynamic World is **154 classifications on 60 days**.

## 4.3 Two VIIRS assets are required, not one

The annual VIIRS series is **split across two product versions** in the Earth
Engine catalogue. `ANNUAL_V21` holds 2013–2021 and `ANNUAL_V22` holds 2022
onward. Querying `ANNUAL_V22` for an earlier year returns an **empty collection
rather than an error**. The two versions share the same core compositing
algorithm, so joining them is a version step rather than a sensor change — but it
is still a discontinuity, and any trend crossing 2021/2022 carries it.

## 4.4 Bands actually used, and why

| Dataset | Band | Reason |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` | `average_masked` | The plain `average` band retains a background noise floor that registers as activity in unlit peri-urban cells — exactly the cells being judged |
| `COPERNICUS/S2_SR_HARMONIZED` | `B8`, `B4` | Near Infrared and Red, giving NDVI |
| `COPERNICUS/S2_SR_HARMONIZED` | `B11`, `B8` | Shortwave Infrared and Near Infrared, giving NDBI (Normalized Difference Built-up Index) |
| `COPERNICUS/S2_SR_HARMONIZED` | `B4`, `B3`, `B2` | Red, Green, Blue — true-colour composite |
| `LANDSAT/LC08/C02/T1_L2` | `ST_B10` | Surface temperature band of Collection 2 Level-2 |

## 4.5 Sentinel-2 coverage is sparse before 2018

| October–March window | Scenes | Distinct days |
|---|---|---|
| 2015–16 | 3 | **1** |
| 2017–18 | 57 | 18 |
| 2018–19 | 117 | 31 |
| 2024–25 | 148 | 35 |

A median composite over a single day is not a seasonal median — it is one
observation with that day's weather and phenology baked in. The vegetation
baseline is therefore **2018**, the first year past 30 acquisition days, and the
code refuses any composite built from fewer than 20 distinct dates.

## 4.6 Dataset, raw variable, derived output

These three are distinct and are never used interchangeably.

| Official dataset | Raw variable | Derived output |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` | Nighttime light radiance | Activity map; activity trend |
| `COPERNICUS/S2_SR_HARMONIZED` | Surface reflectance | NDVI → vegetation map → green-cover change |
| `LANDSAT/LC08/C02/T1_L2` | Surface temperature | Heat-island intensity map |
| `GHS-BUILT-S R2023A` | Built-up surface density | Expansion map; infill/edge/leapfrog classification |
| `GHS-POP R2023A` | Gridded population estimate | Activity denominator |
| OpenStreetMap | Mapped points and lines | Point-of-interest density; road density |

## 4.7 What is measured and what is inferred

No dataset used here contains economic output, occupancy or ownership. Every
statement about those is an inference and is labelled as one.

| Claim | Status |
|---|---|
| Built-up surface area | **Measured**, with model error |
| Nighttime light radiance | **Measured** |
| Land surface temperature | **Measured** |
| Economic activity | **Proxy** — radiance, points of interest and population combined |
| Ghost growth | **Inference** — activity far below the local norm |
| Population | **Estimate** — `GHS-POP R2023A` is modelled, not a census |
| Built-up in 2025 and 2030 | **Projection** — GHSL's own model output |
| Urban extent in 2030 | **Prediction** — our suitability model plus cellular automaton |

## 4.8 Datasets deliberately not used

| Dataset | Why not |
|---|---|
| `NOAA/DMSP-OLS/NIGHTTIME_LIGHTS` | The analysis window starts in 2010 and the baseline is 2010. DMSP-OLS saturates and blooms, and converting it to match VIIRS adds a large error term to buy history the project does not use |
| WorldPop | `GHS-POP R2023A` is built from the same chain as `GHS-BUILT-S`, keeping population and built-up internally consistent. WorldPop is implemented as an independent cross-check but is off the critical path |
| `COPERNICUS/S1_GRD` | Sentinel-1 radar needs a speckle-filtering and calibration chain the project does not require, given GHSL already supplies validated built-up surface |
| `NASA/HLS/HLSL30/v002` | `COPERNICUS/S2_SR_HARMONIZED` alone gives enough clear October–March scenes |
| `GHS-SMOD R2023A` | Itself derived from `GHS-BUILT-S` and `GHS-POP` by thresholding. The two masks needed are derived directly — same information, about 1 GB less transfer, and the masks stay at 100 m instead of a 1 km floor |

---

# 5. System Architecture

## 5.1 Four layers

```
┌─────────────────────────────────────────────────────────┐
│  PRESENTATION                                           │
│  Dashboard — maps, numbers, downloadable files          │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  ANALYSIS                                               │
│  Built-up change · activity · vegetation · heat         │
│  Ghost growth · growth prediction                       │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  ACQUISITION                                            │
│                                                         │
│   OPEN PATH                    EARTH ENGINE PATH        │
│   no account needed            one-time login           │
│   ├ GHS-BUILT-S R2023A         ├ VIIRS nighttime light  │
│   ├ GHS-POP R2023A             ├ Sentinel-2             │
│   └ OpenStreetMap              ├ Landsat 8 and 9        │
│                                ├ Dynamic World          │
│                                └ Open Buildings         │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  CONFIGURATION                                          │
│  City, area, grid size, years, thresholds, sources      │
└─────────────────────────────────────────────────────────┘
```

Data flows upward; each layer talks only to the one below it.

## 5.2 Module map

| Module | Responsibility |
|---|---|
| `config.py` | Reads the configuration file |
| `aoi.py` | Builds the two matching grids from the area of interest |
| `data/ghsl.py` | `GHS-BUILT-S R2023A` and `GHS-POP R2023A`, including tile computation |
| `data/osm.py` | OpenStreetMap places and roads via the Overpass API |
| `data/gee.py` | All Google Earth Engine layers |
| `data/worldpop.py` | Optional independent population cross-check |
| `data/download.py` | Resumable downloads, extraction |
| `analysis/builtup.py` | Change detection, urban form, growth hotspots |
| `analysis/nightlights.py` | Trend fitting, Sum of Lights, normalisation |
| `analysis/vegetation.py` | Green-cover change and conversion to built-up |
| `analysis/thermal.py` | Heat-island intensity, vulnerability |
| `analysis/ghost.py` | Activity index, expected-activity residual, typology |
| `analysis/growth_model.py` | Driver construction, fitting, allocation, projection |
| `analysis/zonal.py` | 100 m → 500 m aggregation and export |
| `pipeline.py` | Runs the stages in order |
| `dashboard/app.py` | The dashboard |

Two rules keep the boundary clean:

- **Acquisition modules never analyse.** They fetch and reproject, nothing else.
- **Analysis modules never download.** They receive grids already prepared.

This is why analysis can be tested on synthetic data with no network access —
the test suite runs in seconds.

## 5.3 Inter-stage data model

Each stage adds to one shared object passed along the pipeline:

| Field | Contents |
|---|---|
| `layers` | The grids themselves, one per indicator |
| `stats` | Summary numbers for the report |
| `provenance` | Which dataset each layer came from |
| `skipped` | Any layer that could not be produced, and why |

`skipped` is the important one. A layer that fails is **recorded rather than
dropped**, so a missing result is visible in the output and on the dashboard
instead of silently reading as zero.

## 5.4 Failure behaviour

```
  stage runs
      ├── success  → results added, next stage starts
      └── failure  → reason recorded in `skipped`, next stage starts
```

Public data sources rate-limit and time out, and Google Earth Engine requires an
account. If any one of those halted the whole run, the system would produce
nothing on a bad day. Instead the `GHS-BUILT-S R2023A` and OpenStreetMap path
always works, so there is always a result.

## 5.5 Design decisions and reasons

| Decision | Reason |
|---|---|
| Two acquisition paths | The core result exists before anyone logs in |
| Everything driven by a configuration file | A different city is a new file, not a code change — this is what makes the city-search goal reachable |
| Two matching grids | Keeps change detection sharp while keeping claims honest |
| Failed stage records itself and the run continues | A partial answer beats no answer |
| Learned norm rather than a fixed threshold | Transfers to a new city unchanged |
| Logistic Regression rather than deep learning | No graphics processing unit, no labels, readable coefficients, little accuracy given up |
| Colour palette validated for colour-vision deficiency | The intuitive green/red pairing measures ΔE 4.1 under deuteranopia — the two most important classes would be indistinguishable to a red-green colourblind reader |

---

# 6. Proposed Solution

## 6.1 The end goal — city search to detailed analysis

```
  1. User searches for a city
             ↓
  2. System draws a circle around the city centre
     (user-adjustable radius; automatic fitting later)
             ↓
  3. System downloads satellite data for that circle
     GHSL · VIIRS · Sentinel-2 · Landsat · OpenStreetMap
             ↓
  4. Indicators computed for every grid cell
     built-up · vegetation · temperature · night light · shops · roads
             ↓
  5. Machine-learning models run on those indicators
             ↓
  6. Dashboard presents
     • how the city has grown so far
     • where growth is predicted, +5 and +10 years
     • which development is underused
```

**Why a circle.** A city has no single official boundary available everywhere,
and municipal limits routinely exclude the fastest-growing peri-urban belt —
which is exactly where the findings concentrate. A circle around the centre is
simple, works for any city, and can be widened by the user.

**Current state.** Steps 3–6 work today. Steps 1–2 are performed by editing
`config/varanasi.yaml` rather than typing a name. Replacing that file with a
search box changes only the centre point and radius; nothing downstream changes.
This is the honest position and it is stated as such.

## 6.2 The complete pipeline — seven stages

Run with `python -m urbanintel.pipeline`.

| # | Stage | Reads | Produces |
|---|---|---|---|
| 1 | `builtup` | `GHS-BUILT-S R2023A`, `GHS-POP R2023A` | Built-up per epoch, change, urban form, population |
| 2 | `osm` | OpenStreetMap | Point-of-interest density by sector, road density |
| 3 | `gee` | VIIRS, Sentinel-2, Landsat, Dynamic World, Open Buildings | Radiance and its trend, NDVI, NDBI, LST, land cover, building height |
| 4 | `vegetation` | NDVI from 3, built-up change from 1 | Green lost, and how much became built-up |
| 5 | `thermal` | LST from 3 | Heat-island intensity, hotspots, vulnerability |
| 6 | `ghost` | Radiance, points of interest, population, built-up | Activity index, expected-activity residual, six-class typology, zones |
| 7 | `export` | Everything above | 500 m grid, 51 rasters, summary with provenance |

The prediction model runs as a separate step, `scripts/run_growth_model.py`,
because it consumes the pipeline's output as its input.

## 6.3 Models used, and why each

| Model | Where used | Why this model |
|---|---|---|
| **Binned median regression** | Expected-activity curve (§3.6) | Non-parametric, so it adapts to any city's own relationship between building and activity without assuming a functional form. This is what replaces a fixed threshold |
| **Ordinary least squares trend** with significance test | Nighttime-light trend per cell | Twelve annual observations per cell; a linear slope with a p-value is sufficient and interpretable. Separates `emerging` from `ghost_growth` |
| **Landscape expansion index** | Urban form classification | A geometric rule, not a learned model — the classification is definitional, so learning it would add error without adding information |
| **Logistic Regression** (balanced class weights) | Growth suitability | Rare-event binary outcome; coefficients are directly readable, which matters for a planning audience |
| **Constrained cellular automaton** | Growth allocation | Enforces spatial contiguity that a per-cell model cannot express. Follows Liang et al. (2021) |
| **Random-allocation baseline** | Model benchmarking | Without it a Figure of Merit is uninterpretable — the reader cannot tell whether 0.07 reflects skill or the base rate |

### Models considered and not adopted

| Model | Why not |
|---|---|
| U-Net or other convolutional network | Needs labelled training data and a graphics processing unit; literature reports parity with cellular automata for this task (§2.4). Recorded as a Phase 3 upgrade |
| Random forest for suitability | Would improve fit but has no view of a cell's surroundings and yields no readable coefficients. Planned as a Phase 3 comparison baseline, following Shojaei et al. |
| CA-Markov | Superseded by patch-based cellular automata in the current literature |

## 6.4 How the datasets are approached

The approach is deliberately layered so that no single dataset failure destroys
the result.

**First, establish the physical facts.** `GHS-BUILT-S R2023A` and
`GHS-POP R2023A` give built-up surface and population with no account required.
This alone yields expansion rates, urban form, and the land-versus-population
ratio — the core finding of the project.

**Second, add activity.** VIIRS radiance, OpenStreetMap points of interest and
population are combined into one index, each normalised per unit of built-up
area. No single signal is trusted; agreement across three is what makes a low
reading meaningful.

**Third, add the trend.** The twelve-year radiance series turns a static reading
into a direction of travel, which is what separates stalled development from
development filling up.

**Fourth, add context.** NDVI gives green-cover loss attributable to
construction; LST gives heat-island intensity; Dynamic World cross-checks land
cover and supplies the water mask; Open Buildings adds the vertical dimension.

**Fifth, project forward.** The seven drivers feed the suitability model, whose
output the cellular automaton allocates.

Each tier is independently useful, and each degrades gracefully if its data is
unavailable — recorded in `skipped` rather than silently dropped.

## 6.5 Dashboard

The delivered dashboard has six tabs:

| Tab | Contents |
|---|---|
| Map | 12 selectable layers over the reporting grid |
| Growth | Expansion by epoch, urban form breakdown, growth hotspots |
| Ghost growth | Typology areas, ranked zone table, zone locations |
| Environment | Green-cover loss, heat-island intensity and hotspots |
| Data | The full 4,765-cell grid, downloadable as CSV, plus the summary |
| Sources | Every dataset with its official identifier and **actual imagery dates** |

A separate lightweight **dataset viewer** (`dataset_viewer/map.html`) presents
each acquired dataset as a georeferenced overlay on a zoomable street map, with
opacity control and per-layer acquisition dates. It requires no server and works
offline.

---

# 7. Results Obtained So Far

## 7.1 Urban expansion, 2010–2020 (observational)

| Year | Built-up surface | Urban extent (≥20% built) | Population |
|---|---|---|---|
| 2010 | 72.48 km² | 128.43 km² | 4.17 M |
| 2015 | 81.05 km² | 142.25 km² | 4.41 M |
| 2020 | 89.73 km² | 154.39 km² | 4.60 M |

- Built-up surface **+23.8%** over ten years
- Urban extent **+1.40% per year** compound
- Population **+10.3%**
- **Land consumed 2.3× faster than population** — the single most
  policy-relevant number in this project

## 7.2 Form of new development

Of 13.45 km² that newly crossed the urban threshold:

| Form | Area | Share |
|---|---|---|
| Infill | 0.95 km² | **7.1%** |
| Edge expansion | 5.94 km² | 44.2% |
| **Leapfrog** | **6.56 km²** | **48.8%** |

Nearly half of new development is detached from the existing urban fabric.

## 7.3 Growth typology (500 m reporting grid)

| Class | Area |
|---|---|
| Undeveloped | 1,101.09 km² |
| Established active | 140.69 km² |
| Healthy growth | 4.54 km² |
| Emerging | 6.88 km² |
| Declining | 5.70 km² |
| **Ghost growth** | **0.35 km²** across 15 zones |

## 7.4 The result that validates the method

Before the nighttime-light series was integrated, the system flagged
**7.24 km²** and labelled it an upper bound, stating in advance that dim-but-
brightening cells could not be separated from dim-and-static ones. Adding the
2013–2024 series split it almost exactly:

```
old ghost_growth   7.24 km²
├── ghost_growth   0.35 km²   dim and NOT rising
└── emerging       6.88 km²   dim but BRIGHTENING — filling up
                   ────────
                   7.23 km²
```

**95% of what looked like stalled development is a neighbourhood mid-occupation.**
A new class also appeared that could not exist before: **5.70 km² `declining`**,
drawn entirely out of `established_active` (146.39 → 140.69 km², an exact match).

All 15 remaining zones are peripheral, consistent with 48.8% leapfrog growth —
two independent analyses agreeing.

## 7.5 Activity, green cover and heat

| Metric | Value |
|---|---|
| Sum of lights, 2013 → 2024 | 518,008 → 905,354 (**+74.8%**) |
| Lit fraction of the area, 2024 | 95.5% |
| Green cover, 2018 → 2024 | 71.0% → 77.9% |
| Green lost | 6.37 km² |
| **Green lost specifically to built-up conversion** | **0.05 km²** |
| Rural reference temperature, pre-monsoon 2024 | 41.12 °C |
| Mean urban heat-island intensity | +1.10 °C |
| Maximum intensity | +9.27 °C |
| Hotspot area (≥ +3 °C) | 26.57 km² |

**The gross green-cover figure is not reported as a finding.** The October–March
window is the *rabi* cropping season, so NDVI across an agricultural area tracks
the wheat and pulse crop far more than urban canopy. Only `lost_to_builtup` is
robust, because intersecting NDVI loss with built-up gain removes anything that
is merely a cropping-calendar difference.

## 7.6 Predictive model validation

| Metric | Value |
|---|---|
| AUC (Area Under the Curve), training | 0.9901 |
| **Figure of Merit**, held-out 2015→2020 | **0.0679** |
| Random-allocation baseline | 0.0055 |
| **Skill versus random** | **12.3×** |
| Cohen's κ | 0.1176 |
| Hits / observed conversions | 154 / 1,214 |
| Projected urban extent, 2030 | **+31.21 km²** |

All seven coefficient signs are theoretically correct — distance from centre
−0.1410, distance from urban edge −0.1438, built-up fraction +2.2616.

**Honest reading.** A Figure of Merit of 0.068 means roughly one in fifteen
predicted conversions is correct, below the 0.1–0.3 typical of published
land-change models and well below the 0.2642 reported by Liang et al. The model
carries real signal — 12.3× better than chance — but is **not accurate enough
for parcel-level use**, and is not presented as such.

**An independent check worth reporting.** Our 2030 projection was compared
against GHSL's own 2025 projection — same 2020 starting state, comparable demand.
They agree at **Figure of Merit 0.0013**, essentially not at all. Two models
starting from identical conditions place growth in almost entirely different
locations. This independently justifies excluding the projected epochs, and is a
real caution about treating modelled land-cover products as data.

## 7.7 Verification

- **25 of 25 automated tests pass**, covering grid nesting, area conservation
  under aggregation, the priority reducer, urban form classification, trend
  recovery, the ghost screen on synthetic data with a known answer, and the
  land-change metric accounting
- **Pipeline runs end to end with no skipped layers**, producing 51 raster
  layers, a 4,765-cell reporting grid, and a summary carrying full provenance
- **Dashboard renders with 0 exceptions**, 6 tabs
- **Colour palette validated** with a colour-vision-deficiency checker rather
  than chosen by eye

---

# 8. Technical Challenges and Corrective Action

Seven defects were found and fixed. Four were caught by disbelieving an
implausible result rather than by a test — which is why they are recorded here
rather than quietly corrected.

| # | Defect | How it would have corrupted the output |
|---|---|---|
| 1 | **Frame misalignment.** The 100 m and 500 m frames were built by independent calls, each snapping outward to its own resolution | They did not tile each other; aggregation crashed on a shape mismatch. Had the dimensions happened to agree, every aggregate would have been silently misaligned instead. Fixed with `AOI.frame_pair()` |
| 2 | **Resolution-dependent threshold.** `min_builtup_m2: 5000` was documented as "2% of a 500 m cell" but applied on the 100 m frame, where it means **50%** | The activity index was defined for only 1,418 of 15,816 urban cells. Now expressed as a fraction of cell area |
| 3 | **Majority aggregation erased the findings.** Ghost cells are a minority by nature | A 500 m majority vote wiped every one out of the reporting grid. Replaced with a `priority` reducer that surfaces the most significant class present; regression test added |
| 4 | **Perfect linear fit mapped to p = 1.** Zero residual gave t = 0 | Discarded exactly the cleanest nightlight trends. Fixed to treat a perfect fit as maximally significant |
| 5 | **GHSL 2025 and 2030 treated as observations.** They are the GHSL model's own projections | The model was being validated against another model's forecast, and Phase 1 headline figures presented a forecast as measurement. All fitting now restricted to 1975–2020 |
| 6 | **Nine of twelve nightlight years silently missing.** The whole series pointed at `ANNUAL_V22`, which holds only 2022 onward | Every pre-2022 year resolved to an *empty* collection. The trend separating `ghost_growth` from `emerging` would have been fitted on three years instead of twelve. Fixed with asset-resolution by year, plus an explicit error when a year yields zero images |
| 7 | **Vegetation baseline was one day of imagery.** The Oct 2015 – Mar 2016 window holds 3 scenes, all from 2015-12-28 | Differencing it against a 148-scene composite produced an apparent green-cover rise from **27.9% to 77.9%** — entirely an artefact of sampling depth. Baseline moved to 2018 and a minimum composite-depth check added |

**Defects 6 and 7 share a shape worth naming.** Neither threw an exception, both
produced numbers of the right order of magnitude, and the vegetation one would
have been reported as a striking positive finding. They were caught by checking
provenance against expectation — asking whether a 50-point rise in green cover
in six years was physically plausible — not by any test. Both now have
**structural guards** so the class of error cannot recur silently for any index,
year or city.

---

# 9. Limitations and Future Work

## 9.1 What this system is not

- **A screening tool, not a census.** VIIRS resolves about 460 m and cannot see
  one empty housing block. The unit of a reliable finding is a neighbourhood.
- **Unvalidated against ground truth.** Nothing here has been checked against
  observation. At 0.35 km², some zones are four 50 m cells — small enough that a
  single mapping error could produce one.
- **Dependent on an uneven OpenStreetMap.** Varanasi's core is well mapped; the
  periphery is not, and all 15 zones are peripheral.
- **Built on a modelled product.** `GHS-BUILT-S R2023A` is modelled, not
  measured, and is documented to under-detect low-rise informal development.
- **Carrying a version discontinuity** at 2021/2022 in the nightlight series.
- **Reporting a modest predictive score.** Figure of Merit 0.0679 is real signal
  but not parcel-accurate.

Zones 14 and 15, at scores 0.56 and 0.50 with the shallowest residuals, are the
boundary of the method's discrimination and should be presented as such rather
than as findings of equal standing.

## 9.2 Future work

| Priority | Task | Why |
|---|---|---|
| 1 | **Ground validation of the 15 zones** | Converts a screening output into an evidenced finding; the single highest-value remaining step |
| 2 | **Ward-level reporting** on Census 2011 Varanasi Nagar Nigam boundaries (90 wards) | Municipal planners act on wards, not a 500 m grid |
| 3 | **City search box** replacing the configuration file | Delivers the stated end goal; nothing downstream changes |
| 4 | **Building height from Open Buildings Temporal** | Distinguishes densification from outward spread, and a tall unlit building is a far stronger signal than area alone |
| 5 | **Random-forest baseline** for the suitability model | Like-for-like comparison following Shojaei et al. |
| 6 | **Master-plan overlay** from the Varanasi Development Authority | Yields development where none was planned, and planned development that never materialised — the sharpest available framing |
| 7 | **Multi-city comparison** | The configuration is already city-agnostic |

---

# 10. References

1. Chen, X., Wang, Z., Zhang, F., Shen, G. & Chen, Q. (2024). A global annual
   simulated VIIRS nighttime light dataset from 1992 to 2023. *Scientific Data*
   **11**, 1380. DOI 10.1038/s41597-024-04228-6
2. Tian, Y., Cheng, K. M., Zhang, Z. et al. (2026). An Extended VIIRS-like
   Artificial Nighttime Light Data Reconstruction (1986–2024). *Scientific Data*
   **13**, 233. DOI 10.1038/s41597-026-06549-0
3. Chen, Z. et al. (2021). An extended time series (2000–2018) of global
   NPP-VIIRS-like nighttime light data from a cross-sensor calibration.
   *Earth System Science Data* **13**, 889–906. DOI 10.5194/essd-13-889-2021
4. Li, X., Zhou, Y., Zhao, M. & Zhao, X. (2020). A harmonized global nighttime
   light dataset 1992–2018. *Scientific Data* **7**, 168.
   DOI 10.1038/s41597-020-0510-y
5. Zhang, L., Ren, Z., Chen, B., Gong, P., Xu, B. & Fu, H. (2024). A Prolonged
   Artificial Nighttime-light Dataset of China (1984–2020). *Scientific Data*
   **11**, 414. DOI 10.1038/s41597-024-03223-1
6. Nechaev, D., Zhizhin, M., Poyda, A., Ghosh, T., Hsu, F.-C. & Elvidge, C.
   (2021). Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and
   SNPP/VIIRS with Residual U-Net. *Remote Sensing* **13**(24), 5026.
   DOI 10.3390/rs13245026
7. Goldblatt, R., Stuhlmacher, M. F., Tellman, B. et al. (2018). Using Landsat
   and nighttime lights for supervised pixel-based image classification of urban
   land cover. *Remote Sensing of Environment* **205**, 253–275.
8. Marconcini, M., Metz-Marconcini, A., Üreyen, S. et al. (2020). Outlining
   where humans live, the World Settlement Footprint 2015. *Scientific Data*
   **7**, 242. DOI 10.1038/s41597-020-00580-5
9. Tang, Y., Shao, Z., Huang, X. & Cai, B. (2021). Mapping Impervious Surface
   Areas Using Time-Series Nighttime Light and MODIS Imagery. *Remote Sensing*
   **13**(10), 1900. DOI 10.3390/rs13101900
10. Sirko, W., Kashubin, S., Ritter, M. et al. (2021). Continental-Scale
    Building Detection from High Resolution Satellite Imagery. *arXiv:2107.12283*
11. Brown, C. F., Brumby, S. P., Guzder-Williams, B. et al. (2022). Dynamic
    World, Near real-time global 10 m land use land cover mapping.
    *Scientific Data* **9**, 251. DOI 10.1038/s41597-022-01307-4
12. Zhang, Y., Tu, T. & Long, Y. (2024). Inferring ghost cities on the globe in
    newly developed urban areas based on urban vitality with multi-source data.
    *arXiv:2408.15117*; published in *Cities* (2025).
13. Yeh, C., Perez, A., Driscoll, A. et al. (2020). Using publicly available
    satellite imagery and deep learning to understand economic well-being in
    Africa. *Nature Communications* **11**, 2583. DOI 10.1038/s41467-020-16185-w
14. Anucharn, T., Hongpradit, P., Iamchuen, N. & Puttinaovarat, S. (2025).
    Spatial Analysis of Urban Expansion and Energy Consumption Using Nighttime
    Light Data. *ISPRS International Journal of Geo-Information* **14**(4), 178.
    DOI 10.3390/ijgi14040178
15. Liang, X., Guan, Q., Clarke, K. C., Liu, S., Wang, B. & Yao, Y. (2021).
    Understanding the drivers of sustainable land expansion using a
    patch-generating land use simulation (PLUS) model. *Computers, Environment
    and Urban Systems* **85**, 101569. DOI 10.1016/j.compenvurbsys.2020.101569
16. Chen, G., Li, X., Liu, X. et al. (2020). Global projections of future urban
    land expansion under shared socioeconomic pathways. *Nature Communications*
    **11**, 537. DOI 10.1038/s41467-020-14386-x
17. Shojaei, H., Nadi, S., Shafizadeh-Moghadam, H., Tayyebi, A. & Van Genderen,
    J. (2022). An efficient built-up land expansion model using a modified
    U-Net. *International Journal of Digital Earth* **15**(1), 148–163.
    DOI 10.1080/17538947.2021.2017035
18. Zhang, A., Tariq, A., Quddoos, A. et al. (2025). Spatio-temporal analysis of
    urban expansion and land use dynamics using google earth engine and
    predictive models. *Scientific Reports* **15**, 6993.
    DOI 10.1038/s41598-025-92034-4
19. Ermida, S. L., Soares, P., Mantas, V., Göttsche, F.-M. & Trigo, I. F.
    (2020). Google Earth Engine Open-Source Code for Land Surface Temperature
    Estimation from the Landsat Series. *Remote Sensing* **12**(9), 1471.
    DOI 10.3390/rs12091471
20. Ramachandra, T. V., Rana, R. S., Vinay, S. & Aithal, B. H. (2025). Urban
    heat island linkages with the landscape morphology. *Scientific Reports*
    **15**, 24485. DOI 10.1038/s41598-025-09141-5

**Cited in support**

21. Liu, X., Li, X., Chen, Y., Tan, Z., Li, S. & Ai, B. (2010). A new landscape
    index for quantifying urban expansion using multi-temporal remotely sensed
    data. *Landscape Ecology* **25**, 671–682.
22. Pontius, R. G. et al. (2008). Comparing the input, output, and validation
    maps for several models of land change. *Annals of Regional Science* **42**,
    11–37. DOI 10.1007/s00168-007-0138-2
23. Henderson, J. V., Storeygard, A. & Weil, D. N. (2012). Measuring Economic
    Growth from Outer Space. *American Economic Review* **102**(2), 994–1028.

---

*Prepared with AI assistance (Claude), in line with §2 of the BCSE497J
guidelines. All figures are from an actual pipeline run recorded in
`outputs/varanasi_summary.json`; all citation metadata was verified against
Crossref or publisher records.*
