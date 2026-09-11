# Moving the data between machines

The repository carries the code, the documents and the figures. It does not
carry the data: the satellite downloads, the Indian statistical archives and
the pipeline's outputs come to about **1.4 GB**, which is more than a git
repository should hold and more than GitHub accepts comfortably. `.gitignore`
excludes `/data/` and `/outputs/`.

So a teammate who clones the repository has the code but no data. They have two
options: re-download everything, or copy this bundle from a pendrive.

| Route | Cost |
|---|---|
| Re-download | GHSL 30–45 minutes; Earth Engine layers need a registered Cloud project; SHRUG about 600 MB |
| Pendrive | 780 MB for the essential bundle, a couple of minutes to copy |

## On the machine that has the data

```bat
python scripts/external_data.py check
python scripts/external_data.py export E:\urbanintel-data
```

`export` writes the bundle in the repository's own layout, plus a `MANIFEST.json`
and a `README.txt` that repeats these instructions:

```
E:\urbanintel-data\
  data\raw\ghsl        GHSL built-up surface and population (zip archives)
  data\raw\gee         Earth Engine exports — night lights, NDVI, temperature,
                       Dynamic World, Open Buildings, WorldCover, SRTM, MODIS
  data\raw\osm         OpenStreetMap points of interest and roads
  data\raw\india       SHRUG census and economic census, UP district GDP
  data\processed       the 100 m analysis rasters
  outputs              grid, summary and validation results
```

Add `--full` to include two large files the essential bundle leaves out,
because the project can rebuild both: the GHSL rasters already extracted from
their zip archives (341 MB) and the all-India SHRUG polygon archive (362 MB),
whose only use — the Varanasi-region subset — is already in the bundle as
`data/raw/india/shrug/cache/`.

## On the machine that receives it

Clone the repository, then run **one** of these from inside it:

```bat
python scripts/external_data.py import E:\urbanintel-data
```

copies the bundle into the folders the project already expects
(`data\`, `outputs\`), or

```bat
python scripts/external_data.py link ..\urbanintel-data
```

leaves the files where they are — on the pendrive, on a D: drive, anywhere —
and writes `config/local.yaml` pointing at them.

Then check and run:

```bat
python scripts/external_data.py check
run_review3.bat
```

## Why `link` cannot cause a merge conflict

`config/local.yaml` is in `.gitignore`. It never enters a commit, so it can
never appear in a diff, a pull or a merge. Each member's data can sit in a
different place while everyone shares one `config/varanasi.yaml`, which keeps
the plain relative defaults `data/raw` and `outputs`.

The file it writes looks like this — relative to the repository root whenever
the bundle is on the same drive, so it survives the repository being moved:

```yaml
paths:
  data_raw: ../urbanintel-data/data/raw
  data_interim: ../urbanintel-data/data/interim
  data_processed: ../urbanintel-data/data/processed
  outputs: ../urbanintel-data/outputs
```

A single environment variable works too, and wins over both files —
`URBANINTEL_DATA_RAW`, `URBANINTEL_DATA_INTERIM`, `URBANINTEL_DATA_PROCESSED`,
`URBANINTEL_OUTPUTS`. Useful for one-off runs:

```bat
set URBANINTEL_OUTPUTS=D:\varanasi-outputs
python -m urbanintel.pipeline
```

`python scripts/external_data.py unlink` removes `config/local.yaml` and
returns to the defaults.

## What is in git, and what is not

| In the repository | Not in the repository |
|---|---|
| all code, tests, `run_*.bat` | `data/raw/**` — GHSL, Earth Engine, OpenStreetMap, Indian archives |
| documents, including the Review 3 report and its PDF | `data/processed/**` — the 100 m analysis rasters |
| all 14 figures and 23 zone cards (7 MB) | `outputs/**` — grid, summary, validation results |
| the presentation decks | `papers/*.pdf` — the reviewed papers (a GitHub release holds them) |
| `config/varanasi.yaml` | `config/local.yaml` — each machine's own paths |

Everything in the right-hand column can be rebuilt from the left-hand one:
`scripts/prefetch.py` (open data, no account), `scripts/export_review3_layers.py`
(Earth Engine, needs an account), `scripts/fetch_indian_data.py` (SHRUG and the
UP government spreadsheets), then `run_review3.bat`.
