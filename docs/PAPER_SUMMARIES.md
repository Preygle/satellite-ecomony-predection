# Research Paper Summaries

**Satellite-Based Urban Growth and Economic Activity Intelligence System**

All 20 papers held in the `papers/` folder, each summarised under four headings:
**Title**, **Technology used**, **Findings / results**, and **How it is useful
for our project**.

Every number below was read out of the paper itself, not from an abstract
listing or a secondary source. Abbreviations and official dataset identifiers
are listed in [`CONVENTIONS.md`](CONVENTIONS.md); the thematic analysis and
research gap are in [`LITERATURE_REVIEW.md`](LITERATURE_REVIEW.md).

**20 papers · 19 published in 2020 or later.**

| Theme | Papers |
|---|---|
| A — Nighttime light as an activity proxy | 1–6 |
| B — Measuring built-up extent | 7–11 |
| C — Inferring activity and vacancy | 12–14 |
| D — Predicting future urban expansion | 15–18 |
| E — Environmental consequences | 19–20 |

---

# Theme A — Nighttime light as a proxy for human activity

## 1. Chen, X. et al. (2024)

**Title.** A global annual simulated VIIRS nighttime light dataset from 1992 to
2023. *Scientific Data* **11**, 1380.

**Technology used.** NTLSRU-Net — a U-Net convolutional neural network reworked
as an image super-resolution model. 23 convolution layers and 4 transposed
convolution layers, all pooling layers removed to preserve fine detail. Inputs
are calibrated DMSP-OLS nighttime light plus Landsat
NDVI (Normalized Difference Vegetation Index). Trained on 12,049 image patches from the
2012–2013 overlap using mean squared error loss and the Adam optimiser.

**Findings / results.** Accuracy rises steadily with the size of the area
compared: R² 0.617 per pixel, 0.747 per city, 0.874 per province and 0.964 per
country for 2012. Correlation with Gross Domestic Product gives R² 0.88
globally. The authors state their accuracy is "closely to that of ChenVNL", a
completely different network. They also report that their product underestimates
light at the urban fringe, because the network pulls bright pixels down towards
darker neighbours.

**How it is useful for our project.** This is the paper our guide asked us to
start from, and it produced two decisions. First, accuracy depends far more on
the scale of the claim than on the model, which supports reporting on a 500 m
grid rather than per pixel. Second, the fringe error matters directly: every
underused zone we identify is on the edge of Varanasi, so we use only observed
VIIRS data and no reconstructed long series.

---

## 2. Tian, Y. et al. (2026)

**Title.** An Extended VIIRS-like Artificial Nighttime Light Data
Reconstruction (1986–2024). *Scientific Data* **13**, 233.

**Technology used.** A two-stage deep learning model. The first stage builds a
rough estimate; the second sharpens the fine structure using high-resolution
impervious-surface data as a guide. Landsat surface reflectance supplies six
bands as extra input.

**Findings / results.** The resulting EVAL dataset for China reaches R² 0.8088,
against 0.6857 for SVNL and 0.5961 for LongNTL. Root Mean Square Error is
0.9965, an improvement of 0.28 and 0.45 over those two products.

**How it is useful for our project.** It is the most recent paper in our set and
confirms the pattern in §1: the improvement comes from adding a *daytime* guide
layer, not from a cleverer network. It also gives us a current statement of the
best available accuracy for reconstructed nighttime light, which is why we do
not rely on reconstructed data for edge-of-city analysis.

---

## 3. Chen, Z. et al. (2021)

**Title.** An extended time series (2000–2018) of global NPP-VIIRS-like
nighttime light data from a cross-sensor calibration. *Earth System Science
Data* **13**, 889–906.

**Technology used.** An auto-encoder neural network combined with a vegetation
index, converting DMSP-OLS data into VIIRS-like data.

**Findings / results.** R² 0.87 at pixel level and 0.95 at city level against
real 2012 VIIRS data, with Root Mean Square Error of 2.96 nW cm⁻² sr⁻¹,
validated on 150,000 randomly chosen pixels. Country-level accuracy ranges from
R² 0.72 in China to 0.86 in Brazil.

