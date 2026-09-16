# Deep learning for Review 4: what to build, and why

Research note for the team, 16 September 2026. Nine candidate methods were researched
independently (one agent per method, web search, the same 24 questions each). Numbers
taken from published papers are marked **[verify]** wherever the agent that found them
could not confirm the figure against a primary source. Check those before quoting any of
them to the panel.

The baseline any new model has to beat, measured on the held-out 2015-2020 period:
**Figure of Merit 0.103, test AUC 0.834** (Random Forest). Logistic Regression scored
0.069 / 0.910, and random placement scored 0.0055.

---

## 1. The constraint that decides everything

Our labels and our imagery do not cover the same years.

| Source | Years available | Resolution |
|---|---|---|
| `JRC/GHSL/P2023A/GHS_BUILT_S` (our only label source) | 2010, 2015, 2020 | 100 m |
| `COPERNICUS/S2_SR_HARMONIZED` composites already downloaded | 2018-19, 2024-25 | 10 m |
| `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2` | 2013, 2024 (more exportable back to 1984) | 30 m |

Three consequences follow, and they shape every recommendation below:

1. **A model trained on Sentinel-2 images cannot reproduce our hold-out design.** We train
   on 2010 to 2015 and test on 2015 to 2020. There is no Sentinel-2 imagery for those
   years, so an image model cannot be scored against the 0.103 baseline.
2. **A 10 m model supervised by 100 m labels cannot be honestly validated at 10 m.** One
   GHSL label covers 100 Sentinel-2 pixels. Any per-pixel accuracy reported from such a
   setup is an artefact of the label, not a measurement.
3. **Therefore the deep model that keeps our validated design must read the existing
   driver rasters** (built-up fraction, population, road density, slope, distances), not
   raw Sentinel-2. Sentinel-2 still gets used, for a different job: change detection as
   evidence for the ghost-growth zones.

This is the answer to give when the panel asks "why not just feed the satellite images
into a CNN?".

---

## 2. Ranked recommendation

| # | Method | What it gives the project | Effort | Honest expectation |
|---|---|---|---|---|
| 1 | **CNN suitability inside the existing cellular automaton** | A real deep model on the same task, same hold-out, directly comparable Figure of Merit | 5-7 student-days | Published gains are real but modest, and were measured on much larger cities. A null result here is possible and reportable |
| 2 | **Ghost-growth labels + semi-supervised classifier** | The precision number the project does not currently have | 6-8 student-days | Highest scientific value of anything on this list |
| 3 | **XGBoost with SHAP explanations** | Answers the guide's suggestion cheaply; drop-in for the Random Forest | 3-4 student-days | 0 to 0.03 AUC, possibly nothing. Report it either way |
| 4 | **Siamese change detection on Sentinel-2, 2018 vs 2024** | A deep model doing something the Random Forest cannot: reading the images | 7-10 student-days | Strong demo and corroboration for the ghost zones; not comparable to the 0.103 baseline |
| 5 | **Frozen foundation-model embeddings as extra features** | Deep image representation feeding the existing tabular model | 4-6 student-days | Small, uncertain gain; keeps explainability if reduced to a few components |
| 6 | **Support Vector Machine** | The classical comparison point the guide asked for | 2-3 student-days | No gain expected; likely a little worse than the Random Forest |
| 7 | **Graph Neural Network** | Comparison point; corridor effects along roads | 5-8 student-days | Published urban-growth GNN hybrids report Figure of Merit 0.048 and 0.034 **[verify]**, below our current 0.103 |
| 8 | **U-Net semantic segmentation** | A built-up or change map at 10 m | 12-19 student-days | Cannot be honestly validated at 10 m with 100 m labels |
| 9 | **Plain CNN patch classifier** | The standard deep baseline the others must beat | 8-13 student-days | Expected to match or trail the Random Forest with only ~1,380 positive cells |

A three-person team with one month can realistically deliver **1, 2 and 3**, plus **4** if
the image preparation goes smoothly. Everything below that belongs in the report as
"considered, with reasons" - which is itself a Review 4 deliverable, because the guide
asked about five of them.

---

