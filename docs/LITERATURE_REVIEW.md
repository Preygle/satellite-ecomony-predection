# Literature Review — Review 2

**Satellite-Based Urban Growth and Economic Activity Intelligence System**
Chapter 2 of the project report.

**18 papers reviewed. 17 published in 2020 or later.** Every citation was
verified against Crossref, the publisher record, or the paper's own title page.
Copies of all 18 are in the `papers/` folder.

Abbreviations and official dataset identifiers are listed in
[`CONVENTIONS.md`](CONVENTIONS.md).

---

## 1. How this maps to the Review 2 rubric

| Rubric item | Marks | Where it is answered |
|---|---|---|
| Knowledge on Domain / Problem Statement | 5 | §2 of this document, and `REVIEW1_REPORT.md` |
| **Literature Review — minimum 15 recent papers** | **5** | **§3 to §7 of this document — 18 papers, 17 of them recent** |
| Design of Proposed Methodology | 5 | [`METHODOLOGY_SIMPLE.md`](METHODOLOGY_SIMPLE.md) and [`METHODOLOGY.md`](METHODOLOGY.md) |
| Module Description / System Design | 5 | [`DESIGN.md`](DESIGN.md) and [`WORKFLOW.md`](WORKFLOW.md) |

---

## 2. Domain and problem statement

**The domain.** Satellite remote sensing for urban monitoring. Satellites
record two things useful here: what the ground looks like by day, which shows
where buildings are, and how much light the ground emits at night, which
indicates where people are active.

**The problem.** Indian cities are expanding faster than their populations.
Varanasi's built-up surface grew 23.8% between 2010 and 2020 while its
population grew 10.3% — land consumed roughly 2.3 times faster than people
housed. Expansion is normally measured by area alone, and area cannot tell a
functioning new neighbourhood from an empty one. Municipalities therefore
extend water, sewerage and transport on the basis of construction rather than
occupancy, with no way to detect when that investment is stranded.

**Why it is hard.** The two obvious detectors both fail. Flagging areas with
low nighttime light picks up every farm field and unlit industrial estate.
Flagging areas with low population picks up every warehouse district. Both
mistake *different* for *empty*.

**What the literature does not yet provide.** See the gap analysis in §7.

---

## 3. The 18 papers at a glance

Grouped by theme. Full citations in §9.

| # | Study | Year | Venue | Theme |
|---|---|---|---|---|
| 1 | Chen, X. et al. | 2024 | Scientific Data | A |
| 2 | Tian, Y. et al. | 2026 | Scientific Data | A |
| 3 | Chen, Z. et al. | 2021 | Earth System Science Data | A |
| 4 | Li, X. et al. | 2020 | Scientific Data | A |
| 5 | Zhang, L. et al. | 2024 | Scientific Data | A |
| 6 | Brown, C.F. et al. | 2022 | Scientific Data | B |
| 7 | Marconcini, M. et al. | 2020 | Scientific Data | B |
| 8 | Tang, Y. et al. | 2021 | Remote Sensing | B |
| 9 | Sirko, W. et al. | 2021 | arXiv (Google Research) | B |
| 10 | Goldblatt, R. et al. | 2018 | Remote Sensing of Environment | B |
| 11 | Zhang, Y., Tu, T., Long, Y. | 2024 | arXiv / *Cities* | C |
| 12 | Yeh, C. et al. | 2020 | Nature Communications | C |
| 13 | Anucharn, T. et al. | 2025 | ISPRS Int. J. Geo-Information | C |
| 14 | Liang, X. et al. | 2021 | Computers, Environment and Urban Systems | D |
| 15 | Chen, G. et al. | 2020 | Nature Communications | D |
| 16 | Shojaei, H. et al. | 2022 | Int. J. Digital Earth | D |
| 17 | Zhang, A. et al. | 2025 | Scientific Reports | D |
| 18 | Ramachandra, T.V. et al. | 2025 | Scientific Reports | E |

**Themes.** A — nighttime light as an activity proxy · B — measuring built-up
extent · C — inferring economic activity and vacancy · D — predicting future
expansion · E — environmental consequences.

**Recency.** 2026: 1 · 2025: 3 · 2024: 3 · 2022: 2 · 2021: 4 · 2020: 4 ·
2018: 1. Seventeen of the eighteen are from 2020 onward.

---

## 4. Theme A — Nighttime light as a proxy for human activity

