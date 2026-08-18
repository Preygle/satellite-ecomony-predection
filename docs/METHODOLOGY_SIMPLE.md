# Simplified Methodology — Review 1

**Satellite-Based Urban Growth and Economic Activity Intelligence System**

This is the short version, written for Review 1. It states what the system will
do, which datasets it uses, how we plan to build it, and what it produces. The
detailed version is in [`METHODOLOGY.md`](METHODOLOGY.md); abbreviations and
official dataset identifiers are in [`CONVENTIONS.md`](CONVENTIONS.md).

---

## 1. What the system does

A user enters the name of a city. The system collects satellite data for that
city, measures how much it has grown, and predicts how much more it will grow
in the next 5 and 10 years. The result is shown on a dashboard as maps and
numbers.

### The end goal, in one flow

```
  1. User searches for a city
              ↓
  2. System draws a circle around the city
     (default radius, or fitted automatically)
              ↓
  3. System downloads satellite data for that circle
     GHSL · VIIRS · Sentinel-2 · Landsat · OpenStreetMap
              ↓
  4. System computes indicators for every grid cell
     built-up area · vegetation · surface temperature
     nighttime light · shops and roads
              ↓
  5. Machine-learning model runs on those indicators
              ↓
  6. Dashboard shows:
     • how the city has grown so far
     • where it is predicted to grow in +5 and +10 years
```

**Why a circle.** A city has no single official boundary that is available
everywhere, and municipal limits often exclude the fastest-growing areas just
outside them. A circle around the city centre is simple, works for any city,
and can be widened by the user if the city is large. We will start with a
user-adjustable radius and add automatic fitting later, where the radius grows
outward until it stops finding built-up area.

---

## 2. Datasets we will use

Official dataset identifiers are written exactly as they appear in the data
provider's catalogue. Never shortened or renamed.

### Works without any account

| Official dataset | Provider | What it gives us |
|---|---|---|
| `GHS-BUILT-S R2023A` | European Commission Joint Research Centre | Built-up surface area per 100 m cell, every 5 years |
| `GHS-POP R2023A` | European Commission Joint Research Centre | Estimated population per 100 m cell |
| OpenStreetMap, via the Overpass API | OpenStreetMap contributors | Shops, clinics, offices and roads |
| OpenStreetMap, via the Nominatim API | OpenStreetMap contributors | City name search → centre coordinates |

### Needs Google Earth Engine

| Official dataset | Provider | What it gives us |
|---|---|---|
| `NOAA/VIIRS/DNB/ANNUAL_V21` | NOAA | Nighttime light radiance, 2013–2021 |
| `NOAA/VIIRS/DNB/ANNUAL_V22` | NOAA | Nighttime light radiance, 2022 onward |
| `COPERNICUS/S2_SR_HARMONIZED` | ESA / Copernicus | Sentinel-2 surface reflectance, used to compute vegetation and built-up indexes |
| `LANDSAT/LC08/C02/T1_L2` | USGS | Landsat 8 surface temperature, band `ST_B10` |
| `LANDSAT/LC09/C02/T1_L2` | USGS | Landsat 9 surface temperature, band `ST_B10` |
| `GOOGLE/DYNAMICWORLD/V1` | Google | Land-cover classes, used as a cross-check |
| `USGS/SRTMGL1_003` | NASA / USGS | Elevation, used to compute slope |

Two nighttime-light datasets are listed because the series is split across two
product versions. `ANNUAL_V21` holds 2013–2021 and `ANNUAL_V22` holds 2022
onward, so both are needed to build a full time series.

### Why each main dataset is used

**`GHS-BUILT-S R2023A`** is the backbone. It already tells us how much of every
100 m cell is built on, for several years going back to 1975, so we can measure
growth by subtracting one year from another. We use the 2010, 2015 and 2020
epochs because those are measured. The 2025 and 2030 epochs that the same
dataset provides are the GHSL model's own projections, not measurements, so we
do not treat them as data.

**`NOAA/VIIRS/DNB/ANNUAL_V21` and `_V22`** give nighttime light radiance. Bright
areas at night usually mean human and economic activity, so this acts as an
indirect indicator of whether new construction is actually being used. It is a
proxy, not a measurement of economic output.

**`COPERNICUS/S2_SR_HARMONIZED`** gives us two indexes. The first is
NDVI (Normalized Difference Vegetation Index), computed from its Near Infrared
and Red bands, which estimates how much vegetation a cell has. Comparing NDVI
between two years shows where green cover was lost to construction. The second
is NDBI (Normalized Difference Built-up Index), computed from its Shortwave
Infrared and Near Infrared bands, which highlights built-up surfaces and is
used as a cross-check on the built-up dataset.

**`LANDSAT/LC08/C02/T1_L2`** gives LST (Land Surface Temperature). Subtracting
the temperature of nearby rural land shows how much hotter the built-up area
is, which identifies urban heat island hotspots.

**OpenStreetMap** tells us what *kind* of activity is present — shops, clinics,
offices — which satellite light alone cannot distinguish.

---

## 3. How we plan to implement it

Six steps. Each one is a separate module, so they can be built and tested
independently.

### Step 1 — Find the city

The user types a city name. We send it to the Nominatim API, which returns the
latitude and longitude of the city centre. We draw a circle of a chosen radius
around that point and convert it to a rectangle, which becomes the area we
analyse.

