# Deep-learning architecture for Review 4

Design note, 17 September 2026. Two architectures: the best image-based model we can
justify, and the best overall system built around it. Diagrams:
`docs/diagrams/dl1_image_model.svg` and `docs/diagrams/dl2_system.svg`.

One sentence before the design: the panel will ask what each model *does* for the
project, not what it is called, so every component below has a job, a test, and a way to
say honestly what it added.

---

## 1. The unlock: the hold-out can be kept after all

Yesterday's note said an image model could not be scored on the 2015-2020 hold-out
because Sentinel-2 does not reach back that far. That is still true for Sentinel-2. It is
not true for Landsat, and it is not true of the label source either:

| Source | Coverage we can use | Resolution |
|---|---|---|
| `JRC/GHSL/P2023A/GHS_BUILT_S` (labels) | every 5 years, 1975-2020 observed; 2025 and 2030 are projections | 100 m |
| `LANDSAT/LT05/C02/T1_L2` (Landsat 5 surface reflectance) | 1984-2012 | 30 m |
| `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2` | 2013 onward | 30 m |
| `NASA/HLS/HLSL30/v002`, `NASA/HLS/HLSS30/v002` (Harmonized Landsat and Sentinel-2) | 2013 onward | 30 m |

So a 30 m image model can be trained on **2005-2010** and **2010-2015** (Landsat 5 at
the start of each), tested on **2015-2020** (Landsat 8, touched once), and then run on
the 2020 and 2025 images to forecast 2025 and 2030. The 2000-2005 transition is a third,
optional training period. Instead of one training transition with about 1,380 positives we
get two or three, and the imagery is native to the years the labels cover.

The cost is the sensor change: Landsat 5 (TM) for the training starts, Landsat 8 (OLI)
for the test and forecast starts. The six shared bands (Blue, Green, Red, NIR, SWIR1,
SWIR2) are harmonised with the published OLI-to-TM regression coefficients, and each tile
is normalised per band before it enters the model, so the network sees relative
reflectance rather than sensor-specific absolute values. Band-jitter augmentation during
training covers what harmonisation misses.

The existing 100 m analysis frame stays the master grid. Landsat is exported at 30 m in
the same projection (EPSG:32644), and each pixel is mapped to the 100 m cell that contains
its centre. Labels are painted onto pixels through that lookup, and predictions are
averaged back through it.

---

## 2. Model A: the image model

`docs/diagrams/dl1_image_model.svg`

**Job.** Predict, from the imagery alone, which non-urban 100 m cells become urban in the
next five years, and feed that suitability into the cellular automaton the project
already validates.

**Input.** Two Landsat dates, t - 5 and t, six bands each, 224 x 224 pixels at 30 m
(a 6.7 km tile), plus acquisition date and tile centre latitude and longitude as
metadata. The second date gives the encoder growth momentum; the metadata is what the
"TL" variant of the encoder was pretrained to accept.

**Encoder.** Prithvi-EO-2.0-300M-TL (IBM and NASA, Apache-2.0). A ViT-L with a 3D
patch embedding of 16 x 16 pixels x 2 dates, pretrained as a masked autoencoder on 4.2
million Harmonized Landsat and Sentinel-2 time series at 30 m. Its six pretraining bands
are exactly our six Landsat bands, in the same order. The masked-autoencoder pretraining
is generative self-supervision: the model learnt to reconstruct hidden patches of the
image, which is what lets it be fine-tuned with so few labels.

**Decoder.** A UNet-style decoder with four up-sampling blocks, from the encoder's
patch tokens back to a 30 m logit map. TerraTorch provides this configuration ready made.

**Output.** Logits at 30 m, masked to pixels whose cell is not urban at t, averaged to the
100 m cells, giving the suitability raster `s`. The cellular automaton then runs exactly
as in Review 3: score = 0.65 s + 0.35 n300, eight rounds, demand from the 1.86 percent
per year CAGR.

**Loss.** Focal loss plus Dice loss, computed only on eligible pixels. The label for a
pixel is 1 if its cell is below 0.20 built-up fraction at t and at or above 0.20 at
t + 5. Positives are about one percent of eligible cells, and focal plus Dice is the
standard pairing for that ratio in segmentation.