## 3. Plan for #1: CNN suitability inside the cellular automaton

This is the PLUS / FLUS design: a deep model replaces only the *suitability* estimator.
The demand calculation, the neighbourhood term and the allocation rounds stay exactly as
they are, so the result is directly comparable to the Random Forest.

**Inputs.** For every cell that is not urban at the start year, a 15 x 15 cell patch
(1.5 km across) with 6 channels, all measured at the start year: built-up fraction,
population, road density, distance to the centre, distance to the urban edge, slope.

**Labels.** Unchanged: the cell reached a built-up fraction of 0.20 or more five years
later.

**Architecture.** Three convolution blocks (16, 32, 64 filters, 3 x 3 kernels, batch
normalisation, ReLU, 2 x 2 pooling), then global average pooling, a dense layer of 64 with
dropout 0.3, and a sigmoid output. Roughly 100,000 parameters. Deliberately small: there
are only about 1,380 positive examples.

**Class imbalance.** Class weights of about 80 to 1, or focal loss, plus a balanced
sampler so every batch contains both classes.

**Augmentation.** The eight rotations and reflections of a square. Valid here because the
task has no natural "up".

**Splitting.** Train on 2010 to 2015. For early stopping, hold out *spatial blocks* of
about 5 x 5 km inside the training period, never random cells - neighbouring patches
overlap, so a random split leaks. Touch 2015 to 2020 once, at the very end.

**Output and evaluation.** The model produces a suitability raster. Feed that to the
existing allocation step unchanged (0.65 suitability plus 0.35 neighbourhood, 8 rounds),
place the same demand, and report Figure of Merit, producer's accuracy, kappa, AUC, the
TOC curve and the ratio to random placement, exactly as for the Random Forest.

**Compute.** Minutes on any GPU, and still workable on the laptop CPU. Inference over all
cells stays fast enough to keep the live demo.

**Risks to watch.**

- Overfitting. With so few positives the model can memorise the training period. Watch the
  gap between training loss and spatial-validation loss.
- Double counting the neighbourhood. The CNN patch already sees the surroundings, and the
  allocation step then adds a neighbourhood term again. Run the comparison with and
  without that term and report both.
- False precision. GHSL is itself a model product, so its labels carry error. Repeat that
  caveat wherever the new numbers appear.

**What the literature reports** (all on far larger study areas, so treat as an upper
bound, not a forecast): a CNN-based vector cellular automaton reaching Figure of Merit
0.361 **[verify]**; a CNN-patch land-change model improving Figure of Merit by about 2 to
4 percent over a Random Forest **[verify]**; an LSTM-CA hybrid improving it by about 10 to
19 percent **[verify]**.

---

## 4. Plan for #2: labels for ghost growth

The ghost-growth screen currently has no ground truth, so it has no precision. That is the
biggest hole in the project, and also the cheapest to fill.

1. Draw a stratified random sample: flagged cells across all the zones, plus unflagged new
   development as controls.
2. Label each one by eye on high-resolution historical imagery (Google Earth Pro, Esri
   World Imagery) for roughly 2020 and today: occupied, under construction, or empty
   plots. Two students label independently, measure agreement with Cohen's kappa, and
   resolve disagreements together. About 150 to 300 labelled cells is enough to measure
   precision usefully.
3. Report precision and recall for the existing rule. That alone is a Review 4 result, and
   it closes the limitation already written into the Review 3 slides.
4. With labels in hand, two cheap models become possible, both in scikit-learn with no new
   dependencies:
   - **Positive-unlabelled learning**: treat the labelled empty cells as positives and the
     rest as unlabelled, and train a classifier on the activity features.
   - **Autoencoder anomaly detection**: train a small autoencoder to reconstruct
     *normally used* built-up cells from their activity features; cells it reconstructs
     badly are anomalies. This needs no rare-class labels at all.
5. Calibrate the output (Platt scaling or isotonic regression) so each zone carries a
   confidence, which is what a planner actually needs.

There is published prior art for the rule-based version of this idea - "ghost city" indices
that compare built-up area against night-time light, mostly for Chinese cities - but no
published deep model for it. A measured, calibrated version is therefore a genuine
contribution rather than a re-implementation.

