# Conventions — Abbreviations and Dataset Registry

Single reference for every abbreviation and every dataset used in this project.
Written to the rules in `CLAUDE.md`: official dataset identifiers are exact,
every abbreviation is expanded, and every explanation is in plain English.

The project report's *List of Abbreviations* preliminary page is generated from
Part 1 of this file.

---

## Part 1 — Abbreviations

Each abbreviation is expanded at its first use in every document. This table is
the reference copy.

| Abbreviation | Full name | Plain meaning |
|---|---|---|
| AOI | Area of Interest | The rectangle of ground the project analyses |
| AUC | Area Under the Curve | How well a model separates two classes; 1.0 is perfect, 0.5 is guessing |
| CA | Cellular Automaton | A model where each grid cell changes based on its neighbours |
| CNN | Convolutional Neural Network | A deep-learning model that learns visual patterns directly from images |
| CRS | Coordinate Reference System | The map projection the data is stored in |
| CVD | Colour Vision Deficiency | Colour blindness; used when checking map colours |
| DMSP-OLS | Defense Meteorological Satellite Program — Operational Linescan System | The older nighttime-light sensor, 1992–2013 |
| DNB | Day/Night Band | The VIIRS band that measures light at night |
| FoM | Figure of Merit | Accuracy measure for land-change models: hits ÷ (hits + misses + false alarms) |
| GHSL | Global Human Settlement Layer | European Commission dataset family for built-up area and population |
| GIS | Geographic Information System | Software and methods for working with map data |
| LST | Land Surface Temperature | The temperature of the ground surface, measured by satellite |
| NDBI | Normalized Difference Built-up Index | An index computed from satellite bands that highlights built-up surfaces |
| NDVI | Normalized Difference Vegetation Index | An index computed from satellite bands that estimates vegetation cover |
| NTL | Nighttime Light | Light emitted from the ground at night, measured by satellite |
| OSM | OpenStreetMap | A free, community-made map database |
| POI | Point of Interest | A mapped place such as a shop, clinic or office |
| RMSE | Root Mean Square Error | Average size of a model's error |
| SUHI | Surface Urban Heat Island | How much hotter a city's surface is than the countryside around it |
| UTM | Universal Transverse Mercator | A map projection measured in metres |
| VIIRS | Visible Infrared Imaging Radiometer Suite | The current nighttime-light sensor, 2012 onward |

---

## Part 2 — Dataset registry

Official identifiers exactly as they appear in the code and in the data
provider's catalogue. Never shortened, renamed or paraphrased when used as a
dataset name. Readable labels are given separately, for figure captions and
dashboard headings only.

### Datasets requiring no account

| Official product | Provider | Readable label | Resolution | Coverage used |
|---|---|---|---|---|
| `GHS-BUILT-S R2023A` | European Commission Joint Research Centre (GHSL) | GHSL Built-up Surface | 100 m | 1975–2030, five-yearly |
| `GHS-POP R2023A` | European Commission Joint Research Centre (GHSL) | GHSL Population | 100 m | 1975–2030, five-yearly |
| OpenStreetMap, via the Overpass API | OpenStreetMap contributors | OpenStreetMap | vector | Current |

### Datasets requiring Google Earth Engine

