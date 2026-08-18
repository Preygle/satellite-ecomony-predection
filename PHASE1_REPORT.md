# Phase 1 Report — Varanasi

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
Generated 2026-07-28 · all figures below are from an actual pipeline run, not
projections.

---

> Abbreviations and official dataset identifiers used throughout this report
> are listed in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

## 1. What Phase 1 delivers

| Project pillar | Phase 1 status |
|---|---|
| Detect new built-up areas | ✅ Complete — 4 epochs, 100 m, classified by urban form |
| Commercial growth zones | ✅ Complete — OSM POI (Point of Interest) density by sector, class-weighted road density |
| Rapid infrastructure development | ✅ Complete — growth-intensity surface + hotspot mask |
| Green cover loss | ✅ Complete — Sentinel-2 NDVI (Normalized Difference Vegetation Index), monsoon-aware, 2018→2024 |
| Urban heat island hotspots | ✅ Complete — Landsat LST (Land Surface Temperature), SUHI (Surface Urban Heat Island), vulnerability |
| Ghost / underutilised zones | ✅ Complete — 15 zones identified |
| Predictive expansion models | ⬜ Phase 2 |
| Investment corridors | ⬜ Phase 3 |
| Smart dashboard | ✅ Complete — 5 tabs, 12 map layers, verified running |

**Roughly 50% of the full system**, which is the Phase 1 target.

> **Update (Earth Engine now authenticated).** The green-cover and heat-island
> layers, previously listed as code-complete but unexecuted, have now been run
> against real data. The full VIIRS (Visible Infrared Imaging Radiometer Suite) annual series 2013–2024 is included, which
> changes the ghost-growth result substantially — see §2 and §3. Two data
> defects were found and fixed in the process; both are recorded in §4.

---

## 2. Results

### Study area

Varanasi, 1,206 km² AOI (82.80–83.15 °E, 25.15–25.45 °N), covering the
Municipal Corporation, Ring Road corridor, peri-urban belt, and the Babatpur
airport corridor. Analysis at 100 m (359 × 339), reporting at 500 m
(73 × 69 → 4,765 cells with signal).

### Urban expansion, 2010–2025

> **Correction (Phase 2).** GHS-BUILT-S R2023A supplies epochs to 2030, but
> only **1975–2020 are observational — 2025 and 2030 are the GHSL (Global Human Settlement Layer) model's own
> projections.** The 2025 row below is therefore a *projected* value, not a
> measurement, and was originally presented here without that qualification.
> The observational record for this project ends at 2020. Figures over
> 2010–2020 are unaffected.

| Year | Built-up surface | Urban extent (≥20% built) | Population |
|---|---|---|---|
| 2010 | 72.48 km² | 128.43 km² | 4.17 M |
| 2015 | 81.05 km² | 142.25 km² | 4.41 M |
| 2020 | 89.73 km² | 154.39 km² | 4.60 M |
| 2025 *(projected)* | 95.95 km² | 158.16 km² | 4.75 M |

- **Built-up surface grew 32.4%** (+23.47 km²) over 15 years.
- **Urban extent grew 23.1%**, a compound 1.40% per year.
- Population grew **13.9%** (+581,000).

Built-up area grew **2.3× faster than population**. The city is consuming land
per resident at an accelerating rate — the single most policy-relevant number
in this report.

### Form of new development

Of 13.45 km² of land that newly crossed the urban threshold:

| Form | Area | Share |
|---|---|---|
| Infill | 0.95 km² | **7.1%** |
| Edge expansion | 5.94 km² | 44.2% |
| **Leapfrog** | **6.56 km²** | **48.8%** |

Nearly half of Varanasi's new development is **detached from the existing
urban fabric**. Leapfrog growth is the most expensive form to service — water,
sewerage, and transit all cost more per household — and it is the form most
associated with under-occupancy. Infill, the cheapest form, accounts for
7.1%.

*(Note the two "new" figures measure different things: 23.47 km² is total
gain in built surface including densification within already-urban cells;
13.45 km² is land that newly crossed the 20% urban threshold. Both are
reported because they answer different questions.)*

### Ghost growth

**0.35 km² flagged, distributed across 15 zones.**

Activity index now rests on all three signals — nightlights 0.45, POI 0.35,
population 0.20.

