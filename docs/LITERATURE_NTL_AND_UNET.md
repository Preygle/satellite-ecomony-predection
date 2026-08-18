# Literature Set — VIIRS Nighttime-Light Implementations and U-Net Architectures

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
Prepared in response to the mentor's remarks on *Chen et al. (2024), "A global
annual simulated VIIRS nighttime light dataset from 1992 to 2023"*, Scientific
Data 11:1380.

> **Abbreviations.** VIIRS is the Visible Infrared Imaging Radiometer Suite,
> the current nighttime-light sensor. DMSP-OLS is the Defense Meteorological
> Satellite Program — Operational Linescan System, the older one. NTL means
> nighttime light. Every abbreviation used in this project is listed in
> [`CONVENTIONS.md`](CONVENTIONS.md).

Two sets are required:

- **Set A** — at least five VIIRS papers that share a *similar model
  implementation* and produce *comparable outputs*, from which a single common
  trend is drawn.
- **Set B** — five papers that use **U-Net or a closely related architecture**
  in a concrete implementation.

Both sets exclude conceptual, review and survey papers. Every entry below
implements a model, releases or reports a product, and reports quantitative
validation. Citation metadata was verified against Crossref or the publisher
record; the verification status of every number is stated in §6.

---

## 1. The anchor paper, in one page

Read from the PDF in the project root, not from the abstract.

| Aspect | Chen et al. 2024 |
|---|---|
| Problem | DMSP-OLS (1992–2013) and NPP-VIIRS (2012–) are incompatible; no global VIIRS-like series exists before 2000 |
| Model | **NTLSRU-Net** — U-Net CNN (Convolutional Neural Network) reframed as an image super-resolution network |
| Direction | **DMSP → VIIRS** (upgrade: 1 km, 6-bit, saturated → 500 m, wide dynamic range) |
| Inputs | Calibrated DMSP NTL **+ Landsat NDVI (Normalized Difference Vegetation Index)** (two channels) |
| Architecture | 23 conv layers + 4 transposed-conv layers, 3×3 kernels, stride 1, receptive field 37 px. **All pooling layers removed**; batch-norm removed on the expansive path; skip-connection features compressed by 1×1 conv before fusion; zero padding to preserve size |
| Training | 12,049 image-patch triples (DMSP/NDVI/VIIRS) from the 2012–2013 overlap; 80/13/7 train/test/val; MSE loss; Adam |
| Inference | 2°×2° tiles (480 px), 0.3° overlap, central 380×380 retained, mosaicked |
| Output | **SVNL**, global annual 500 m simulated VIIRS, 1992–2023 |
| Validation | R² / RMSE (Root Mean Square Error) / MAE at pixel, city, province and national scale; profile analysis; GDP regression |
| Code | https://github.com/cxxtribal/NTLSRU-Net (Python 3.7 + ArcGIS 10.2) |

Its headline numbers, which anchor every comparison below:

| Scale | R² 2012 | R² 2013 |
|---|---|---|
| Pixel | 0.617 | 0.564 |
| City | 0.747 | 0.647 |
| Province | 0.874 | 0.841 |
| National | 0.964 | 0.943 |

Global SVNL-vs-GDP R² = 0.88 (1992–2023). India is among the three countries
with national R² > 0.8.

**Note this before anything else:** the paper's own comparison shows its
accuracy is "closely to that of ChenVNL" — a completely different architecture.
That observation is the seed of the common trend in §3.

---

## 2. Set A — five VIIRS implementations with comparable outputs

### 2.1 Selection criterion

To be *comparable* rather than merely *related*, a paper had to satisfy all
four:

1. Perform **DMSP↔VIIRS cross-sensor calibration** (the same modelling task as
   the anchor).
2. Release a **continuous multi-decadal annual NTL product**, not a one-off map.
3. Validate by **regressing simulated against real NTL** and report R².
4. Be an implementation, not a review.

