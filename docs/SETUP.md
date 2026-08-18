# Setup

## 1. Environment

Use a virtual environment. Besides the usual isolation benefit, it avoids two
concrete problems seen on this project: a broken distribution in the user
site-packages that makes every `pip` call emit warnings, and `streamlit.exe`
landing in a `Scripts/` directory that is not on PATH.

**Windows**

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
```

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

The `-e .` install puts `urbanintel` on the import path (the project uses a
`src/` layout). Without it, every command needs a `PYTHONPATH=src` prefix.

> **Always run Streamlit as `python -m streamlit run ...`.** Bare `streamlit`
> depends on a `Scripts/` directory being on PATH, which it frequently is not
> on Windows — you get *"'streamlit' is not recognized as an internal or
> external command"*. The module form resolves through the interpreter and
> always works. `run_dashboard.bat` handles this.

Python 3.10+. The geospatial stack (`rasterio`, `geopandas`, `pyproj`) ships
manylinux/Windows wheels, so no GDAL system install is needed.

### Convenience launchers (Windows)

| Script | Does |
|---|---|
| `run_pipeline.bat [--no-gee]` | Downloads inputs if missing, then runs the pipeline |
| `run_dashboard.bat` | Starts the dashboard at <http://localhost:8501> |

Both use `.venv` directly, so no activation step is needed.

**Disk:** the open-path download is ~250 MB; Earth Engine exports add ~200 MB.
Rasters and outputs go to `data/` and `outputs/`. Both may be symlinks or
Windows junctions onto another drive:

```powershell
New-Item -ItemType Junction -Path .\data -Target D:\satellite-prediction-data
```

## 2. Open path — works immediately, no account

```bash
python scripts/prefetch.py
```

Downloads 8 GHSL (Global Human Settlement Layer) tiles (built-up surface + population × 4 epochs) and the OSM (OpenStreetMap)
POI/road extract for the AOI (Area of Interest).

The JRC server throttles to roughly 30 KB/s per connection, so the tiles are
fetched concurrently; expect **30–45 minutes** on a typical link. It is
resumable in the sense that completed files are cached — re-running only
fetches what is missing. Tune with `--workers N`.

If Overpass is busy (it frequently is), the client rotates across three public
endpoints and backs off. Failures are non-fatal: the pipeline records the gap
and continues without the POI (Point of Interest) layer.

```bash
python -m urbanintel.pipeline --no-gee
streamlit run dashboard/app.py
```

## 3. Earth Engine path — adds nightlights, NDVI (Normalized Difference Vegetation Index), LST (Land Surface Temperature)

Needed for green cover loss, urban heat island, and the nightlight axis of the
activity index.

### One-time

1. Sign up at <https://earthengine.google.com/signup/> (free for research).
2. Create or pick a Google Cloud project and enable the Earth Engine API.
3. Authenticate:

```bash
pip install earthengine-api
earthengine authenticate
```

That opens a browser for consent and writes a token locally. **Run it
yourself in a terminal** — it is interactive and cannot be automated.

### Export

```bash
python scripts/gee_export.py --project YOUR_GCP_PROJECT
```

Downloads directly for a city-sized AOI (Varanasi at 30 m is ~1300×1100 px,
a few MB per layer). Earth Engine caps direct downloads at 32 MB per band, so
for a larger AOI use batch export to Drive:

```bash
python scripts/gee_export.py --project YOUR_GCP_PROJECT --drive
```

Then copy the GeoTIFFs from Drive into `data/raw/gee/`.

Subsets: `--only nightlights ndvi lst`

### Code Editor alternative

If you would rather not install the Python client, paste
[`scripts/gee_export.js`](../scripts/gee_export.js) into
<https://code.earthengine.google.com>, press Run, and start the tasks from the
Tasks tab. It mirrors the Python module exactly — same assets, same seasonal
windows, same masking — so results are identical either way.

### Re-run

```bash
python -m urbanintel.pipeline
```

The pipeline picks up whatever is in `data/raw/gee/` and adds the layers that
depend on it.

## 4. Configuration

Everything tunable is in `config/varanasi.yaml`: AOI bounds, CRS, analysis
epochs, and every threshold. To analyse a different city, copy the file, change
`city` and `aoi.bbox`, set `crs.projected` to the right UTM zone, and:

```bash
python -m urbanintel.pipeline --config config/yourcity.yaml
```

GHSL tiles are computed from the bbox, so no tile IDs need editing.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `GHSL URL not reachable` | JRC server hiccup — re-run `prefetch.py`; cached files are skipped |
| Overpass `406` | Missing User-Agent. The client sets one; a proxy may be stripping it |
| Overpass `429` / `504` | Public endpoint under load. Wait and re-run, or set a different endpoint first in the config list |
| `EEException: not signed up` | Earth Engine account not yet approved, or wrong `--project` |
| `Total request size ... exceeds` | AOI too large for direct download — use `--drive` |
| `only N valid rural reference cells` | AOI has too little non-built land for a SUHI (Surface Urban Heat Island) baseline; widen `aoi.bbox` |
| Dashboard: "No pipeline output found" | Run the pipeline first; check `outputs/` |
| `'streamlit' is not recognized...` | The console script isn't on PATH. Use `python -m streamlit run dashboard/app.py`, or `run_dashboard.bat` |
| `No module named 'urbanintel'` | Run `pip install -e .`, or prefix with `PYTHONPATH=src` |
| `Ignoring invalid distribution ~orch` | A corrupted package in your *user* site-packages, unrelated to this project. Harmless, and a venv avoids it entirely |
| `use_container_width` deprecation | Streamlit < 1.49. Upgrade, or ignore — it is a warning, not an error |