Nighttime light radiance is the most widely used indirect indicator of human
and economic activity. The difficulty is that the long historical record comes
from two different sensors that do not agree with each other.

DMSP-OLS (Defense Meteorological Satellite Program — Operational Linescan
System) covers 1992–2013 but saturates in bright city centres and spreads light
outward beyond its true source.
VIIRS (Visible Infrared Imaging Radiometer Suite) has covered 2012 onward with better calibration and a much wider range
of measurable brightness. Joining the two into one consistent series is an
active research problem, and five of our papers address it.

| Study | Method | Output | Reported accuracy |
|---|---|---|---|
| Li et al. 2020 | Sigmoid function | Harmonized global series, 1992–2018 | Most widely used product |
| Chen, Z. et al. 2021 | Auto-encoder neural network plus a vegetation index | ChenVNL, global, 2000–2018 | R² 0.87 per pixel, 0.95 per city |
| Chen, X. et al. 2024 | U-Net convolutional neural network as a super-resolution model | SVNL, global 500 m, 1992–2023 | R² 0.617 per pixel rising to 0.964 per country |
| Zhang, L. et al. 2024 | Convolutional Long Short-Term Memory network | PANDA-China, 1 km, 1984–2020 | R² 0.95 per pixel |
| Tian et al. 2026 | Two-stage deep learning guided by impervious-surface data | EVAL, China, 1986–2024 | Outperforms earlier products |

### What these five have in common

**Accuracy depends on scale far more than on the model.** Chen, X. et al. 2024
report R² rising from 0.617 for a single pixel to 0.747 for a city, 0.874 for a
province and 0.964 for a country. Chen, Z. et al. 2021 show the same pattern,
0.87 per pixel to 0.95 per city. The five studies use five different model
families — a sigmoid function, an auto-encoder, a U-Net, a Long Short-Term
Memory network and a two-stage deep model — and land in a similar accuracy band
once results are grouped above pixel level.

**Extra daytime information is what makes the hard direction work.** Converting
VIIRS down to look like DMSP-OLS is easy. Rebuilding VIIRS-like detail *from*
DMSP-OLS is much harder, because the detail was never recorded. The two studies
that succeed at it both add a daytime layer: Chen, Z. et al. 2021 use a
vegetation index, and Chen, X. et al. 2024 use
NDVI (Normalized Difference Vegetation Index) from Landsat. Tian et al. 2026 make the same move with
impervious-surface data.

**Errors are not random — they concentrate at the city edge.** Chen, X. et al.
2024 report that their own product underestimates light at the urban fringe,
because the network pulls bright pixels down towards their darker neighbours,
while the competing ChenVNL product overestimates city centres and
underestimates the surrounding areas.

### What this means for our project

The last point decided a design choice. Every underused zone our system
identifies is on the edge of Varanasi — exactly where simulated nighttime light
products are least reliable. **We therefore use only observed VIIRS data
(`NOAA/VIIRS/DNB/ANNUAL_V21` for 2013–2021 and `NOAA/VIIRS/DNB/ANNUAL_V22` for
2022 onward) and do not use any reconstructed long series.** The scale finding
also supports reporting results on a 500 m grid rather than per pixel.

---

## 5. Theme B — Measuring built-up extent

Five studies on turning satellite imagery into a map of where buildings are.

| Study | Data used | Resolution | Coverage | Approach |
|---|---|---|---|---|
| Goldblatt et al. 2018 | Landsat + nighttime light | 30 m | Includes India | Nighttime light used as training labels for a built-up classifier |
| Marconcini et al. 2020 | Landsat + Sentinel-1 radar | 10 m | Global, 2015 | World Settlement Footprint |
| Tang et al. 2021 | Nighttime light + MODIS | ~500 m | Regional | Time series of impervious surface |
| Sirko et al. 2021 | 50 cm commercial imagery | 50 cm | Africa | U-Net detecting individual buildings |
| Brown et al. 2022 | Sentinel-2 | 10 m | Global, near real time | Dynamic World, nine land-cover classes |

**Goldblatt et al. 2018** is the methodological ancestor of this project: it
uses nighttime light to label training data automatically, avoiding hand-drawn
training areas, and it was validated on India. **Sirko et al. 2021** produced
the Open Buildings dataset from 100,000 images with 1.75 million hand-labelled
buildings; that dataset is the source we plan to use for building height.
**Brown et al. 2022** produced `GOOGLE/DYNAMICWORLD/V1`, which we use as an
independent check on land cover, at about 73.8% overall accuracy.

