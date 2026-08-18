# System Design

**Satellite-Based Urban Growth and Economic Activity Intelligence System**

A basic overview of how the system is put together and why. The order in which
things run is described separately in [`WORKFLOW.md`](WORKFLOW.md); abbreviations
and official dataset identifiers are in [`CONVENTIONS.md`](CONVENTIONS.md).

This is an overview, not a specification. It gives the layers, the modules and
the reasons behind the main choices, and stops there.

---

## 1. Architecture at a glance

Four layers. Data flows downward. Each layer only talks to the one below it.

```
┌─────────────────────────────────────────────────────────┐
│  PRESENTATION                                           │
│  Dashboard — maps, numbers, downloadable files          │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  ANALYSIS                                               │
│  Built-up change · activity · vegetation · heat          │
│  Ghost growth · growth prediction                       │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  ACQUISITION                                            │
│                                                         │
│   OPEN PATH                    EARTH ENGINE PATH        │
│   no account needed            one-time login           │
│   ├ GHS-BUILT-S R2023A         ├ VIIRS nighttime light  │
│   ├ GHS-POP R2023A             ├ Sentinel-2             │
│   └ OpenStreetMap              ├ Landsat 8 and 9        │
│                                └ Dynamic World          │
└───────────────────────────┬─────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│  CONFIGURATION                                          │
│  City, area, grid size, years, thresholds, data sources │
└─────────────────────────────────────────────────────────┘
```

### What each layer is for

**Configuration** holds everything that changes between cities: where the city
is, how big the area is, which years to compare, and every threshold. Nothing
below it is hard-coded, which is why pointing the system at a different city
means writing a new configuration file rather than changing code.

**Acquisition** fetches data and puts it on a common grid. The Earth Engine path
supplies nighttime light radiance from
VIIRS (Visible Infrared Imaging Radiometer Suite), together with Sentinel-2 and
Landsat imagery. The split into two paths is deliberate — see §5.

**Analysis** turns raw data into findings. Each kind of analysis is a separate
module so it can be built and tested on its own.

**Presentation** shows the results. It reads only the files that Analysis wrote,
so it never needs the internet or an Earth Engine account.

---

## 2. Module map

| Module | Responsibility |
|---|---|
| `config.py` | Reads the configuration file |
| `aoi.py` | Turns the area into two matching grids, one fine and one coarse |
| **Acquisition** | |
| `data/ghsl.py` | `GHS-BUILT-S R2023A` and `GHS-POP R2023A` |
| `data/osm.py` | OpenStreetMap places and roads |
| `data/gee.py` | All Google Earth Engine layers |
| `data/worldpop.py` | Optional second population source, used as a check |
| `data/download.py` | Downloading files, resuming, unzipping |
| **Analysis** | |
| `analysis/builtup.py` | Built-up change, urban form, growth hotspots |
| `analysis/nightlights.py` | Activity trend, total light, normalising by built-up area |
| `analysis/vegetation.py` | Green cover change and conversion to built-up |
| `analysis/thermal.py` | Heat island intensity and vulnerability |
| `analysis/ghost.py` | Activity index, expected activity, growth typology |
| `analysis/growth_model.py` | Predicting future growth |
| `analysis/zonal.py` | Combining 100 m results into the 500 m reporting grid |
| **Orchestration and output** | |
| `pipeline.py` | Runs the stages in order |
| `dashboard/app.py` | The dashboard |

Two rules keep this tidy:

- Acquisition modules never analyse. They fetch and reproject, nothing else.
- Analysis modules never download. They receive grids already prepared.

This means an analysis module can be tested with made-up data, without any
network access — which is how the test suite runs in seconds.

---

## 3. How data moves between modules

Each stage of the pipeline adds to one shared object that is passed along.

| It holds | What that means |
|---|---|
| `layers` | The grids themselves, one per indicator |
| `stats` | The summary numbers for the report |
| `provenance` | Which dataset each layer came from |
| `skipped` | Any layer that could not be produced, and why |

`skipped` is the important one. A layer that fails is recorded rather than
dropped, so a missing result is always visible in the output and on the
dashboard instead of quietly reading as zero.

---

## 4. The data model: two grids

Everything in the system is a grid of square cells covering the study area.
There are two of them, and they line up exactly.

| Grid | Cell size | Used for |
|---|---|---|
| Fine | 100 m | All analysis |
| Coarse | 500 m | All reporting and display |

Exactly 25 fine cells fit inside one coarse cell.

**Why two.** Analysis is done at 100 m because that is the resolution of
`GHS-BUILT-S R2023A`, and detecting change works better at the finest
resolution available. Reporting is done at 500 m because a map of the study
area at 100 m has more than a hundred thousand cells, which is unusable in a
browser and would suggest more precision than the satellites actually provide —
the nighttime light sensor sees about 460 m at best.

Both grids are created together from the same starting corner. If they were
created separately, each would round outward to its own cell size, the two
would not line up, and every combined result would be quietly shifted.

---

## 5. Key design decisions

The six choices that shaped the system, and the reason for each.

| Decision | Reason |
|---|---|
| **Two acquisition paths** — open and Earth Engine | Most projects of this kind stall at "first, get an Earth Engine account". Splitting the sources means the core result is produced before anyone logs in, and the satellite layers are added when available |
| **Everything driven by a configuration file** | A different city should be a new configuration file, not a code change. This is what makes the "search for any city" goal reachable |
| **Two matching grids instead of one** | Keeps change detection sharp while keeping the map usable and the claims honest |
| **A failed stage records itself and the run continues** | Public data sources rate-limit and time out. A run that produces most of the answer is far more useful than one that produces nothing |
| **Learn the normal activity level, rather than set a threshold** | A fixed brightness cut-off has to be re-tuned for every city. Learning the city's own normal level means the method moves to a new city unchanged |
| **Logistic Regression rather than deep learning for prediction** | It needs no GPU and no labelled training set, published work reports similar accuracy for this task, and its coefficients can be read and explained |

---

## 6. Technology choices

| Layer | Technology | Why |
|---|---|---|
| Language | Python | Standard for geospatial and machine-learning work |
| Grid data | NumPy, rasterio | Reading, writing and reprojecting raster files |
| Map shapes | GeoPandas, Shapely | Handling the reporting grid and boundaries |
| Machine learning | scikit-learn | Logistic Regression, and the accuracy measures |
| Satellite processing | Google Earth Engine | Processes imagery on Google's servers, so only small results are downloaded |
| Dashboard | Streamlit | A working web interface from Python alone, with no separate front-end to build |
| Configuration | YAML | Readable by a person, editable without touching code |

---

## 7. What we deliberately kept simple

Stated so that these read as choices rather than gaps.

| Not done | Why not, for now |
|---|---|
| No database | The output is a few files. A database would add setup with nothing gained |
| No login or user accounts | The system answers a question about a city. It stores nothing about the person asking |
| No live or automatic updating | The satellite datasets are annual. There is nothing to refresh more often |
| No separate web front end | Streamlit is enough for the audience, which is a planner reading maps and numbers |
| No cloud deployment yet | It runs on a normal laptop. Deployment matters once the city search box exists |

---

## 8. What the design still has to solve

Honest list of the parts that are planned rather than built.

| Open question | Current thinking |
|---|---|
| A dashboard user has no Earth Engine account | The application will hold its own account. The open path still works without one, so there is always a result |
| Processing a new city takes minutes | Show progress, and save results so the same city is not computed twice |
| One circle size will not suit every city | Let the user adjust the radius, and add automatic fitting later |
| Results for many cities will need storing | A simple folder per city is likely enough before a database is worth adding |