Papers that use NTL for an application (poverty, CO₂, electricity) were
excluded — they consume these products rather than produce them, so their
outputs are not comparable.

### 2.2 The five

| # | Study | Model family | Direction | Product | Extent · period |
|---|---|---|---|---|---|
| A1 | Zheng, Weng & Wang (2019) | Regression-based cross-sensor calibration | VIIRS → DMSP-like | Consistent NTL series | China · 1996–2017 |
| A2 | Li, Zhou, Zhao & Zhao (2020) | **Sigmoid** inter-calibration | VIIRS → DMSP-like | Harmonized global NTL | Global · 1992–2018 |
| A3 | Zhao et al. (2020) | **Sigmoid** model | VIIRS → DMSP-like | Consistent NTL series | SE Asia · 1992–2018 |
| A4 | Chen Z. et al. (2021) | **Auto-encoder CNN + vegetation index** | **DMSP → VIIRS** | ChenVNL (NPP-VIIRS-like) | Global · 2000–2018 |
| A5 | Nechaev et al. (2021) | **Residual U-Net CNN** | VIIRS → DMSP-like | DMSP-like composites | Global · overlap-trained |
| A6 *(extension)* | Zhang L. et al. (2024) | **NTL convolutional LSTM** | Temporal reconstruction | PANDA-China | China · 1984–2020 |

A6 is listed as an extension rather than a sixth core entry because it solves
the *temporal* reconstruction problem rather than the cross-sensor one; it is
included because it is the strongest published counter-example to the trend in
§3 and should be raised if the panel pushes back.

### 2.3 Study cards

**A1 — Zheng, Q., Weng, Q. & Wang, K. (2019).** *Developing a new cross-sensor
calibration model for DMSP-OLS and Suomi-NPP VIIRS night-light imageries.*
ISPRS J. Photogramm. Remote Sens. **153**, 36–47. DOI 10.1016/j.isprsjprs.2019.04.019

Builds a calibration model relating radiance-calibrated DMSP to VIIRS and
generates a consistent series for China, 1996–2017. Reports that the temporal
consistency of the calibrated series "significantly improved" over the raw
inputs. Represents the pre-deep-learning statistical school and is the paper
Chen et al. cite as the geographically-weighted-regression precedent.

**A2 — Li, X., Zhou, Y., Zhao, M. & Zhao, X. (2020).** *A harmonized global
nighttime light dataset 1992–2018.* Scientific Data **7**, 168.
DOI 10.1038/s41597-020-0510-y

The most widely used harmonised product. Inter-calibrates DMSP and converts
VIIRS to DMSP-like using a sigmoid function, giving a single global series.
Mirrored into the Earth Engine community catalogue, which is why it is the
default choice in applied work. **Its known weakness is directly relevant:**
Chen et al. 2024 (Fig. 9) show the LiDNL global total exhibits a visible jump
across the DMSP/VIIRS handover, while SVNL and ChenVNL do not.

**A3 — Zhao, M. et al. (2020).** *Building a Series of Consistent Night-Time
Light Data (1992–2018) in Southeast Asia by Integrating DMSP-OLS and
NPP-VIIRS.* IEEE Trans. Geosci. Remote Sens. **58**(3), 1843–1856.
DOI 10.1109/TGRS.2019.2949797

Same sigmoid family as A2, applied regionally. Its companion application paper
(Zhao et al., *Remote Sens. Environ.* 248:111980, 2020) maps urban dynamics
1992–2018 from the product — a useful template for how a harmonised series is
then used for expansion analysis.

**A4 — Chen, Z. et al. (2021).** *An extended time series (2000–2018) of global
NPP-VIIRS-like nighttime light data from a cross-sensor calibration.*
Earth Syst. Sci. Data **13**, 889–906. DOI 10.5194/essd-13-889-2021

