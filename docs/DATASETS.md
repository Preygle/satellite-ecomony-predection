# Datasets

Two parts: (1) what this system uses and why, (2) **additions beyond
`satellite-dataset.md`** that materially change what the project can do.

---

## Part 1 — Datasets in use

### Open path (no credentials)

| Dataset | Product | Res. | Coverage | Role |
|---|---|---|---|---|
| **GHSL** | `GHS-BUILT-S` R2023A | 100 m | 1975–2030, 5-yearly | **Built-up expansion — the backbone** |
| **GHSL** | `GHS-POP` R2023A | 100 m | 1975–2030, 5-yearly | Population; activity denominator |
| **OpenStreetMap** | Overpass API | vector | current | Commercial POIs, roads → activity & infrastructure |

Access: `https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/` (direct HTTP,
verified working, no account) and the public Overpass endpoints.

GHSL is the backbone because it is the only multi-epoch, globally consistent
built-up product that is **bulk-downloadable without an account**, and its
5-yearly epochs land exactly on 2010 / 2015 / 2020 / 2025.

Tiling: R2023A uses a 1,000,000 m Mollweide (ESRI:54009) grid. Varanasi falls
entirely inside tile **R6_C26** — computed in `data/ghsl.py:tile_for()`, not
hard-coded, so other cities work unchanged.

### Earth Engine path (one-time `earthengine authenticate`)