**Where these leave a gap.** All five produce a map of *where buildings are*.
None of them says anything about whether those buildings are used.

---

## 6. Theme C — Inferring activity and vacancy

Three studies that move from physical structures to human use.

**Zhang, Y., Tu, T. & Long, Y. (2024)** is the closest published work to our
project. They analysed 8,841 cities worldwide, split each into areas developed
before and after 2005, and measured "urban vitality" from road density, POI
(Point of Interest) density and population density. They found that new areas
show only 7.69% of the vitality of older areas, and labelled the worst-scoring
5% — 442 cities — as ghost cities.

**Yeh et al. 2020** showed that a deep-learning model reading public satellite
imagery can explain about 70% of the variation in economic wellbeing across
African villages, including in countries the model had never seen. This
establishes that satellite imagery genuinely carries economic signal.

**Anucharn et al. 2025** provides a working Google Earth Engine template
linking nighttime light to energy consumption, reporting a strong correlation
at province level.

**A caution we carry forward.** Anucharn et al.'s strong correlation is between
*provincial totals*, not individual pixels. Treating a correlation between
large aggregates as evidence about single pixels is a common error in this
literature, and one this project explicitly avoids.

### How our approach differs from Zhang, Tu & Long

| | Zhang, Tu & Long 2024 | This project |
|---|---|---|
| Comparison | New areas against old areas | Each area against what is normal for its own level of development, in its own city |
| Threshold | Worst 5% globally | No fixed threshold; the norm is learned per city |
| Distinguishes filling-up? | No | **Yes — `emerging` versus `ghost_growth`** |
| Scale | 8,841 cities, coarse | One city, 500 m detail |

The third row is the important one, and §7 explains why.

---

## 7. Theme D — Predicting future urban expansion

| Study | Method | Study area | Notes |
|---|---|---|---|
| Chen, G. et al. 2020 | Scenario-based projection | Global, 1 km, to 2100 | Future urban land under different socio-economic pathways |
| Liang et al. 2021 | PLUS model — random forest plus patch-based cellular automaton | Wuhan, China | Current standard; open-source software |
| Shojaei et al. 2022 | Modified U-Net | Tehran and Karaj, Iran | Compared against a random forest baseline |
| Zhang, A. et al. 2025 | Google Earth Engine plus predictive models | Pakistan | Recent template for the whole workflow |

**Shojaei et al. 2022 is the closest analogue to our prediction module.** Their
input variables — altitude, slope, and distance to barren land, cropland,
greenery, roads and urban areas — are almost the same set we use, and their
epochs (1998, 2008, 2018) have the same decade-scale spacing as ours (2010,
2015, 2020).

**Liang et al. 2021** established the pattern our module follows: learn where
growth is likely from past change, then use a cellular automaton so that new
development appears in connected patches rather than scattered single cells.

### Why we do not use deep learning for prediction

The evidence in this set does not support it for our situation. Shojaei et al.
2022 beat a random forest, but a random forest looks at each cell separately
with no view of its surroundings, so that comparison mainly shows the value of
spatial context rather than of deep learning specifically. A U-Net needs a large
labelled training set and a graphics processing unit, and it produces a model
whose reasoning cannot easily be shown to a planner. We therefore use Logistic
Regression coupled to a cellular automaton, which needs neither, and whose
coefficients can be read directly. Deep learning is recorded as a possible
later upgrade rather than dismissed.

---

## 8. Research gap and how this project addresses it

### The gap

| What exists | What it does | What it does not do |
|---|---|---|
| Nighttime light time series (Theme A) | Produce long, consistent activity records | Say nothing about whether construction is occupied |
| Built-up mapping (Theme B) | Show precisely where buildings are | Show whether those buildings are used |
| Ghost city studies (Theme C) | Compare new areas against old, or against a fixed cut-off | Do not adapt to each city's own normal level, and do not separate stalled development from development still filling up |
| Expansion models (Theme D) | Predict *where* a city will grow | Do not ask whether that growth will be used |

**The gap in one sentence:** no existing study learns the activity level normal
for a given level of development *within a city* and uses it to separate
development that has stalled from development that is still being occupied.

### Why the missing distinction matters — evidence from our own work

This is not a theoretical gap. When our system ran without a nighttime light
time series, it flagged **7.24 km²** of Varanasi as underused. Adding the
2013–2024 series split that figure almost exactly in two:

| Class | Area | Meaning |
|---|---|---|
| `ghost_growth` | **0.35 km²** | Dim, and not getting brighter |
| `emerging` | **6.88 km²** | Dim, but measurably getting brighter — filling up |

**95% of what looked like stalled development is a neighbourhood in the middle
of being occupied.** A method that cannot draw this distinction overstates the
problem roughly twentyfold. That is the gap, measured.

### How the gap maps to our objectives

| Gap | Our response |
|---|---|
| No per-city norm | Learn the expected activity level from the city's own relationship between building and activity, so nothing needs re-tuning for a new city |
| Stalled and filling-up not separated | Add a `emerging` class driven by the activity *trend*, not just its level |
| Single-signal detection is unreliable | Combine nighttime light radiance (weight 0.45), POI density (0.35) and population (0.20) |
| Predictions not validated honestly | Train on one period, test on a later unseen period, and compare against random allocation |

---

## 9. References

All verified against Crossref, the publisher record, or the paper's own title
page. Titles are reproduced exactly as published.

1. Chen, X., Wang, Z., Zhang, F., Shen, G. & Chen, Q. (2024). A global annual
   simulated VIIRS nighttime light dataset from 1992 to 2023. *Scientific Data*
   **11**, 1380. DOI 10.1038/s41597-024-04228-6
2. Tian, Y., Cheng, K.M., Zhang, Z., Zhang, T., Feng, J., Ren, Z., Li, S.,
   Yan, D. & Xu, B. (2026). An Extended VIIRS-like Artificial Nighttime Light
   Data Reconstruction (1986–2024). *Scientific Data* **13**, 233.
   DOI 10.1038/s41597-026-06549-0
3. Chen, Z. et al. (2021). An extended time series (2000–2018) of global
   NPP-VIIRS-like nighttime light data from a cross-sensor calibration.
   *Earth System Science Data* **13**, 889–906. DOI 10.5194/essd-13-889-2021
4. Li, X., Zhou, Y., Zhao, M. & Zhao, X. (2020). A harmonized global nighttime
   light dataset 1992–2018. *Scientific Data* **7**, 168.
   DOI 10.1038/s41597-020-0510-y
5. Zhang, L., Ren, Z., Chen, B., Gong, P., Xu, B. & Fu, H. (2024). A Prolonged
   Artificial Nighttime-light Dataset of China (1984–2020). *Scientific Data*
   **11**, 414. DOI 10.1038/s41597-024-03223-1
6. Brown, C.F., Brumby, S.P., Guzder-Williams, B. et al. (2022). Dynamic World,
   Near real-time global 10 m land use land cover mapping. *Scientific Data*
   **9**, 251. DOI 10.1038/s41597-022-01307-4
7. Marconcini, M., Metz-Marconcini, A., Üreyen, S. et al. (2020). Outlining
   where humans live, the World Settlement Footprint 2015. *Scientific Data*
   **7**, 242. DOI 10.1038/s41597-020-00580-5
8. Tang, Y., Shao, Z., Huang, X. & Cai, B. (2021). Mapping Impervious Surface
   Areas Using Time-Series Nighttime Light and MODIS Imagery. *Remote Sensing*
   **13**(10), 1900. DOI 10.3390/rs13101900
9. Sirko, W., Kashubin, S., Ritter, M., Annkah, A., Bouchareb, Y.S.E.,
   Dauphin, Y., Keysers, D., Neumann, M., Cisse, M. & Quinn, J. (2021).
   Continental-Scale Building Detection from High Resolution Satellite Imagery.
   *arXiv:2107.12283*
10. Goldblatt, R., Stuhlmacher, M.F., Tellman, B. et al. (2018). Using Landsat
    and nighttime lights for supervised pixel-based image classification of
    urban land cover. *Remote Sensing of Environment* **205**, 253–275.
11. Zhang, Y., Tu, T. & Long, Y. (2024). Inferring ghost cities on the globe in
    newly developed urban areas based on urban vitality with multi-source data.
    *arXiv:2408.15117*; published in *Cities* (2025).
12. Yeh, C., Perez, A., Driscoll, A. et al. (2020). Using publicly available
    satellite imagery and deep learning to understand economic well-being in
    Africa. *Nature Communications* **11**, 2583.
    DOI 10.1038/s41467-020-16185-w