The direct predecessor and the benchmark Chen et al. 2024 measure themselves
against. Auto-encoder neural network plus a **vegetation index** to break the
DMSP saturation ambiguity — the same auxiliary-data idea the anchor paper
reuses with Landsat NDVI. **Reports R² 0.87 at pixel level and 0.95 at city
level** against real 2012 VIIRS. Data: https://doi.org/10.7910/DVN/YGIVCD

**A5 — Nechaev, D., Zhizhin, M., Poyda, A., Ghosh, T., Hsu, F.-C. & Elvidge,
C. (2021).** *Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and
SNPP/VIIRS with Residual U-Net.* Remote Sensing **13**(24), 5026.
DOI 10.3390/rs13245026

The bridge between Set A and Set B, and the paper Chen et al. 2024 name as the
deep-learning precedent. Residual U-Net producing DMSP-like composites from
VIIRS; reports **R² > 0.87**. Authored by the EOG team that produces the VNL
product itself. Code, notebooks and weights:
https://github.com/megavaz/CNN-DMSP-generation

**A6 — Zhang, L., Ren, Z., Chen, B., Gong, P., Xu, B. & Fu, H. (2024).**
*A Prolonged Artificial Nighttime-light Dataset of China (1984–2020).*
Scientific Data **11**, 414. DOI 10.1038/s41597-024-03223-1

NTL convolutional-LSTM network producing PANDA-China at 1 km, 1984–2020.
**Pixel-level RMSE 0.73, R² 0.95, regression slope 0.99** — the highest
pixel-level agreement in this set, and the reason it is flagged as the
counter-example in §3.4.

### 2.4 Comparable outputs, side by side

| Study | Architecture | Aux. data | Pixel R² | City R² | Province R² | National R² | Product released |
|---|---|---|---|---|---|---|---|
| **Chen et al. 2024** (anchor) | U-Net super-res | Landsat NDVI | **0.617** | **0.747** | **0.874** | **0.964** | SVNL, global 500 m |
| A4 Chen Z. 2021 | Auto-encoder CNN | Vegetation index | **0.87** | **0.95** | — | — | ChenVNL, global |
| A5 Nechaev 2021 | Residual U-Net | none | **> 0.87** | — | — | — | DMSP-like, global |
| A6 Zhang 2024 | ConvLSTM | none | **0.95** | — | — | — | PANDA-China, 1 km |
| A1 Zheng 2019 | Statistical calibration | none | ⚠ not extracted | — | — | — | China series |
| A2 Li 2020 | Sigmoid | none | ⚠ not extracted | — | — | — | Harmonized global |
| A3 Zhao 2020 | Sigmoid | none | ⚠ not extracted | — | — | — | SE Asia series |

⚠ = the paper reports validation, but the specific coefficient was not
extracted from the full text in this pass. See §6 before quoting.

The pixel R² values are **not** directly comparable across rows, and this is
the single most important thing to understand before presenting the table:

- Anchor and A4 solve **DMSP → VIIRS** (super-resolution — under-determined,
  hard). Anchor pixel R² 0.617.
- A5 solves **VIIRS → DMSP** (downgrading — well-posed, easy). R² > 0.87.
- A6 solves **temporal** reconstruction within one sensor family. R² 0.95.

Reading 0.617 as "worse than 0.95" without that distinction is the mistake the
panel is most likely to make, and the mistake worth pre-empting in the slide.

---

## 3. Set A — the central common trend

Four findings, ordered by how well the evidence supports them. The first is the
one to present.

### 3.1 Accuracy is a function of spatial scale, not of model family

Every implementation in Set A validates the same way — regress simulated
against real NTL — and every one that reports more than one aggregation level
shows R² rising monotonically with scale:

```
Chen 2024   pixel 0.617 -> city 0.747 -> province 0.874 -> national 0.964
Chen 2021   pixel 0.87  -> city 0.95
```

