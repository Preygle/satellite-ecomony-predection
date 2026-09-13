# Satellite-Based Urban Growth and Economic Activity Intelligence System

Detects urban expansion, commercial growth, green cover loss, urban heat
islands, and **built-but-inactive "ghost growth" zones** from open satellite
and geospatial data — then presents them as planning intelligence.

**Study city: Varanasi, Uttar Pradesh, India.** The system is city-agnostic;
Varanasi is set in `config/varanasi.yaml` and any other city is a new config
file.

**Status (Review 3, September 2026):** analysis pipeline, growth models,
validation against independent and Indian data, and the dashboard are
complete; city search follows in Review 4. Start with
[`docs/REVIEW3_REPORT.md`](docs/REVIEW3_REPORT.md). `run_review3.bat`
reproduces every number and figure in it.

---

## Why it works without credentials

Most satellite-analysis projects stall at "first, get an Earth Engine account."
This one is built on two data paths:

| Path | Sources | Credentials | Gives you |
|---|---|---|---|
| **Open** | GHSL (Global Human Settlement Layer), OpenStreetMap | none | Built-up growth, urban form, population, POI/road activity, ghost-growth screening |
| **Earth Engine** | VIIRS (Visible Infrared Imaging Radiometer Suite), Sentinel-2, Landsat, Dynamic World, Open Buildings | one-time `earthengine authenticate` | Nightlights, NDVI/green cover, land surface temperature, building height |

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

### If a teammate hands you the data on a pendrive

The repository does not carry the satellite downloads, the Indian statistical
archives or the pipeline outputs — about 1.4 GB, excluded by `.gitignore`.
Rather than re-downloading them:

```bat
python scripts\external_data.py import E:\urbanintel-data
```

or leave the files where they are and point the project at them:

```bat
python scripts\external_data.py link ..\urbanintel-data
python scripts\external_data.py check
```

`link` writes `config/local.yaml`, which is never tracked by git, so each
machine can keep its data somewhere different without any merge conflict.
Full instructions, including how to make the bundle:
[`docs/DATA_TRANSFER.md`](docs/DATA_TRANSFER.md).

> Always invoke Streamlit as `python -m streamlit`, not bare `streamlit`. The
> console script is installed into a `Scripts/` directory that is often not on
> PATH on Windows; the module form always works. The `.bat` launchers do this
> for you.

Verified 11 September 2026 (Python 3.13): 41/41 tests pass, the pipeline
writes 61 raster layers and a 4,754-cell reporting grid, and the dashboard
renders with 0 exceptions.

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

### The analytical layers

1. **Built-up expansion** — GHSL built-up surface differenced across the
   observed epochs 2010/2015/2020 (GHSL's 2025 epoch is a model projection and
   appears only as a labelled comparison), classified into **infill / edge expansion / leapfrog**
   using a landscape-expansion-index method (Liu et al. 2010). Leapfrog share
   is the leading indicator for ghost growth.
2. **Economic activity** — VIIRS nightlight radiance and its per-pixel trend,
   plus OSM commercial POI (Point of Interest) density. Always normalised **per unit built-up
   area**, because raw radiance mostly measures how big a place is.
3. **Green cover loss** — Sentinel-2 NDVI (Normalized Difference Vegetation Index) change, intersected with
   Dynamic World built-up gain over the same years, so the reported figure is
   *conversion to urban*, not the cropping calendar.
4. **Urban heat island** — Landsat land surface temperature minus an in-scene
   rural reference (water and recently built land excluded), with a
   population-weighted vulnerability surface.
5. **Ghost growth** — the differentiating layer. See below.
6. **Growth prediction** — logistic regression and a random forest trained on
   2010–2015 conversions, scored on a held-out 2015–2020, then used to project
   new urban land +5 and +10 years from 2020 (`scripts/run_growth_model.py`).

Every layer is checked against independent data — other satellite products,
the Census of India, the 2013 Economic Census and Uttar Pradesh district GDP —
in `scripts/validate_*.py` and `scripts/cross_checks.py`; the results are in
[`docs/REVIEW3_REPORT.md`](docs/REVIEW3_REPORT.md) §5.

### Ghost growth: the method

Flagging "low nightlights" catches every empty field. Flagging "low
population" catches every industrial estate. Both mistake *different* for
*empty*.

Instead, this system learns **the activity level normal for a given built-up
intensity in this specific city** (a binned median, so it adapts rather than
imposing a threshold), and flags cells that fall far below their own city's
norm **and** are recently developed. Where a nightlight time series is
available, cells that are dim but brightening *significantly faster than the
established city* are separated out as `emerging` — a neighbourhood
mid-occupation is not a failed one.

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

## Documentation

