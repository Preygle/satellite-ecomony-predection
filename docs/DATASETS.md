# Datasets

Two parts: (1) what this system uses and why, (2) additions beyond
`satellite-dataset.md` that materially change what the project can do.

Official dataset identifiers are written exactly as they appear in the
provider's catalogue and in the code. Readable labels are given separately and
are used only in figure captions and dashboard headings. Every abbreviation is
expanded at first use; the full list is in
[`CONVENTIONS.md`](CONVENTIONS.md).

---

## Part 1 — Datasets in use

### Datasets requiring no account

| Official product | Provider | Readable label | Resolution | Coverage | Role |
|---|---|---|---|---|---|
| `GHS-BUILT-S R2023A` | European Commission Joint Research Centre | GHSL Built-up Surface | 100 m | 1975–2030, five-yearly | Built-up expansion — the backbone |
| `GHS-POP R2023A` | European Commission Joint Research Centre | GHSL Population | 100 m | 1975–2030, five-yearly | Population; activity denominator |
| OpenStreetMap, via the Overpass API | OpenStreetMap contributors | OpenStreetMap | vector | Current | Commercial POI (Point of Interest) and road data |

GHSL (Global Human Settlement Layer) is the backbone because it is the only
multi-epoch, globally consistent built-up product that can be downloaded in
bulk without an account, and its five-yearly epochs land exactly on 2010, 2015
and 2020.

Access: `https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/` over plain
HTTP, verified working with no account, plus the public Overpass endpoints.

**Tiling.** `GHS-BUILT-S R2023A` is distributed on a 1,000,000 m Mollweide
(ESRI:54009) grid. Varanasi falls entirely inside tile `R6_C26`. The tile is
computed from the area of interest in `src/urbanintel/data/ghsl.py`, not
hard-coded, so a different city works unchanged.

**Important limit on the later epochs.** `GHS-BUILT-S R2023A` supplies epochs
up to 2030, but only 1975–2020 are observational. The 2025 and 2030 epochs are
the GHSL model's own projections. All measured claims in this project stop at
2020; anything later is labelled a projection.

### Datasets requiring Google Earth Engine

One-time `earthengine authenticate` plus a registered Cloud project.

| Official asset identifier | Provider | Readable label | Resolution | Coverage used | Role |
|---|---|---|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` | NOAA | VIIRS Annual Nighttime Lights v2.1 | 463 m | **2013–2021** | Nighttime light radiance → activity proxy |
| `NOAA/VIIRS/DNB/ANNUAL_V22` | NOAA | VIIRS Annual Nighttime Lights v2.2 | 463 m | **2022 onward** | Same, later years |
| `COPERNICUS/S2_SR_HARMONIZED` | ESA / Copernicus | Sentinel-2 Surface Reflectance Harmonized | 10 m | 2018 onward | NDVI (Normalized Difference Vegetation Index) for green cover; NDBI (Normalized Difference Built-up Index) |
| `LANDSAT/LC08/C02/T1_L2` | USGS | Landsat 8 Collection 2 Level-2 | 30 m | 2013 onward | LST (Land Surface Temperature), band `ST_B10` |
| `LANDSAT/LC09/C02/T1_L2` | USGS | Landsat 9 Collection 2 Level-2 | 30 m | 2021 onward | Same, later years |
| `GOOGLE/DYNAMICWORLD/V1` | Google | Dynamic World Land Cover | 10 m | 2015 onward | Land-cover cross-check |
| `GOOGLE/Research/open-buildings-temporal/v1` | Google | Open Buildings Temporal | 4 m | 2016–2023 | Building height → vertical growth |
| `ESA/WorldCover/v200` | ESA | WorldCover 10 m land cover | 10 m | 2021 | Independent built-up comparison |
| `MODIS/061/MOD11A2` | NASA LP DAAC | MODIS 8-day land surface temperature | 1 km | 2024 | Independent check on the Landsat LST |
| `USGS/SRTMGL1_003` | NASA / USGS | SRTM elevation | 30 m | single epoch | Terrain slope, a driver of the growth model |
| `WorldPop/GP/100m/pop` | WorldPop, University of Southampton | WorldPop annual population | ~92 m | 2001–2020 | Independent population estimate |

VIIRS is the Visible Infrared Imaging Radiometer Suite; DNB is its Day/Night
Band, the band that measures light at night.

#### Two VIIRS assets are required, not one

The annual nighttime-light series is split across two product versions in the
Earth Engine catalogue:

- `NOAA/VIIRS/DNB/ANNUAL_V21` holds **2013–2021**
- `NOAA/VIIRS/DNB/ANNUAL_V22` holds **2022 onward**

Querying `NOAA/VIIRS/DNB/ANNUAL_V22` for an earlier year returns an empty
result rather than an error. An earlier version of this document stated that
`ANNUAL_V22` covered 2012–2025, which is wrong; the claim was corrected after
checking the catalogue directly on 17 August 2026. The code now selects the
asset by year in `src/urbanintel/data/gee.py`.

The two versions share the same core compositing method, so joining them is a
version step rather than a sensor change. It is still a discontinuity, and any
trend crossing 2021/2022 carries it.

#### Sentinel-2 coverage before 2018

`COPERNICUS/S2_SR_HARMONIZED` is the Level-2A surface reflectance archive, and
it is sparse over Varanasi in its early years. The October–March window holds:

| Window | Scenes | Distinct days |
|---|---|---|
| Oct 2015 – Mar 2016 | 3 | **1** |
| Oct 2017 – Mar 2018 | 57 | 18 |
| Oct 2018 – Mar 2019 | 117 | 31 |
| Oct 2024 – Mar 2025 | 148 | 35 |

A median composite built from a single day is not a seasonal median — it is one
observation with that day's weather and phenology in it. Comparing such a
composite against a full-season one measures the difference in sampling, not
the difference on the ground. The vegetation baseline is therefore 2018, the
first year with more than 30 acquisition days, and the code refuses any
composite built from fewer than 20 distinct dates.

#### Bands actually used

| Dataset | Band | Why this band |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` / `_V22` | `average_masked` | The plain `average` band keeps a background noise floor that registers as activity in unlit peri-urban cells — exactly the cells the ghost-growth analysis judges |
| `COPERNICUS/S2_SR_HARMONIZED` | `B8`, `B4` | Near Infrared and Red, used to compute NDVI |
| `COPERNICUS/S2_SR_HARMONIZED` | `B11`, `B8` | Shortwave Infrared and Near Infrared, used to compute NDBI |
| `LANDSAT/LC08/C02/T1_L2` | `ST_B10` | Surface temperature band of Collection 2 Level-2 |

