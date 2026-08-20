# Mentor Task — Sentinel and Landsat

> *"Before the next meeting (Friday afternoon), we need to extract both datasets
> (Sentinel and Landsat), and also find research papers on both related to our
> current project."*

Everything for that task is in this folder.

---

## 1. Were these already implemented?

**Yes — both were extracted before this task was set.** Evidence:

| Sensor | Official dataset identifier | Where it is used | Files already produced |
|---|---|---|---|
| Sentinel-2 | `COPERNICUS/S2_SR_HARMONIZED` | Green-cover loss, built-up cross-check, true colour | `ndvi_2018.tif`, `ndvi_2024.tif`, `ndbi_2018.tif`, `ndbi_2024.tif`, `truecolour_2024.tif`, plus higher-resolution versions |
| Landsat 8 and 9 | `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2` | Land surface temperature, urban heat island | `lst_2013.tif`, `lst_2024.tif` |

Both are declared in `config/varanasi.yaml`, implemented in
`src/urbanintel/data/gee.py`, and wired into the main pipeline as stage 3.

**What was missing, and is added here:** the ability to choose *any* date window
rather than the fixed epochs the pipeline uses, and a single place where both
sensors are pulled for the *same* window so they can be compared directly.

---

## 2. The extraction dashboard

```bash
python -m streamlit run mentor_task/app.py
```

Pick a date window in the sidebar, then:

1. **Check availability** — reports how many scenes exist in that window and on
   how many distinct days, *before* downloading anything. A window with only one
   or two distinct days produces a composite carrying that day's weather and
   haze rather than a seasonal median, so the dashboard warns when the count is
   low.
2. **Extract Sentinel-2** — true colour and NDVI (Normalized Difference
   Vegetation Index)
3. **Extract Landsat** — true colour and LST (Land Surface Temperature) in °C
4. **Preview** — renders each result and offers the GeoTIFF for download

Cloud limits and export scale are adjustable. Earth Engine caps a direct
download at about 50 MB, so if a fine scale over a long window exceeds that, the
scale steps down automatically rather than failing.

Command-line equivalent, if you prefer it:

```bash
python mentor_task/extract.py 2024-10-01 2025-03-31
```

### What it produced on a test run

Window **01 Oct 2024 – 31 Mar 2025**:

| Sensor | Scenes | Distinct days | Files |
|---|---|---|---|
| Sentinel-2 | 116 | 29 | `sentinel_truecolour` 19.8 MB, `sentinel_ndvi` 10.3 MB |
| Landsat 8 & 9 | 38 | 20 | `landsat_truecolour` 15.1 MB, `landsat_lst` 5.4 MB |

Value ranges were checked to confirm the processing is right, not merely that
files appeared:

| Output | Range | Expected |
|---|---|---|
| Landsat LST | 21.6 – 40.7 °C, median 27.4 °C | Correct for Varanasi in the cool season |
| Surface reflectance | 0.03 – 0.49 | Correct, reflectance is 0–1 |
| NDVI | −0.56 – 0.83, median 0.45 | Correct, index is −1 to +1 |

---

## 3. Research papers

Ten of the project's twenty reviewed papers carry substantial Sentinel or
Landsat content. They are copied into [`papers/`](papers/), and the reasoning —
including the mention counts that decided the split — is in
[`PAPERS.md`](PAPERS.md).

The strongest three for this task:

| Paper | Why |
|---|---|
| **Ermida et al. 2020** | The Landsat land-surface-temperature method our thermal layer follows, with RMSE 1.0–1.3 K against ground sensors |
| **Brown et al. 2022** | Dynamic World, built entirely on Sentinel-2 at 10 m |
| **Marconcini et al. 2020** | Fuses Landsat optical with Sentinel-1 radar; improves on GHSL by Kappa +0.23 for small settlements |

---

## 4. Files in this folder

```
mentor_task/
  README.md      this file
  PAPERS.md      the ten papers, why each was selected, mention counts
  app.py         the extraction dashboard
  extract.py     extraction functions, also runnable from the command line
  papers/        the ten Sentinel/Landsat papers (68 MB)
  output/        extracted GeoTIFFs land here
```

---

## 5. Two things worth raising at the meeting

**Sentinel-2 is 10 m but we export coarser.** Earth Engine's 50 MB direct-download
cap means a 10 m three-band image over this area (181 MB) will not come through.
The practical ceiling is 15–20 m. Reaching true 10 m needs a Drive export, which
is slower and needs manual copying — worth doing if the sharper imagery matters.

**Landsat 9 only starts in 2021.** Windows before that draw on Landsat 8 alone,
which halves the number of scenes available. The dashboard merges both
collections, so this shows up in the scene count rather than silently reducing
composite quality.