Meanwhile the *architectures* span sigmoid functions, geographically weighted
regression, auto-encoders, U-Nets and ConvLSTMs — and within a fixed transform
direction they land in the same band. Chen et al. 2024 state it about their own
work: their multi-scale R² is "closely to that of ChenVNL", and their GDP
correlation is "close and similar" to ChenVNL's at both global and national
level, despite a completely different network.

**The trend, in one sentence:** *cross-sensor nighttime-light calibration is
effectively solved at city scale and above, and unsolved at pixel scale, and
changing the model family moves the result far less than changing the scale at
which the claim is made.*

### 3.2 The direction of the transform is what makes the problem hard

Three of the five (A1, A2, A3) solve the *easy* direction: degrade VIIRS to
look like DMSP. That is a monotone scalar mapping plus a blur, so a sigmoid
suffices and no learning is needed. Only A4, A5 and the anchor attempt the
useful direction — reconstructing detail and dynamic range that the DMSP sensor
never recorded.

Deep learning entered this field for exactly one reason: the upgrade direction
is under-determined and cannot be solved by a per-pixel function. This explains
why the U-Net appears here and not in A1–A3, and it is the honest answer to
"why did they use a neural network?"

### 3.3 Auxiliary daytime data, not the architecture, is the enabling ingredient

A4 uses a vegetation index; the anchor uses Landsat NDVI. Both give the same
justification — vegetation information reduces DMSP saturation and blooming,
which is what makes recovery of sub-pixel structure possible at all. The two
implementations that attempt the hard direction *and* succeed both add a
daytime channel. The architectures differ (auto-encoder vs. U-Net); the
auxiliary input does not.

### 3.4 Residual error is spatially structured, and it concentrates at the urban fringe

This is the finding with the most direct consequence for our project.

Chen et al. 2024 document, from their own Figs. 7–8, that:

- **SVNL underestimates** NTL intensity in urban cores (London, New York, Los
  Angeles), and the underestimation "primarily occurs in urban fringe areas,
  where certain pixels exhibit high NTL intensity while surrounding pixels show
  relatively lower NTL intensity. In these areas, the CNN operations may result
  in the reduction of NTL intensity for central pixels by their neighboring
  pixels."
- **ChenVNL overestimates** urban cores and **underestimates peri-urban areas.**

Two different networks, two different bias signs — but both biased, both
systematically, and both worst at the fringe. The error is not noise that
averages out; it is a spatial pattern that a fringe-focused analysis will read
as signal.

**Counter-example to state honestly:** A6 (PANDA-China) reports pixel R² 0.95
with slope 0.99, which appears to contradict §3.1. It does not, because it
never crosses sensors — it reconstructs *within* the DMSP family over time. It
is evidence for the same underlying claim: the difficulty lives in the
cross-sensor upgrade, not in the network.

---

## 4. Set B — five implementations using U-Net or a closely related architecture

### 4.1 Selection criterion

Concrete implementation, U-Net or a direct descendant (residual U-Net, U-Net++,
encoder–decoder with skip connections, ConvLSTM), and — apart from the
foundational paper — applied to satellite imagery in an urban or nighttime-light
context so the set is defensible as *relevant*, not merely *architecturally
matching*.

### 4.2 The five

| # | Study | Architecture | Task | Study area |
|---|---|---|---|---|
| B1 | Ronneberger, Fischer & Brox (2015) | **U-Net** (original) | Semantic segmentation — labelling every pixel of an image with a class | — (foundational) |
| B2 | Nechaev et al. (2021) | **Residual U-Net** | NTL cross-sensor calibration | Global |
| B3 | Sirko et al. (2021) | **U-Net** + mixup, self-training | Building footprint segmentation | Africa (continental) |
| B4 | Shojaei et al. (2022) | **Modified U-Net** | Built-up land expansion simulation | Tehran & Karaj, Iran |
| B5 | Wang et al. (2022) | **U-Net** | Urban land-use pattern simulation | China (362 cities) |
| B6 *(state of the art)* | Gui, Bhardwaj & Sam (2025) | **U-Net++ + attention + autoregressive CA** | Urban expansion simulation | Changsha, China |

