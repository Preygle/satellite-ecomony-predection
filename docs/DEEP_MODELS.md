# Deep models: what was built, what it scores, what it changed

Run on 20 September 2026. Both models in `docs/ARCHITECTURE_DEEP_LEARNING.md` are now
implemented and have been run end to end on the Varanasi data. Diagrams:
`docs/diagrams/dl3_model_a_detail.svg` (Model A) and `dl4_system_detail.svg` (Model B).
Every number below comes from `outputs/varanasi_deep_system.json` and
`outputs/varanasi_image_model.json`, written by the two commands in section 5.

---

## 1. Results, held-out 2015-2020, scored once

| Model | AUC | Average precision | Figure of Merit | Hits of 1,214 | Kappa |
|---|---|---|---|---|---|
| Image model (Model A) | 0.681 | 0.097 | **0.1067** | 234 | 0.184 |
| Random forest (Review 3) | 0.833 | 0.127 | 0.1016 | 224 | 0.176 |
| XGBoost + 16 image components | 0.902 | 0.141 | 0.0898 | 200 | 0.156 |
| Blend of image and tabular | 0.899 | 0.137 | 0.0868 | 194 | 0.151 |
| XGBoost, 8 drivers | **0.905** | **0.148** | 0.0864 | 193 | 0.150 |
| Logistic regression | 0.910 | 0.109 | 0.0687 | 156 | 0.119 |
| Random allocation | 0.500 | - | 0.0055 | 13 | - |

Read that table twice, because it says two different things. By **ranking** — AUC and
average precision — XGBoost is clearly best and the image model is clearly worst. By
**Figure of Merit**, which is what the project reports, the order is almost exactly
reversed.

The reason is the cellular automaton, and it is the most important finding here.

## 2. The cellular automaton is costing accuracy

The allocation step mixes suitability with how much development is already nearby:
`score = 0.65 x suitability + 0.35 x neighbourhood`. That 0.35 has been fixed by hand
since Review 2 and was never tested. Sweeping it, for every model
(`docs/figures/dl/DL11_neighbourhood_weight.png`):

| Model | weight 0 | 0.1 | 0.2 | **0.35 in use** | 0.5 | best |
|---|---|---|---|---|---|---|
| XGBoost | **0.1262** | 0.1082 | 0.0976 | 0.0864 | 0.0825 | 0 |
| XGBoost + image | **0.1236** | 0.1072 | 0.0991 | 0.0898 | 0.0815 | 0 |
| Random forest | 0.1087 | **0.1097** | 0.1056 | 0.1016 | 0.0937 | 0.1 |
| Logistic regression | **0.1051** | 0.0796 | 0.0743 | 0.0687 | 0.0630 | 0 |
| Image model | 0.1036 | 0.1046 | 0.1056 | **0.1067** | 0.1046 | 0.35 |

**Allocating purely by suitability, XGBoost reaches a Figure of Merit of 0.1262** against
the 0.1016 the random forest scores through the automaton — about 70 more correctly
placed cells out of 1,214. Only the image model prefers the current setting, and only
because its surface is already spatially smooth, so the neighbourhood term adds little
and costs little.

This is consistent with something the project already measured: Varanasi's growth is
heavily leapfrog. Insisting on contiguity moves predictions to the edge of the existing
city when much of the new development appeared away from it.

**What to do about it.** Do not simply set the weight to zero — that removes the
mechanism that makes the predicted map look like a city rather than a scatter of cells,
and the projection maps for 2025 and 2030 would change character. Report the sweep, say
that the automaton buys plausibility at a measurable cost in accuracy, and let the panel
see the trade-off. That is a stronger Review 4 answer than either extreme.

## 3. The image model, honestly

It reaches the best Figure of Merit under the current settings, but three things have to
be said with it.

- **The margin is close to noise.** Trained again with seeds 1 and 2, the Figure of Merit
  is 0.1041 on average with a spread of 0.0018 (0.1016, 0.1051, 0.1056). The gap to the
  forest is about one and a half times that spread.
- **Its ranking is weak and unstable.** Test AUC across the three seeds is 0.679, 0.835
  and 0.768. Scored on each fifth of the city separately, it averages 0.645 with a spread
  of 0.056, where XGBoost averages 0.899 with a spread of 0.007. The image model is good
  at the very top of the ranking and poor everywhere else.