**Training.** Random 224-pixel crops from the two training transitions, oversampling crops
that contain at least one conversion; the eight flips and rotations of a square; per-band
gain and offset jitter. AdamW, encoder learning rate 1e-5 with layer-wise decay, decoder
1e-4, mixed precision, 20-30 epochs. Early stopping on spatial blocks of about 5 x 5 km
held out from the training transitions, never on random pixels, because neighbouring
crops overlap.

**Two runs, in this order.**
1. Frozen encoder, train the decoder only. Minutes on any GPU. This is the safe result.
2. Full fine-tune. Better if the labels support it; the spatial-validation loss says
   whether they do.

**Evaluation.** Identical to the Random Forest: same eligible cells, same demand, Figure
of Merit, producer's accuracy, kappa, AUC, TOC curve, ratio to random placement, on
2015-2020, once.

**What "success" means.** The Random Forest reads roads, population and distances from
OpenStreetMap and GHS-POP. Model A reads pixels only. Matching the forest's Figure of
Merit of 0.103 without those inputs is already a result: it means the growth signal is in
the imagery. Beating it is the hope, not the promise, and a null result is reported as
one.

**Why this encoder and not the others.**
- SSL4EO-L (Landsat-pretrained ResNet-50 and ViT-S via TorchGeo) is the lighter fallback
  if 300M parameters prove too much for the label budget. Separate weights exist for
  TM and OLI, which is useful if the sensor change turns out to matter.
- SSL4EO-S12, Clay and SatMAE are Sentinel-2 or RGB models; none of them speaks
  Landsat 5.
- Very-high-resolution change-detection checkpoints (LEVIR-CD, WHU-CD) are trained at
  0.5-2 m and do not transfer to 30 m.
- A plain CNN from scratch is the baseline that any of these must beat, and it is worth
  one line in the comparison table, not a week.

**Compute.** Frozen-encoder run: under an hour on a T4 (Colab free tier). Full fine-tune
of the 300M encoder: batch 4-8 with gradient checkpointing fits in 16 GB; a few hours on
a T4, well under an hour on an A100. Inference over the whole study area is about 120
overlapping tiles, seconds on a GPU. The data volume is small: one transition is about
1,400 x 1,200 pixels x 12 channels, under 100 MB as float32.

---

## 3. Model B: the best overall system

`docs/diagrams/dl2_system.svg`

Three tiers. Tier 1 sees; tier 2 reasons and is where every validated number comes from;
tier 3 explains.

### Tier 1: perception (deep learning on imagery)

One Prithvi-EO-2.0 encoder, shared by three uses:

- **Growth head** (Model A above): `s_img`, the image-only suitability.
- **Change head**: the same encoder with a bi-temporal input of 2018 and 2024, decoded to
  a built-up change map. Sentinel-2 enters here as `NASA/HLS/HLSS30/v002`, which is
  Sentinel-2 harmonised to Landsat at 30 m, so the encoder sees the data it was
  pretrained on. Supervised by GHSL change (100 m) and checked against Open Buildings
  2016-2023. Its output is evidence for the ghost typology: what visibly changed inside
  each flagged zone.
- **Embeddings**: the mean token embedding of each cell's neighbourhood, reduced by PCA
  to 16 components, handed to tier 2 as extra columns.

### Tier 2: reasoning (tabular model and cellular automaton)

- **XGBoost** on the eight existing drivers plus the 16 image components gives `s_tab`,
  with TreeSHAP for per-cell explanations. `scale_pos_weight` at the inverse positive
  rate; tuned with spatial block cross-validation inside the training period.
- **Stacker**: a logistic regression on the logits of `s_img` and `s_tab`, fitted on the
  spatial validation blocks only, never on 2015-2020. Two weights and an intercept, so it
  cannot overfit and it says in one line how much each model contributed.
- **Cellular automaton**, unchanged, run with 20 random seeds so every cell carries a
  probability of conversion for 2025 and 2030 rather than a single yes or no.