**How it is useful for our project.** It is the benchmark that Chen, X. et al.
2024 measure themselves against, so it lets us show that two very different
networks reach a similar accuracy band. It is the second independent piece of
evidence that a daytime vegetation layer is what makes the difficult direction
work.

---

## 4. Li, X. et al. (2020)

**Title.** A harmonized global nighttime light dataset 1992–2018. *Scientific
Data* **7**, 168.

**Technology used.** A sigmoid function converting VIIRS data into DMSP-like
values, joined to step-calibrated DMSP data from satellites F10, F12, F14, F16
and F18. Implemented in MATLAB and ArcGIS.

**Findings / results.** Produces the most widely used harmonised global series,
covering 1992–2018 with a consistent trend over time.

**How it is useful for our project.** It is the standard product other work is
compared against, and it shows that a simple mathematical function is enough
for the *easy* direction — converting the newer, better sensor down to match
the older one. That contrast is what makes the case that deep learning entered
this field only because the reverse direction is genuinely harder.

---

## 5. Zhang, L. et al. (2024)

**Title.** A Prolonged Artificial Nighttime-light Dataset of China (1984–2020).
*Scientific Data* **11**, 414.

**Technology used.** A Night-Time Light convolutional Long Short-Term Memory
network — a neural network designed for sequences, so it learns how light
changes over time rather than treating each year separately.

**Findings / results.** Root Mean Square Error 0.73, R² 0.95 and a regression
slope of 0.99 at pixel level. The authors note it captures trends well in newly
built areas but slightly underestimates older city cores.

**How it is useful for our project.** This is the strongest counter-example to
our "pixel accuracy is always poor" claim, and we present it as such rather than
hiding it. The reason it scores higher is that it never crosses between two
sensors — it reconstructs within one family over time. That distinction is
exactly what makes our argument precise instead of sweeping.

---

## 6. Nechaev, D. et al. (2021)

**Title.** Cross-Sensor Nighttime Lights Image Calibration for DMSP/OLS and
SNPP/VIIRS with Residual U-Net. *Remote Sensing* **13**(24), 5026.

**Technology used.** A residual U-Net convolutional neural network producing
DMSP-like composites from VIIRS annual composites. Written by the Earth
Observation Group team that produces the VIIRS product itself.

**Findings / results.** Pixel radiances predicted from VIIRS correlate strongly
with those observed by the older sensor, with R² between 0.96 and 0.99. The
global image reaches R² 0.94, with Las Vegas and Los Angeles at 0.99 and Moscow
at 0.97.

**How it is useful for our project.** It answers the guide's question of whether
anyone else has applied U-Net to VIIRS data — they have, and Chen, X. et al.
2024 cite this paper as their precedent. Its very high R² also proves the point
in §4 from the other side: this is the *easy* direction, which is why the score
is so much higher than the 0.617 obtained going the other way.

---

# Theme B — Measuring built-up extent

## 7. Goldblatt, R. et al. (2018)

**Title.** Using Landsat and nighttime lights for supervised pixel-based image
classification of urban land cover. *Remote Sensing of Environment* **205**,
253–275.

**Technology used.** Machine learning in Google Earth Engine, using nighttime
light to label training data automatically instead of drawing training areas by
hand. Inputs include NDVI, NDWI, NDBI, EVI and UI spectral indices. Validated
against 84,564 hand-labelled polygons.

**Findings / results.** Balanced accuracy of 80.8% for India, 78.8% for the
United States and 83.8% for Mexico. For India specifically, producer's accuracy
is 77.5% and user's accuracy 60.1%.

**How it is useful for our project.** It is the methodological ancestor of this
work and one of the few in our set validated on India. The idea of using one
satellite signal to label another automatically is the same principle our
learned expected-activity curve uses. The noticeably lower user's accuracy for
India is also a useful caution about how well these methods transfer.

---

## 8. Marconcini, M. et al. (2020)

**Title.** Outlining where humans live, the World Settlement Footprint 2015.
*Scientific Data* **7**, 242.

