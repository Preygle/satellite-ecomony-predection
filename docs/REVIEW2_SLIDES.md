# Review 2 — Presentation Slide Content

**BCSE497J Project I · Panel Review · 20 marks · 19 August 2026**
Satellite-Based Urban Growth and Economic Activity Intelligence System — Varanasi

> **Correction notice (Review 3, 11 September 2026).** Kept as presented at
> Review 2. Several numbers below were computed against GHSL's 2025 epoch, a
> model projection. Use [`REVIEW3_REPORT.md`](REVIEW3_REPORT.md) for current
> figures; its §6 lists every correction.

> This file is the **content** for the slides, not the slides themselves. Each
> block below is one slide: what goes on it, and what you say. Build the deck
> from this. Keep the on-slide text as terse as it appears here — the sentences
> under *Say* are spoken, not projected.
>
> **Budget:** 22 slides for a 12–14 minute talk. Slides 23–28 are backup, held
> for questions and never presented. If you are cut to 8 minutes, drop 5, 11,
> 17 and 21.

---

## Rubric map — check this before you finalise

| # | Review 2 criterion | Marks | Slides |
|---|---|---|---|
| 1 | Domain understanding and problem definition | 3 | 2, 3, 4 |
| 2 | Literature review and analysis of existing approaches | 3 | 6, 7, 8, 9 |
| 3 | Objectives, scope and expected outcomes | 2 | 5 |
| 4 | Proposed methodology | 3 | 11, 12, 13 |
| 5 | System architecture and module design | 3 | 10 |
| 6 | Feasibility, risks, ethics and work planning | 3 | 20, 21 |
| 7 | Report quality, presentation, response to questions | 3 | 22, 23–28 |

Criterion 2 carries 3 marks and is where most teams are thin. Slides 6–9 are
built to carry it — do not compress them to make room for more results.

---

# SLIDE 1 — Title

**On slide**

> ### Satellite-Based Urban Growth and Economic Activity Intelligence System
> **Detecting built-but-inactive development from open satellite data**
> Case study: Varanasi, Uttar Pradesh
>
> *(names, register numbers)*
> Guide: *(name)* · SCOPE · Fall 2026–27 · Review 2

**Say:** Nothing beyond your names. Be on slide 2 within fifteen seconds.

---

# SLIDE 2 — The problem in one number

**On slide**

> ## Varanasi's built-up area grew **2.3× faster** than its population
>
> | 2010 → 2020 | Growth |
> |---|---|
> | Built-up surface | **+23.8%** (72.48 → 89.73 km²) |
> | Population | **+10.3%** (4.17 M → 4.60 M) |
>
> Land is being consumed far faster than people are being housed.
>
> **No municipal dataset records whether that land is actually being used.**

**Say:** Land consumption outpacing population by more than double is not
unusual for an Indian city. What is unusual is that nobody measures whether the
new land is occupied. That gap is the project.

**If asked why the table stops at 2020:** the observational record ends there.
GHSL (Global Human Settlement Layer)'s 2025 and 2030 epochs are the GHSL model's own projections — see slide 24.

---

# SLIDE 3 — Problem definition: why this is hard

**On slide**

> ### The two obvious detectors both fail
>
> | Detector | What it actually flags |
> |---|---|
> | Low nighttime lights | Every agricultural field, every unlit industrial estate |
> | Low population density | Every warehouse district, every commercial zone |
>
> Both mistake **different** for **empty**.
>
> ### What a correct method must do
> 1. Learn what "normal" activity is **for that city**, at each level of development
> 2. Flag departures from that norm — not from a fixed global threshold
> 3. Separate **stalled** development from **mid-occupation** development

**Say:** Spend time here. If the panel understands why the naive approach fails,
every later design decision reads as necessary rather than arbitrary. Point 3
turned out to matter most — hold that thought for slide 16.

---

# SLIDE 4 — Domain: what the sensors can and cannot see

**On slide**