---

### Indian statistical datasets (no account)

Added for Review 3, to check the satellite results against ground records.

| Dataset | Publisher | What it gives us | Licence |
|---|---|---|---|
| SHRUG — 2011 and 2001 Population Census Abstract, by town/village and district | Development Data Lab, from the Census of India | Official population for 71 districts of Uttar Pradesh and 11,624 towns and villages | CC BY-NC-SA 4.0 |
| SHRUG — 2013 Economic Census (6th Economic Census, MoSPI) | Development Data Lab | Non-farm employment and establishments by town/village and district | CC BY-NC-SA 4.0 |
| SHRUG — town/village (shrid) and 2011 district boundaries | Development Data Lab | Polygons for summing satellite values place by place | CC BY-NC-SA 4.0 |
| District Domestic Product of Uttar Pradesh, base year 2011-12 | Directorate of Economics & Statistics, Government of Uttar Pradesh | Gross District Domestic Product for all districts, 2020-21 and 2021-22 | Published government statistics |

SHRUG is the Socioeconomic High-resolution Rural-Urban Geographic Platform for
India. It matters here because it ties census tables to one set of town and
village identifiers, which is what lets a satellite value be compared with a
census count for the same place. Cite as Asher, Lunt, Matsuura and Novosad
(2021), *The World Bank Economic Review* 35(4).

Downloaded by `scripts/fetch_indian_data.py`; every file, its source, size and
SHA-256 hash is recorded in `data/raw/india/MANIFEST.json`. What these datasets
showed is in `REVIEW3_REPORT.md` §5.2 and §5.11.

---

## Part 2 — How each main dataset is used

Following the pattern used throughout this project: what it is, why we use it,
how we use it on the Varanasi data, and what it produces.

### GHS-BUILT-S R2023A

**What it is.** A gridded dataset of built-up surface density from the European
Commission Joint Research Centre, produced from Sentinel-2 and Landsat imagery.
Each 100 m cell records how many square metres of it are built on.

**Why we use it.** It is the only multi-epoch, globally consistent built-up
product that can be downloaded without an account, and its five-yearly epochs
match the years we want to compare.

**How we use it.** We take the 2010, 2015 and 2020 epochs for the Varanasi area
of interest, convert them to density, reproject them to UTM zone 44N, and
subtract one epoch from another to find where new building appeared. Each newly
built cell is then classified as infill, edge expansion or leapfrog.

**Result.** A map of urban expansion for Varanasi, with the total area added
and the share of it that is detached from the existing city.

### NOAA/VIIRS/DNB/ANNUAL_V21 and NOAA/VIIRS/DNB/ANNUAL_V22

**What it is.** Annual composites of nighttime light radiance from NOAA,
measured by the VIIRS Day/Night Band at about 463 m.

**Why we use it.** Nighttime light radiance is an indirect indicator of human
and economic activity. It is a proxy, not a measurement of economic output.

