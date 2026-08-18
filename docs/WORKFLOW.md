# Workflow

**Satellite-Based Urban Growth and Economic Activity Intelligence System**

What happens, in what order, from the moment a city is chosen to the moment
results appear on the dashboard. The structure of the system is described
separately in [`DESIGN.md`](DESIGN.md); abbreviations and official dataset
identifiers are in [`CONVENTIONS.md`](CONVENTIONS.md).

---

## 1. Two workflows

There are two ways to look at this system, and both matter.

| | Who follows it | Covered in |
|---|---|---|
| **User workflow** | Someone who wants to know about a city | §2 |
| **System workflow** | The pipeline, running inside | §3 |

---

## 2. User workflow

This is the end goal — what a user does.

```
   ┌──────────────────────────────────────────────┐
   │  1.  Type a city name                        │
   │      "Varanasi"                              │
   └──────────────────────┬───────────────────────┘
                          ↓
   ┌──────────────────────────────────────────────┐
   │  2.  Confirm the area                        │
   │      A circle is drawn around the city.      │
   │      The user can widen or narrow it.        │
   └──────────────────────┬───────────────────────┘
                          ↓
   ┌──────────────────────────────────────────────┐
   │  3.  Wait while the system works             │
   │      Progress is shown stage by stage.       │
   │      Takes minutes, not seconds.             │
   └──────────────────────┬───────────────────────┘
                          ↓
   ┌──────────────────────────────────────────────┐
   │  4.  Read the results                        │
   │      • how the city grew so far              │
   │      • where growth is predicted, +5 / +10   │
   │      • maps, numbers, downloadable files     │
   └──────────────────────────────────────────────┘
```

**Where this stands today.** Steps 3 and 4 work now. Steps 1 and 2 are
currently done by editing a configuration file (`config/varanasi.yaml`) instead
of typing a name, because the study city is fixed for this stage of the
project. Replacing that file with a search box is the next piece of work, and
it does not change anything that follows it — only the centre point and radius
change.

---

## 3. System workflow

Seven stages, run in a fixed order. Each stage adds its results to a shared
object that the next stage reads from.

```
  config/varanasi.yaml
         ↓
  ┌──────────────┐
  │ 1. builtup   │  GHS-BUILT-S R2023A, GHS-POP R2023A
  ├──────────────┤
  │ 2. osm       │  OpenStreetMap, via the Overpass API
  ├──────────────┤
  │ 3. gee       │  VIIRS, Sentinel-2, Landsat, Dynamic World
  ├──────────────┤
  │ 4. vegetation│  needs stage 3
  ├──────────────┤
  │ 5. thermal   │  needs stage 3
  ├──────────────┤
  │ 6. ghost     │  needs stages 1, 2 and 3
  ├──────────────┤
  │ 7. export    │  writes everything to disk
  └──────┬───────┘
         ↓
  outputs/  →  dashboard
```

Run with:

```bash
python -m urbanintel.pipeline
```

### What each stage does

| # | Stage | Reads | Produces |
|---|---|---|---|
| 1 | `builtup` | `GHS-BUILT-S R2023A`, `GHS-POP R2023A` | Built-up area per year, change between years, urban form, population |
| 2 | `osm` | OpenStreetMap | Density of shops and offices, density of roads |
| 3 | `gee` | `NOAA/VIIRS/DNB/ANNUAL_V21` and `_V22`, `COPERNICUS/S2_SR_HARMONIZED`, `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2` | Nighttime light radiance and its trend, NDVI, land surface temperature |
| 4 | `vegetation` | NDVI from stage 3, built-up change from stage 1 | Green cover lost, and how much of it became built-up |
| 5 | `thermal` | Land surface temperature from stage 3 | Heat island intensity, hotspots, heat vulnerability |
| 6 | `ghost` | Nighttime light, shops, population, built-up | Activity index, expected-activity residual, six-class growth typology |
| 7 | `export` | Everything above | 500 m grid, raster files, summary file |

### Stage by stage, in plain terms

**Stage 1 — `builtup`.** Downloads the built-up surface and population grids for
the chosen area, puts them on a single 100 m grid, and subtracts one year from
another to find where new building appeared. Each newly built cell is then
labelled infill, edge expansion or leapfrog depending on whether it sits inside
the existing city, on its edge, or detached from it.

**Stage 2 — `osm`.** Asks OpenStreetMap for every shop, clinic, office and road
inside the area, groups the places by sector, and turns them into a density per
cell.