| Zone | Zone area | Flagged | Score | Residual | New share | Location |
|---|---|---|---|---|---|---|
| 1 | 2.43 km² | 0.10 km² | 0.87 | −0.25 | 98% | 25.451, 83.097 |
| 2 | 1.32 km² | 0.05 km² | 0.98 | −0.38 | 90% | 25.452, 83.052 |
| 3 | 1.81 km² | 0.04 km² | 0.96 | −0.33 | 69% | 25.238, 82.796 |
| 4 | 1.20 km² | 0.02 km² | 1.00 | −0.51 | 100% | 25.235, 83.128 |
| 5 | 0.88 km² | 0.02 km² | 1.00 | −0.43 | 97% | 25.173, 83.150 |
| 6 | 0.79 km² | 0.02 km² | 1.00 | −0.34 | 97% | 25.172, 82.794 |
| 7 | 0.89 km² | 0.02 km² | 0.95 | −0.29 | 57% | 25.456, 82.809 |
| 8 | 0.63 km² | 0.01 km² | 1.00 | −0.35 | 98% | 25.454, 82.976 |
| 9 | 0.60 km² | 0.01 km² | 1.00 | −0.28 | 96% | 25.453, 83.070 |
| 10 | 0.60 km² | 0.01 km² | 1.00 | −0.43 | 97% | 25.420, 83.155 |
| 11 | 0.60 km² | 0.01 km² | 1.00 | −0.28 | 90% | 25.339, 82.796 |
| 12 | 0.63 km² | 0.01 km² | 1.00 | −0.25 | 57% | 25.441, 82.798 |
| 13 | 0.60 km² | 0.01 km² | 0.83 | −0.21 | 100% | 25.311, 83.153 |
| 14 | 0.69 km² | 0.01 km² | 0.56 | −0.14 | 58% | 25.342, 82.962 |
| 15 | 0.69 km² | 0.01 km² | 0.50 | −0.13 | 95% | 25.310, 83.097 |

"New share" is the proportion of each zone's current built-up that appeared
after 2010. "Residual" is how far activity falls below what comparably
developed land elsewhere in Varanasi achieves.

**All 15 zones remain peripheral**, which is internally consistent with 48.8%
leapfrog growth: detached development is exactly where built-but-inactive land
should concentrate.

Zones 14 and 15 sit at scores 0.56 and 0.50 with the shallowest residuals in
the set (−0.14, −0.13). They are the marginal cases and should be treated as
the boundary of the method's discrimination, not as findings of equal standing
with zones 4–6.

### Growth typology (500 m reporting grid)

| Class | Area | Change from the no-nightlight run |
|---|---|---|
| Undeveloped | 1,101.09 km² | — |
| Established active | 140.69 km² | −5.70 |
| Healthy growth | 4.54 km² | +0.01 |
| **Ghost growth** | **0.35 km²** | **−6.89** |
| Emerging | 6.88 km² | +6.88 |
| Declining | 5.70 km² | +5.70 |

### Commercial activity (OpenStreetMap)

1,999 POIs (Points of Interest) and 38,455 road ways: retail 581, food/hospitality 583,
health/education 510, finance/office 178, industrial 95, transport 52.

---

## 3. The upper bound resolved — and what it cost

The previous version of this report stated 7.24 km² and called it **an upper
bound**, on the grounds that without a nightlight time series, cells that are
dim *but brightening* could not be separated from cells that are dim and
staying dim. Everything low fell into `ghost_growth`.

With the 2013–2024 VIIRS series in place, that prediction is confirmed and the
split is almost exact:

```
old ghost_growth   7.24 km²
new ghost_growth   0.35 km²   genuinely dim and not rising
new emerging       6.88 km²   dim but brightening — filling up
                   -------
                   7.23 km²
```

**95% of what was flagged as ghost growth is a neighbourhood mid-occupation,
not a failed one.** The single most important number in the earlier report was
wrong by a factor of twenty, in the direction the report predicted.

A second class appeared that could not exist before: **5.70 km² of `declining`**
— established land whose activity is both below expectation and falling. It
came entirely out of `established_active` (146.39 → 140.69 km², an exact
match). This is a different and arguably more actionable finding than ghost
growth: it is not stalled new development, it is existing urban fabric losing
activity.

The honest reading of this sequence: the method's *structure* was right — the
report said the figure was an upper bound and said why — but the headline
number was unusable until the third signal arrived. A screening tool missing
its largest single weight does not produce a conservative estimate; it produces
one that is wrong by an order of magnitude.

### Sum of lights, 2013–2024

| Year | Sum of lights | Year | Sum of lights |
|---|---|---|---|
| 2013 | 518,008 | 2019 | 651,218 |
| 2014 | 493,110 | 2020 | 656,448 |
| 2015 | 488,194 | 2021 | 669,991 |
| 2016 | 546,727 | 2022 | 707,999 |
| 2017 | 644,241 | 2023 | 786,284 |
| 2018 | 658,338 | 2024 | 905,354 |

Total lit output rose **74.8%** over twelve years, against 23.8% built-up
growth over 2010–2020. Lit fraction of the AOI (Area of Interest) in 2024 is 95.5%.