**How we use it.** We build a twelve-year series, 2013–2024, for the Varanasi
area of interest, normalise radiance per unit of built-up area so that the
value reflects intensity of use rather than size of settlement, and fit a trend
per cell to see whether activity is rising or flat.

**Result.** An activity map and an activity trend, which together separate land
that is dim and staying dim from land that is dim but brightening.

### COPERNICUS/S2_SR_HARMONIZED

**What it is.** Sentinel-2 Surface Reflectance Harmonized, from ESA and
Copernicus, at 10 m for the bands we need.

**Why we use it.** The Near Infrared and Red bands give NDVI, which estimates
vegetation cover; the Shortwave Infrared and Near Infrared bands give NDBI,
which highlights built-up surfaces.

**How we use it.** We build October–March median composites for 2018 and 2024,
avoiding the heavily clouded June–September monsoon, and compare them. Only
NDVI decline that coincides with built-up gain is counted as urbanisation.

**Result.** A green-cover change map, and a figure for vegetation lost
specifically to building rather than to the cropping calendar.

### LANDSAT/LC08/C02/T1_L2 and LANDSAT/LC09/C02/T1_L2

**What it is.** Landsat 8 and Landsat 9 Collection 2 Level-2 products from
USGS, including the surface temperature band `ST_B10` at 30 m.

**Why we use it.** LST lets us measure the surface urban heat island, which is
how much hotter the city surface is than the countryside around it.

**How we use it.** We take pre-monsoon (March–May) imagery from both
satellites, mask cloud with QA_PIXEL bits 1–4 (dilated cloud, cirrus, cloud,
cloud shadow), and compute LST. From it we subtract a rural reference: cells
under 2% built surface, excluding water and land that `GOOGLE/DYNAMICWORLD/V1`
already sees as built in 2024. Excluding water matters because the Ganga would
otherwise pull the rural baseline down. The mean is taken over urban cells
(at least 20% built).

**Result.** A heat-island intensity map and a hotspot area, combined with
population to give a heat-vulnerability surface. In March–May 2024 urban cells
are on average 1.66 °C *cooler* than the rural reference — a daytime surface
cool island, confirmed by `MODIS/061/MOD11A2` (see `REVIEW3_REPORT.md`, §5.7).

### OpenStreetMap

**What it is.** A free, community-made map database, queried through the
Overpass API.

**Why we use it.** It tells us what *kind* of activity is present — shops,
clinics, offices — which radiance alone cannot.

**How we use it.** We extract commercial POIs and roads for the area of
interest, group POIs by sector, and compute POI density and class-weighted road
density per cell.

**Result.** A commercial-activity surface that forms one of the three signals
in the activity index.

**Known limitation.** OpenStreetMap coverage is uneven. Varanasi's core is well
mapped; the periphery is not. Because all the ghost-growth zones are
peripheral, some of their low POI count may reflect mapping effort rather than
absence of activity. This is why the activity index requires agreement across
three signals rather than trusting any one.

---

## Part 3 — Recommended additions beyond `satellite-dataset.md`

The dataset list in `satellite-dataset.md` is sound and complete for Google
Earth Engine. These are the gaps it leaves.

### 1. GHSL — the largest omission

`satellite-dataset.md` has no multi-epoch built-up product. Without one, urban
expansion has to be derived by thresholding NDBI on Landsat or Sentinel-2
composites, which is noisy, needs calibrating for every year, and is not
comparable across sensors.

`GHS-BUILT-S R2023A` solves this outright: consistent, validated, five-yearly,
100 m, and downloadable without an account — which is why the whole pipeline
can run before anyone authenticates.

- Portal: <https://human-settlement.emergency.copernicus.eu/ghs_buS2023.php>
- An Earth Engine mirror exists (`JRC/GHSL/P2023A/GHS_BUILT_S`), but direct
  download is preferred here precisely so the project keeps a path that needs
  no credentials.

### 2. GOOGLE/Research/open-buildings-temporal/v1 — the vertical dimension

**4 m, annual, 2016–2023, covers India.** Bands: `building_presence`,
`building_height`, `building_fractional_count`.

This is the single most valuable addition for ghost-growth work. Built-up
*area* cannot distinguish a neighbourhood that is getting denser from one that
is spreading outward, and cannot see a finished but empty tower at all.
Building height can. A cell where height rises while area stays flat is
getting denser; a cell with tall new buildings and no light is a much stronger
ghost signal than area alone.

### 3. GOOGLE/DYNAMICWORLD/V1 — green cover without threshold-tuning

10 m, updated every two to five days, 2015 onward, nine land-cover classes
including `trees`, `grass`, `built` and `water`.

