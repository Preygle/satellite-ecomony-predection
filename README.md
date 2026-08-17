# Satellite-Based Urban Growth and Economic Activity Intelligence System

Detects urban expansion, commercial growth, green cover loss, urban heat
islands, and **built-but-inactive "ghost growth" zones** from open satellite
and geospatial data — then presents them as planning intelligence.

**Study city: Varanasi, Uttar Pradesh, India.** The system is city-agnostic;
Varanasi is set in `config/varanasi.yaml` and any other city is a new config
file.

**Status: Phase 1 (~50%) complete.** See [`PHASE1_REPORT.md`](PHASE1_REPORT.md)
for exactly what is delivered and what Phases 2–3 will add.

---

## Why it works without credentials

Most satellite-analysis projects stall at "first, get an Earth Engine account."
This one is built on two data paths:

| Path | Sources | Credentials | Gives you |
|---|---|---|---|
| **Open** | GHSL, OpenStreetMap | none | Built-up growth, urban form, population, POI/road activity, ghost-growth screening |
| **Earth Engine** | VIIRS, Sentinel-2, Landsat, Dynamic World, Open Buildings | one-time `earthengine authenticate` | Nightlights, NDVI/green cover, land surface temperature, building height |

The pipeline runs end-to-end on the open path alone and folds in the Earth
Engine layers automatically once they exist. Missing layers are recorded with
a reason in the output rather than silently dropped, and the dashboard shows
what was skipped.

---

## Quick start

Use a virtual environment — it keeps this project's dependencies off your
system Python and puts `streamlit` somewhere findable.

**Windows**

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .

run_pipeline.bat --no-gee
run_dashboard.bat
```

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

python scripts/prefetch.py      # ~330 MB, one time, 30-45 min
python -m urbanintel.pipeline --no-gee
streamlit run dashboard/app.py
```

> Always invoke Streamlit as `python -m streamlit`, not bare `streamlit`. The
> console script is installed into a `Scripts/` directory that is often not on
> PATH on Windows; the module form always works. The `.bat` launchers do this
> for you.

Verified on a clean run (Python 3.13, pandas 3.0, streamlit 1.60): 20/20 tests
pass, the pipeline produces 35 raster layers and a 4,765-cell reporting grid,
and the dashboard renders with 0 exceptions.

To add the satellite layers:

```bash
earthengine authenticate
python scripts/gee_export.py --project YOUR_GCP_PROJECT
python -m urbanintel.pipeline       # re-run; now includes NTL, NDVI, LST
```

See [`docs/SETUP.md`](docs/SETUP.md) for the full setup, including the
Code Editor route (`scripts/gee_export.js`) if you prefer not to install the
Python Earth Engine client.

---

## What it produces

```
outputs/
  varanasi_summary.json     all statistics, provenance, and skipped layers
  varanasi_grid.geojson     500 m reporting grid, every layer as an attribute
  varanasi_grid.csv         same, tabular
data/processed/rasters/
  *.tif                     every analytical layer at 100 m, UTM 44N
```

### The five analytical layers

1. **Built-up expansion** — GHSL built-up surface differenced across
   2010/2015/2020/2025, classified into **infill / edge expansion / leapfrog**
   using a landscape-expansion-index method (Liu et al. 2010). Leapfrog share
   is the leading indicator for ghost growth.
2. **Economic activity** — VIIRS nightlight radiance and its per-pixel trend,
   plus OSM commercial POI density. Always normalised **per unit built-up
   area**, because raw radiance mostly measures how big a place is.
3. **Green cover loss** — Sentinel-2 NDVI change, intersected with built-up
   gain so the reported figure is *conversion to urban*, not the cropping
   calendar.
4. **Urban heat island** — Landsat land surface temperature minus an in-scene
   rural reference (water excluded), with a population-weighted vulnerability
   surface.
5. **Ghost growth** — the differentiating layer. See below.

### Ghost growth: the method

Flagging "low nightlights" catches every empty field. Flagging "low
population" catches every industrial estate. Both mistake *different* for
*empty*.

Instead, this system learns **the activity level normal for a given built-up
intensity in this specific city** (a binned median, so it adapts rather than
imposing a threshold), and flags cells that fall far below their own city's
norm **and** are recently developed. Where a nightlight time series is
available, cells that are dim but *brightening* are separated out as
`emerging` — a neighbourhood mid-occupation is not a failed one.

