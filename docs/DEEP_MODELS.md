# Deep models: what was built, what it scores, what it changed

Last run 21 September 2026. Both models are implemented and have been run end to
end on the Varanasi data, the image model now on **real Landsat surface reflectance
at 30 m**. Diagrams: `docs/diagrams/dl3_model_a_detail.svg` and `dl4_system_detail.svg`.
Every number below comes from `outputs/varanasi_deep_system.json` and
`outputs/varanasi_image_model.json`.

---

## 1. The complete image model

| | First run (7 Sep) | Complete run |
|---|---|---|
| Input | 8 driver maps, 100 m | **6-band Landsat surface reflectance, 30 m** |
| Dates per sample | 1 | **2** (t - 5 and t) |
| Training transitions | 1 (2010-2015) | **2** (1995-2000, 2010-2015) |
| Working grid | 100 m, 125,925 cells | **30 m, 1,343,384 pixels**, averaged back to 100 m |
| Parameters | 500,481 | 501,633 |
| Training time | 3.4 min | 22.7 min |

**Result on the held-out 2015-2020 period, scored once:**

- test AUC **0.8603**
- average precision 0.0761 (7.0x the base rate)
- Figure of Merit **0.0635**, 145 of 1,214 conversions found
- validation AUC 0.8691, average precision 0.6444 (spatial blocks, training period)

The first thing to say about that: **reading nothing but satellite pixels, the model
reaches a higher test AUC (0.860) than the random forest does (0.833) with
OpenStreetMap roads and GHS-POP population in hand.** The growth signal really is
visible in the imagery. That is the answer to "can the model use satellite images",
and it is a yes.

The second thing to say is that its Figure of Merit is the lowest in the table
(0.0635). It ranks the whole map well and the top of the map badly, and the Figure
of Merit only looks at the top. Both facts are true at once and both belong in the
report.

**It is also undertrained.** The run was capped at 15 epochs to fit a time budget,
and validation average precision was still climbing when it stopped (0.6119 at epoch
5, 0.6444 at epoch 14). The earlier 100 m model peaked at epoch 27. A longer run is
the obvious next step and may well move the Figure of Merit.

## 2. Where the imagery actually pays: as features

| Model | AUC | Avg. precision | Figure of Merit | FoM, no automaton | Hits / 1,214 |
|---|---|---|---|---|---|
| Random forest (Review 3) | 0.8331 | 0.1270 | **0.1016** | 0.1087 | 224 |
| XGBoost + 16 image components | **0.9080** | 0.1295 | 0.0981 | 0.1204 | 217 |
| Blend of image and tabular | 0.8759 | 0.1096 | 0.0903 | 0.1122 | 201 |
| XGBoost, 8 drivers | 0.9048 | **0.1476** | 0.0864 | **0.1262** | 193 |
| Logistic regression | 0.9096 | 0.1092 | 0.0687 | 0.1051 | 156 |
| Image model alone | 0.8597 | 0.0752 | 0.0635 | 0.0673 | 145 |
| Random allocation | 0.5000 | - | 0.0055 | 0.0055 | 13 |

Feeding the encoder's features into the boosted model — sixteen components holding
98.2 percent of the feature variance — moves it from 0.0864 to **0.0981** and from
193 hits to 217, an extra 24 correctly placed cells. That is the clearest benefit
the deep model delivers: **as a feature extractor it helps, as a standalone
predictor it does not.**