> | Signal | Source | Resolution | Measures |
> |---|---|---|---|
> | Built-up surface | GHS-BUILT-S (Sentinel-2 + Landsat) | 100 m | Built surface density |
> | Economic activity | VIIRS (Visible Infrared Imaging Radiometer Suite) DNB nighttime lights | ~460 m | Radiance ≈ human activity |
> | Commercial function | OpenStreetMap POIs (Points of Interest) | vector | What kind of activity |
> | Vegetation | Sentinel-2 NDVI (Normalized Difference Vegetation Index) | 10 m | Green cover |
> | Surface heat | Landsat 8/9 thermal | 30 m | Land surface temperature |
>
> **VIIRS resolves ~460 m. The smallest honest unit of a finding is a
> neighbourhood, not a building.**
>
> Nighttime light is a **proxy** for economic activity, not a measurement of it
> — Henderson, Storeygard & Weil, *AER* 2012.

**Say:** The last two lines are where the domain-understanding marks are. Stating
the resolution limit unprompted separates a team that has read the literature
from one that has read a tutorial.

---

# SLIDE 5 — Objectives, scope and expected outcomes

**On slide**

> ### Objectives
> | | Objective | Status |
> |---|---|---|
> | O1 | Quantify built-up expansion across epochs | ✅ |
> | O2 | Classify form: infill / edge / leapfrog | ✅ |
> | O3 | Multi-signal economic activity index | ✅ |
> | O4 | Detect ghost growth without fixed thresholds | ✅ |
> | O5 | Green cover loss attributable to urbanisation | ✅ |
> | O6 | Surface urban heat island + vulnerability | ✅ |
> | O7 | Predict future expansion, validated | ✅ |
> | O8 | Deliver as an interactive dashboard | ✅ |
>
> **Scope:** Varanasi, 1,206 km² AOI (Area of Interest). Analysis 100 m, reporting 500 m.
> Observational epochs 2010 / 2015 / 2020, projection to 2030.
>
> **Explicitly out of scope:** building-level occupancy (below sensor
> resolution) · ground survey (Phase 3) · causal explanation of *why* a zone
> underperforms.

**Say:** Naming what is out of scope, and why, is worth more than adding a ninth
objective. The out-of-scope list shows the boundary was chosen, not stumbled into.

---

# SLIDE 6 — Literature: the landscape

**On slide**

> ### Two sets, reviewed on a stated selection criterion
>
> **Set A — VIIRS cross-sensor calibration (5 implementations)**
> Must: calibrate DMSP↔VIIRS · release a continuous annual product · validate by
> regression against real VIIRS · be an implementation, not a review
>
> | Study | Model | Product |
> |---|---|---|
> | Zheng, Weng & Wang 2019 | Statistical calibration | China 1996–2017 |
> | Li et al. 2020 | Sigmoid | Harmonized global 1992–2018 |
> | Zhao et al. 2020 | Sigmoid | SE Asia 1992–2018 |
> | Chen Z. et al. 2021 | Auto-encoder CNN (Convolutional Neural Network) + NDVI | ChenVNL, global |
> | Nechaev et al. 2021 | **Residual U-Net** | DMSP-like, global |
>
> **Set B — U-Net architectures (6 implementations)**
> Ronneberger 2015 · Nechaev 2021 · Sirko 2021 (Open Buildings) ·
> Shojaei 2022 (built-up expansion) · Wang 2022 (land-use simulation) ·
> Gui 2025 (U-Net++ + attention + CA)

**Say:** Lead with the *criterion*, not the list. Anyone can list five papers.
Stating the inclusion rule — and what it excluded, namely application papers
that consume these products rather than produce them — is the analysis mark.

---

# SLIDE 7 — Literature finding 1: accuracy is a function of scale, not model

**On slide**

> ### Chen et al. 2024 — U-Net super-resolution, DMSP → VIIRS
>
> | Scale | R² (2012) |
> |---|---|
> | Pixel | 0.617 |
> | City | 0.747 |
> | Province | 0.874 |
> | National | **0.964** |
>
> Model families across Set A: sigmoid · geographically weighted regression ·
> auto-encoder · U-Net · ConvLSTM.
> **Within a fixed transform direction they land in the same accuracy band.**
> Chen et al. describe their own U-Net as performing "closely to" an auto-encoder.
>
> > **Cross-sensor nighttime-light calibration is effectively solved at city
> > scale and unsolved at pixel scale. Changing the model family moves the
> > result far less than changing the scale at which the claim is made.**

**Say:** The most important slide in the literature section. It justifies both
our 500 m reporting grid and our refusal to make pixel-level claims.

---

# SLIDE 8 — Literature finding 2: error concentrates at the urban fringe