B2 is deliberately in both sets — it is the paper that connects the mentor's
two questions, and the one to open with.

### 4.3 Study cards

**B1 — Ronneberger, O., Fischer, P. & Brox, T. (2015).** *U-Net: Convolutional
Networks for Biomedical Image Segmentation.* MICCAI 2015, LNCS **9351**,
234–241. DOI 10.1007/978-3-319-24574-4_28

The architecture itself. Contracting path for context, expansive path for
localisation, skip connections carrying full-resolution features across.
Included because every other entry is a modification of it, and because the
anchor paper's design choices are all stated as *departures from the original*
— pooling removed, batch-norm removed on the expansive path, 1×1 compression
before fusion. You cannot explain the anchor without this reference.

**B2 — Nechaev, D. et al. (2021).** Remote Sensing **13**, 5026.
DOI 10.3390/rs13245026 — see A5.

Residual U-Net for cross-sensor NTL calibration, R² > 0.87, code and weights
public. Directly answers "has anyone else used a U-Net on VIIRS data?" — yes,
and the anchor paper cites it as its precedent.

**B3 — Sirko, W., Kashubin, S., Ritter, M., Annkah, A., Bouchareb, Y.S.E.,
Dauphin, Y., Keysers, D., Neumann, M., Cisse, M. & Quinn, J. (2021).**
*Continental-Scale Building Detection from High Resolution Satellite Imagery.*
arXiv:2107.12283 (Google Research).

Starts from a standard U-Net on 50 cm imagery and studies architecture, loss,
regularisation, pre-training, self-training and post-processing. Trained on
100k images with 1.75M manually labelled building instances. Reports **mixup
+0.12 mAP** and **self-training with soft-KL loss +0.06 mAP**. Produced the
**Open Buildings** dataset (516M footprints).

This one matters operationally: Open Buildings Temporal is already listed in
`docs/DATASETS.md` as the Phase 3 building-height source. B3 is the paper
behind a dataset we intend to consume.

**B4 — Shojaei, H., Nadi, S., Shafizadeh-Moghadam, H., Tayyebi, A. & Van
Genderen, J. (2022).** *An efficient built-up land expansion model using a
modified U-Net.* Int. J. Digital Earth **15**(1), 148–163.
DOI 10.1080/17538947.2021.2017035

The closest published analogue to our Phase 2 module. The network labels every
pixel as built-up or not — what the paper calls pixel-wise semantic
segmentation — driven by altitude, slope, and distance to barren land,
cropland, greenery, roads and urban areas, over 1998 / 2008 / 2018.
Baseline: **random forest**.

Our Phase 2 driver set (distance to centre, distance to urban edge, road
density, built-up fraction, population) is a near-subset of theirs, and our
epoch spacing (2010/2015/2020) mirrors their decadal structure. This is the
paper to cite when justifying the Phase 2 design, and the one to benchmark
against in Phase 3.

**B5 — Wang, J., Hadjikakou, M., Hewitt, R.J. & Bryan, B.A. (2022).**
*Simulating large-scale urban land-use patterns and dynamics using the U-Net
deep learning architecture.* Comput. Environ. Urban Syst. **97**, 101855.
DOI 10.1016/j.compenvurbsys.2022.101855

Trained on population-migration data across 362 Chinese cities, forecasting the
urban network to 2025. Reports three things that matter to us:

1. Transition rules were **learned automatically**, with minimal data
   requirements — no hand-specified neighbourhood rules.
2. The network recovered **neighbourhood, gravity and linear-development
   effects** without being told about them.
3. It achieved **similar accuracies to CA-based models** in a comparable
   urbanisation context.

Point 3 is the single most useful sentence in Set B for our purposes; see §5.

**B6 — Gui, B., Bhardwaj, A. & Sam, L. (2025).** *A novel multi-scale deep
learning framework for adaptive urban expansion simulation.* Sustainable Cities
and Society **130**, 106594. DOI 10.1016/j.scs.2025.106594