### Step 2 — Download the data

For that rectangle we download `GHS-BUILT-S R2023A` and `GHS-POP R2023A`
directly over HTTP, and query OpenStreetMap through the Overpass API. The
satellite layers are requested from Google Earth Engine, which clips them to
the rectangle on its own servers so only a few megabytes are transferred
instead of whole scenes.

### Step 3 — Put everything on one grid

Every dataset arrives at a different resolution and in a different map
projection. We reproject all of them onto a single 100 m grid so that each
grid cell has one value from each dataset. Analysis is done at 100 m; results
are reported at 500 m, because a map with hundreds of thousands of cells is
unusable and would suggest more precision than the satellites provide.

### Step 4 — Compute the indicators

For each cell we compute:

- built-up area, and how much it changed between years
- NDVI, and how much vegetation was lost
- land surface temperature, compared to nearby rural land
- nighttime light radiance, and whether it is rising or flat
- density of shops and offices, and density of roads

### Step 5 — Train the machine-learning model

We use **Logistic Regression**, a machine-learning model that estimates the
probability of an outcome from several input variables. Here the outcome is
"did this cell become built-up?"

The inputs, called drivers, are:

| Driver | Reason |
|---|---|
| Distance from the city centre | Growth usually happens closer to the centre |
| Distance from the existing built-up edge | New building tends to appear next to old building |
| Current built-up fraction | Partly built cells fill in further |
| Road density | Roads come before buildings |
| Population | People attract construction |
| Slope | Steep land is harder to build on |

Training uses two past years the model can learn from — for example, which
cells changed between 2010 and 2015. The model learns which combination of
drivers made a cell likely to be built on.

We then add a **cellular automaton**, a simple rule-based step where each cell
also looks at its neighbours. This stops the model from scattering predicted
growth randomly, and makes new development appear in connected patches, which
is how cities actually grow.

**Why not deep learning.** A CNN (Convolutional Neural Network) could be used
here, but it needs a large labelled training set and a GPU, and published
studies report that it performs about as well as the simpler approach for this
task. Logistic Regression also gives us readable coefficients, so we can show
*why* the model expects growth in a location. We therefore use the simpler
model, and treat deep learning as a possible later upgrade.

### Step 6 — Predict and display

We estimate how much new built-up area to expect over the next 5 and 10 years
from the city's own past growth rate, then let the model place that amount on
the most suitable cells. The dashboard shows the results as maps and numbers.

### How we check the model is not guessing

We train the model on one period and test it on a later period it has never
seen. We then compare its score against a model that places the same amount of
growth completely at random. If our model is not clearly better than random, it
is not useful. We report both numbers side by side rather than only our own.

---

## 4. What output we expect

### Numbers

| Output | Example form |
|---|---|
| Built-up area for each year | 72.48 km² in 2010, 89.73 km² in 2020 |
| Growth rate | +23.8% over ten years |
| Population growth for comparison | +10.3% over the same period |
| Land consumed per person | Built-up area grew 2.3× faster than population |
| Green cover lost to construction | in km² |
| Urban heat island intensity | in °C above nearby rural land |
| **Predicted growth, +5 and +10 years** | in km² of new urban area |

### Maps

- Built-up area now, and how it changed between years
- Vegetation, and where it was lost to construction
- Surface temperature and heat hotspots
- Nighttime light activity
- **Predicted new urban area for +5 and +10 years**

### Files

A grid file in CSV and GeoJSON format holding every indicator per cell, so the
results can be opened in any GIS software, and a summary file recording which
datasets were used.

### An important label on the forecast

The 5-year and 10-year maps are a **prediction**, not a measurement. They show
where growth is likely if the city keeps growing as it has been. They are not a
statement about what will definitely be built, and the dashboard says so.

---

## 5. Tools

| Tool | Use |
|---|---|
| Python | Main language |
| NumPy, GeoPandas, rasterio | Handling grids and map data |
| scikit-learn | Logistic Regression |
| Google Earth Engine | Satellite data access and cloud processing |
| Streamlit | Dashboard |

---

## 6. What we know will be difficult

Stated now so that it is planned for rather than discovered later.

| Issue | How we will handle it |
|---|---|
| Google Earth Engine needs a login, but a public dashboard user will not have one | The app will hold its own Earth Engine account. The parts using `GHS-BUILT-S R2023A` and OpenStreetMap will still run without any account, so the system always produces a result |
| Processing a new city takes minutes, not seconds | Show progress in the dashboard, and store results so the same city is not recomputed |
| One circle size does not suit every city | Let the user change the radius, and add automatic fitting later |
| Satellite data cannot see inside buildings | We report at neighbourhood level, never per building, and describe the output as a screening tool |
| The forecast can be wrong | Always show the accuracy score from the held-out test, and compare against a random baseline |

---

## 7. Scope

| Stage | What is covered |
|---|---|
| **Now (Review 1 plan)** | One city, Varanasi, defined in a configuration file. All six steps working end to end |
| **Next** | Replace the configuration file with a city search box and an adjustable circle |
| **Later** | Automatic circle fitting, saved results for previously searched cities, and comparison between cities |

The processing steps do not change when the city changes. Only the centre point
and radius change, which is why the same pipeline can be pointed at any city.