**Technology used.** A classification system that uses optical and radar
satellite imagery together for the first time, producing a 10 m global map of
human settlements. Validated against 900,000 crowd-labelled samples.

**Findings / results.** Average Kappa of 0.6885, an improvement of 0.2338 over
GHSL and 0.2975 over GLC30. Average accuracy up to 89.33% with Kappa 0.7822.
Particularly better at finding very small rural settlements and scattered
suburban areas.

**How it is useful for our project.** It is the main alternative to the
`GHS-BUILT-S R2023A` dataset we use, and this paper quantifies where GHSL is
weaker — small and scattered settlements. That is a documented limitation we
state honestly, because Varanasi's periphery contains exactly that kind of
low-rise development.

---

## 9. Tang, Y. et al. (2021)

**Title.** Mapping Impervious Surface Areas Using Time-Series Nighttime Light
and MODIS Imagery. *Remote Sensing* **13**(10), 1900.

**Technology used.** An Enhanced Vegetation Index-adjusted nighttime light
index, geographically weighted regression to join DMSP-OLS and VIIRS, and a
genetic-algorithm-tuned back-propagation neural network to estimate the
percentage of sealed surface per cell.

**Findings / results.** Mean Absolute Error 0.0647, Root Mean Square Error
0.1003, Pearson coefficient 0.9613 and R² 0.9239. Sealed surface in the
Guangdong–Hong Kong–Macao Greater Bay Area rose from 7.97% in 2000 to 17.11% in
2019.

**How it is useful for our project.** It shows a complete worked example of
combining nighttime light with daytime imagery to measure built-up growth over
time, and it demonstrates the vegetation-adjustment idea we also rely on when
separating real vegetation loss from the farming calendar.

---

## 10. Sirko, W. et al. (2021)

**Title.** Continental-Scale Building Detection from High Resolution Satellite
Imagery. *arXiv:2107.12283*, Google Research.

**Technology used.** A U-Net model on 50 cm imagery, with studies of
architecture, loss function, regularisation, pre-training, self-training and
post-processing. Trained on 100,000 images containing 1.75 million hand-labelled
buildings.

**Findings / results.** Mixup improved mean average precision by 0.12 and
self-training with a soft loss by 0.06. Deeper encoders (ResNet-v2-101 and -152)
did **not** improve accuracy. The pipeline produced the Open Buildings dataset
of 516 million building footprints across Africa.

**How it is useful for our project.** This is the paper behind
`GOOGLE/Research/open-buildings-temporal/v1`, the dataset we plan to use for
building height. It is also useful evidence against reaching for a bigger model:
even at Google's scale, a deeper network gave no gain, and the improvements came
from training technique rather than architecture.

---

## 11. Brown, C.F. et al. (2022)

**Title.** Dynamic World, Near real-time global 10 m land use land cover
mapping. *Scientific Data* **9**, 251.

**Technology used.** Deep learning on 10 m Sentinel-2 imagery, run on a scalable
cloud system that publishes predictions alongside each new Sentinel-2 image.
Training labels came from about 4,000 tiles by 25 experts and about 20,000 tiles
by 45 non-expert annotators.

**Findings / results.** The first near-real-time global land cover product, with
per-pixel class probabilities for nine classes rather than a single hard label.

**How it is useful for our project.** We use `GOOGLE/DYNAMICWORLD/V1` as an
independent check on land cover, and its water class supplies the mask our
heat-island rural reference needs. Without excluding water, the Ganga would drag
the rural baseline down and exaggerate the heat island across the whole city.

---

# Theme C — Inferring activity and vacancy

## 12. Zhang, Y., Tu, T. & Long, Y. (2024)

**Title.** Inferring ghost cities on the globe in newly developed urban areas
based on urban vitality with multi-source data. *arXiv:2408.15117*; published in
*Cities* (2025).

**Technology used.** A framework based on urban vitality theory using several
data sources at 1 km resolution: road network density, POI (Point of Interest)
density and population density, covering morphological, functional and social
dimensions. Cities were split into areas developed before and after 2005.

