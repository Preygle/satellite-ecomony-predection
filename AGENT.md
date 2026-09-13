# AGENT.md — working on this repository

A briefing for any coding agent (or new team member) picking this project up.
It covers what the project is, the rules that are not negotiable, how the code
and data are laid out, how to run and verify everything, how the Review 3 work
was done, and the traps that have already cost time.

Read this file first, then [`CLAUDE.md`](CLAUDE.md) (writing rules), then
[`docs/REVIEW3_REPORT.md`](docs/REVIEW3_REPORT.md) (current state and numbers).

---

## 1. What this project is

**Satellite-Based Urban Growth and Economic Activity Intelligence System** — a
B.Tech capstone (BCSE497J Project I, VIT SCOPE, Fall 2026–27) studying
**Varanasi, Uttar Pradesh**.

| | |
|---|---|
| Team | Mayank (23BCE1753), Achal Pramod Tripathi (23BCE1734), Mohammad Owais (23BCE1746) |
| Guide | Joshan |
| Repository | `github.com/Preygle/satellite-ecomony-predection`, branch `main` |
| Reviews | R1 9–11 Jul · R2 19 Aug · **R3 16 Sep 2026** · R4 12–16 Oct · R5 21 Oct — rubric in `PROJECT_GUIDELINES.md` |

It measures urban growth from satellite data, flags **ghost growth** (new
development with little activity), measures green-cover loss and surface heat,
and predicts where the city grows next. It is a screening tool, not an
occupancy census.

---

## 2. Rules that are not negotiable

1. **Writing rules — `CLAUDE.md`.** Official dataset identifiers are written
   exactly (`NOAA/VIIRS/DNB/ANNUAL_V22`, never "VIIRS dataset"); every acronym is
   expanded at first use; proxies are called proxies; the tone is a capable
   final-year B.Tech student, not a journal paper and not marketing. Every
   document and every user-facing string follows it.
2. **Epoch discipline.** GHS-BUILT-S / GHS-POP R2023A epochs **after 2020 are
   the GHSL model's projections**, not observations. Analysis uses 2010, 2015
   and 2020 only. GHSL 2025 may appear only under a `_projected` name, labelled
   as a projection. `Config.check_epochs()` enforces this and is unit-tested.
   Using 2025 as "current" was the worst defect found for Review 3 — do not
   reintroduce it.
3. **Never claim a dataset gives what it does not.** Night-time light is a
   proxy for activity, not a measurement of GDP. Predictions are labelled
   predictions. If a number is derived, say how.
4. **Do not overwrite user-edited files.** `docs/Review_Presentation_v2.pptx`
   carries manual edits by the team; regenerate decks under a new name. The
   Review 2 documents (`docs/REVIEW2_*.md`, `PHASE1_REPORT.md`,
   `PHASE2_REPORT.md`) are the record of what was presented — they carry a
   correction notice at the top and are otherwise left as they were.
5. **Keep the AI acknowledgement.** `PROJECT_GUIDELINES.md` §2 requires
   significant AI use to be acknowledged. It lives in `CONTRIBUTIONS.md` and in
   the report (§10). Do not remove it, even if asked.
6. **Do not rewrite published git history.** Local, unpushed commits may be
   reorganised; anything on `origin/main` may not.
7. **Data ethics.** Do not scrape property portals (99acres, MagicBricks). Use
   only data with a clear licence; cite SHRUG as Asher et al. (2021).
8. **The user's email is for identification only** — never send it to an
   external service.

---

## 3. Repository map

```
config/varanasi.yaml          study area, epochs, thresholds, sources — the single tracked config
config/local.yaml             (gitignored) this machine's data paths — see §5
src/urbanintel/
  config.py                   config loading, epoch checks, path resolution + local overrides
  aoi.py                      AOI, 100 m analysis frame and 500 m reporting frame (exactly nested)
  pipeline.py                 the 7-stage pipeline:  python -m urbanintel.pipeline
  data/
    ghsl.py                   GHS-BUILT-S / GHS-POP bulk tiles, density-preserving reprojection
    osm.py                    OpenStreetMap POIs and roads via Overpass
    gee.py                    every Earth Engine layer, cloud masks, composite-depth check
    shrug.py                  SHRUG census / economic census / polygons (Indian data)
    worldpop.py, download.py  bulk WorldPop (unused on the main path), resumable HTTP
  analysis/
    builtup.py                change detection, urban form (infill / edge / leapfrog)
    nightlights.py            trends, relative-to-city trend, Sum of Lights
    ghost.py                  activity index, expected-activity residual, typology, rising rules
    thermal.py                surface heat island, vulnerability, cooling potential
    vegetation.py             NDVI change, built-up gain from Dynamic World
    growth_model.py           logistic regression, random forest, CA allocation, FoM, TOC
    validation.py             kappa, Mann-Whitney, log-log elasticity, paired comparison
    zonal.py                  100 m -> 500 m aggregation
scripts/                      one job per script — see §6
dashboard/app.py              Streamlit dashboard (7 tabs):  run_dashboard.bat
tests/test_core.py            41 tests:  python tests/test_core.py
docs/                         reports, method docs, figures/, diagrams/ (see DIAGRAMS.md), decks, PDFs
dataset_viewer/               static Leaflet viewer of the raw layers (Review 2 demo)
mentor_task/                  Sentinel/Landsat date-window extraction app + papers list
papers/                       reviewed PDFs (gitignored; held in a GitHub release)
run_pipeline.bat              pipeline only
run_review3.bat               EVERYTHING, end to end — see §6
```