**On slide**

> ### The finding that changed our design
>
> Chen et al. 2024 document, from their own validation:
> - **Their product underestimates** radiance at the urban fringe — the CNN
>   pulls bright pixels down toward dark neighbours
> - **The competing ChenVNL product** overestimates urban cores and
>   underestimates peri-urban areas
>
> Two networks. Two bias signs. **Both worst at the fringe.**
>
> ### Consequence for us
> Every ghost-growth zone we identify is peripheral — the exact location where
> simulated nighttime-light products are least trustworthy.
>
> **→ We use observed VIIRS (VNL V2, 2012–) only. No harmonised long series.**

**Say:** This is your strongest "analysis of existing approaches" evidence. You
did not summarise the papers — you found the failure mode that applies to your
own study area and changed the design because of it.

---

# SLIDE 9 — Literature finding 3, and the gap

**On slide**

> ### U-Net's contribution is automation, not accuracy
> - **Wang et al. 2022:** U-Net achieved **similar accuracy to CA-based models** —
>   but learned neighbourhood, gravity and linear-development effects
>   *without being told about them*
> - **Sirko et al. 2021:** gains over a U-Net baseline were **+0.12 and +0.06 mAP**
>   — real, but tuning-scale
> - Cost: labelled data, GPU time, interpretability
>
> **→ Justifies our logistic suitability + constrained CA: no GPU, no labels,
> interpretable coefficients, little accuracy given up.**
>
> ### The gap
> | Existing work | Does | Does not do |
> |---|---|---|
> | Ghost-city studies (Jin 2017, Lu 2018) | Fixed thresholds on NTL + built-up | Adapt to the city's own norm |
> | NTL harmonisation (Set A) | Produce long consistent series | Say anything about occupancy |
> | Expansion models (Set B) | Predict *where* growth goes | Not *whether it will be used* |
>
> **Nobody combines a learned expected-activity curve with urban-form
> classification to separate stalled development from development
> mid-occupation.**

**Say:** The gap statement is the payoff of the whole literature section. Land it
slowly.

---

# SLIDE 10 — System architecture

**On slide**

> ```
> ┌──────────────── ACQUISITION ────────────────┐
> │ OPEN PATH (no credentials)   EARTH ENGINE   │
> │ ├── ghsl.py   built-up+pop   └── gee.py     │
> │ ├── osm.py    POIs + roads       ├ VIIRS NTL│
> │ └── worldpop.py cross-check      ├ S2 NDVI  │
> │                                  ├ Landsat  │
> │                                  ├ Dyn.World│
> └──────────────────────────────────┴ Buildings┘
>                      ↓
> ┌────────── ANALYSIS (100 m, UTM 44N) ──────────┐
> │ builtup.py     change, urban form, hotspots   │
> │ nightlights.py trend, Sum of Lights, norm.    │
> │ vegetation.py  green change and conversion    │
> │ thermal.py     SUHI, vulnerability            │
> │ ghost.py       activity → expected → residual │
> └───────────────────────────────────────────────┘
>                      ↓
> ┌─ zonal.py: 100 m → 500 m reporting grid ─┐
> │ 4,765 cells · GeoJSON · CSV · summary JSON│
> └───────────────────────────────────────────┘
>                      ↓
>            dashboard/app.py — 5 tabs
> ```
>
> **Dual-path design:** the open path runs end-to-end with **no account of any
> kind**. Earth Engine layers fold in automatically once available. Missing
> layers are recorded with a reason, never silently dropped.

**Say:** Defend the dual path out loud. Most projects of this kind stall at
"first, get an Earth Engine account." A pipeline that produces partial results
is a pipeline that produces results.

---

# SLIDE 11 — Methodology: data and processing

**On slide**

> ### Two grids, deliberately
> - **Analysis at 100 m** — GHSL-native, keeps change detection sharp
> - **Reporting at 500 m** — a 121,000-polygon web map is unusable, and would
>   over-claim precision that VIIRS cannot support
>
> ### Density-preserving reprojection
> GHSL ships in Mollweide (equal-area); analysis runs in UTM 44N. Built-up m²
> and population are **extensive** quantities → convert to density, reproject,
> rescale. Otherwise the totals do not survive the warp.
>
> ### Urban form classification
> Landscape expansion index (Liu et al. 2010) — each newly urbanised cell
> labelled **infill**, **edge expansion** or **leapfrog** by its spatial
> relationship to the existing urban fabric.

