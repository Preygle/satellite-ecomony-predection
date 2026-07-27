# Phase 1 Report — Varanasi

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
Generated 2026-07-28 · all figures below are from an actual pipeline run, not
projections.

---

## 1. What Phase 1 delivers

| Project pillar | Phase 1 status |
|---|---|
| Detect new built-up areas | ✅ Complete — 4 epochs, 100 m, classified by urban form |
| Commercial growth zones | ✅ Complete — OSM POI density by sector, class-weighted road density |
| Rapid infrastructure development | ✅ Complete — growth-intensity surface + hotspot mask |
| Green cover loss | ⚙️ **Code complete, needs Earth Engine** — Sentinel-2 NDVI, monsoon-aware |
| Urban heat island hotspots | ⚙️ **Code complete, needs Earth Engine** — Landsat LST, SUHI, vulnerability |
| Ghost / underutilised zones | ✅ Complete — 9 zones identified |
| Predictive expansion models | ⬜ Phase 2 |
| Investment corridors | ⬜ Phase 3 |
| Smart dashboard | ✅ Complete — 5 tabs, 12 map layers, verified running |

**Roughly 50% of the full system**, which is the Phase 1 target.

The two ⚙️ items are fully implemented and tested — `analysis/vegetation.py`,
`analysis/thermal.py`, and their Earth Engine exporters all exist and are
wired into the pipeline. They activate the moment `earthengine authenticate`
is run. They are listed as incomplete rather than done because **they have not
yet been executed against real data**, and claiming otherwise would be false.

---

## 2. Results

### Study area

Varanasi, 1,206 km² AOI (82.80–83.15 °E, 25.15–25.45 °N), covering the
Municipal Corporation, Ring Road corridor, peri-urban belt, and the Babatpur
airport corridor. Analysis at 100 m (359 × 339), reporting at 500 m
(73 × 69 → 4,765 cells with signal).

### Urban expansion, 2010–2025

| Year | Built-up surface | Urban extent (≥20% built) | Population |
|---|---|---|---|
| 2010 | 72.48 km² | 128.43 km² | 4.17 M |
| 2015 | 81.05 km² | 142.25 km² | 4.41 M |
| 2020 | 89.73 km² | 154.39 km² | 4.60 M |
| 2025 | 95.95 km² | 158.16 km² | 4.75 M |

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

**7.24 km² flagged, concentrated into 9 zones.**

| Zone | Zone area | Flagged | Score | Residual | New share | Location |
|---|---|---|---|---|---|---|
| 1 | 0.97 km² | 0.22 km² | 0.94 | −0.34 | 93% | 25.300, 83.062 |
| 2 | 0.41 km² | 0.11 km² | 0.74 | −0.20 | 85% | 25.307, 83.039 |
| 3 | 0.33 km² | 0.10 km² | 1.00 | −0.54 | 92% | 25.433, 83.098 |
| 4 | 0.34 km² | 0.10 km² | 1.00 | −0.40 | 93% | 25.286, 83.027 |
| 5 | 0.43 km² | 0.10 km² | 0.92 | −0.33 | 95% | 25.397, 83.126 |
| 6 | 0.28 km² | 0.08 km² | 1.00 | −0.47 | 92% | 25.399, 83.026 |
| 7 | 0.33 km² | 0.07 km² | 1.00 | −0.52 | 83% | 25.427, 83.116 |
| 8 | 0.34 km² | 0.07 km² | 1.00 | −0.49 | 73% | 25.257, 83.096 |
| 9 | 0.26 km² | 0.05 km² | 0.90 | −0.33 | 96% | 25.282, 83.068 |

"New share" is the proportion of each zone's current built-up that appeared
after 2010 — every zone is 73–96% new. "Residual" is how far activity falls
below what comparably developed land elsewhere in Varanasi achieves.

**All nine zones are peripheral**, which is internally consistent with 48.8%
leapfrog growth: detached development is exactly where built-but-inactive land
should concentrate. That the two independent analyses agree is the strongest
evidence available at this stage that the signal is real.

### Growth typology (500 m reporting grid)

| Class | Area |
|---|---|
| Undeveloped | 1,101.09 km² |
| Established active | 146.39 km² |
| Healthy growth | 4.53 km² |
| **Ghost growth** | **7.24 km²** |
| Emerging | 0.00 km² — *requires nightlight trend* |
| Declining | 0.00 km² — *requires nightlight trend* |

### Commercial activity (OpenStreetMap)

1,999 POIs and 38,455 road ways: retail 581, food/hospitality 583,
health/education 510, finance/office 178, industrial 95, transport 52.

---

## 3. Important caveat on the ghost-growth figure

**7.24 km² is an upper bound.** Without a nightlight time series, cells that
are dim *but brightening* — neighbourhoods mid-occupation — cannot be
separated from cells that are dim and staying dim. Everything low falls into
`ghost_growth`, which is why `emerging` reads 0.00 km².

Running the Earth Engine export will split that 7.24 km² into genuine ghost
growth and normal fill-up, and the true figure will be **lower**. The pipeline
records this caveat in `outputs/varanasi_summary.json` and the dashboard
displays it.

The activity index currently rests on 2 of 3 signals (POI 0.64, population
0.36). Nightlights would add the third and the largest single weight.

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

---

## 5. Verification

- **20/20 unit tests pass** (`python tests/test_core.py`), covering frame
  nesting, area conservation under aggregation, the priority reducer, urban
  form classification, trend recovery, and the ghost screen on synthetic data
  with a known answer.
- **Pipeline runs end-to-end** producing 35 raster layers, a 4,765-cell
  reporting grid, and a summary JSON with full provenance.
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
   2010→2020 and testing against observed 2025.
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
  not. Since all 9 ghost zones are peripheral, some of their low POI count may
  reflect mapping effort rather than absence of activity. This is precisely
  why the index requires agreement across signals — and why adding nightlights
  matters.
- **GHS-BUILT-S is modelled, not measured**, and is documented to under-detect
  low-rise informal development.
- **No ground truth yet.** Nothing here has been validated against
  observation.
- **`emerging` and `declining` are structurally empty** in this run, not
  genuinely zero.