Outputs: `outputs/` (summary, grid, validation JSONs, `review3_results.json`)
and `data/processed/rasters/` (every 100 m layer as GeoTIFF). Both gitignored.

---

## 4. The analysis, in one pass

1. **Built-up** — GHSL 2010/2015/2020 → change, urban extent (cells ≥ 20 %
   built), urban form, growth hotspots.
2. **OpenStreetMap** — POI density by sector, class-weighted road density.
3. **Earth Engine** — VIIRS 2013–2024 (`ANNUAL_V21` to 2021, `ANNUAL_V22`
   after), Sentinel-2 NDVI (Oct–Mar 2018-19, 2024-25), Dynamic World 2018/2024,
   Landsat 8+9 LST (Mar–May 2013, 2024).
4. **Vegetation** — NDVI loss intersected with Dynamic World built-up gain over
   the *same* years.
5. **Heat** — LST minus a rural reference (under 2 % built, not water, not
   recently built); mean over urban cells; 2013→2024 change on intensity.
6. **Ghost typology** — activity index (lights 2022–24 mean, POIs, population)
   against the city's own expected activity for that built-up intensity; new
   underperforming cells are *emerging* if their light rises **significantly
   faster than the established city**, else *ghost growth*; zones by density.
7. **Export** — 500 m grid GeoJSON/CSV, rasters, `varanasi_summary.json`.

Then, outside the pipeline: `run_growth_model.py` (train 2010–15, test
2015–20, LR vs RF, projections 2025/2030) and the four validation scripts.

---

## 5. Data — what git does not carry

About **1.4 GB** is gitignored: `data/raw/{ghsl,gee,osm,india}`,
`data/processed/`, `outputs/`. On the original machine `outputs/` is a symlink
to `D:\satellite-prediction-outputs`.

| Need | Command |
|---|---|
| See what is present and where | `python scripts/external_data.py check` |
| Make a pendrive bundle (780 MB, or `--full` 1.4 GB) | `python scripts/external_data.py export E:/urbanintel-data` |
| Copy a bundle into this clone | `python scripts/external_data.py import E:/urbanintel-data` |
| Use a bundle where it sits | `python scripts/external_data.py link ../urbanintel-data` |
| Re-download from scratch | `prefetch.py` (open data) · `export_review3_layers.py` (Earth Engine, needs login) · `fetch_indian_data.py` |

Path resolution, highest priority first: `URBANINTEL_DATA_RAW` /
`URBANINTEL_DATA_INTERIM` / `URBANINTEL_DATA_PROCESSED` / `URBANINTEL_OUTPUTS`
environment variables → `config/local.yaml` (gitignored) →
`config/varanasi.yaml`. **Never put a machine-specific path in
`config/varanasi.yaml`** — it would conflict on every teammate's merge. Details:
[`docs/DATA_TRANSFER.md`](docs/DATA_TRANSFER.md).

Earth Engine project: `satellite-505815` (in the config). Earth Engine direct
downloads cap at ~50 MB; the export scripts step down the scale automatically.

---

## 6. Running and verifying

| Step | Command | Time on cached data |
|---|---|---|
| Tests | `python tests/test_core.py` | ~3 s |
| Pipeline | `python -m urbanintel.pipeline` | ~60 s |
| Growth models | `python scripts/run_growth_model.py` | ~25 s |
| Typology hold-out test | `python scripts/validate_typology.py` | ~3 s |
| Satellite cross-checks | `python scripts/cross_checks.py` | ~3 s |
| Population vs Census | `python scripts/validate_population.py` | ~35 s (Earth Engine) |
| Lights vs economy | `python scripts/validate_economy.py` | ~40 s (Earth Engine) |
| Figures + results pack | `python scripts/make_figures.py` | ~8 s |
| Zone evidence cards | `python scripts/make_zone_cards.py` | ~15 s |
| Architecture diagrams + progress charts | `python scripts/make_diagrams.py` | ~17 s |
| Panel deck, no code on slides | `python scripts/make_diagrams.py --clean` then `python scripts/make_presentation_panel.py` | ~20 s |
| **All of the above** | **`run_review3.bat`** | **about 3 min 40 s** |
| Report PDF | `python scripts/md_to_pdf.py docs/REVIEW3_REPORT.md` | ~20 s |
| Review 3 deck | `python scripts/make_presentation_r3.py` | ~5 s |
| Dashboard | `run_dashboard.bat` | — |