| Asset ID | Res. | Range | Role |
|---|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V22` | 463 m | 2012–2025 | Nightlights → economic activity |
| `COPERNICUS/S2_SR_HARMONIZED` | 10 m | 2017– | NDVI (green cover), NDBI |
| `LANDSAT/LC08/C02/T1_L2` + `LC09` | 30 m | 2013– | Land surface temperature (`ST_B10`) |
| `GOOGLE/DYNAMICWORLD/V1` | 10 m | 2015– | Land cover cross-check |
| `GOOGLE/Research/open-buildings-temporal/v1` | 4 m | 2016–2023 | Building height → vertical growth |

Band note: the VIIRS **`average_masked`** band is used, not `average`. The
plain band retains a background noise floor that registers as spurious
activity in unlit peri-urban cells — precisely the cells the ghost-growth
analysis is judging.

---

## Part 2 — Recommended additions beyond `satellite-dataset.md`

Your dataset list is sound and GEE-complete. These are the gaps it leaves.

### 1. GHSL — the largest omission

`satellite-dataset.md` has no multi-epoch built-up product. Without one, urban
expansion has to be derived by thresholding NDBI on Landsat/Sentinel
composites, which is noisy, needs per-year calibration, and is not comparable
across sensors.

GHS-BUILT-S solves this outright: consistent, validated, 5-yearly, 100 m,
1975–2030 — and downloadable without an account, which is why the whole
pipeline can run before anyone authenticates.

- Portal: <https://human-settlement.emergency.copernicus.eu/ghs_buS2023.php>
- GEE mirror also exists (`JRC/GHSL/P2023A/GHS_BUILT_S`), but direct download
  is preferred here precisely so the project has a no-credential path.

### 2. Google Open Buildings Temporal — the vertical dimension

`GOOGLE/Research/open-buildings-temporal/v1` — **4 m, annual, 2016–2023,
covers India.** Bands: `building_presence`, `building_height`,
`building_fractional_count`.

This is the single most valuable addition for ghost-growth work. Built-up
*area* cannot distinguish a densifying neighbourhood from an expanding one,
and cannot see a completed-but-empty tower at all. Building height can.
A cell where height rises while area stays flat is densifying; a cell with
tall new buildings and no lights is a much stronger ghost signal than area
alone provides.

### 3. Dynamic World — green cover without threshold-tuning

`GOOGLE/DYNAMICWORLD/V1` — 10 m, near-real-time, 2015–present, nine classes
including `trees`, `grass`, `built`, `water`.

Your list derives green cover from NDVI thresholds. That works but needs a
threshold defended per season and per year. Dynamic World gives per-pixel
class probabilities directly, updated every 2–5 days, and supplies the
**water mask** the SUHI rural reference needs — without it the Ganga
contaminates the rural baseline and inflates apparent heat-island intensity
city-wide.

### 4. NASA Black Marble (`VNP46A2` / `A3` / `A4`) — better nightlights

Your list has VIIRS annual `V22`, which is correct for trend work. For
*change detection* the Black Marble suite is better: BRDF-, atmosphere- and
moonlight-corrected, so month-to-month differences reflect activity rather
than lunar phase and viewing geometry.

- GEE: `NASA/VIIRS/002/VNP46A2` (daily), `VNP46A3` (monthly)
- Use `V22` annual for the long trend; Black Marble monthly to see *when* a
  zone lit up.

### 5. ESA WorldCover — an independent land-cover check

`ESA/WorldCover/v200` — 10 m, 2020/2021, 11 classes. Cheap cross-check on
Dynamic World; where the two disagree, treat that cell's land-cover-derived
results as low-confidence.

### 6. GAIA and WSF Evolution — longer built-up history

- **GAIA**: annual 30 m global impervious, 1985–2018 (Gong et al. 2020,
  *RSE* 236:111510)
- **WSF Evolution**: annual 30 m settlement extent, 1985–2015

Both are finer than GHSL's 100 m and annual rather than 5-yearly. Neither
extends past 2018, so they complement rather than replace GHSL. Worth adding
in Phase 2 if annual resolution matters for the growth model.

### 7. India-specific layers worth pursuing

| Source | What | Why |
|---|---|---|
| **Census 2011 ward boundaries** | Varanasi Nagar Nigam, 90 wards | Ward-level reporting is what a municipal planner actually acts on; the 500 m grid is a proxy for it |
| **Bhuvan (ISRO)** | LULC 1:50k, thematic layers | National reference LULC; useful validation against Dynamic World |
| **Varanasi Development Authority master plan** | Planned land use | The *intent* layer — comparing planned vs. actual built-up is the sharpest possible ghost-growth framing |
| **UP power distribution (PuVVNL) feeder data** | Consumption by area | Ground truth for the nightlight-as-activity assumption |

The master plan comparison is the strongest available upgrade to this project:
"development that happened where none was planned" and "planned development
that never materialised" are both directly derivable, and both are exactly
what an evaluator will find compelling.

---

## Datasets deliberately **not** used

| Dataset | Why not |
|---|---|
| **DMSP-OLS** (1992–2014) | The project's analysis window starts 2010 and the built-up baseline is 2010. DMSP's 6-bit saturation and blooming would degrade the activity signal, and harmonising DMSP→VIIRS adds a large error term to buy pre-2012 history this project does not need. |
| **WorldPop** | GHS-POP is multi-epoch and built from the same chain as GHS-BUILT-S, so population and built-up stay internally consistent. WorldPop is implemented (`data/worldpop.py`) as an *independent* cross-check but is off the critical path — it is a ~1 GB country raster for one 2020 estimate. |
| **Sentinel-1 SAR** | Valuable for all-weather built-up detection, but adds a speckle-filtering and calibration chain that Phase 1 does not need given GHSL already provides validated built-up. Reconsider in Phase 2 for change *timing*. |
| **HLS** | Genuinely useful for dense time series, but Sentinel-2 alone gives enough clear Oct–Mar scenes over Varanasi for annual composites. |
| **GHS-SMOD** | A large global file that is itself derived from BUILT-S + POP by thresholding. The two masks needed are derived directly — same information, ~1 GB less transfer, and the masks stay at 100 m rather than being forced to a 1 km floor. |

---

## Access verification

Checked 2026-07-27 from this machine:

| Source | Status |
|---|---|
| GHSL JRC open-data HTTP | ✅ 200, no auth (~30 KB/s per connection — parallelise) |
| WorldPop HTTP | ✅ 200, no auth |
| Overpass API | ✅ works; **requires a `User-Agent` header** (406 without) and rate-limits — the client rotates across three endpoints |
| EOG VIIRS direct download | ❌ OAuth required (redirects to `eogauth.mines.edu`) — use the GEE mirror instead |
| Earth Engine | ⚠ requires `earthengine authenticate` |
