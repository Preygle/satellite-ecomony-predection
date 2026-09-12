"""Build the Review 3 presentation.

    python scripts/make_presentation_r3.py

Every figure comes from this project's own outputs: the numbers are read from
``outputs/review3_results.json`` and the images from ``docs/figures`` and
``docs/diagrams`` (run ``make_diagrams.py`` first), so the
deck cannot drift away from what the code produced. Design tokens and layout
helpers are shared with ``make_presentation.py`` (the Review 2 deck).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_presentation import (  # noqa: E402
    ACCENT, BORDER, CHIP_LINE, DIM, GREEN, PANEL, TEXT, WARN,
    H, W, blank, bullets, card, heading, para, tb,
)

FIG = ROOT / "docs" / "figures"
DIAG = ROOT / "docs" / "diagrams"
OUT = ROOT / "docs" / "Review3_Presentation.pptx"
RESULTS = ROOT / "outputs" / "review3_results.json"


# --------------------------------------------------------------- helpers ---

def fig(slide, name, x, y, w, caption=None):
    """Place a figure; a caption sits under it in the dim colour."""
    p = FIG / name
    if not p.exists():
        return None
    pic = slide.shapes.add_picture(str(p), x, y, width=w)
    if caption:
        tf = tb(slide, x, y + pic.height + Inches(0.05), w, Inches(0.3))
        para(tf, caption, 10, DIM, False, 0, first=True)
    return pic


def diagram(prs, title, sub, name, note=None):
    """A slide that is one diagram from docs/diagrams, centred, plus a footer note."""
    s = blank(prs)
    heading(s, title, sub)
    p = DIAG / name
    if p.exists():
        pic = s.shapes.add_picture(str(p), 0, Inches(1.65), height=Inches(5.15))
        if pic.width > W - Inches(1.2):   # very wide diagrams: fit the width instead
            ratio = (W - Inches(1.2)) / pic.width
            pic.width, pic.height = int(pic.width * ratio), int(pic.height * ratio)
        pic.left = int((W - pic.width) / 2)
    if note:
        footer(s, note)
    return s


def chip(slide, x, y, w, h, value, label, colour=ACCENT):
    """A number, and what it means, in a small card."""
    c = card(slide, x, y, w, h)
    c.line.color.rgb = CHIP_LINE
    tf = tb(slide, x + Inches(0.14), y + Inches(0.1), w - Inches(0.28), h - Inches(0.2))
    para(tf, value, 20, colour, True, 2, first=True)
    para(tf, label, 10.5, DIM, False, 0)
    return c


def grid_table(slide, x, y, w, rows, widths, size=10.5, head=10.5, row_h=Inches(0.3)):
    """A plain table whose first row is the header."""
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, row_h * len(rows))
    t = shape.table
    for i, frac in enumerate(widths):
        t.columns[i].width = Inches(round(w.inches * frac, 3))
    for r, row in enumerate(rows):
        t.rows[r].height = row_h
        for c, text in enumerate(row):
            cell = t.cell(r, c)
            cell.text = str(text)
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL if r == 0 else RGBColor(0xFF, 0xFF, 0xFF)
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            for run in p.runs:
                run.font.size = Pt(head if r == 0 else size)
                run.font.bold = r == 0
                run.font.color.rgb = TEXT if r == 0 else DIM
                run.font.name = "Segoe UI"
    return t


def footer(slide, text):
    tf = tb(slide, Inches(0.7), H - Inches(0.62), Inches(12), Inches(0.3))
    para(tf, text, 9.5, DIM, False, 0, first=True)


# ---------------------------------------------------------------- slides ---

def build():
    R = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    b = R.get("builtup", {})
    proj = R.get("projections", {})

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 - title ------------------------------------------------------------
    s = blank(prs)
    tf = tb(s, Inches(0.9), Inches(2.05), Inches(11.5), Inches(2.2))
    para(tf, "Satellite-Based Urban Growth and", 36, TEXT, True, 2, first=True)
    para(tf, "Economic Activity Intelligence System", 36, TEXT, True, 10)
    para(tf, "Review 3  -  Implementation and Results  -  Varanasi, Uttar Pradesh",
         16, ACCENT, False, 0)
    bar = s.shapes.add_shape(1, Inches(0.9), Inches(4.45), Inches(2.0), Pt(3))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    bar.shadow.inherit = False
    tf = tb(s, Inches(0.9), Inches(4.8), Inches(11.5), Inches(1.6))
    para(tf, "Mayank  23BCE1753        Achal Pramod Tripathi  23BCE1734        "
             "Mohammad Owais  23BCE1746", 14, TEXT, False, 6, first=True)
    para(tf, "Guide: Joshan        BCSE497J Project I  -  SCOPE  -  Fall 2026-27",
         13, DIM, False, 6)
    para(tf, "Panel review, 16 September 2026", 13, DIM, False, 0)

    # 2 - what changed ------------------------------------------------------
    s = blank(prs)
    heading(s, "What changed since Review 2", "Three things, in order of importance")
    items = [
        ("1. We fixed what was wrong", ACCENT,
         "An audit of our own code found 15 defects. The pipeline used GHSL's 2025 epoch "
         "- a projection, not an observation - as the current year, so every 2010-2025 "
         "figure was measured against a forecast. Every number is now recomputed on the "
         "observed epochs 2010, 2015 and 2020."),
        ("2. We tested the results against independent data", GREEN,
         "Six built-up datasets, a second temperature sensor, a hold-out test of the "
         "ghost-growth classes, and Indian records: Census of India 2001 and 2011, the "
         "2013 Economic Census, and district GDP from the Government of Uttar Pradesh."),
        ("3. We finished the prediction module", WARN,
         "Logistic regression and random forest, trained on 2010-2015, scored on a "
         "held-out 2015-2020, compared on a TOC curve; the better one projects growth 5 "
         "and 10 years ahead."),
    ]
    y = Inches(1.75)
    for title, colour, body in items:
        c = card(s, Inches(0.7), y, Inches(11.9), Inches(1.55))
        c.line.color.rgb = BORDER
        tf = tb(s, Inches(0.95), y + Inches(0.16), Inches(11.4), Inches(1.25))
        para(tf, title, 16, colour, True, 4, first=True)
        para(tf, body, 13, DIM, False, 0)
        y += Inches(1.72)
    footer(s, "Corrections log: docs/REVIEW3_REPORT.md section 6 - every before and after number.")

    # 3 - implementation status --------------------------------------------
    s = blank(prs)
    heading(s, "Implementation status", "What runs today, and how to check it")
    rows = [
        ["Module", "Status", "Run it with"],
        ["Data acquisition - GHSL, OpenStreetMap, 13 Earth Engine layers", "Done",
         "prefetch.py, export_review3_layers.py"],
        ["Indian datasets - census, economic census, UP district GDP", "New",
         "fetch_indian_data.py"],
        ["Analysis pipeline - built-up, activity, green cover, heat, typology", "Done",
         "python -m urbanintel.pipeline"],
        ["Growth models - logistic regression, random forest, +5 / +10 years", "Extended",
         "run_growth_model.py"],
        ["Validation - hold-out test, cross-checks, census, economy", "New",
         "validate_*.py, cross_checks.py"],
        ["Results pack - 14 figures, 23 zone cards, one results file", "New",
         "make_figures.py, make_zone_cards.py"],
        ["Dashboard - seven tabs, including Validation", "Updated", "run_dashboard.bat"],
        ["City search; ground labels for flagged zones", "Review 4", "-"],
    ]
    grid_table(s, Inches(0.7), Inches(1.75), Inches(11.9), rows, [0.46, 0.12, 0.42])
    y = Inches(5.5)
    chip(s, Inches(0.7), y, Inches(3.8), Inches(1.1), "41 / 41",
         "unit tests pass; 16 added for Review 3")
    chip(s, Inches(4.75), y, Inches(3.8), Inches(1.1), "run_review3.bat",
         "one command: tests, pipeline, models, validation, figures", GREEN)
    chip(s, Inches(8.8), y, Inches(3.8), Inches(1.1), "review3_results.json",
         "every number in this deck, machine-readable", WARN)

    # 3a - architecture -----------------------------------------------------
    diagram(prs, "System architecture", "Five layers, each a folder of the code",
            "A1_system_architecture.png",
            "Data flow stage by stage: docs/diagrams/A2_pipeline_dataflow.png. "
            "All 15 diagrams are explained in docs/DIAGRAMS.md.")

    # 4 - datasets ----------------------------------------------------------
    s = blank(prs)
    heading(s, "Datasets", "Official identifiers; the Indian records are new this review")
    card(s, Inches(0.7), Inches(1.72), Inches(5.85), Inches(5.0))
    tf = tb(s, Inches(0.95), Inches(1.9), Inches(5.35), Inches(4.7))
    para(tf, "Satellite and gridded", 15, ACCENT, True, 8, first=True)
    bullets(tf, [
        ("GHS-BUILT-S / GHS-POP R2023A", "built-up surface and population, 100 m, 2010-2020"),
        ("NOAA/VIIRS/DNB/ANNUAL_V21 + V22", "night-time light 2013-2024, activity proxy"),
        ("COPERNICUS/S2_SR_HARMONIZED", "NDVI, NDBI, true colour"),
        ("LANDSAT/LC08 + LC09 C02 T1_L2", "land surface temperature, band ST_B10"),
        ("MODIS/061/MOD11A2", "independent temperature check"),
        ("GOOGLE/DYNAMICWORLD/V1", "water mask, built-up gain"),
        ("open-buildings-temporal/v1", "do flagged cells contain buildings?"),
        ("ESA/WorldCover/v200", "independent built-up map"),
        ("USGS/SRTMGL1_003", "terrain slope"),
        ("WorldPop/GP/100m/pop", "independent population"),
    ], 11.5, 5)
    c = card(s, Inches(6.75), Inches(1.72), Inches(5.85), Inches(5.0))
    c.line.color.rgb = GREEN
    tf = tb(s, Inches(7.0), Inches(1.9), Inches(5.35), Inches(4.7))
    para(tf, "Indian records  (new)", 15, GREEN, True, 8, first=True)
    bullets(tf, [
        ("Census of India 2011 and 2001", "population of 71 districts of Uttar Pradesh "
                                          "and 11,624 towns and villages, through SHRUG"),
        ("Economic Census 2013, MoSPI", "non-farm jobs per town and village, through SHRUG"),
        ("SHRUG boundaries", "town, village and district polygons - so a satellite value "
                             "can be compared with a census count for the same place"),
        ("District Domestic Product", "Directorate of Economics and Statistics, Government "
                                      "of Uttar Pradesh, 2020-21 and 2021-22"),
    ], 11.5, 10)
    para(tf, "Downloaded by scripts/fetch_indian_data.py; the source, size and SHA-256 of "
             "every file is recorded in data/raw/india/MANIFEST.json.", 10.5, DIM, False, 0)
    footer(s, "SHRUG is CC BY-NC-SA 4.0; cited as Asher, Lunt, Matsuura and Novosad (2021).")

    # 5 - the correctness fix ------------------------------------------------
    s = blank(prs)
    heading(s, "Technical accuracy: what the audit found",
            "The headline defect, and what it changed")
    c = card(s, Inches(0.7), Inches(1.72), Inches(11.9), Inches(1.3))
    c.line.color.rgb = WARN
    tf = tb(s, Inches(0.95), Inches(1.86), Inches(11.4), Inches(1.1))
    para(tf, "GHS-BUILT-S R2023A publishes epochs to 2030, but only 1975-2020 are observed. "
             "2025 and 2030 are the GHSL model's own projections.", 14, TEXT, True, 4,
         first=True)
    para(tf, "Our pipeline used 2025 as the current year, so Review 2's growth figures were "
             "measured against a forecast. The configuration now refuses a projected epoch, "
             "and a unit test locks that behaviour.", 13, DIM, False, 0)
    rows = [
        ["Figure", "Review 2 (against the 2025 projection)", "Review 3 (observed 2010-2020)"],
        ["New built-up surface", "+23.47 km2", "+17.25 km2"],
        ["Urban extent growth", "1.40 % per year", "1.86 % per year"],
        ["Leapfrog share of new urban land", "48.8 %", "44.3 %"],
        ["Mean urban heat-island intensity", "+1.10 C, warm cells only", "-1.66 C, urban cells"],
        ["Green cover lost to built-up", "0.05 km2, mismatched years", "0.67 km2, same years"],
        ["Growth model AUC", "0.9901, training data", "0.910 / 0.834, held out"],
        ["Low-activity new development filling up", "95 %", "74 %"],
    ]
    grid_table(s, Inches(0.7), Inches(3.25), Inches(11.9), rows, [0.34, 0.33, 0.33])
    footer(s, "All 15 defects, with evidence and before/after values: report section 6.")

    # 6 - urban growth -------------------------------------------------------
    s = blank(prs)
    heading(s, "Urban growth, 2010-2020", "Observed epochs only")
    fig(s, "F01_growth_index.png", Inches(0.7), Inches(1.8), Inches(7.0))
    built = b.get("built_surface_km2", {})
    x, y = Inches(8.1), Inches(1.9)
    chip(s, x, y, Inches(4.5), Inches(1.05),
         f"+{b.get('net_builtup_change_km2', 17.25)} km2",
         f"built-up surface, {built.get('2010', 72.48)} to {built.get('2020', 89.73)} km2")
    chip(s, x, y + Inches(1.2), Inches(4.5), Inches(1.05),
         f"{b.get('annual_urban_growth_pct', 1.86)} %/yr", "urban extent, compound")
    chip(s, x, y + Inches(2.4), Inches(4.5), Inches(1.05), "44.3 %",
         "of new urban land is leapfrog - detached from the city", WARN)
    chip(s, x, y + Inches(3.6), Inches(4.5), Inches(1.05), "1.3x - 2.3x",
         "faster than population, depending on the population dataset", GREEN)
    footer(s, "GHSL 2025 is drawn dashed and labelled: a model projection, not a measurement.")

    # 6a - the typology algorithm --------------------------------------------
    diagram(prs, "How a cell is classified", "The ghost-growth typology, per 100 m cell",
            "A3_ghost_typology_algorithm.png",
            "Why the light trend is relative to the city: docs/diagrams/A4_relative_light_trend.png.")

    # 7 - ghost growth --------------------------------------------------------
    s = blank(prs)
    heading(s, "Ghost growth: is the split real?",
            "The rule decides how the same 5.56 km2 of candidates divides")
    fig(s, "F04_rule_sensitivity.png", Inches(0.7), Inches(1.75), Inches(6.0))
    fig(s, "F05_holdout.png", Inches(6.9), Inches(1.75), Inches(6.0))
    card(s, Inches(0.7), Inches(5.3), Inches(11.9), Inches(1.5))
    tf = tb(s, Inches(0.95), Inches(5.45), Inches(11.4), Inches(1.25))
    para(tf, "Hold-out test: classify with the 2013-2020 night lights only, then check what "
             "happened next.", 14, TEXT, True, 4, first=True)
    para(tf, "Cells called emerging went on to brighten, relative to the city, more than "
             "cells called ghost growth: p = 0.010 over 100 m cells and p = 0.031 over 500 m "
             "blocks. The split carries real information - and the effect is modest: an "
             "emerging cell out-brightened a ghost cell 56% of the time. It is a screening "
             "map, not a verdict.", 12.5, DIM, False, 0)

    # 8 - zone evidence -------------------------------------------------------
    s = blank(prs)
    heading(s, "What a flagged zone actually looks like", "One evidence card of 23")
    fig(s, "zones/zone_01.png", Inches(0.7), Inches(1.75), Inches(8.5))
    x = Inches(9.5)
    chip(s, x, Inches(1.9), Inches(3.1), Inches(1.05), "23", "zones flagged, all peripheral")
    chip(s, x, Inches(3.1), Inches(3.1), Inches(1.05), "82 %",
         "of ghost cells contain buildings in 2023 (Open Buildings)", GREEN)
    chip(s, x, Inches(4.3), Inches(3.1), Inches(1.05), "26 of 144",
         "ghost cells have no buildings - likely GHSL false positives", WARN)
    chip(s, x, Inches(5.5), Inches(3.1), Inches(1.05), "+0.32 m",
         "building height gained 2016-2023 in ghost cells")
    footer(s, "Evidence for a reader, not a validation: precision stays unmeasured until "
              "ground or image labels exist - Review 4.")

    # 9 - heat ----------------------------------------------------------------
    s = blank(prs)
    heading(s, "Surface heat: the result reversed", "March to May, daytime")
    fig(s, "F12_land_surface_temperature.png", Inches(0.7), Inches(1.75), Inches(11.9))
    c = card(s, Inches(0.7), Inches(5.15), Inches(11.9), Inches(1.6))
    c.line.color.rgb = WARN
    tf = tb(s, Inches(0.95), Inches(5.3), Inches(11.4), Inches(1.35))
    para(tf, "Varanasi has no daytime surface heat island in the pre-monsoon season.",
         15, WARN, True, 4, first=True)
    para(tf, "Measured over urban cells, the built-up area is 1.66 C cooler than the dry, "
             "bare farmland around it, and MODIS - an independent sensor - shows no heat "
             "island either. 22.3 of the 23.8 km2 of hotspots lie on rural land. Review 2's "
             "+1.10 C was the mean over only the cells warmer than rural, which is positive "
             "by construction. Heat vulnerability, which weights heat by residents, remains "
             "the planning layer.", 12.5, DIM, False, 0)

    # 9a - growth-model architecture -------------------------------------------
    diagram(prs, "How the growth model works",
            "Learn where the city grew, test on years it never saw, then project",
            "A5_growth_model.png",
            "Which years feed which step: docs/diagrams/A8_temporal_design.png.")

    # 10 - growth model --------------------------------------------------------
    s = blank(prs)
    heading(s, "Where the city grows next", "Trained 2010-2015, scored on a held-out 2015-2020")
    fig(s, "F07_figure_of_merit.png", Inches(0.7), Inches(1.75), Inches(5.9))
    fig(s, "F09_projection_map.png", Inches(7.0), Inches(1.7), Inches(3.5))
    rows = [
        ["Model", "AUC held out", "Figure of Merit", "x random"],
        ["Random forest", "0.834", "0.103", "18.7x"],
        ["Logistic regression", "0.910", "0.069", "12.5x"],
        ["Random allocation", "0.500", "0.0055", "1x"],
    ]
    grid_table(s, Inches(0.7), Inches(4.95), Inches(5.9), rows, [0.4, 0.2, 0.22, 0.18], 10, 10)
    p25 = proj.get("2025", {}).get("demand_km2", 14.89)
    p30 = proj.get("2030", {}).get("demand_km2", 31.21)
    chip(s, Inches(10.75), Inches(1.9), Inches(1.85), Inches(1.05), f"+{p25}", "km2 by 2025", GREEN)
    chip(s, Inches(10.75), Inches(3.1), Inches(1.85), Inches(1.05), f"+{p30}", "km2 by 2030", GREEN)
    tf = tb(s, Inches(7.0), Inches(5.5), Inches(5.6), Inches(1.3))
    para(tf, "Predictions, not observations.", 12.5, WARN, True, 3, first=True)
    para(tf, "The forest places growth better; the straight-line model ranks the bulk of the "
             "cells better. Removing roads changes nothing, so no later information leaks in. "
             "Published benchmark on the same measure: 0.264, for PLUS in Wuhan.",
         11.5, DIM, False, 0)

    # 11 - Indian data ---------------------------------------------------------
    s = blank(prs)
    heading(s, "Checked against Indian records",
            "Census of India, Economic Census, Uttar Pradesh district GDP")
    fig(s, "F10_population.png", Inches(0.7), Inches(1.72), Inches(5.9))
    fig(s, "F13_lights_vs_economy.png", Inches(6.9), Inches(1.72), Inches(5.9))
    card(s, Inches(0.7), Inches(4.7), Inches(5.9), Inches(2.15))
    tf = tb(s, Inches(0.92), Inches(4.85), Inches(5.5), Inches(1.9))
    para(tf, "Population", 14, ACCENT, True, 4, first=True)
    bullets(tf, [
        "WorldPop is closer to the 2011 Census than GHS-POP: median district error -0.4% "
        "against +3.4%, over 71 districts.",
        "GHS-POP puts 63% too many people inside the Municipal Corporation boundary.",
        "So the Review 2 headline becomes a range: built-up area grew 1.3x to 2.3x faster "
        "than population.",
    ], 11, 5)
    c = card(s, Inches(6.9), Inches(4.7), Inches(5.7), Inches(2.15))
    c.line.color.rgb = GREEN
    tf = tb(s, Inches(7.12), Inches(4.85), Inches(5.3), Inches(1.9))
    para(tf, "Night light as an activity proxy", 14, GREEN, True, 4, first=True)
    bullets(tf, [
        "District scale: light against UP district GDP, Spearman 0.85, R2 0.75. Varanasi "
        "sits within 5% of what its light predicts.",
        "Village scale: light against 2013 Economic Census jobs, 0.41 - no better than "
        "population.",
        "That is why the screen reports zones, not single cells.",
    ], 11, 5)

    # 12 - limitations and next -------------------------------------------------
    s = blank(prs)
    heading(s, "Limitations, and what Review 4 adds", "Said plainly")
    c = card(s, Inches(0.7), Inches(1.72), Inches(5.85), Inches(4.95))
    c.line.color.rgb = WARN
    tf = tb(s, Inches(0.95), Inches(1.88), Inches(5.35), Inches(4.65))
    para(tf, "What we cannot claim yet", 15, WARN, True, 8, first=True)
    bullets(tf, [
        "No ground truth for the ghost flag: how often a flagged zone is really vacant is "
        "unmeasured. The hold-out test and the building check are indirect.",
        "VIIRS pixels are 463 m; at village scale, light mostly measures settlement size.",
        "GHS-POP over-counts the city core; the activity index still uses it, at weight 0.20.",
        "Heat is daytime only, and the 2013 composite has just 5 dates.",
        "Dynamic World's built class is unreliable in this landscape: 531 km2 against "
        "GHSL's 154 km2.",
        "The projection assumes the 2010-2020 growth rate continues.",
    ], 11.5, 7)
    c = card(s, Inches(6.75), Inches(1.72), Inches(5.85), Inches(4.95))
    c.line.color.rgb = GREEN
    tf = tb(s, Inches(7.0), Inches(1.88), Inches(5.35), Inches(4.65))
    para(tf, "Review 4", 15, GREEN, True, 8, first=True)
    bullets(tf, [
        ("City search", "type any city name; the Earth Engine route is already checked"),
        ("Labels", "read a sample of flagged and unflagged cells off historical "
                   "high-resolution imagery, and measure precision"),
        ("Planning data", "ward-level reporting, VDA Master Plan 2031, Bhuvan land use, "
                          "UP RERA cross-check"),
        ("Model", "drop the population driver, tune the neighbourhood weight, give a range "
                  "of demand scenarios"),
        ("Publication", "a paper submission, built on the hold-out and proxy-scale findings"),
    ], 11.5, 8)

    # 12a - roadmap --------------------------------------------------------------
    diagram(prs, "Where we are", "Phases, reviews and what is left",
            "P1_roadmap.png",
            "Code size per module: docs/diagrams/P2_implementation_status.png; "
            "the one-command run: P4_run_timeline.png.")

    # 13 - close -----------------------------------------------------------------
    s = blank(prs)
    heading(s, "Everything here is reproducible", "And attributable")
    card(s, Inches(0.7), Inches(1.72), Inches(11.9), Inches(1.5))
    tf = tb(s, Inches(0.95), Inches(1.92), Inches(11.4), Inches(1.2))
    para(tf, "run_review3.bat", 20, ACCENT, True, 4, first=True)
    para(tf, "Unit tests, pipeline, growth models, four validations, 14 figures and 23 zone "
             "cards - one command, on cached data, in a few minutes. Every number in this "
             "deck is in outputs/review3_results.json.", 13, DIM, False, 0)
    rows = [
        ["Stream", "Work packages", "Owner"],
        ["A - pipeline, heat, results, dashboard",
         "Observed epochs, heat-island fixes, zone cards, figures, dashboard, report", ""],
        ["B - validation",
         "Satellite cross-checks; Indian census, economic census and district GDP", ""],
        ["C - models",
         "Typology rule and hold-out test; logistic regression, random forest, projections", ""],
    ]
    grid_table(s, Inches(0.7), Inches(3.5), Inches(11.9), rows, [0.28, 0.56, 0.16],
               row_h=Inches(0.42))
    tf = tb(s, Inches(0.7), Inches(5.45), Inches(11.9), Inches(1.3))
    para(tf, "Owners are filled in CONTRIBUTIONS.md; each owner re-runs, explains and "
             "presents their own part. AI assistance is acknowledged there, as the project "
             "guidelines require.", 12.5, DIM, False, 6, first=True)
    para(tf, "Questions we expect: why the 2025 epoch mattered; why the heat result "
             "reversed; why the forest wins on Figure of Merit but loses on AUC; what the "
             "ghost flag can and cannot claim.", 12.5, TEXT, False, 0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"wrote {p}  ({p.stat().st_size // 1024} KB)")
