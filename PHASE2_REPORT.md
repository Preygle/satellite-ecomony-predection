# Phase 2 Report — Predictive Expansion Model

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
**Varanasi, Uttar Pradesh** · Generated 2026-07-28

Aligned to **Review 3** (Panel, 16 September 2026, 20 marks). Every figure
below comes from an executed run; nothing is projected forward from intent.

> **Correction notice (Review 3, 11 September 2026).** The model scores below
> are superseded. The AUC of 0.9901 was measured on the training data; the
> allocation step dropped 6 of 1,214 cells; and only a +10-year projection
> existed. The current results — held-out AUC, a random-forest comparison, TOC
> curves and +5 / +10-year projections — are in
> [`docs/REVIEW3_REPORT.md`](docs/REVIEW3_REPORT.md) (§5.9 and the corrections
> log, §6).

---

## 1. Summary

Phase 2 adds the predictive layer: a model that learns from observed
conversions where Varanasi has grown, validates against a period it never
saw, and projects forward.

It also surfaced a **data-validity error affecting Phase 1**, which is
documented in §5 and corrected in the Phase 1 report.

| Deliverable | Status |
|---|---|
| Transition model (logistic suitability) | ✅ Implemented, fitted, AUC (Area Under the Curve) 0.990 |
| Constrained CA allocation | ✅ Implemented |
| Hold-out validation with land-change metrics | ✅ FoM 0.068, **12.3× better than random** |
| Random-allocation baseline | ✅ Implemented |
| 2030 projection | ✅ +31.21 km² urban extent |
| Investment-corridor surface | ✅ Suitability raster produced |
| Green cover / heat island | ⬜ Still requires Earth Engine authentication |
| Building height (vertical growth) | ⬜ Requires Earth Engine |
| Ward-level reporting | ⬜ Phase 3 |
| Ground validation of ghost zones | ⬜ Phase 3 |

---

## 2. Method

### 2.1 Three stages

**Suitability.** A logistic model learns from observed non-urban → urban
conversions how strongly each driver predicts development. Only cells that
were non-urban at the period start are used; already-urban cells cannot
convert, and including them would let the model learn "urban stays urban"
rather than what drives new growth.

**Allocation.** A constrained cellular automaton allocates demand to the
highest-scoring cells over eight iterations, with a 300 m neighbourhood term
re-weighting the score each pass. Suitability alone scatters growth across
every well-connected cell; the neighbourhood feedback is what produces
contiguous accretion. Allocating iteratively rather than all at once lets
earlier conversions influence later ones — the defining feedback of a CA.

**Validation.** Fitted on 2010→2015, tested against observed 2015→2020.

### 2.2 Drivers

| Driver | Rationale |
|---|---|
| Distance to city centre | Classical monocentric gradient |
| Neighbourhood built-up, 500 m | Immediate adjacency — existing service connections |
| Neighbourhood built-up, 1500 m | District-scale agglomeration |
| Distance to urban edge | Accretion tends to occur at the fringe |
| Road density (class-weighted) | Access precedes development |
| Population density | Demand pressure |
| Built-up fraction | Partially-developed cells are closest to converting |

---

## 3. Results

### 3.1 Fitted model

Trained on **2010→2015**: 113,082 eligible cells, 1,382 observed conversions
(1.22% conversion rate). **AUC = 0.9901.**

| Driver | Coefficient | Interpretation |
|---|---|---|
| Built-up fraction | **+2.2616** | Dominant. Partially-built cells convert. |
| Neighbourhood built 1500 m | +0.2940 | District agglomeration matters more than… |
| Neighbourhood built 500 m | +0.1701 | …immediate adjacency |
| Road density | +0.0487 | Access has a positive but modest effect |
| Population density | −0.0738 | New growth favours lower-density land |
| Distance to urban edge | **−0.1438** | Nearer the fringe → more likely |
| Distance to centre | **−0.1410** | Nearer the centre → more likely |

**All seven signs are theoretically correct.** That is a meaningful check, not
a formality — the first fitted version produced inverted signs on distance to
centre and neighbourhood density, which is what led to discovering the data
error in §5.

The dominance of `builtup_fraction` deserves a caveat: it is partly
mechanical, since a cell at 0.19 built fraction is by construction close to
crossing the 0.20 threshold. It is a legitimate predictor but not an
interesting one, and the genuinely informative signal lies in the remaining
six drivers.

### 3.2 Hold-out validation, 2015→2020

Demand was set to the observed conversion count (1,214 cells) so the test
isolates *allocation skill* from demand estimation — a model also guessing
the quantity would confound two different errors.