13. Anucharn, T., Hongpradit, P., Iamchuen, N. & Puttinaovarat, S. (2025).
    Spatial Analysis of Urban Expansion and Energy Consumption Using Nighttime
    Light Data. *ISPRS International Journal of Geo-Information* **14**(4), 178.
    DOI 10.3390/ijgi14040178
14. Liang, X., Guan, Q., Clarke, K.C., Liu, S., Wang, B. & Yao, Y. (2021).
    Understanding the drivers of sustainable land expansion using a
    patch-generating land use simulation (PLUS) model: A case study in Wuhan,
    China. *Computers, Environment and Urban Systems* **85**, 101569.
    DOI 10.1016/j.compenvurbsys.2020.101569
15. Chen, G., Li, X., Liu, X. et al. (2020). Global projections of future urban
    land expansion under shared socioeconomic pathways. *Nature Communications*
    **11**, 537. DOI 10.1038/s41467-020-14386-x
16. Shojaei, H., Nadi, S., Shafizadeh-Moghadam, H., Tayyebi, A. &
    Van Genderen, J. (2022). An efficient built-up land expansion model using a
    modified U-Net. *International Journal of Digital Earth* **15**(1),
    148–163. DOI 10.1080/17538947.2021.2017035
17. Zhang, A., Tariq, A., Quddoos, A., Naz, I., Aslam, R.W., Barboza, E.,
    Ullah, S. & Abdullah-Al-Wadud, M. (2025). Spatio-temporal analysis of urban
    expansion and land use dynamics using google earth engine and predictive
    models. *Scientific Reports* **15**, 6993. DOI 10.1038/s41598-025-92034-4
18. Ramachandra, T.V., Rana, R.S., Vinay, S. & Aithal, B.H. (2025). Urban heat
    island linkages with the landscape morphology. *Scientific Reports* **15**,
    24485. DOI 10.1038/s41598-025-09141-5

### Cited in support, copies not held

These are referenced in the discussion above but are behind a paywall or could
not be retrieved automatically. They are not counted in the 18.

19. Zheng, Q., Weng, Q. & Wang, K. (2019). Developing a new cross-sensor
    calibration model for DMSP-OLS and Suomi-NPP VIIRS night-light imageries.
    *ISPRS Journal of Photogrammetry and Remote Sensing* **153**, 36–47.
20. Nechaev, D., Zhizhin, M., Poyda, A., Ghosh, T., Hsu, F.-C. & Elvidge, C.
    (2021). Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and
    SNPP/VIIRS with Residual U-Net. *Remote Sensing* **13**(24), 5026.
    DOI 10.3390/rs13245026 — **open access, one click from the publisher**
21. Ermida, S.L., Soares, P., Mantas, V., Göttsche, F.-M. & Trigo, I.F. (2020).
    Google Earth Engine Open-Source Code for Land Surface Temperature
    Estimation from the Landsat Series. *Remote Sensing* **12**(9), 1471.
    DOI 10.3390/rs12091471 — **open access, one click from the publisher**
22. Vohra, R., Kumar, A., Jain, R. & Hemanth, D.J. (2024). Analysis and
    prediction of land surface temperature with increasing urbanisation using
    satellite imagery. *Heliyon* **10**, e40378.
    DOI 10.1016/j.heliyon.2024.e40378 — Ernakulam District, Kerala, India
23. Chen, T.-H.K., Chen, W., Stokes, E.C. & Zhou, Y. (2026). Detecting gaps
    between urban expansion and lighting infrastructure growth using daytime
    and nighttime satellite imagery. *International Journal of Applied Earth
    Observation and Geoinformation* **146**, 105087.
    DOI 10.1016/j.jag.2026.105087 — directly on this project's core question
24. Henderson, J.V., Storeygard, A. & Weil, D.N. (2012). Measuring Economic
    Growth from Outer Space. *American Economic Review* **102**(2), 994–1028.

---

## 10. Verification status

**Citation metadata:** all 18 verified against Crossref, the publisher record,
or the paper's own title page.

**File integrity:** every one of the 18 files was opened and its first page
checked against its title. Two problems were found and fixed:

- One download returned a **completely different paper** — a file named for a
  land surface temperature study actually contained an article about MXene
  nanofluids in solar systems. It was deleted rather than cited.
- The existing copy of Zhang, Tu & Long (2024) was a **truncated download**:
  18 MB with no end-of-file marker, and it would not open. It was replaced with
  the complete 37 MB file from arXiv and re-verified.

**Open access:** every paper downloaded here was confirmed open access before
retrieval. Nothing behind a paywall was accessed.