- **Ghost typology**: the existing activity-index rule, plus a positive-unlabelled
  classifier trained on 150-300 hand-labelled cells, calibrated so every zone carries a
  probability. The change head's map is one of its inputs.

Everything in this tier is scored on the same hold-out as Review 3.

### Tier 3: explanation (generative AI)

An LLM assistant (Claude API) with three tools: `read_zone`, `read_metric`,
`read_layer`. It writes the zone briefs and answers questions on the dashboard
("why is this zone flagged?", "which wards grow fastest by 2030?"). The rules that make
it honest:

- every number in its text comes from a tool call against tier 2 outputs; the model
  writes prose, it never computes;
- every brief is labelled as AI-generated, with the numbers it used listed underneath;
- it is evaluated too: a set of 30 questions with known answers, scored for factual
  agreement with the outputs JSON.

This is where "generative AI" earns its place in the project: as the layer that turns
validated numbers into readable planning text, not as the thing producing the numbers.

### Where each keyword lands

| Keyword | Where it is in the system | What it is validated against |
|---|---|---|
| Deep learning | Prithvi encoder, growth head, change head | 2015-2020 hold-out; Open Buildings |
| Transfer learning | Pretrained encoder fine-tuned on Varanasi | Frozen vs fine-tuned comparison |
| Transformer | ViT-L encoder | Same as above |
| Siamese / change detection | Change head, bi-temporal input, shared weights | GHSL change, Open Buildings |
| XGBoost | Tier 2 tabular model | Same hold-out as the Random Forest |
| Generative AI | Masked-autoencoder pretraining; LLM briefs | 30-question factual check |
| Ensemble | Stacker; 20-seed cellular automaton | Same hold-out |

---

## 4. Considered and not built

- **GAN or diffusion urban simulator** (MetroGAN family). Needs many cities to learn
  urban morphology; one city gives it nothing to generalise from, and the result cannot
  be validated beyond the Figure of Merit we already compute. The 20-seed cellular
  automaton gives the same "distribution of futures" honestly.
- **Fine-tuning at 10 m on Sentinel-2.** No labels at 10 m, no imagery before 2018.
- **Graph neural network.** Message passing on a grid repeats the neighbourhood term;
  road connectivity goes in as an ordinary feature.
- **Fine-tuning the 600M encoder.** More parameters than the labels can support; the
  300M model is already generous.

---

## 5. Four weeks, three people

| Week | Stream A: imagery | Stream B: tabular and labels | Stream C: explanation and delivery |
|---|---|---|---|
| 1 | Export Landsat 2000-2025 and HLS at 30 m; download GHSL 2000 and 2005; build the pixel-to-cell lookup and the tile sampler | XGBoost drop-in with spatial CV; SHAP | Label sample design; first 100 hand labels |
| 2 | Frozen-encoder run, then fine-tune; spatial-validation curves | Embedding PCA into XGBoost; stacker | Finish labels; agreement kappa; PU classifier |
| 3 | Change head on 2018 vs 2024; Open Buildings check | 20-seed cellular automaton; probability maps | LLM tools and briefs; 30-question check |
| 4 | Ablations: pixels only, drivers only, both | Report numbers, corrections log | Dashboard, deck, rehearsal |

Dependencies go in a separate `requirements-dl.txt`: `torch`, `terratorch`, `torchgeo`,
`xgboost`, `shap`, `anthropic`. The main pipeline does not import any of them.

---

## Sources

- Prithvi-EO-2.0 model card and paper: https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL , https://arxiv.org/abs/2412.02732
- TerraTorch fine-tuning examples: https://github.com/blumenstiel/TerraTorch-Examples
- SSL4EO-L, Landsat foundation models: https://arxiv.org/abs/2306.09424
- GHS-BUILT-S R2023A epochs: https://human-settlement.emergency.copernicus.eu/ghs_buS2023.php
- Landsat 5 Collection 2 Level 2 in Earth Engine: https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LT05_C02_T1_L2
- MetroGAN (considered, not built): https://arxiv.org/abs/2207.02590