**Say:** The reprojection point is small but signals the work was done properly.
One sentence, then move on.

---

# SLIDE 12 — Methodology: the ghost-growth method *(the differentiator)*

**On slide**

> ### Step 1 — Composite activity index
> | Signal | Weight |
> |---|---|
> | VIIRS nighttime radiance | 0.45 |
> | OSM POI (Point of Interest) density | 0.35 |
> | Gridded population | 0.20 |
>
> All normalised **per unit built-up area** — raw radiance mostly measures how
> big a place is.
>
> ### Step 2 — Learn the city's own norm
> Binned median of activity against built-up intensity → an **expected-activity
> curve for Varanasi**. No global threshold. Transfers to any city unchanged.
>
> ### Step 3 — Residual + recency screen
> Flag cells where activity falls far below expectation **and** development is
> recent (`new_share` = share of current built-up that appeared post-2010).
>
> ### Step 4 — Six-class typology
> `ghost_growth` · `emerging` · `healthy_growth` · `established_active` ·
> `declining` · `undeveloped`
>
> **`emerging` is the class that makes this honest** — dim *but brightening* is
> a neighbourhood filling up, not a failed one.

**Say:** This is your novelty slide. Say the word "learned" and contrast it
explicitly with "threshold".

---

# SLIDE 13 — Methodology: predictive expansion model

**On slide**

> ### Logistic suitability + constrained cellular automaton
>
> **Seven drivers:** distance to centre · distance to urban edge · built-up
> fraction · road density · population · neighbourhood built-up · slope
>
> **Training discipline:** fit on 2010→2015, validate on **held-out** 2015→2020
>
> **Epoch discipline:** GHSL 2025 and 2030 are the GHSL model's own
> **projections**, not observations. Fitting to them would measure agreement
> between two models rather than accuracy against reality. **Excluded.**
>
> ### Why Figure of Merit, not accuracy
> `FoM = hits / (hits + misses + false alarms)`
>
> A null model predicting *no change* scores **98.91% overall accuracy** on this
> data. Ours scores 98.1%. **Overall accuracy is worse than useless here**
> — Pontius et al. 2008.

**Say:** The null-model number is your defence if a panel member fixates on
accuracy. Have it ready; it turns a hostile question into a strong answer.

---

# SLIDE 14 — Results: urban expansion

**On slide**

> | Year | Built-up surface | Urban extent | Population |
> |---|---|---|---|
> | 2010 | 72.48 km² | 128.43 km² | 4.17 M |
> | 2015 | 81.05 km² | 142.25 km² | 4.41 M |
> | 2020 | 89.73 km² | 154.39 km² | 4.60 M |
>
> - Built-up surface **+23.8%** in ten years
> - Urban extent **+1.40% per year** compound
> - Population **+10.3%**
>
> ## Ratio: **2.3× more land per person**

**Say:** One number to remember from this slide: 2.3.

---

# SLIDE 15 — Results: the form of new development

**On slide**

> ### Of 13.45 km² that newly crossed the urban threshold
>
> | Form | Area | Share |
> |---|---|---|
> | Infill | 0.95 km² | **7.1%** |
> | Edge expansion | 5.94 km² | 44.2% |
> | **Leapfrog** | **6.56 km²** | **48.8%** |
>
> **Nearly half of Varanasi's new development is detached from the existing
> urban fabric.**
>
> Leapfrog is the most expensive form to service — water, sewerage and transit
> all cost more per household — and the form most associated with
> under-occupancy. Infill, the cheapest, is 7.1%.

**Say:** This sets up slide 16. Leapfrog is *where* you expect ghost growth, so
two independent analyses agreeing is evidence, not coincidence.

---

# SLIDE 16 — Results: ghost growth, and a 20× correction

**On slide**