Current state of the art for the Phase 2 problem: U-Net++ with attention-driven
factor weighting, coupled to autoregressive CA, explicitly designed to remove
CA's "rigid neighbourhood definitions and static factor weighting". Changsha,
2010–2022. Reports **overall accuracy 0.87 and Figure of Merit 0.90**.

⚠ **Raise this carefully.** A Figure of Merit of 0.90 alongside an overall
accuracy of 0.87 is difficult to reconcile with the usual definitions: in land-
change accounting persistence dominates, so overall accuracy is normally far
*higher* than FoM, and published FoM for urban expansion typically falls in the
0.1–0.3 range (Pontius et al., *Ann. Reg. Sci.* 42:11–37, 2008). Either a
different normalisation is in use or the two numbers refer to different
quantities. **Verify against the full text before citing it as a target.** Do
not present our FoM of 0.0679 as "13× worse than the state of the art" on the
strength of an unverified figure.

---

## 5. Set B — the central common trend

### 5.1 U-Net replaces hand-specified spatial rules with learned spatial context

Every entry uses U-Net for the same underlying reason, and it is not accuracy:

| Study | The spatial rule that was *not* hand-specified |
|---|---|
| B1 | Localisation vs. context trade-off resolved by skip connections |
| B2 / anchor | Sub-pixel structure recovered from saturated, bloomed DMSP pixels |
| B3 | Building instance boundaries across an entire continent |
| B4 | Neighbourhood influence on built-up conversion |
| B5 | Neighbourhood, gravity and linear-development effects — learned, not encoded |
| B6 | Neighbourhood definition and driver weighting, both made adaptive |

The architecture is chosen because the task is **dense, co-registered,
pixel-to-pixel prediction** — output grid identical to input grid — which is
precisely what the encoder–decoder-with-skips design exists to do. Whenever a
paper in this domain needs a same-size output that depends on the *surroundings*
of each pixel, U-Net is the answer.

### 5.2 The gain over a well-tuned conventional baseline is consistently modest

This is the trend, and it is the more useful half:

- **B5 states it outright:** U-Net achieved *similar* accuracies to CA-based
  models.
- **The anchor states it outright:** its multi-scale accuracy is "closely to
  that of" an auto-encoder, and its GDP correlations are "close and similar".
- **B3's gains are incremental:** +0.12 and +0.06 mAP from mixup and
  self-training — real, but tuning-scale, and obtained on top of a U-Net that
  was already the baseline.
- **B4** beats a random forest, but random forest is a per-pixel model with no
  spatial context at all, so the comparison isolates exactly the contextual
  advantage rather than showing a general leap.

What U-Net actually buys is **automation, transferability and the removal of
subjective parameterisation** — B5's framing, "the high degree of subjectivity
involved in CA model parameterisation", is the honest statement of the benefit.
What it costs is labelled data, GPU time, and interpretability.

### 5.3 Combining §3.1 and §5.2 — the cross-cutting insight

Both sets converge on the same statement, from opposite directions:

> **The choice of architecture is a second-order decision. The first-order
> decisions are the direction of the transform, the auxiliary data supplied,
> and the spatial scale at which the claim is made.**

Set A shows it for calibration: five model families, one accuracy band, and
accuracy that rises with aggregation regardless of family. Set B shows it for
simulation: U-Net reaches parity with CA, and its real contribution is removing
subjective parameters rather than raising the score.

That is the single slide for the meeting.

---

## 6. What this decides for the Varanasi system

These are consequences, not observations — each changes something in the code
or in what we are allowed to claim.