**Findings / results.** Across 8,841 cities worldwide with an area above 5 km²,
the vitality of new urban areas is only **7.69%** of that of older areas. The
worst-scoring 5% — 442 cities — were labelled ghost cities.

**How it is useful for our project.** This is the closest published work to
ours, and comparing the two defines our contribution. They compare new areas
against old areas and take a fixed worst-5% cut-off. We compare each area
against what is normal *for its own level of development in its own city*, and
we separate development that has stalled from development still filling up —
a distinction they do not make, and which our own results show accounts for 95%
of the flagged area.

---

## 13. Yeh, C. et al. (2020)

**Title.** Using publicly available satellite imagery and deep learning to
understand economic well-being in Africa. *Nature Communications* **11**, 2583.

**Technology used.** Deep convolutional neural networks using the ResNet-18
architecture, trained on multispectral Landsat imagery at 30 m with seven bands
plus nighttime light, across about 20,000 African villages.

**Findings / results.** The models explain **70%** of the variation in
ground-measured village wealth in countries the model was never trained on, and
up to 50% of the variation in changes in wealth over time. For targeting a
programme at households below median wealth, accuracy was 81% using
multispectral plus nighttime light, against 62% using nighttime light alone.

**How it is useful for our project.** It establishes that satellite imagery
genuinely carries economic signal, which is the assumption our whole activity
index rests on. The 81%-versus-62% comparison is direct evidence for our design
choice of combining three signals rather than trusting nighttime light alone.

---

## 14. Anucharn, T. et al. (2025)

**Title.** Spatial Analysis of Urban Expansion and Energy Consumption Using
Nighttime Light Data: A Comparative Study of Google Earth Engine and
Traditional Methods for Improved Living Spaces. *ISPRS International Journal of
Geo-Information* **14**(4), 178.

**Technology used.** A dual-threshold classification in Google Earth Engine
compared against K-means clustering in traditional software, using VIIRS data
from 2014 to 2023 for Chiang Mai, Thailand. Accuracy checked with 256 stratified
random sampling points.

**Findings / results.** Google Earth Engine achieved overall accuracy of
0.80–0.82 against 0.73–0.76 for the traditional method, with Kappa of 0.60–0.65
against 0.44–0.52. Correlation between nighttime light and electricity
consumption reached R² 0.9744.

**How it is useful for our project.** It is a working template for the Earth
Engine workflow we use. It also carries an important warning we repeat in our
own reporting: that very high R² of 0.97 is between *provincial totals*, not
individual pixels. Treating a correlation between large aggregates as evidence
about single pixels is a common error, and one we avoid explicitly.

---

# Theme D — Predicting future urban expansion

## 15. Liang, X. et al. (2021)

**Title.** Understanding the drivers of sustainable land expansion using a
patch-generating land use simulation (PLUS) model: A case study in Wuhan,
China. *Computers, Environment and Urban Systems* **85**, 101569.

**Technology used.** The PLUS model — a land expansion analysis strategy using
random forest to find the drivers of change, joined to a cellular automaton
that grows realistic patches from multiple random seeds rather than changing
scattered single cells. Software is open source.

**Findings / results.** Simulation accuracy of **Figure of Merit 0.2642**,
against 0.1310 and 0.2514 for two reduced versions of the same model, and 0.1895
for the alternatives tested. The driver analysis also produced readable rules —
for example that deciduous forest tends to grow beside main roads.

**How it is useful for our project.** This is the model our prediction module is
patterned on: learn where growth is likely, then use a cellular automaton so new
development appears in connected patches. **It also gives us the single most
useful benchmark in the whole set.** Their Figure of Merit of 0.2642 is a
published, well-tuned result on the same measure we report, so our 0.0679 can be
placed honestly against it instead of being described only as "modest".

---

## 16. Chen, G. et al. (2020)

**Title.** Global projections of future urban land expansion under shared
socioeconomic pathways. *Nature Communications* **11**, 537.

**Technology used.** Scenario-based projection of global urban land at 1 km
resolution to 2100, following the shared socioeconomic pathways framework.
Validated using the Figure of Merit.