Note the 2013–2015 *decline* before the rise, and the acceleration after 2022
(+11.1% then +15.1% year on year). The series crosses a product-version
boundary at 2021/2022 (VNL V2.1 → V2.2, see §4), but the join step of +5.7%
sits between its neighbours and is not the source of the late acceleration —
the largest jumps are both inside V2.2.

### Green cover and heat, now measured

| Metric | Value |
|---|---|
| Green cover 2018 → 2024 | 71.0% → 77.9% |
| Green lost | 6.37 km² |
| **Green lost specifically to built-up conversion** | **0.05 km² (0.8% of loss)** |
| Rural reference temperature (pre-monsoon 2024) | 41.12 °C |
| Mean urban heat-island intensity | 1.10 °C |
| Maximum intensity | 9.27 °C |
| Hotspot area (≥3 °C above rural) | 26.57 km² |

**Do not report the +6.9 percentage-point green gain as a finding.** The Oct–Mar
window is the *rabi* cropping season, so NDVI across a largely agricultural AOI
tracks the wheat and pulse crop far more than it tracks urban tree canopy; a
wetter year reads as a greener one. The figure that is robust to this is
`lost_to_builtup` — 0.05 km² — because intersecting NDVI loss with built-up
*gain* removes anything that is merely a cropping-calendar difference. That is
the number to present.

---

## 4. Bugs found and fixed during the build

Recorded because they are the kind of error that silently corrupts every
downstream number, and all four were caught by tests or by disbelieving an
implausible result.

1. **Frame misalignment.** The 100 m and 500 m frames were built by two
   independent calls, each snapping outward to its own resolution — so they
   did not tile each other and zonal aggregation crashed on a shape mismatch.
   Had the dimensions happened to agree, it would have silently misaligned
   every aggregate instead. Fixed with `AOI.frame_pair`.

2. **Resolution-dependent threshold.** `min_builtup_m2: 5000` was documented
   as "2% of a 500 m cell" but applied on the 100 m frame, where it means
   **50%**. The activity index was defined for only 1,418 of 15,816 urban
   cells. Now expressed as a fraction of cell area.

3. **Unreachable newness threshold.** `min_new_builtup_fraction: 0.15` sits at
   the 99th percentile of observed GHSL change. Replaced with a *relative*
   definition — what share of a cell's current built-up is post-baseline —
   which is both semantically better and scale-robust.

4. **Majority aggregation erased the findings.** Ghost cells are a minority by
   nature, so a 500 m majority vote wiped every one of them out of the
   reporting grid. Replaced with a `priority` reducer that surfaces the most
   significant class present. Regression test added.

A fifth, in `nightlights.trend`: a perfect linear fit gives zero residual, and
the code mapped that to t = 0 (p = 1), discarding exactly the cleanest trends.
Fixed to treat it as maximally significant.

Two further defects surfaced the moment Earth Engine was authenticated. Both
are data-provenance errors rather than logic errors, and neither would have
raised an exception — they are the kind that produce a plausible wrong number.

6. **Nine of twelve nightlight years silently missing.** The config pointed the
   whole 2013–2024 series at `NOAA/VIIRS/DNB/ANNUAL_V22`. That collection only
   holds **2022–2025**; the Earth Engine catalogue keeps 2013–2021 in a
   separate asset, `ANNUAL_V21`. Every year before 2022 resolved to an *empty*
   collection. The nightlight trend — the entire basis for separating
   `ghost_growth` from `emerging` — would have been fitted on three consecutive
   years instead of twelve. Fixed with `gee.viirs_annual_asset()`, which picks
   the collection by year with the cutover in config, plus an explicit error
   when a year yields zero images (an empty EE collection otherwise fails later
   with `Image.bandNames: Parameter 'image' is required and may not be null`,
   which points at the wrong thing entirely). All 12 years now resolve.

   *Residual caveat:* V2.1 and V2.2 are different product versions sharing the
   same core compositing algorithm. Joining them is a version step, not a
   sensor change — far smaller than the DMSP↔VIIRS discontinuity — but it is
   real, and any trend crossing 2021/2022 inherits it.

7. **The vegetation baseline was one day of imagery.** `vegetation_start` was
   2015, but the Sentinel-2 **L2A** archive over Varanasi is nearly empty that
   early: the Oct 2015 – Mar 2016 window contains **3 scenes, all from
   2015-12-28**, against 148 scenes on 35 distinct days for 2024. A "seasonal
   median" over one date is a single observation with that day's phenology,
   haze and view geometry baked in. Differencing it against a full-season
   composite measured the difference in *sampling*, and produced an apparent
   green-cover rise from **27.9% to 77.9%** — a headline finding that was
   entirely an artefact.

   Fixed by moving the baseline to 2018, the first year with more than 30
   acquisition days, and by adding `gee.require_composite_depth()`, which
   refuses any composite built from fewer than `min_composite_dates` (20)
   distinct dates. The corrected comparison uses 25 dates against 29. This
   guard is the general fix: the class of error cannot recur silently for any
   index, year or city.