- **It sees no more than the forest does.** Its eight input channels are the random
  forest's eight drivers, kept as maps instead of as a table — there is a test that
  asserts they are identical (`tests/test_deep.py`). So its advantage, where it has one,
  comes from reading spatial pattern, not from extra information.

Within-period validation reached an AUC of 0.96 while the held-out period gave 0.68. The
network learns *where* growth happened in 2010-2015, and that knowledge does not carry to
2015-2020. This is the clearest argument in the project for why a temporal hold-out is
the only honest test.

## 4. The other pieces

**Image components in the tabular model.** The encoder's feature map, reduced to 16
components holding 98.4 percent of its variance, lifts XGBoost from 0.0864 to 0.0898 and
its average precision falls slightly. A small, mixed effect, reported as such.

**The blend.** A logistic stacker on the two logits, fitted only on validation blocks
where neither member trained, gives the tabular model a weight of 0.75 and the image
model 0.09. It does not beat either parent on Figure of Merit. Reported as a null result.

**Uncertainty.** Three separately trained models, six dropout draws each, one allocation
per draw: 1,113 cells are chosen in every one of the 18 draws, 108 in most of them and 75
only sometimes. The confident core is much larger than the uncertain fringe, which is
worth saying plainly to a planner.

**Ghost growth without labels.** An autoencoder trained only on built-up cells whose
activity is at or above expected flags the 5 percent it reconstructs worst: 772 cells. It
independently picks out 34 of the 144 cells the existing rule flags. Neither method has
ground truth, so this is corroboration, not accuracy — the hand-labelling step remains
the one thing that would turn the ghost screen into a measured result.

## 5. Running it

```
python scripts/train_image_model.py                 # Model A, about 4 minutes on CPU
python scripts/run_deep_system.py                   # Model B, about 1 minute
python scripts/make_dl_figures.py                   # 11 figures into docs/figures/dl
python tests/test_deep.py                           # 12 tests
```

Useful options: `--quick` for a three-epoch smoke run, `--seed N --tag seedN` for the
spread, `--monitor auc` to stop on AUC instead of average precision, `--no-image` to run
the tabular half alone, `--source landsat` once the imagery is exported.

Deep-learning dependencies are listed separately in `requirements-dl.txt`; the main
pipeline imports none of them.

## 6. Reproducibility, and one warning

Every result file now records the library versions it was produced with. That matters
more than it sounds:

> Re-running the **unmodified** Review 3 script on this machine today gives the random
> forest a Figure of Merit of **0.1016** and a test AUC of **0.8331**, where the recorded
> Review 3 run gives **0.1031** and **0.834**. The rasters have not changed. Logistic
> regression reproduces exactly, so this is scikit-learn's forest differing between
> versions.

The difference is 3 cells out of 1,214 and changes no conclusion, but the team should
quote 0.103 as "0.103 on the recorded run, 0.102 when re-run on scikit-learn 1.6.1"
rather than be caught by it in the viva. The current environment is Python 3.13.3, numpy
2.3.3, scikit-learn 1.6.1, xgboost 3.0.5, torch 2.10.0+cpu.

## 7. What is implemented but not yet fed

The code supports two input dates and 30 m Landsat bands; today only one GHSL date is on
disk, so the model runs on a single snapshot. `scripts/export_landsat_stack.py` exports
six-band dry-season composites for 2000 to 2025, harmonising Landsat 5 and 7 onto the
Landsat 8 scale with the Roy et al. (2016) coefficients, and with `--ghsl` it also
downloads the 2000 and 2005 label epochs. That turns one training transition of about
1,400 conversions into three, which is the single biggest thing that would help the image
model. It needs an Earth Engine session, so it has not been run here.

The Prithvi-EO-2.0 encoder is wired in behind `--encoder prithvi` and loads through
TerraTorch, which is not installed on this machine. The fallback encoder trained from
scratch is what produced every number above.

## 8. Figures

`docs/figures/dl/`

| | |
|---|---|
| DL01 | learning curve, with the epoch that was kept |
| DL02 | TOC curves, linear axes |
| DL03 | Figure of Merit with and without the automaton |
| DL04 | precision at the top 1, 2, 5 and 10 percent |
| DL05 | reliability curves and Brier scores |
| DL06 | exact TreeSHAP contributions, drivers against image components |
| DL07 | Figure of Merit by distance to the built-up edge |
| DL08 | AUC per fifth of the city |
| DL09 | seed spread |
| DL10 | suitability, conversion probability and uncertainty maps |
| DL11 | the neighbourhood-weight sweep |