| Official asset identifier | Provider | Readable label | Resolution | Coverage used |
|---|---|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` | NOAA | VIIRS Annual Nighttime Lights, version 2.1 | 463 m | **2013–2021** |
| `NOAA/VIIRS/DNB/ANNUAL_V22` | NOAA | VIIRS Annual Nighttime Lights, version 2.2 | 463 m | **2022 onward** |
| `COPERNICUS/S2_SR_HARMONIZED` | ESA / Copernicus | Sentinel-2 Surface Reflectance Harmonized | 10 m | 2018 onward *(sparse before 2018)* |
| `LANDSAT/LC08/C02/T1_L2` | USGS | Landsat 8 Collection 2 Level-2 | 30 m | 2013 onward |
| `LANDSAT/LC09/C02/T1_L2` | USGS | Landsat 9 Collection 2 Level-2 | 30 m | 2021 onward |
| `GOOGLE/DYNAMICWORLD/V1` | Google | Dynamic World Land Cover | 10 m | 2015 onward |
| `GOOGLE/Research/open-buildings-temporal/v1` | Google | Open Buildings Temporal | 4 m | 2016–2023 |
| `USGS/SRTMGL1_003` | NASA / USGS | SRTM Elevation | 30 m | Single epoch |

> **Two VIIRS assets are required, not one.** The annual nighttime-light series
> is split across two product versions in the Earth Engine catalogue.
> `NOAA/VIIRS/DNB/ANNUAL_V21` holds 2013–2021 and
> `NOAA/VIIRS/DNB/ANNUAL_V22` holds 2022 onward. Querying `ANNUAL_V22` for an
> earlier year returns an empty result rather than an error. Verified directly
> against the catalogue on 17 August 2026.

### Band actually used

| Dataset | Band | Why this band |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` | `average_masked` | The plain `average` band keeps a background noise floor, which would register as activity in unlit peri-urban cells — exactly the cells the ghost-growth analysis judges |
| `LANDSAT/LC08/C02/T1_L2` | `ST_B10` | Surface temperature band of Collection 2 Level-2 |
| `COPERNICUS/S2_SR_HARMONIZED` | `B8`, `B4` | Near Infrared and Red, used to compute NDVI (Normalized Difference Vegetation Index) |
| `COPERNICUS/S2_SR_HARMONIZED` | `B11`, `B8` | Shortwave Infrared and Near Infrared, used to compute NDBI (Normalized Difference Built-up Index) |

---

## Part 3 — Dataset, raw variable, derived output

These three are different things and are never used interchangeably.

| Official dataset | Raw variable it contains | Derived output we compute |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` | Nighttime light radiance | Nighttime activity map; activity trend |
| `COPERNICUS/S2_SR_HARMONIZED` | Surface reflectance | NDVI → vegetation map → green-cover change |
| `LANDSAT/LC08/C02/T1_L2` | Surface temperature | SUHI (Surface Urban Heat Island) intensity map |
| `GHS-BUILT-S R2023A` | Built-up surface density | Urban expansion map; infill / edge / leapfrog classification |
| `GHS-POP R2023A` | Gridded population estimate | Population density used as an activity denominator |
| OpenStreetMap | Mapped points and lines | POI (Point of Interest) density; road density |

---

## Part 4 — What is measured and what is inferred

No dataset used here contains economic output, occupancy, or ownership. Every
statement about those is an inference, and is labelled as one.

| Claim | Status | Basis |
|---|---|---|
| Built-up surface area | **Measured**, with model error | `GHS-BUILT-S R2023A`, itself a modelled product |
| Nighttime light radiance | **Measured** | `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` |
| Land surface temperature | **Measured** | `LANDSAT/LC08/C02/T1_L2`, band `ST_B10` |
| Economic activity | **Proxy** | Radiance, POI density and population combined |
| "Ghost growth" | **Inference** | Activity far below the level normal for comparable land in the same city |
| Population | **Estimate** | `GHS-POP R2023A` is modelled, not a census count |
| Built-up area for 2025 and 2030 | **Projection** | GHSL supplies these epochs as its own model output, not observation |
| Urban extent in 2030 | **Prediction** | Our suitability model plus cellular automaton |

---

## Part 5 — Writing rules applied in this project

Condensed from `CLAUDE.md`. Checked before any document is finalised.

1. Use the proper technical term, then explain it simply.
2. Expand every abbreviation at its first use in each document.
3. Never rename, shorten or invent an official dataset identifier.
4. Keep the dataset, the raw variable and the derived output distinct.
5. Never claim a dataset provides something it does not. Verify bands,
   resolution, temporal coverage and product type first.
6. Label anything derived as a proxy, estimate, inference, prediction or
   projection.
7. Do not introduce specialised terminology unless it is genuinely part of the
   implementation or is needed to describe a specific research paper.
8. Do not replace a scientific term with a vaguer one. "Nighttime light
   radiance", not "brightness". "Land Surface Temperature", not "ground heat".
9. Explain each technical component as: what it is, why we use it, how we use
   it on the Varanasi data, and what it produces.
10. Prefer the simpler method when it is sufficient. Do not add a model because
    it sounds advanced.