| Metric | Value |
|---|---|
| Hits | 154 |
| Misses | 1,060 |
| False alarms | 1,054 |
| Correct rejections | 109,432 |
| **Figure of Merit** | **0.0679** |
| Producer's accuracy | 0.1269 |
| User's accuracy | 0.1275 |
| Cohen's κ | 0.1176 |
| Overall accuracy | 0.9811 |
| **Null model accuracy** | **0.9891** |

### 3.3 Reading these numbers honestly

**Overall accuracy of 98.1% means nothing here, and is in fact worse than
doing nothing.** A null model predicting no change anywhere scores 98.91%,
because the overwhelming majority of the AOI (Area of Interest) simply does not convert. Any
report quoting overall accuracy for a land-change model is reporting the base
rate, not skill. This is why Figure of Merit and κ are the reported metrics.

**Figure of Merit 0.068 is modest.** Roughly one in fifteen predicted
conversions is correct. Against a random-allocation baseline over the same
eligible cells with the same demand:

| | Figure of Merit | Hits |
|---|---|---|
| Random allocation (20 draws) | 0.0055 | 13.3 |
| **This model** | **0.0679** | **154** |
| **Skill ratio** | **12.3×** | **11.6×** |

So the model carries real signal — an order of magnitude better than chance —
while remaining weak in absolute terms. Published land-change models
typically report FoM between 0.1 and 0.3 over comparable intervals, so this
sits below the usual range.

**Why it is weak, honestly:**

1. **Only three observational epochs exist**, giving exactly one training
   period and one test period. No cross-validation is possible.
2. **The strongest real-world drivers are absent** — zoning, master-plan
   designations, land prices, ownership, and approved layouts. These
   determine where development is *permitted*, which physical geography
   cannot infer.
3. **GHSL (Global Human Settlement Layer) is itself modelled**, so the model is partly learning GHSL's
   allocation behaviour rather than ground reality.
4. **100 m cells with small change quantities** make exact placement hard;
   the model may identify the right *neighbourhood* while missing the exact
   cell, which FoM penalises fully.

### 3.4 Projection to 2030

Demand extrapolated from the compound annual growth of urban extent over
2010–2020 and allocated by the fitted model:

| | |
|---|---|
| Projected new urban extent by 2030 | **+31.21 km²** (3,121 cells) |
| Basis | Compound annual growth, observational epochs only |

Given FoM 0.068, this projection should be read as **a suitability surface
indicating where pressure concentrates**, not as a cell-level forecast. Its
defensible use is prioritising corridors for infrastructure planning; its
indefensible use is any parcel-level decision.

Outputs: `data/processed/rasters/growth_suitability.tif` and
`predicted_new_urban_2030.tif`.

---

## 4. An unexpected finding

The model's projection was cross-checked against **GHSL's own 2025
projection** — both starting from the identical observed 2020 state, both
allocating a comparable quantity of new urban land.

**They agree at Figure of Merit 0.0013 — effectively not at all.**

Two independent models, given the same starting condition and the same
demand, place future growth in almost entirely different locations. This is
worth stating plainly for two reasons:

- It independently corroborates the decision to exclude GHSL's projected
  epochs from fitting and validation (§5). Those epochs encode a specific
  allocation logic that is not the observed historical pattern.
- It is a caution about projected land-cover products generally. A user who
  treats GHSL 2025 or 2030 as data rather than as one model's output — as
  this project initially did — inherits that model's assumptions invisibly.

---

## 5. Data-validity error found and corrected

**GHS-BUILT-S R2023A epochs 2025 and 2030 are projections, not observations.
The last observational epoch is 2020.**

Phase 1 used all four epochs as though equivalent. Consequences:

| Affected | Impact | Resolution |
|---|---|---|
| Phase 1 headline "2010–2025" figures | The 2025 column is GHSL's forecast presented as measurement | Marked *(projected)* in `PHASE1_REPORT.md`; observational figures now 2010–2020 |
| Original validation design | Trained 2010→2020, tested against 2025 — testing one model against another model's output | Refitted on observational epochs only |
| First fitted coefficients | Signs inverted on distance-to-centre and neighbourhood density | Corrected; all signs now theoretically consistent |

Corrected observational figures:

| Metric | 2010 | 2020 (observed) | Change |
|---|---|---|---|
| Built-up surface | 72.48 km² | 89.73 km² | +23.8% |
| Urban extent | 128.43 km² | 154.39 km² | +20.2% |
| Population | 4.17 M | 4.60 M | +10.3% |