**Stage 3 — `gee`.** Asks Google Earth Engine for the satellite layers —
nighttime light radiance from VIIRS (Visible Infrared Imaging Radiometer Suite),
plus Sentinel-2 and Landsat imagery. Earth Engine cuts each layer to the area on
its own servers, so only a few megabytes come back instead of whole satellite
scenes. This is the only stage that needs an account.

**Stage 4 — `vegetation`.** Compares the vegetation index
NDVI (Normalized Difference Vegetation Index) between two years to find where
vegetation was lost, then keeps only the loss that happened where building also
appeared. This matters because most vegetation change in Varanasi is the
farming calendar, not construction.

**Stage 5 — `thermal`.** Takes land surface temperature and subtracts the
temperature of rural land in the same image, with water left out. Water is
excluded because the Ganga would otherwise make the rural reference look cold
and exaggerate the heat island across the whole city.

**Stage 6 — `ghost`.** Combines nighttime light radiance, shop density and
population into one activity score, learns what activity level is normal for
each level of building *in this city*, and flags cells that fall far below their
own city's normal level and were built recently.

**Stage 7 — `export`.** Combines the 100 m results into a 500 m reporting grid
and writes everything to `outputs/`.

---

## 4. Prediction workflow

The forecast runs as a separate step after the main pipeline, because it needs
the pipeline's output as its input.

```bash
python scripts/run_growth_model.py
```

```
  1. Build the drivers
     distance from centre · distance from the built-up edge
     built-up fraction · road density · population · slope
                    ↓
  2. Train on an early period          e.g. 2010 → 2015
     Logistic Regression learns which cells became built-up
                    ↓
  3. Test on a later period            e.g. 2015 → 2020
     The model has never seen this period
                    ↓
  4. Compare against random allocation
     If it is not clearly better than random, it is not useful
                    ↓
  5. Estimate how much growth to expect in +5 and +10 years
     from the city's own past growth rate
                    ↓
  6. Place that growth on the most suitable cells,
     with each cell also looking at its neighbours
                    ↓
  7. Write the predicted growth maps
```

**Important.** Steps 5 to 7 produce a **prediction**, not a measurement. The
maps show where growth is likely if the city keeps growing as it has been.

---

## 5. What happens when a stage cannot run

A missing dataset does not stop the pipeline. The stage records why it could not
run, and the pipeline continues.

```
  stage runs
      ├── success  → results added, next stage starts
      └── failure  → reason recorded in `skipped`, next stage starts
```

The reason is written into the summary file and shown on the dashboard, so a
missing layer is always visible rather than silently absent.

**Why it is built this way.** Google Earth Engine needs an account, and the
public data sources sometimes rate-limit or time out. If any one of those
stopped the whole run, the system would produce nothing at all on a bad day.
Instead the parts that use `GHS-BUILT-S R2023A` and OpenStreetMap always work,
so there is always a result.

To skip Earth Engine deliberately:

```bash
python -m urbanintel.pipeline --no-gee
```

---

## 6. Development workflow

How the team builds and checks the system.

```
  1. Set up once
     python -m venv .venv
     pip install -r requirements.txt && pip install -e .

  2. Download the open data once
     python scripts/prefetch.py

  3. Connect Earth Engine once
     earthengine authenticate
     python scripts/gee_export.py --project YOUR_PROJECT

  4. Change something
     edit code or config/varanasi.yaml

  5. Run the tests
     python tests/test_core.py

  6. Run the pipeline
     python -m urbanintel.pipeline

  7. Look at the result
     run_dashboard.bat
```

Steps 4 to 7 repeat. Steps 1 to 3 are done once.

**Why tests come before the pipeline.** The pipeline takes minutes and produces
numbers that look plausible even when they are wrong. The tests run in seconds
and check things with known answers — that areas survive being combined into
larger cells, that a known trend is recovered correctly, and that the
ghost-growth screen finds a planted answer in made-up data.

---

## 7. How long each part takes

| Step | Time | How often |
|---|---|---|
| Downloading the open data | 30–45 minutes | Once |
| Connecting Earth Engine | A few minutes | Once |
| Exporting satellite layers | About 5 minutes | Once per city |
| Running the pipeline | 2–3 minutes | Every change |
| Running the tests | A few seconds | Every change |
| Running the prediction model | Under a minute | When needed |

Downloads are cached, so re-running only fetches what is missing. This is why
the pipeline is fast to re-run even though the first run is slow.