| Document | What it covers |
|---|---|
| [`REVIEW3_REPORT.md`](docs/REVIEW3_REPORT.md) | **Current state.** Review 3: implementation status, results, validation, corrections log ([PDF](docs/REVIEW3_REPORT.pdf)) |
| [`DIAGRAMS.md`](docs/DIAGRAMS.md) | **Architecture diagrams and progress charts** — 15 images, what each shows, what to say over it |
| [`Review3_Panel_Presentation.pptx`](docs/Review3_Panel_Presentation.pptx) | **Review 3 panel deck** — 24 slides on architecture, algorithms, flow and results; no code on any slide; talking points in the speaker notes |
| [`AGENT.md`](AGENT.md) | **For anyone continuing the work** — rules, repository map, how to run and verify, known traps |
| [`DATA_TRANSFER.md`](docs/DATA_TRANSFER.md) | Moving the 1.4 GB of data between machines; `config/local.yaml` |
| [`CONTRIBUTIONS.md`](CONTRIBUTIONS.md) | Who owns which work package; AI acknowledgement |
| [`METHODOLOGY_SIMPLE.md`](docs/METHODOLOGY_SIMPLE.md) | The simple version: datasets, the six implementation steps, expected output |
| [`WORKFLOW.md`](docs/WORKFLOW.md) | What runs, in what order — the seven pipeline stages and the prediction step |
| [`DESIGN.md`](docs/DESIGN.md) | How the system is put together — layers, modules, key decisions |
| [`METHODOLOGY.md`](docs/METHODOLOGY.md) | The full method, with thresholds and the ghost-growth screen |
| [`DATASETS.md`](docs/DATASETS.md) | Every dataset, why it is used, and what is deliberately not used |
| [`REVIEW2_DOCUMENTATION.md`](docs/REVIEW2_DOCUMENTATION.md) | **Review 2 submission** — abstract, literature, methodology, datasets, architecture, proposed solution |
| [`LITERATURE_REVIEW.md`](docs/LITERATURE_REVIEW.md) | Chapter 2 — 20 papers by theme, comparison, research gap |
| [`PAPER_SUMMARIES.md`](docs/PAPER_SUMMARIES.md) | Each paper: title, technology, results, use to this project |
| [`CONVENTIONS.md`](docs/CONVENTIONS.md) | Abbreviations, official dataset identifiers, writing rules |
| [`SETUP.md`](docs/SETUP.md) | Installation and Earth Engine setup |

---

## Writing and naming conventions

Official dataset identifiers, the full abbreviation list, and the writing rules
this project follows are in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).
Dataset identifiers are never shortened or renamed; readable labels are used
only in figure captions and dashboard headings.

---

## Repository layout

```
config/varanasi.yaml            AOI, epochs, thresholds, sources — the one tracked config
config/local.yaml               (gitignored) this machine's data paths
src/urbanintel/
  config.py  aoi.py             config loading, epoch checks, paths; AOI, frames, grid
  data/                         acquisition
    ghsl.py                     GHS-BUILT-S / GHS-POP (open)
    osm.py                      Overpass POIs + roads (open)
    gee.py                      Earth Engine layers, cloud masks, composite-depth check
    shrug.py                    SHRUG census, economic census and polygons (Indian data)
    worldpop.py                 bulk WorldPop download (the checks use Earth Engine)
    download.py                 resumable HTTP, zip extraction
  analysis/
    builtup.py                  change detection, urban form, hotspots
    nightlights.py              trends, relative-to-city trend, Sum of Lights
    vegetation.py               green cover change, Dynamic World built-up gain
    thermal.py                  SUHI, heat vulnerability, cooling potential
    ghost.py                    activity index, expected-activity residual, typology
    growth_model.py             logistic regression, random forest, CA allocation, FoM, TOC
    validation.py               kappa, Mann-Whitney, elasticity, paired comparison
    zonal.py                    100 m -> 500 m aggregation, export
  pipeline.py                   orchestration; `python -m urbanintel.pipeline`
scripts/
  prefetch.py                   parallel download of all open data
  gee_export.py / .js           Earth Engine exports (Python and Code Editor)
  export_review3_layers.py      the extra Earth Engine layers used by the checks
  fetch_indian_data.py          SHRUG and Uttar Pradesh district GDP downloads
  run_growth_model.py           fit, validate, compare and project the growth models
  validate_typology.py          temporal hold-out test of the ghost / emerging split
  cross_checks.py               six built-up datasets, Open Buildings, Landsat vs MODIS
  validate_population.py        GHS-POP and WorldPop against the Census of India
  validate_economy.py           night light against the Economic Census and district GDP
  make_figures.py               14 figures + outputs/review3_results.json
  make_zone_cards.py            one evidence card per ghost-growth zone
  make_diagrams.py              architecture diagrams + progress charts -> docs/diagrams/
  make_presentation_r3.py       the Review 3 deck
  external_data.py              check / export / import / link the data bundle
  md_to_pdf.py                  Markdown report -> PDF
dashboard/app.py                Streamlit dashboard, 7 tabs
tests/test_core.py              41 tests
docs/                           reports, method documents, figures/, diagrams/, decks
run_review3.bat                 the whole chain in one command
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
- Zhou et al. 2019, *Remote Sensing* 11:48 — SUHI (Surface Urban Heat Island) definition and the urban/rural reference
- Ermida et al. 2020, *Remote Sensing* 12:1471 — Landsat LST (Land Surface Temperature) in Earth Engine

---

## Licence and data terms

Code: for academic use. Data: GHSL (CC BY 4.0), OpenStreetMap (ODbL — requires
attribution), Copernicus/Sentinel (open), Landsat/VIIRS (US public domain),
Dynamic World (CC BY 4.0), Google Open Buildings (CC BY 4.0).