The headline conclusion survives: built-up area grew **2.3× faster than
population** (23.8% vs 10.3%). The magnitudes are lower than originally
reported, and the reported period is now ten years rather than fifteen.

**How it was found.** Not by a test. The first validation run returned
FoM 0.0013 with inverted coefficient signs — a result too poor to be a tuning
problem. Investigating why led to checking the provenance of each epoch.

---

## 6. Second bug: metrics confined to the wrong population

`change_metrics` masked predicted and observed change by the eligible set but
counted correct rejections over the *entire* array. Every already-urban cell
the model correctly left alone was scored as a correct rejection, inflating
overall accuracy toward 1 regardless of skill.

Fixed so all four confusion quadrants are confined to eligible cells, with a
regression test asserting that the four quadrants sum exactly to the eligible
count.

This bug and the epoch error compounded: together they produced a model that
looked defensible on overall accuracy while having essentially zero skill.

---

## 7. Verification

- **25/25 tests pass**, including 5 new growth-model tests: confusion-quadrant
  masking, the Figure of Merit formula, allocation respecting demand and
  never re-converting urban land, demand extrapolation, and recovery of a
  planted driver on a synthetic city.
- Model run is reproducible: `python scripts/run_growth_model.py`
- Full record: `outputs/varanasi_growth_model.json`

---

## 8. Mapping to Review 3 rubric

| # | Criterion | Marks | Evidence |
|---|---|---|---|
| 1 | Follow-up on Review 2 feedback and progress against plan | 3 | *Requires your Review 2 panel comments — see below* |
| 2 | Implementation and functional progress (~50% of scope) | 3 | Phase 1 (5 analytical layers, dashboard) + Phase 2 predictive model. Exceeds 50%. |
| 3 | Technical accuracy and best practices | 3 | Held-out validation; land-change-appropriate metrics; random baseline; epoch-provenance discipline |
| 4 | Interim testing, results and analysis | 3 | §3 metrics with interpretation; §3.3 explains why accuracy is the wrong metric |
| 5 | **Problem-solving and technical refinement** | 2 | §5 and §6 — two substantive defects found, diagnosed and corrected, with the diagnostic path recorded |
| 6 | Progress of report and documentation | 3 | Updated Ch 1–3 (`docs/REVIEW2_REPORT.md`) + this document as initial Ch 4 |
| 7 | Presentation, responsibility, response to questions | 3 | *Presentation-dependent* |

**Criterion 5 is where this phase is strongest.** It asks for "identification
of technical challenges and evidence of corrective action" — §5 and §6
document exactly that, including the reasoning that led to each discovery.
A panel is markedly more persuaded by a corrected error explained clearly
than by results with no visible failure.

**Criterion 1 needs input only you have.** It allocates 1 mark to action taken
on Review 2 comments. Record the panel's comments verbatim on 19 August and
bring the action taken; without that record the mark is unobtainable.

---

## 9. Limitations

- **The model is weak in absolute terms** (FoM 0.068). Useful for corridor
  prioritisation; not for parcel-level decisions.
- **One training period, one test period.** Three observational epochs do not
  permit cross-validation.
- **Institutional drivers absent** — zoning, master plan, land prices,
  ownership. These likely dominate the physical drivers in reality.
- **GHSL is modelled**, so the model partly learns GHSL's behaviour.
- **No ground truth.** Neither the ghost zones nor the projection has been
  verified against observation.
- **Green cover and heat island remain unexecuted**, pending Earth Engine.

---

## 10. Phase 3

1. **Earth Engine authentication** — unlocks green cover, heat island, and
   the nightlight trend that refines the ghost figure. (Completed since: 7.24 → 0.35 km², with 6.88 km² reclassified as emerging.)
2. **Master plan digitisation** — the strongest available upgrade. Comparing
   planned against actual development yields both "development where none was
   planned" and "planned development that never materialised", and adds the
   institutional driver the model most lacks.
3. **Ground validation** of the nine ghost zones against high-resolution
   imagery.
4. **Ward-level reporting** on Census 2011 Nagar Nigam boundaries.
5. **Investment corridors** — combining the suitability surface with road
   accessibility and commercial-activity gradients.

---

## Appendix — Reproduction

```bash
run_pipeline.bat --no-gee                              # Phase 1 layers
.venv\Scripts\python.exe scripts\run_growth_model.py   # Phase 2 model
.venv\Scripts\python.exe tests\test_core.py            # 25 tests
```

Outputs: `outputs/varanasi_growth_model.json`,
`data/processed/rasters/growth_suitability.tif`,
`data/processed/rasters/predicted_new_urban_2030.tif`.