> ### The number changed by a factor of twenty — and that is the result
>
> **Before** the nighttime-light series was integrated: **7.24 km² flagged.**
> The report labelled it *an upper bound* and said why: without a time series, a
> neighbourhood filling up cannot be told from one that never will.
>
> **After** integrating VIIRS 2013–2024:
>
> ```
> old ghost_growth   7.24 km²
> ├── ghost_growth   0.35 km²   dim and NOT rising
> └── emerging       6.88 km²   dim but BRIGHTENING — filling up
> ```
>
> **95% of what looked like ghost growth is a neighbourhood mid-occupation.**
>
> A new class also appeared: **5.70 km² `declining`** — established land whose
> activity is below expectation *and falling*. Drawn entirely out of
> `established_active` (146.39 → 140.69 km², an exact match).
>
> All 15 remaining ghost zones are **peripheral** — consistent with 48.8%
> leapfrog.

**Say:** Do not hide this. Present it as the method working: the caveat was
stated in advance, the correction went in the predicted direction, and the
classifier's structure never changed — only the input completeness did. A panel
trusts a team that reports its own number moving.

---

# SLIDE 17 — Results: activity, green cover, heat

**On slide**

> ### Nighttime lights, 2013 → 2024
> Sum of lights **518,008 → 905,354 (+74.8%)** · lit fraction 95.5%
>
> ### Green cover, 2018 → 2024
> | Metric | Value |
> |---|---|
> | Green lost | 6.37 km² |
> | **Lost specifically to built-up conversion** | **0.05 km²** |
>
> ⚠ The gross green-cover figure tracks the **rabi cropping calendar**, not
> urban canopy. Only the built-up-conversion number is robust — we report that
> one.
>
> ### Urban heat island, pre-monsoon 2024
> Rural reference 41.12 °C · mean urban intensity **+1.10 °C** · peak **+9.27 °C** ·
> hotspot area **26.57 km²**

**Say:** The green-cover caveat is deliberate. Reporting the smaller defensible
number instead of the larger impressive one is the point.

---

# SLIDE 18 — Results: predictive model validation

**On slide**

> ### Train 2010→2015 · validate 2015→2020 (held out)
>
> | Metric | Value |
> |---|---|
> | AUC (training) | 0.9901 |
> | **Figure of Merit** | **0.0679** |
> | Random-allocation baseline | 0.0055 |
> | **Skill vs random** | **12.3×** |
> | Cohen's κ | 0.1176 |
> | Hits / observed | 154 / 1,214 |
>
> **2030 projection: +31.21 km² urban extent**
>
> ### Honest reading
> FoM 0.068 means roughly **1 in 15 predicted conversions is correct** — below
> the 0.1–0.3 typical of published land-change models. Real signal, **not good
> enough for parcel-level use**, and we say so.
>
> All seven coefficient signs are theoretically correct.

**Say:** Reporting a modest number as modest, with the baseline that makes it
interpretable, is worth more than a large number with no baseline.

---

# SLIDE 19 — Technical challenges and corrective action

**On slide**

> ### Seven defects found and fixed — four by disbelieving a result
>
> | # | Defect | How it would have corrupted the output |
> |---|---|---|
> | 1 | Frame misalignment (100 m vs 500 m) | Silently misaligned every aggregate |
> | 2 | Threshold applied at the wrong resolution | Activity defined for 1,418 of 15,816 cells |
> | 3 | Majority aggregation | Erased **every** ghost cell from the reporting grid |
> | 4 | Perfect linear fit → p = 1 | Discarded the *cleanest* nightlight trends |
> | 5 | GHSL 2025/2030 treated as observations | Validated our model against another model's forecast |
> | 6 | **9 of 12 nightlight years silently empty** | Trend fitted on 3 years instead of 12 |
> | 7 | **Vegetation baseline was ONE day of imagery** | Reported green cover 27.9% → 77.9%. Pure artefact. |
>
> **Defects 6 and 7 threw no exception and produced plausible numbers.** Caught
> by asking whether a 50-point green-cover rise in six years was physically
> possible.
>
> Both now have **structural guards**: asset-resolved-by-year, and a minimum
> composite-depth check that refuses any composite under 20 acquisition dates.

**Say:** This slide distinguishes you most. Panels see polished results
constantly; they rarely see a team that can explain a bug it caught in its own
work. Defect 7 is the best story — tell it in one sentence.

---

# SLIDE 20 — Feasibility, risks and ethics

**On slide**