**Findings / results.** Global urban land keeps expanding rapidly until the
2040s. Between **50% and 63%** of newly expanded urban land is expected to
appear on current cropland, reducing global crop production by 1–4%. The authors
chose Figure of Merit explicitly because conventional measures such as the Kappa
coefficient overstate accuracy.

**How it is useful for our project.** Their stated reason for choosing Figure of
Merit is exactly our own argument, from an independent and highly cited source:
ordinary accuracy measures are misleading for land change. The cropland finding
also gives our leapfrog result a wider significance, since detached development
on the edge of Varanasi is mostly built on farmland.

---

## 17. Shojaei, H. et al. (2022)

**Title.** An efficient built-up land expansion model using a modified U-Net.
*International Journal of Digital Earth* **15**(1), 148–163.

**Technology used.** A modified U-Net that labels every pixel as built-up or
not. Input variables are altitude, slope, and distance from barren land,
cropland, greenery, roads and urban areas, arranged as data cubes for 1998, 2008
and 2018. Compared against a random forest baseline. Spatial dropout was added
to the network.

**Findings / results.** Area under the Total Operating Characteristic of
**0.87** for the modified U-Net against **0.82** for random forest. The authors
report the network learns neighbourhood effects effectively, and that spatial
dropout improved accuracy.

**How it is useful for our project.** It is the closest published analogue to
our prediction module — almost the same driver variables, and the same
decade-scale spacing between epochs. It also frames our choice not to use deep
learning honestly: the gain over random forest is 0.05 in area under the curve,
and random forest has no view of a cell's surroundings at all, so much of that
gain reflects spatial context rather than deep learning as such.

---

## 18. Zhang, A. et al. (2025)

**Title.** Spatio-temporal analysis of urban expansion and land use dynamics
using google earth engine and predictive models. *Scientific Reports* **15**,
6993.

**Technology used.** Random forest classification of Landsat 5 and Landsat 8
imagery in Google Earth Engine, followed by a simulation combining a cellular
automaton with an artificial neural network multilayer perceptron, run in the
MOLUSCE plugin for QGIS. Study area: Multan and Sargodha districts, Pakistan,
1990–2030.

**Findings / results.** Classification accuracy above 92% throughout, with
overall accuracy 0.88–0.97 and Kappa 0.82–0.95. Multan's built-up area grew from
240.56 km² (6.58%) in 1990 to 440.30 km² (12.04%) in 2020; Sargodha grew from
730.91 km² to 1,029.07 km². By 2030 Multan is projected to stabilise at 433.22
km² while Sargodha reaches 1,404.97 km².

**How it is useful for our project.** It is the most recent complete example of
the exact workflow we propose — Earth Engine, machine learning classification,
then a cellular automaton forecast — carried out on South Asian cities of a
comparable size to Varanasi. It is the strongest evidence that our proposed
pipeline is realistic and has precedent.

---

# Theme E — Environmental consequences of urban growth

## 19. Ermida, S.L. et al. (2020)

**Title.** Google Earth Engine Open-Source Code for Land Surface Temperature
Estimation from the Landsat Series. *Remote Sensing* **12**(9), 1471.

**Technology used.** An open code repository computing
LST (Land Surface Temperature) from Landsat 4, 5, 7 and 8 entirely inside Google Earth Engine,
using ASTER emissivity data. Validated against ground radiometers at several
stations.

**Findings / results.** Accuracy of 0.5 K, 0.03 K and 0.3 K for Landsat 5, 7 and
8 respectively, with Root Mean Square Error of 1.3 K, 1.1 K and 1.0 K. All meet
the accuracy threshold usually required for this kind of product.

**How it is useful for our project.** It is the reference method behind our
heat-island layer, and it tells us how much error to expect. Knowing that a good
Landsat land surface temperature estimate carries roughly 1 K of error tells us
how large a heat-island difference has to be before it is worth reporting —
which matters, because our measured mean urban intensity is 1.10 °C.

---

## 20. Ramachandra, T.V. et al. (2025)

**Title.** Urban heat island linkages with the landscape morphology.
*Scientific Reports* **15**, 24485.