| Finding | Consequence for this project | Status |
|---|---|---|
| §3.4 residual bias concentrates at the urban fringe | **Do not use simulated pre-2012 NTL for ghost-zone detection.** All nine of our ghost zones are peripheral — the exact location where SVNL and ChenVNL disagree with real VIIRS. Use observed VIIRS (VNL V2, 2012–) only. | Already the design: `config/varanasi.yaml` sources `NOAA/VIIRS/DNB/ANNUAL_V22` |
| §3.1 pixel-level NTL is the weakest unit | The reporting grid must stay coarser than the claim. We report at 500 m and state the unit of a reliable finding as a neighbourhood. | Already implemented (100 m analysis / 500 m reporting) |
| §3.3 auxiliary daytime data breaks NTL ambiguity | Our activity index already fuses NTL with POI (Point of Interest) density and population rather than trusting radiance alone. Same principle, different auxiliary source. | Already implemented (`analysis/ghost.py`) |
| §5.2 U-Net reaches parity with CA, at the cost of labels and GPU | **Justifies the Phase 2 choice of logistic suitability + constrained CA.** We have no GPU, no labelled training set, and we need interpretable coefficients for a planning audience. The literature says we give up little accuracy for that. | Decision now documented rather than assumed |
| B4 is the closest published analogue | Adopt its baseline discipline: it benchmarks against random forest, we benchmark against random allocation (12.3× skill). Add an RF baseline in Phase 3 for a like-for-like comparison. | **Phase 3 action** |
| B3 is the paper behind Open Buildings | Cite Sirko et al. when Open Buildings Temporal is introduced as the building-height source. | **Phase 3 action** |
| B6 is the upgrade path | If Phase 3 has GPU access, U-Net++ + attention CA is the documented next step from our current model. | **Phase 3 option** |

Two of these are new work items; the rest confirm decisions already taken, which
is itself the useful result — the literature was checked *against* the design,
not selected to flatter it.

---

## 7. Verification status

Honest accounting of what was checked and how, so nothing is quoted with more
confidence than it has earned.

**Verified against Crossref or the publisher record** (authors, journal, volume,
article number, year, DOI): every entry in Set A and Set B.

**Verified from the full text:** Chen et al. 2024 — all architecture details,
all R² values, both bias descriptions in §3.4, and the code URL were read from
the PDF in the project root.

**Verified from the publisher abstract or record:** Chen Z. 2021 (R² 0.87 pixel
/ 0.95 city); Nechaev 2021 (R² > 0.87, repository); Zhang 2024 (RMSE 0.73,
R² 0.95, slope 0.99); Sirko 2021 (mAP gains, dataset sizes); Shojaei 2022
(covariates, study area, RF baseline); Wang 2022 (four findings); Gui 2025
(architecture, study area, OA 0.87, FoM 0.90).

**Not yet extracted — do not quote a number for these:** Zheng 2019, Li 2020 and
Zhao 2020 validation coefficients. Their qualitative claims in §2.3 are from the
publisher record and from Chen et al. 2024's discussion of them, which is a
secondary source and is marked as such.

**Flagged as internally inconsistent pending full-text check:** Gui et al. 2025,
FoM 0.90 with OA 0.87 (§4.3).

One citation error was caught and corrected during this pass: a search result
attributed the Wang et al. U-Net paper to *Comput. Environ. Urban Syst.* 94
(2022) 101801. That article number belongs to **Kim, Y., Safikhani, A. & Tepe,
E. (2022), "Machine learning application to spatio-temporal modeling of urban
growth"** — a random-forest paper, not a U-Net one. The correct reference is
volume **97**, article **101855**. Verified via Crossref.

---

## 8. Full reference list

**Set A**

1. Chen, X., Wang, Z., Zhang, F., Shen, G. & Chen, Q. (2024). A global annual
   simulated VIIRS nighttime light dataset from 1992 to 2023. *Scientific Data*
   **11**, 1380. DOI 10.1038/s41597-024-04228-6
2. Zheng, Q., Weng, Q. & Wang, K. (2019). Developing a new cross-sensor
   calibration model for DMSP-OLS and Suomi-NPP VIIRS night-light imageries.
   *ISPRS J. Photogramm. Remote Sens.* **153**, 36–47.
   DOI 10.1016/j.isprsjprs.2019.04.019