> ### Feasibility
> - Every data source **open and free**. Credential-free path ≈ 330 MB.
> - **No GPU required** — the literature (slide 9) shows U-Net reaches CA
>   parity, so the deep-learning route was not worth its cost here.
> - Standard laptop. Python + rasterio / geopandas / scikit-learn / Streamlit.
>
> ### Risk register (abridged)
> | Risk | Mitigation | Status |
> |---|---|---|
> | Earth Engine unavailable | Dual-path architecture | **Realised** — Phase 1 completed without it |
> | Sparse OSM in the periphery | Require agreement across signals | Stated in every report |
> | No ground truth | Specified as a **screening tool** | Phase 3 |
> | Products confused with observations | Restrict claims to observational epochs | **Realised** — defect 5 |
>
> ### Ethics
> - All data **open-licensed**; OSM attribution (ODbL) carried
> - **No personal data.** The analysis unit is a 500 m cell, never a household
> - Output is a **screening tool for inspection**, not an occupancy census —
>   stated in the code, the summary JSON and the dashboard
> - AI assistance acknowledged, per guidelines §2

**Say:** Two of your four listed risks actually occurred and were handled. Say
that — a risk register that predicted real events is more credible than one
listing hypotheticals.

---

# SLIDE 21 — Work plan and progress

**On slide**

> | Phase | Target | Deliverable | Review |
> |---|---|---|---|
> | Setup | — | AOI, data inventory, literature | Review 1 ✅ |
> | Phase 1 | ~50% | Expansion, form, activity, ghost, dashboard | **Review 2 ✅** |
> | Phase 2 | ~80% | Predictive model, validation, corrections | Review 3 ✅ *(early)* |
> | Phase 3 | 100% | Ground validation, ward reporting, corridors, master plan | Review 4 |
>
> ### Verification status
> - **25/25** automated tests passing
> - Pipeline: **51 raster layers**, 4,765-cell grid, **no skipped layers**
> - Dashboard: **0 exceptions**, 5 tabs, 14 metrics
> - Colour palette **CVD-validated** — the intuitive green/red pairing measures
>   ΔE 4.1 under deuteranopia and was rejected
>
> *(Individual contribution: one line per member)*

**Say:** Phase 2 being complete ahead of Review 3 is worth one sentence, not a
paragraph. Do not oversell — they will ask what remains.

---

# SLIDE 22 — Limitations and next steps

**On slide**

> ### What this is not
> - **Screening, not census.** VIIRS at ~460 m cannot resolve one empty block.
>   The unit of a reliable finding is a neighbourhood.
> - **No ground truth yet.** At 0.35 km², some zones are four 50 m cells — small
>   enough that a single mapping error could produce one.
> - **OSM coverage is uneven**, and all 15 zones are peripheral.
> - **GHS-BUILT-S is modelled, not measured**; it under-detects low-rise
>   informal development.
> - Zones 14 and 15 (scores 0.56, 0.50) are the **boundary of the method's
>   discrimination**, not findings of equal standing.
>
> ### Phase 3
> 1. **Ground validation** of the 15 zones — the single highest-value step
> 2. Ward-level reporting (Census 2011, 90 wards) — planners act on wards
> 3. Building height from Open Buildings Temporal — vertical vs horizontal growth
> 4. Master-plan overlay — development where none was planned, and vice versa
> 5. Random-forest baseline, following Shojaei et al. 2022

**Say:** Close on limitations, then Phase 3. Ending on what you know you cannot
yet claim is the strongest possible finish for a mid-project review.

---
---

# BACKUP SLIDES — do not present, hold for questions

---

# SLIDE 23 — Q: "Your ghost number moved 20×. Why trust the new one?"

> Because the **structure did not change — only input completeness did.**
>
> - Classifier, thresholds and expected-activity curve: unchanged
> - Activity index went from 2 signals to 3
> - The third signal carries the **largest weight (0.45)**
>
> A screening tool missing its largest single weight does not produce a
> conservative estimate. It produces one wrong by an order of magnitude — and
> the earlier report said so **in advance**, not in hindsight.

---

# SLIDE 24 — Q: "Why do your figures stop at 2020?"

> GHS-BUILT-S R2023A ships epochs to 2030, but **only 1975–2020 are
> observational. 2025 and 2030 are the GHSL model's own projections.**
>
> We originally presented 2010–2025 figures without that qualification. It was
> caught during Phase 2 validation and corrected across every report.
>
> **Independent evidence it mattered:** we compared our own 2030 projection
> against GHSL's 2025 projection — same 2020 starting state, comparable demand.
> They agree at **FoM 0.0013**. Two models from identical starting conditions
> put growth in almost entirely different places.
>
> That is why modelled land-cover projections are not treated as data here.