The blend disagrees with the image model even more bluntly. Fitted on the blocks the
image model itself held out, it gives the image surface a **negative** weight
(-0.237 against the tabular model's 0.782): once the tabular score is present, the
image surface actively subtracts. Reported as the null result it is.

The random forest still has the best Figure of Merit. Nothing here displaces it.

## 3. The cellular automaton still costs accuracy

The sweep from the previous run holds, and now prefers an even lower weight: the
best setting for the leading model is **0.1**, not the 0.35 in use, and allocating by
suitability alone gives XGBoost 0.1262 against the 0.1016 the forest scores through
the automaton. See `docs/figures/dl/DL11_neighbourhood_weight.png`.

## 4. The imagery itself checks out

Six dry-season composites exported at 30 m (1990, 1995, 2000, 2005, 2010, 2015),
six bands each, Landsat 5 harmonised onto the Landsat 8 scale with the Roy et al.
(2016) coefficients.

- **97.06 percent valid pixels in every epoch** — the missing 3 percent is the frame
  corner outside the clip.
- Median near-infrared reflectance **0.251 to 0.260 across all six epochs**, straight
  through the 2013 sensor change. A jump there would have meant the model was reading
  the satellite rather than the city. See `DL12_sensor_consistency.png`.
- Blue varies more (0.048 to 0.075), which is what winter haze over the
  Indo-Gangetic plain does to the blue band.

The model is not circular, and it is worth being able to say why: GHSL for the label
year is derived from imagery of that year, which the model never sees. It reads
t - 5 and t and is asked about t + 5.

## 5. Uncertainty and the ghost check

Twenty dropout draws, one allocation each: 1,167 cells chosen in every draw, 44 in
most, 54 only sometimes. The confident core is far larger than the uncertain fringe.

The label-free autoencoder flags the 5 percent of built-up cells it reconstructs
worst (772 cells) and independently picks out 34 of the 144 the activity rule flags.
Neither has ground truth, so this is corroboration, not accuracy.

## 6. Running it

```
python scripts/export_landsat_stack.py --years 1990 1995 2000 2005 2010 2015
python scripts/train_image_model.py --source landsat --epochs 30   # ~45 min, CPU
python scripts/run_deep_system.py --components 16                  # ~3 min
python scripts/make_dl_figures.py                                  # 12 figures
python tests/test_deep.py                                          # 16 tests
python scripts/run_ablations.py                                    # the whole matrix
```

Add `--encoder prithvi --cache-encoder` once the pretrained weights are downloaded.
`--single-transition`, `--source drivers` and `--max-dates 1` reproduce the earlier
runs for comparison.

## 7. Defects found and fixed while building this

Worth keeping, because each one would have produced a confident wrong number.

- **Validation could vanish silently.** At 30 m the study area divides into nine
  16 km blocks, but the ones along the edges are slivers. The random split picked two
  slivers, no 224-pixel validation tile fitted inside either, and the run had no
  validation data at all. Block selection now refuses blocks too small to hold a tile.
- **Two models, one block size.** The system inherited the image model's 16 km blocks
  for every model. Early stopping a boosted tree on two such blocks is far too coarse
  a signal: XGBoost stopped after **2 rounds** and scored 0.0557 instead of 0.0864.
  The tabular models now get their own finer split; only the blend uses the image
  model's blocks, because that is the one thing that has to match.
- **The blend could have been fitted on cells the image model trained on.** Its split
  is now reproduced on the model's own grid and projected down, not guessed at 100 m.
- **Channel sets could differ between transitions.** GHSL 1995 has no population
  raster, so that transition carried 7 channels against 2010's 8. A driver is now used
  only if every date the model sees has it, and the log says which was dropped.
- **Earth Engine refuses downloads over 50 MB**; the six-band float32 export was
  72 MB. It is written as scaled integers, which is how the products are published.
- **The JRC label server drops these 40 MB tiles**; the shared downloader restarted
  from zero each time and never finished. It now resumes by byte range.

## 8. Reproducibility

Re-running the **unmodified** Review 3 script on this machine gives the random forest
a Figure of Merit of **0.1016** and a test AUC of **0.8331**, where the recorded
Review 3 run gives **0.1031** and **0.834**. The rasters have not changed and logistic
regression reproduces exactly, so this is scikit-learn's forest differing between
versions. Quote it as "0.103 on the recorded run, 0.102 re-run on scikit-learn 1.6.1".

Environment: Python 3.13.3, numpy 2.3.3, scikit-learn 1.6.1, xgboost 3.0.5,
torch 2.10.0+cpu, no GPU. Every result file records these.

## 9. Not yet run

- **Prithvi-EO-2.0-300M.** The loader is implemented and tested (it reconstructs the
  published encoder and regenerates its three-dimensional position encoding); the
  weights download reached 855 MB of 1.2 GB before being stopped. `--encoder prithvi`
  is one command once it completes.
- **Two more transitions.** GHSL labels for 2005 are still missing, so 2000-2005 and
  2005-2010 cannot be used. Four transitions instead of two would roughly double the
  training data.
- **A longer image-model run.** Validation was still improving at the 15-epoch cap.

## 10. Figures

`docs/figures/dl/` — DL01 learning curve, DL02 TOC curves, DL03 Figure of Merit with
and without the automaton, DL04 precision at the top k, DL05 calibration, DL06
TreeSHAP contributions, DL07 error by distance band, DL08 per-block stability,
DL10 maps, DL11 the neighbourhood-weight sweep, DL12 sensor consistency.