**Technology used.** Multi-resolution remote sensing combining land use
assessment with LST, mapped through urban hotspot analysis and the Urban Thermal
Field Variance Index.

**Findings / results.** 15.41 km² of the study city registers very high
temperature. Barren and urban land classes form the hotspots. The relationship
modelled between land cover and temperature gives R² 0.49.

**How it is useful for our project.** It is a recent Indian study confirming the
method we use — comparing built and unbuilt surfaces to locate heat hotspots —
and its hotspot area of 15.41 km² is a useful sanity check against our own
26.57 km² for Varanasi. The modest R² of 0.49 is also a helpful reminder that
land cover explains only part of surface temperature, so we present our heat
layer as one indicator among several rather than a complete explanation.

---

# Summary table

| # | Paper | Year | Core technology | Headline result |
|---|---|---|---|---|
| 1 | Chen, X. et al. | 2024 | U-Net super-resolution | R² 0.617 pixel → 0.964 country |
| 2 | Tian, Y. et al. | 2026 | Two-stage deep learning | R² 0.8088, beats prior products |
| 3 | Chen, Z. et al. | 2021 | Auto-encoder + vegetation index | R² 0.87 pixel, 0.95 city |
| 4 | Li, X. et al. | 2020 | Sigmoid function | Standard harmonised global series |
| 5 | Zhang, L. et al. | 2024 | Convolutional LSTM | R² 0.95, RMSE 0.73 |
| 6 | Nechaev, D. et al. | 2021 | Residual U-Net | R² 0.94–0.99 |
| 7 | Goldblatt, R. et al. | 2018 | Machine learning in Earth Engine | 80.8% balanced accuracy, India |
| 8 | Marconcini, M. et al. | 2020 | Optical + radar classification | Kappa 0.6885, +0.23 over GHSL |
| 9 | Tang, Y. et al. | 2021 | Neural network + weighted regression | R² 0.9239 |
| 10 | Sirko, W. et al. | 2021 | U-Net segmentation | 516M buildings; mixup +0.12 mAP |
| 11 | Brown, C.F. et al. | 2022 | Deep learning on Sentinel-2 | First near-real-time global land cover |
| 12 | Zhang, Y. et al. | 2024 | Urban vitality, multi-source | New areas 7.69% of old; 442 ghost cities |
| 13 | Yeh, C. et al. | 2020 | ResNet-18 CNN | Explains 70% of wealth variation |
| 14 | Anucharn, T. et al. | 2025 | Earth Engine vs K-means | Accuracy 0.80–0.82 vs 0.73–0.76 |
| 15 | Liang, X. et al. | 2021 | PLUS: random forest + cellular automaton | **Figure of Merit 0.2642** |
| 16 | Chen, G. et al. | 2020 | Scenario projection | 50–63% of new urban land on cropland |
| 17 | Shojaei, H. et al. | 2022 | Modified U-Net | AUC 0.87 vs random forest 0.82 |
| 18 | Zhang, A. et al. | 2025 | Earth Engine + cellular automaton | Accuracy > 92%; 2030 projection |
| 19 | Ermida, S.L. et al. | 2020 | Earth Engine LST code | RMSE 1.0–1.3 K |
| 20 | Ramachandra, T.V. et al. | 2025 | Land use + thermal index | 15.41 km² very high temperature |

---

# What these 20 papers changed in our project

| Decision | Papers behind it |
|---|---|
| Report on a 500 m grid, never per pixel | 1, 3, 5 |
| Use only observed VIIRS, no reconstructed long series | 1, 2 |
| Combine three activity signals rather than trusting nighttime light alone | 12, 13, 14 |
| Use Figure of Merit, not overall accuracy | 15, 16 |
| Benchmark our Figure of Merit of 0.0679 against a published 0.2642 | 15 |
| Logistic Regression plus cellular automaton rather than a deep network | 10, 15, 17 |
| Exclude water from the rural reference for heat | 11, 19 |
| State that GHSL under-detects small and low-rise settlements | 8 |
| Never quote an aggregate correlation as evidence about pixels | 14 |
| Separate stalled development from development still filling up | 12 |
