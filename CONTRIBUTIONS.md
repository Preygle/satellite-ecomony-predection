# Contributions — Review 3

Review 3 asks for evidence that is "executable and attributable to the team",
and the Project Guidelines (§2) ask every student to state their own
contribution. This file records who owns which part of the work.

**The team fills in the Owner column.** Every member owns at least one work
package, re-runs it on their own machine, can explain every step, commits it
from their own git account, and presents it at the review. Past commits are
not rewritten.

## Team

| Name | Register number |
|---|---|
| Mayank | 23BCE1753 |
| Achal Pramod Tripathi | 23BCE1734 |
| Mohammad Owais | 23BCE1746 |

Guide: Joshan

## Work packages

| Stream | Work package | Main files | Run it with | Owner |
|---|---|---|---|---|
| A | WP1 — Observed epochs only | `config/varanasi.yaml`, `src/urbanintel/config.py`, `src/urbanintel/pipeline.py` (built-up stage), `scripts/prefetch.py` | `python -m urbanintel.pipeline` | |
| A | WP2 — Heat-island corrections | `src/urbanintel/data/gee.py` (Landsat mask, depth check), `src/urbanintel/data/ghsl.py`, `src/urbanintel/analysis/thermal.py`, `pipeline.py` (thermal stage), `scripts/collect_layer_dates.py`, `scripts/gee_export.js`, `mentor_task/extract.py` | `python -m urbanintel.pipeline` | |
| C | WP3 — Typology rule and hold-out test | `src/urbanintel/analysis/nightlights.py`, `src/urbanintel/analysis/ghost.py`, `pipeline.py` (ghost stage), `scripts/validate_typology.py` | `python scripts/validate_typology.py` | |
| C | WP4 — Growth models | `src/urbanintel/analysis/growth_model.py`, `scripts/run_growth_model.py` | `python scripts/run_growth_model.py` | |
| B | WP5 — Satellite cross-checks | `scripts/export_review3_layers.py`, `scripts/cross_checks.py`, `src/urbanintel/analysis/vegetation.py`, `pipeline.py` (vegetation stage) | `python scripts/cross_checks.py` | |
| B | WP6 — Indian-data validation | `scripts/fetch_indian_data.py`, `src/urbanintel/data/shrug.py`, `scripts/validate_population.py`, `scripts/validate_economy.py`, `src/urbanintel/analysis/validation.py` | `python scripts/validate_population.py` and `validate_economy.py` | |
| A | WP7 — Zone evidence cards | `scripts/make_zone_cards.py`, `docs/figures/zones/` | `python scripts/make_zone_cards.py` | |
| A | WP8 — Results pack | `scripts/make_figures.py`, `docs/figures/` | `python scripts/make_figures.py` | |
| A | WP9 — Dashboard and documents | `dashboard/app.py`, `docs/REVIEW3_REPORT.md`, correction notices | `run_dashboard.bat` | |
| All | WP10 — Tests, one-command run, presentation | `tests/test_core.py`, `run_review3.bat`, `docs/Review3_Presentation.pptx`, this file | `run_review3.bat` | all three |

`pipeline.py` is one file shared by three streams. It is committed once, by the
stream A owner, and each stage's owner is the person listed above.

## Before the review

Each owner, for their own work package:

1. Run it from a clean terminal and compare the output with
   `docs/REVIEW3_REPORT.md`.
2. Be able to answer: what dataset goes in (official identifier), what the
   code does to it, what comes out, and what can go wrong.
3. Read the matching rows of the corrections log (report §6) — the panel is
   likely to ask about them.
4. Commit the files listed above from your own account.

## AI assistance

An AI assistant (Claude, by Anthropic) was used for code, analysis scripts and
documentation in this project, including the Review 3 work. This is
acknowledged as the Project Guidelines (§2) require. Ownership above means the
owner has re-run, checked and understood the work and presents it — not that
it was written without assistance.