3. Li, X., Zhou, Y., Zhao, M. & Zhao, X. (2020). A harmonized global nighttime
   light dataset 1992–2018. *Scientific Data* **7**, 168.
   DOI 10.1038/s41597-020-0510-y
4. Zhao, M. et al. (2020). Building a Series of Consistent Night-Time Light Data
   (1992–2018) in Southeast Asia by Integrating DMSP-OLS and NPP-VIIRS.
   *IEEE Trans. Geosci. Remote Sens.* **58**(3), 1843–1856.
   DOI 10.1109/TGRS.2019.2949797
5. Chen, Z. et al. (2021). An extended time series (2000–2018) of global
   NPP-VIIRS-like nighttime light data from a cross-sensor calibration.
   *Earth Syst. Sci. Data* **13**, 889–906. DOI 10.5194/essd-13-889-2021
6. Nechaev, D., Zhizhin, M., Poyda, A., Ghosh, T., Hsu, F.-C. & Elvidge, C.
   (2021). Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and
   SNPP/VIIRS with Residual U-Net. *Remote Sensing* **13**(24), 5026.
   DOI 10.3390/rs13245026
7. Zhang, L., Ren, Z., Chen, B., Gong, P., Xu, B. & Fu, H. (2024). A Prolonged
   Artificial Nighttime-light Dataset of China (1984–2020). *Scientific Data*
   **11**, 414. DOI 10.1038/s41597-024-03223-1

**Set B**

8. Ronneberger, O., Fischer, P. & Brox, T. (2015). U-Net: Convolutional Networks
   for Biomedical Image Segmentation. *MICCAI 2015*, LNCS **9351**, 234–241.
   DOI 10.1007/978-3-319-24574-4_28
9. Sirko, W. et al. (2021). Continental-Scale Building Detection from High
   Resolution Satellite Imagery. *arXiv:2107.12283*.
10. Shojaei, H., Nadi, S., Shafizadeh-Moghadam, H., Tayyebi, A. & Van Genderen,
    J. (2022). An efficient built-up land expansion model using a modified
    U-Net. *Int. J. Digital Earth* **15**(1), 148–163.
    DOI 10.1080/17538947.2021.2017035
11. Wang, J., Hadjikakou, M., Hewitt, R.J. & Bryan, B.A. (2022). Simulating
    large-scale urban land-use patterns and dynamics using the U-Net deep
    learning architecture. *Comput. Environ. Urban Syst.* **97**, 101855.
    DOI 10.1016/j.compenvurbsys.2022.101855
12. Gui, B., Bhardwaj, A. & Sam, L. (2025). A novel multi-scale deep learning
    framework for adaptive urban expansion simulation. *Sustainable Cities and
    Society* **130**, 106594. DOI 10.1016/j.scs.2025.106594

**Cited in support**

13. Pontius, R.G. et al. (2008). Comparing the input, output, and validation
    maps for several models of land change. *Ann. Reg. Sci.* **42**, 11–37.
    DOI 10.1007/s00168-007-0138-2
14. Kim, Y., Safikhani, A. & Tepe, E. (2022). Machine learning application to
    spatio-temporal modeling of urban growth. *Comput. Environ. Urban Syst.*
    **94**, 101801. *(cited only to document the corrected attribution in §7)*
15. Zhao, M. et al. (2020). Mapping urban dynamics (1992–2018) in Southeast Asia
    using consistent nighttime light data from DMSP and VIIRS. *Remote Sens.
    Environ.* **248**, 111980. DOI 10.1016/j.rse.2020.111980

---

*Prepared with AI assistance (Claude), in line with §2 of the BCSE497J
guidelines. All citation metadata independently verified against Crossref or
publisher records; verification status of every quantitative claim is recorded
in §7.*