Defects 6 and 7 share a shape worth naming for the panel: **both were invisible
without ground knowledge of the archive.** Neither threw an exception, both
produced numbers of the right order of magnitude, and the vegetation one would
have been reported as a striking positive result. They were caught by checking
provenance against expectation — asking whether a 50-point rise in green cover
in six years was physically plausible — not by any test.

---

## 5. Verification

- **25/25 unit tests pass** (`python tests/test_core.py`), covering frame
  nesting, area conservation under aggregation, the priority reducer, urban
  form classification, trend recovery, the ghost screen on synthetic data with
  a known answer, and the land-change metric accounting.
- **Pipeline runs end-to-end with no skipped layers**, producing 51 raster
  layers, a 4,765-cell reporting grid, and a summary JSON with full provenance.
  The `skipped` block is now empty.
- **Dashboard verified running** via Streamlit's headless `AppTest`: 0
  exceptions, 7 metrics, 5 tabs.
- **Colour palette validated** with a CVD checker, not chosen by eye — the
  intuitive green-healthy/red-ghost pairing measures ΔE 4.1 under
  deuteranopia and was rejected.

---

## 6. What Phase 2 and Phase 3 should cover

### Phase 2 (~80%)

1. **Run the Earth Engine layers.** Highest-value single action: it completes
   green cover loss and urban heat island, and tightens the ghost-growth
   figure. Everything is already written.
2. **Predictive expansion model.** Implement the PLUS model (Liang et al.
   2021, `CEUS` 85:101569) driven by the layers already produced — distance
   to centre, road density, existing built-up, slope. Validate by training on
   2010→2015 and testing against observed 2015→2020. (Originally written as
   "testing against observed 2025"; corrected in Phase 2 — 2025 is projected.)
3. **Add building height.** Google Open Buildings Temporal (4 m, annual,
   2016–2023, covers India) supplies the vertical dimension. A cell whose
   height rises while area is flat is densifying, not expanding — and a tall
   new building with no lights is a far stronger ghost signal than area alone.
4. **Ward-level reporting.** Municipal planners act on wards, not a 500 m
   grid. Census 2011 Varanasi Nagar Nigam boundaries (90 wards).

### Phase 3 (100%)

5. **Investment corridors.** Combine predicted expansion with road-network
   accessibility and commercial-activity gradients.
6. **Master plan comparison.** The sharpest available framing: overlay the
   Varanasi Development Authority master plan to derive *development that
   happened where none was planned* and *planned development that never
   materialised*. Requires digitising the plan.
7. **Ground validation.** Spot-check the 9 ghost zones against high-resolution
   imagery or a site visit. Without this the output remains a screening tool,
   which is exactly how it is currently described.
8. **Deployment** and multi-city comparison (the config is already
   city-agnostic).

---

## 7. Honest limitations

- **Screening, not census.** VIIRS at ~460 m cannot resolve one empty housing
  block. The unit of a reliable finding is a neighbourhood.
- **OSM coverage is uneven.** Varanasi's core is well mapped; the periphery is
  not. Since all 15 ghost zones are peripheral, some of their low POI count may
  reflect mapping effort rather than absence of activity. This is why the index
  requires agreement across signals, and why the nightlight weight (0.45)
  exceeding the POI weight (0.35) matters.
- **GHS-BUILT-S is modelled, not measured**, and is documented to under-detect
  low-rise informal development.
- **No ground truth yet.** Nothing here has been validated against
  observation. With the flagged area now at 0.35 km² across 15 zones, ground
  validation is both more tractable and more necessary — a 0.01 km² zone is
  four 50 m cells, small enough that a single mapping error could produce it.
- **The green-cover series is dominated by the rabi crop**, not by urban
  canopy. Only `lost_to_builtup` (0.05 km²) is robust to the cropping
  calendar. See §3.
- **The nightlight series crosses a product-version boundary** at 2021/2022
  (VNL V2.1 → V2.2). Trends spanning it inherit a version step.
- **The literature predicts the residual error of nighttime-light products
  concentrates at the urban fringe** (`docs/LITERATURE_NTL_AND_UNET.md` §3.4),
  and every zone here is peripheral. Using observed VIIRS rather than a
  simulated long series avoids the worst of this, but does not eliminate it.