---

# SLIDE 25 — Q: "Why not use deep learning / a U-Net?"

> We reviewed six U-Net implementations before deciding (slide 9).
>
> - Wang et al. 2022 report U-Net at **parity with CA models** for this task
> - Gains in Sirko et al. 2021 were **+0.12 / +0.06 mAP** — tuning-scale
> - U-Net buys **automation and transferability**, not a step change in accuracy
> - It costs labelled training data, GPU time and interpretability
>
> We have no GPU, no labelled set, and need coefficients a planner can read.
>
> **Phase 3 upgrade path is documented:** Gui et al. 2025, U-Net++ with
> attention coupled to autoregressive CA.

---

# SLIDE 26 — Q: "Your accuracy is 98%. Isn't that suspiciously high?"

> It is meaningless, and we say so on slide 13.
>
> - A null model predicting **no change at all** scores **98.91%**
> - Ours scores 98.1% — *worse* than the null model on that metric
> - Land change is a rare event; persistence dominates every cell count
>
> **The metric that works is Figure of Merit**, benchmarked against random
> allocation: 0.0679 vs 0.0055 = **12.3× skill**.

---

# SLIDE 27 — Q: "How do you know the 15 zones are real?"

> We do not, yet — and that is stated in the report.
>
> **What supports them:**
> - Every zone is peripheral, matching the independent 48.8% leapfrog finding
> - Each is 57–100% post-2010 development
> - Residuals of −0.13 to −0.51 against the city's own learned norm
> - Three independent signals must agree
>
> **What does not:**
> - No ground truth
> - OSM undercounts the periphery — where all the zones are
> - Zones 14 and 15 sit at the discrimination boundary (scores 0.56, 0.50)
>
> Ground validation is the first Phase 3 task.

---

# SLIDE 28 — Q: "What is genuinely novel here?"

> Not the data — all of it is public. Not the sensors. The **combination**:
>
> 1. **Learned expected-activity, not a fixed threshold.** The norm is derived
>    from the city's own built-up/activity relationship, so it transfers to any
>    city without re-tuning.
> 2. **`emerging` as a first-class outcome.** Existing ghost-city work flags
>    "low activity". We separate *stalled* from *filling up* — and that
>    distinction turned out to account for 95% of the flagged area.
> 3. **Urban form as corroboration.** Leapfrog share and ghost location are
>    derived independently and agree.
> 4. **Runs with no credentials.** The open path produces the core result
>    before any account exists.

---

## Figures to have on hand but not on slides

| Quantity | Value |
|---|---|
| AOI | 1,206 km², 82.80–83.15 °E, 25.15–25.45 °N |
| Analysis grid | 100 m, 359 × 339 |
| Reporting grid | 500 m, 4,765 cells with signal |
| OSM features | 1,999 POIs · 38,455 road ways |
| POI breakdown | retail 581 · food 583 · health/education 510 · finance 178 · industrial 95 · transport 52 |
| Typology totals | undeveloped 1,101.09 · established 140.69 · healthy 4.54 · emerging 6.88 · declining 5.70 · ghost 0.35 km² |
| Nightlight epochs | 2013–2024, 12 annual composites |
| VNL version join | V2.1 (2013–2021) → V2.2 (2022–), step +5.7% at the join |

---

## Presentation checklist

- [ ] Names, register numbers, guide name filled on slide 1
- [ ] Individual contribution line added to slide 21
- [ ] Dashboard running locally as a live fallback (`run_dashboard.bat`)
- [ ] Screenshots of the dashboard embedded, in case the live demo fails
- [ ] Ghost-zone map exported as an image for slide 16
- [ ] Someone nominated to answer each backup slide
- [ ] **Review 2 panel comments recorded verbatim** — Review 3 allocates 1 mark
      to action taken on them, and it cannot be earned without the record

---

*Prepared with AI assistance (Claude), in line with §2 of the BCSE497J
guidelines. All figures are from an actual pipeline run
(`outputs/varanasi_summary.json`); citation metadata verified against Crossref
or publisher records.*