---

## 5. Plan for #3: XGBoost

A drop-in replacement for the Random Forest: same 8 drivers, same interface, same hold-out.

- Set `scale_pos_weight` to about 80 to 99 (the inverse positive rate) instead of
  resampling the data.
- The hyperparameters that matter, in order: `scale_pos_weight`, then `max_depth` together
  with `min_child_weight`, then `learning_rate` with early stopping.
- Tune with spatial block cross-validation inside the training period. Random k-fold leaks,
  because the neighbourhood features are smoothed across adjacent cells.
- TreeSHAP gives exact per-feature contributions, which is a direct upgrade on the
  permutation importance we report now, and it is easy to show a panel.
- Probability calibration matters little here, because the allocation step uses only the
  *ranking* of the scores, not their absolute values.

---

## 6. If the images are to be used: Siamese change detection

This is the guide's "transfer learning, Siamese" suggestion, done in a way that survives
scrutiny.

- **Do not** use LEVIR-CD, WHU-CD or S2Looking checkpoints directly. They are trained on
  0.5 to 2 m imagery, 20 to 100 times sharper than Sentinel-2, so their learned features do
  not transfer. Their published scores (BIT about 83.9 IoU, ChangeFormer about 82.5 IoU on
  LEVIR-CD **[verify]**) describe a different problem on a different sensor.
- **Do** use an encoder pretrained on Sentinel-2 itself: SSL4EO-S12 weights through
  TorchGeo, or Prithvi-EO-2.0, whose band set matches our composites **[verify licences
  before use]**.
- Two encoder branches that share weights, one per date, then take the difference of the
  features and decode it to a change map.
- Validate against `GOOGLE/Research/open-buildings-temporal/v1` for 2016 and 2023 and
  against the GHSL change we already have, and say plainly that this is not the same test
  as the growth model's.
- Deliverable: "here is what visibly changed inside the flagged zones between 2018 and
  2024" - exactly the evidence the ghost zones currently lack.

---

## 7. One line for each method the guide suggested

- **Graph Neural Network.** Investigated. On a regular grid, message passing largely
  repeats what our neighbourhood features already encode, and published urban-growth GNN
  hybrids report Figure of Merit values below our current baseline **[verify]**. The part
  worth keeping is road-network connectivity, which we can add as an ordinary feature
  without a graph library.
- **Transfer learning with a Siamese network.** Adopted, for change detection between the
  2018 and 2024 images, using encoders pretrained on Sentinel-2 rather than the
  very-high-resolution change-detection checkpoints, because of the resolution gap.
- **Transformer.** Used as a frozen feature extractor rather than fine-tuned. With about
  1,380 positive examples, fine-tuning a model with hundreds of millions of parameters
  would overfit. The right family is the foundation models pretrained on Sentinel-2.
- **Support Vector Machine.** Included as a classical comparison. An RBF kernel does not
  scale to 113,000 training rows, because its cost grows with the square of the sample, so
  it runs on a stratified subsample with a linear model on the full sample alongside.
- **XGBoost.** Implemented as the direct competitor to the Random Forest, with SHAP
  explanations.

---

## 8. Evaluation protocol, identical for every method

Any method not judged this way cannot be compared with the others:

- the same eligible cells (not urban at the start year);
- the same demand (the number of cells that really converted);
- the same metrics: Figure of Merit, producer's accuracy, kappa, AUC, TOC curve, and the
  ratio to random placement;
- the 2015 to 2020 period used once, at the end;
- a null result reported as a result.

## 9. Setup

Keep the deep-learning dependencies out of the main pipeline so the existing run stays
light: a separate `requirements-dl.txt` holding `torch` (the CPU build locally, a GPU build
on Colab or Kaggle), `xgboost`, and `torchgeo` or `timm` only if the pretrained encoders
are actually used.

---

Raw research output: nine JSON files, 24 fields each, produced by independent agents on
16 September 2026 and kept in the session scratchpad. Each file lists the fields its agent
could not verify in an `uncertain` array; the same caution applies to every number marked
**[verify]** above.