Use the project venv: `.venv/Scripts/python.exe`. The order matters: figures
read the JSONs the pipeline, growth model and validations write.

**Where every number comes from.** `outputs/review3_results.json` is written by
`make_figures.py` and holds every figure the report and deck quote. When a
number changes, regenerate — do not hand-edit numbers into documents without
re-running.

**Verifying the dashboard headlessly** (no browser):

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("dashboard/app.py", default_timeout=240); at.run()
assert not at.exception
```

---

## 7. How the Review 3 work was done — and how to continue it

The method that worked, in order:

1. **Audit before building.** Three code audits plus live Earth Engine checks
   produced 15 numbered defects (D1–D15), each with file, line, consequence
   and fix. They are the corrections log in `docs/REVIEW3_REPORT.md` §6.
2. **Plan against the rubric.** Work packages WP1–WP10 in three streams
   (A pipeline/results/dashboard, B validation, C models) so each team member
   owns something attributable. Ownership: `CONTRIBUTIONS.md`.
3. **Fix correctness first**, then re-run everything — every downstream
   number moved when the epoch fix landed.
4. **Every fix gets a test** named after the defect it prevents (see the
   "Review 3 fixes" block in `tests/test_core.py`).
5. **Validate with independent data** rather than trusting the method: a
   temporal hold-out (classify on 2013–2020 light, check 2021–2024), six
   built-up datasets with Cohen's kappa, Landsat vs MODIS, Census 2001/2011,
   2013 Economic Census, UP district GDP.
6. **Report results that go against us.** The heat result reversed (no daytime
   heat island), the ghost/emerging split weakened (95 % → 74 %), lights proved
   weak at village scale. These are stated plainly — the panel rewards it.
7. **Look at every figure** before shipping it (overlapping titles and labels
   were caught this way), and run the dashboard headlessly.
8. **Keep documents honest about history**: correction notices on old
   documents, a corrections log with before/after numbers, never a silent edit.

**Still open (Review 4):** city search for any city (Nominatim → circle →
`JRC/GHSL/P2023A/GHS_BUILT_S` → automatic UTM); image labels for a sample of
flagged cells to measure the ghost flag's precision; a WorldPop-based activity
index; ward-level reporting; VDA Master Plan 2031 and Bhuvan land-use overlays;
tuning the growth model's neighbourhood weight; a paper submission. The team
still has to fill the Review 2 comments table (report §7) and the owners in
`CONTRIBUTIONS.md`.

---

## 8. Known results you should not "fix"

These look like bugs and are not:

| Observation | Why it is real |
|---|---|
| Mean urban heat-island intensity is **negative** (−1.66 °C) | Pre-monsoon daytime: bare farmland is hotter than the city. MODIS agrees. |
| Random forest has lower held-out AUC (0.83) but higher Figure of Merit (0.103) than logistic regression (0.91 / 0.069) | The forest ranks the top cells better, which is what allocation uses; the TOC curve shows it. |
| Dynamic World says 531 km² is built; GHSL says 154 km² | Dynamic World's built class spills into villages and dry fields here; it is used only for water and direction of change. |
| GHS-POP is +63 % inside the Municipal Corporation | It spreads population by built-up volume; WorldPop is closer to the Census. |
| Slope has a median of 1.95° on a flat plain | SRTM noise; its model importance is near zero and the report says so. |

---

## 9. Environment traps (Windows 11, Git Bash + PowerShell)

- **Batch files:** `cmd /c run_x.bat` from Git Bash silently opens an
  interactive cmd and runs nothing (Git Bash rewrites `/c`). Run `.bat` files
  from PowerShell: `& cmd /c "C:\...\run_review3.bat"`, with an absolute path.
- **Heredocs:** a quoted heredoc through the Bash tool collapses `\\n` to `\n`
  and `\\u` to `\u` — Python written that way breaks, and Windows paths corrupt.
  Write such files with a file-writing tool, or avoid backslashes.
- **Console encoding:** cp1252 — printing `°`, `≥`, `ρ`, `²` crashes a script.
  Prefix runs with `PYTHONIOENCODING=utf-8`.
- **Earth Engine uint8 exports** record 0 as no-data. Class masks must be read
  with `gee.to_frame(..., nodata=None)`, or the "not this class" pixels vanish
  (WorldCover came out as 480 km² instead of 191 km² before this was caught).
- **Population sums** must be taken on each dataset's native grid
  (`reduceRegions` with the image's own projection) — sampling per-pixel counts
  on another grid biases totals by about a fifth.
- **Pushing to GitHub:** the connection resets on transfers of a few MB.
  Commit binaries in small groups and push after each; this repo has
  `http.postBuffer=524288000` and `http.version=HTTP/1.1` set locally.
- **`gauntlet-loop/`** is an unrelated nested git repository (gitignored).
  Leave it alone.

---

## 10. Commit conventions

Conventional prefixes (`feat`, `fix`, `docs`, `chore`) with a scope, a body
that says *why*, and — for work done with Claude — the attribution trailer:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

Team members commit their own work packages from their own git accounts.