`satellite-dataset.md` derives green cover from NDVI thresholds. That works,
but each threshold has to be defended for every season and year. Dynamic World
gives per-pixel class probabilities directly, and supplies the water mask the
heat-island rural reference needs.

### 4. NASA/VIIRS/002/VNP46A2 — better nightlights for change detection

The NASA Black Marble suite is corrected for surface reflectance geometry, the
atmosphere and moonlight, so differences between months reflect activity rather
than lunar phase and viewing angle.

- `NASA/VIIRS/002/VNP46A2` (daily), `NASA/VIIRS/002/VNP46A3` (monthly)
- Use `NOAA/VIIRS/DNB/ANNUAL_V21` and `_V22` for the long trend, and Black
  Marble monthly to see *when* a zone lit up.

### 5. ESA/WorldCover/v200 — an independent land-cover check

10 m, 2020 and 2021, 11 classes. A cheap cross-check on Dynamic World. Where
the two disagree, that cell's land-cover-derived results should be treated as
low-confidence.

### 6. GAIA and WSF Evolution — longer built-up history

- **GAIA**: annual 30 m global impervious surface, 1985–2018 (Gong et al.
  2020, *Remote Sensing of Environment* 236:111510)
- **WSF Evolution**: annual 30 m settlement extent, 1985–2015

Both are finer than GHSL's 100 m and annual rather than five-yearly. Neither
extends past 2018, so they complement GHSL rather than replacing it. Worth
adding if annual resolution matters for the growth model.

### 7. India-specific layers worth pursuing

| Source | What it provides | Why it matters |
|---|---|---|
| Census 2011 ward boundaries | Varanasi Nagar Nigam, 90 wards | Ward-level reporting is what a municipal planner acts on; the 500 m grid is a stand-in for it |
| Bhuvan (ISRO) | Land use and land cover at 1:50,000 | National reference land cover; useful for checking Dynamic World |
| Varanasi Development Authority master plan | Planned land use | The intent layer — comparing planned against actual built-up is the sharpest framing available |
| Uttar Pradesh power distribution (PuVVNL) feeder data | Electricity consumption by area | Ground truth for the assumption that nighttime light indicates activity |

The master plan comparison is the strongest available upgrade to this project.
"Development that happened where none was planned" and "planned development
that never materialised" are both directly derivable from it.

---

## Part 4 — Datasets deliberately not used

| Dataset | Why not |
|---|---|
| `NOAA/DMSP-OLS/NIGHTTIME_LIGHTS` | DMSP-OLS covers 1992–2014, but this project's analysis window starts in 2010 and its built-up baseline is 2010. DMSP-OLS saturates in bright city cores and blurs light outward, and converting it to match VIIRS adds a large error term to buy pre-2012 history the project does not use. |
| WorldPop | **Now used** (Review 3). `GHS-POP R2023A` remains the primary layer because it is multi-epoch and built from the same chain as `GHS-BUILT-S R2023A`. `WorldPop/GP/100m/pop` is read from Earth Engine as an independent estimate: against the 2011 Census it is the more accurate of the two (median district error −0.4% against +3.4%), and the two disagree enough about 2010–2020 growth that the headline ratio is reported as a range. See `REVIEW3_REPORT.md` §5.2. |
| `COPERNICUS/S1_GRD` | Sentinel-1 radar is valuable for detecting built-up area in any weather, but it needs a speckle-filtering and calibration chain the project does not require, given GHSL already provides validated built-up surface. Worth reconsidering for change *timing*. |
| `NASA/HLS/HLSL30/v002`, `NASA/HLS/HLSS30/v002` | Harmonized Landsat and Sentinel is genuinely useful for dense time series, but `COPERNICUS/S2_SR_HARMONIZED` alone gives enough clear October–March scenes over Varanasi for annual composites. |
| `GHS-SMOD R2023A` | A large global file that is itself derived from `GHS-BUILT-S` and `GHS-POP` by thresholding. The two masks the project needs are derived directly instead — same information, about 1 GB less transfer, and the masks stay at 100 m rather than being forced to a 1 km floor. |

---

## Part 5 — Access verification

Checked on 27 July 2026, and re-checked for Earth Engine on 17 August 2026.

| Source | Status |
|---|---|
| GHSL open-data HTTP (Joint Research Centre) | Working, 200, no account. About 30 KB/s per connection, so downloads are run in parallel |
| WorldPop HTTP | Working, 200, no account |
| Overpass API | Working. Requires a `User-Agent` header — returns 406 without one — and rate-limits, so the client rotates across three endpoints |
| Earth Observation Group direct VIIRS download | Not usable: requires OAuth, redirects to `eogauth.mines.edu`. The Earth Engine copy is used instead |
| Google Earth Engine | Working, after `earthengine authenticate` and registering a Cloud project |
