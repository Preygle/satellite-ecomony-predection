# Research Papers — Sentinel and Landsat

Ten of the project's twenty reviewed papers carry substantial Sentinel or
Landsat content. They are copied into `papers/` in this folder.

## How the ten were chosen

Rather than picking by memory, the full text of all twenty papers was scanned
and every mention of "Sentinel" and "Landsat" counted. The ten below are the
ones where either sensor is genuinely part of the work; the other ten mention a
sensor once or twice in passing, or not at all.

| Paper | Year | Sentinel mentions | Landsat mentions | Role of the sensor |
|---|---|---|---|---|
| Ermida, S. L. et al. — Google Earth Engine Open-Source Code for Landsat Land Surface Temperature | 2020 | 1 | **237** | The paper *is* a Landsat method — the reference implementation behind our thermal layer |
| Goldblatt, R. et al. — Using Landsat and nighttime lights for supervised pixel-based image classification | 2018 | 1 | **65** | Landsat is the classified imagery; validated on India |
| Brown, C. F. et al. — Dynamic World | 2022 | **62** | 2 | Built entirely on Sentinel-2; the 10 m land-cover product we cross-check against |
| Marconcini, M. et al. — World Settlement Footprint 2015 | 2020 | 5 | **43** | Landsat optical combined with Sentinel-1 radar — the first product to fuse both |
| Ramachandra, T. V. et al. — Urban heat island linkages with landscape morphology | 2025 | **15** | **27** | Landsat thermal plus Sentinel-2 optical, on an Indian city |
| Chen, X. et al. — A global annual simulated VIIRS nighttime light dataset | 2024 | 0 | **22** | Landsat NDVI is the second input channel that makes the network work |
| Tang, Y. et al. — Mapping Impervious Surface Areas | 2021 | 3 | **19** | Landsat used for validation of the impervious-surface estimate |
| Yeh, C. et al. — Satellite imagery and deep learning for economic well-being | 2020 | 1 | **21** | Landsat multispectral bands are the model input |
| Tian, Y. et al. — An Extended VIIRS-like Artificial Nighttime Light Reconstruction | 2026 | 0 | **12** | Six Landsat surface-reflectance bands as model features |
| Zhang, A. et al. — Spatio-temporal analysis using Google Earth Engine | 2025 | 0 | **10** | Landsat 5 and Landsat 8 classified in Earth Engine, then projected forward |

## The ten not copied

Counted 3 or fewer mentions of either sensor, so they are about nighttime light,
modelling or building detection rather than these two sensors:

Chen, Z. et al. 2021 · Nechaev et al. 2021 · Zhang, Tu & Long 2024 ·
Li et al. 2020 · Chen, G. et al. 2020 · Sirko et al. 2021 ·
Anucharn et al. 2025 · Liang et al. 2021 · Shojaei et al. 2022 ·
Zhang, L. et al. 2024

They remain in the project's main `papers/` folder and in
[`PAPER_SUMMARIES.md`](../docs/PAPER_SUMMARIES.md).

## What these papers say that we use

**On Landsat.** Ermida et al. is the method our thermal layer follows, and it
tells us how much error to expect: **RMSE 1.0–1.3 K** against ground sensors.
That matters, because our measured mean urban heat-island intensity is 1.10 °C —
the same order as the measurement error, which is why we report the hotspot area
rather than leaning on the mean. Goldblatt et al. showed that Landsat can be
classified into built-up land using nighttime light as automatic training
labels, reporting **80.8% balanced accuracy for India**.

**On Sentinel-2.** Brown et al. built Dynamic World from Sentinel-2 at 10 m,
publishing a class probability per pixel rather than one fixed label. We use it
as an independent land-cover check and for the water mask the heat calculation
needs.

**On using both together.** Marconcini et al. fused Landsat optical with
Sentinel-1 radar and improved on GHSL by **Kappa +0.23**, particularly for small
and scattered settlements — which is a documented weakness of the built-up
dataset this project relies on. Ramachandra et al. combine Landsat thermal with
Sentinel-2 optical for an Indian city, which is the closest published parallel
to how we use the two.