Output is a six-class growth typology:

| Class | Meaning |
|---|---|
| `ghost_growth` | New development, activity far below expectation, not rising |
| `emerging` | New development, low activity but rising — filling up |
| `healthy_growth` | New development performing normally |
| `established_active` | Built before the baseline, performing normally |
| `declining` | Established, underperforming and falling |
| `undeveloped` | Below the built-up threshold |

**This is a screening tool, not an occupancy census.** VIIRS at ~460 m cannot
resolve one empty housing block; the unit of a reliable finding is a
neighbourhood. Limitations are stated in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and surfaced in the dashboard.

---

## Repository layout

```
config/varanasi.yaml            AOI, epochs, thresholds, sources — all tunable
src/urbanintel/
  config.py  aoi.py             config loading; AOI, analysis frame, grid
  data/                         acquisition
    ghsl.py                     GHS-BUILT-S / GHS-POP (open)
    osm.py                      Overpass POIs + roads (open)
    gee.py                      Earth Engine layers
    worldpop.py                 optional independent population cross-check
    download.py                 resumable HTTP, zip extraction
  analysis/
    builtup.py                  change detection, urban form, hotspots
    nightlights.py              trends, Sum of Lights, activity normalisation
    vegetation.py               green cover change and conversion
    thermal.py                  SUHI, heat vulnerability, cooling potential
    ghost.py                    activity index, expected-activity residual, typology
    zonal.py                    100 m -> 500 m aggregation, export
  pipeline.py                   orchestration; `python -m urbanintel.pipeline`
scripts/
  prefetch.py                   parallel download of all open data
  gee_export.py / .js           Earth Engine exports (Python and Code Editor)
dashboard/app.py                Streamlit dashboard
docs/                           SETUP, METHODOLOGY, DATASETS
```

---

## Design decisions worth knowing

- **Two grids.** Analysis runs at GHSL-native 100 m to keep change detection
  sharp; reporting is at 500 m, because a 121,000-polygon web map is unusable
  and would over-claim precision that VIIRS cannot support.
- **Density-preserving reprojection.** GHSL ships in Mollweide (equal-area);
  the analysis frame is UTM. Built-up m² and population are *extensive*
  quantities, so both are converted to density, reprojected, and rescaled —
  otherwise totals would not survive the warp.
- **GHS-SMOD is not downloaded.** It is a large global file that is itself
  derived from BUILT-S + POP by thresholding, so the two masks actually needed
  are derived directly — no fidelity lost, ~1 GB of transfer saved, and the
  masks stay at 100 m instead of being forced to a 1 km floor.
- **The chart palette is validated, not chosen by eye.** The obvious
  green-for-healthy / red-for-ghost pairing measures ΔE 4.1 under
  deuteranopia — the two most important classes would be indistinguishable to
  a red-green colourblind reader. Blue carries "healthy" instead. See
  `analysis/ghost.py`.

---

## Literature

Method choices are grounded in [`RECOMMENDED_PAPERS.md`](RECOMMENDED_PAPERS.md).
Two focused sets — VIIRS cross-sensor calibration implementations, and U-Net
architectures in urban remote sensing — with comparison tables and the trends
drawn from them are in
[`docs/LITERATURE_NTL_AND_UNET.md`](docs/LITERATURE_NTL_AND_UNET.md).

The load-bearing references:

- Jin et al. 2017, *Applied Geography* 80:112 — multi-source ghost-city identification
- Lu et al. 2018, *Remote Sensing* 10:1037 — nighttime + daytime ghost-city mapping
- Liu et al. 2010, *Landscape and Urban Planning* — landscape expansion index (urban form)
- Henderson, Storeygard & Weil 2012, *AER* 102:994 — what nightlights can and cannot say about output
- Zhou et al. 2019, *Remote Sensing* 11:48 — SUHI definition and the urban/rural reference
- Ermida et al. 2020, *Remote Sensing* 12:1471 — Landsat LST in Earth Engine

---

## Licence and data terms

Code: for academic use. Data: GHSL (CC BY 4.0), OpenStreetMap (ODbL — requires
attribution), Copernicus/Sentinel (open), Landsat/VIIRS (US public domain),
Dynamic World (CC BY 4.0), Google Open Buildings (CC BY 4.0).
