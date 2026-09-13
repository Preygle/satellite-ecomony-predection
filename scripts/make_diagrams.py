"""Architecture diagrams and progress charts for the reviews.

    python scripts/make_diagrams.py            # everything
    python scripts/make_diagrams.py A3 P1      # just some
    python scripts/make_diagrams.py --clean    # talk version, no code names,
                                               # into docs/diagrams/presentation/

Writes PNG (for slides and the report) and SVG (editable text) into
``docs/diagrams/``. Numbers are read from ``outputs/review3_results.json``
and the other pipeline outputs, so a re-run after new results keeps every
label true. What each image shows, and what to say over it, is in
``docs/DIAGRAMS.md``.

Architecture                              Progress
  A1  system architecture                   P1  roadmap and reviews
  A2  pipeline data flow                    P2  implementation status and code size
  A3  ghost-growth typology algorithm       P3  corrections: Review 2 vs Review 3
  A4  relative night-light trend            P4  one-command run, step by step
  A5  growth-model architecture             P5  data inventory
  A6  heat-island method                    P6  tests and defects
  A7  validation framework
  A8  temporal design of the study
  A9  analysis grid and aggregation

Colour follows the dataviz reference palette (validated for colour-blind
separation): each architecture layer takes one categorical hue in a fixed
order, and state (done / planned / supports / qualified) uses the reserved
status colours, always with a text label beside them.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

from urbanintel.analysis.ghost import TYPE_COLOURS, TYPE_LABELS  # noqa: E402

OUT = ROOT / "docs" / "diagrams"
# --clean renders the talk version into docs/diagrams/presentation/: module,
# file and function names are replaced by what the component does.
CLEAN = False


def c(dev: str, talk: str):
    """Developer label normally; plain-language label in --clean mode."""
    return talk if CLEAN else dev

# ------------------------------------------------------------------ tokens ---
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
HAIR, BASE = "#e1e0d9", "#c3c2b7"
# Categorical slots 1-5, fixed order (dataviz reference palette, validated).
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
LAYER = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA]
# Status palette - reserved for state, always paired with a label.
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
CLASS_COLOUR = {label: TYPE_COLOURS[code] for code, label in TYPE_LABELS.items()}

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 10,
    "svg.fonttype": "none",          # keep SVG text editable
    "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": HAIR, "grid.linewidth": 0.6, "axes.axisbelow": True,
})


def tint(hex_colour: str, t: float = 0.12) -> tuple:
    """`hex_colour` mixed with white; t = share of the colour."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (1 - t + t * r, 1 - t + t * g, 1 - t + t * b)


def load(name: str) -> dict:
    p = ROOT / "outputs" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


R = load("review3_results.json")
S = load("varanasi_summary.json")
G = load("varanasi_growth_model.json")


def val(path: str, default=None):
    """Dotted lookup into review3_results.json."""
    node = R
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ----------------------------------------------------------------- drawing ---

def canvas(w: float = 16, h: float = 9):
    """A blank figure whose coordinates are tenths of an inch."""
    fig = plt.figure(figsize=(w, h), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w * 10)
    ax.set_ylim(0, h * 10)
    ax.set_autoscale_on(False)
    ax.axis("off")
    return fig, ax


def title(ax, text: str, sub: str | None = None, h: float = 90):
    if CLEAN:   # the slide carries the title; the image keeps only the drawing
        return
    ax.text(3, h - 3.2, text, size=19, weight="bold", color=INK, va="top")
    if sub:
        ax.text(3, h - 7.4, sub, size=11, color=INK2, va="top")


def box(ax, x, y, w, h, head, lines=(), hue=BASE, fill=None, hsize=10.5, bsize=8.8,
        bold=True, lw=1.3, align="center"):
    """A rounded box: a bold head line and optional body lines, in ink."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.1",
                                fc=fill if fill is not None else "white", ec=hue, lw=lw))
    n = len(lines)
    total = 1.9 + 1.55 * n
    top = y + h / 2 + total / 2
    tx = x + w / 2 if align == "center" else x + 1.4
    ax.text(tx, top - 0.95, head, size=hsize, weight="bold" if bold else "normal", color=INK,
            ha=align if align != "center" else "center", va="center")
    for i, line in enumerate(lines):
        ax.text(tx, top - 1.9 - 1.55 * i - 0.75, line, size=bsize, color=INK2,
                ha=align if align != "center" else "center", va="center")
    return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y + h),
            "b": (x + w / 2, y), "x": x, "y": y, "w": w, "h": h}


def diamond(ax, cx, cy, w, h, lines, hue=INK2):
    ax.add_patch(Polygon([(cx - w / 2, cy), (cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2)],
                         closed=True, fc="white", ec=hue, lw=1.3))
    n = len(lines)
    for i, line in enumerate(lines):
        ax.text(cx, cy + (n - 1) * 0.8 - i * 1.6, line, size=8.8, color=INK, ha="center",
                va="center", weight="bold" if i == 0 else "normal")
    return {"l": (cx - w / 2, cy), "r": (cx + w / 2, cy), "t": (cx, cy + h / 2), "b": (cx, cy - h / 2)}


def arrow(ax, a, b, label=None, color=INK2, lw=1.2, dashed=False, conn="arc3,rad=0",
          loff=(0, 0), lsize=8.3, lcolor=None, ha="center"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, lw=lw, color=color,
                                 linestyle=(0, (4, 3)) if dashed else "-", connectionstyle=conn,
                                 shrinkA=0, shrinkB=0))
    if label:
        mx, my = (a[0] + b[0]) / 2 + loff[0], (a[1] + b[1]) / 2 + loff[1]
        ax.text(mx, my, label, size=lsize, color=lcolor or INK2, ha=ha, va="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))


def route(ax, pts, label=None, color=INK2, lw=1.2, dashed=False, seg=None, loff=(0, 0),
          lsize=8.3, ha="center"):
    """An orthogonal connector through `pts`, with the arrowhead on the last leg.

    `seg` picks the leg that carries the label (default: the longest one).
    """
    ls = (0, (4, 3)) if dashed else "-"
    for (x1, y1), (x2, y2) in zip(pts[:-2], pts[1:-1]):
        ax.plot([x1, x2], [y1, y2], color=color, lw=lw, linestyle=ls, solid_capstyle="butt")
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=11, lw=lw,
                                 color=color, linestyle=ls, shrinkA=0, shrinkB=0))
    if label:
        legs = range(len(pts) - 1)
        i = seg if seg is not None else max(
            legs, key=lambda k: abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1]))
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        ax.text((x1 + x2) / 2 + loff[0], (y1 + y2) / 2 + loff[1], label, size=lsize, color=INK2,
                ha=ha, va="center", bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))


def chip(ax, x, y, text, colour, size=8.5, w=None):
    """A status chip: a coloured dot plus the state written out."""
    ax.add_patch(plt.Circle((x + 0.9, y), 0.7, color=colour))
    ax.text(x + 2.1, y, text, size=size, color=INK, va="center")


def save(fig, name: str):
    out = OUT / "presentation" if CLEAN else OUT
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(out / f"{name}.{ext}", dpi=200, facecolor="white", bbox_inches="tight",
                    pad_inches=0.15)
    plt.close(fig)
    if CLEAN:   # trim the blank band the dropped title leaves, so the slide can use the space
        from PIL import Image, ImageChops
        p = out / f"{name}.png"
        im = Image.open(p).convert("RGB")
        box_ = ImageChops.difference(im, Image.new("RGB", im.size, "white")).getbbox()
        if box_:
            m = 30
            im.crop((max(box_[0] - m, 0), max(box_[1] - m, 0),
                     min(box_[2] + m, im.width), min(box_[3] + m, im.height))).save(p)
    print(f"  wrote {out.relative_to(ROOT).as_posix()}/{name}.png / .svg")


def fmt(x, nd=2, default="-"):
    return default if x is None else f"{x:.{nd}f}"


# ================================================================ diagrams ===

def a1_system():
    fig, ax = canvas(16, 9.2)
    title(ax, "System architecture",
          c("Five layers, each a folder of the code. Data moves top to bottom; every arrow is a real hand-off.",
            "Five layers. Data moves top to bottom; every arrow is a real hand-off."), 92)
    lanes = [("Data sources", "open, Earth Engine, Indian records"),
             ("Acquisition and common grid", c("src/urbanintel/data, aoi.py", "download, clean, align")),
             ("Analysis", c("src/urbanintel/pipeline.py", "per 100 m cell")),
             ("Prediction and validation", c("analysis/growth_model.py, scripts/", "what next; is it right?")),
             ("Outputs and presentation", c("outputs/, dashboard/, docs/", "maps, dashboard, report"))]
    top, lh, gap = 80, 13.2, 2.9
    ys = [top - (i + 1) * lh - i * gap for i in range(5)]
    for (name, sub), y, hue in zip(lanes, ys, LAYER):
        ax.add_patch(Rectangle((2, y), 156, lh, fc=tint(hue, 0.07), ec="none"))
        ax.add_patch(Rectangle((2, y), 0.9, lh, fc=hue, ec="none"))
        ax.text(4.2, y + lh / 2 + 1.3, name, size=11, weight="bold", color=INK, va="center")
        ax.text(4.2, y + lh / 2 - 1.5, sub, size=8.2, color=INK2, va="center")

    def row(y, specs, hue):
        out = []
        for x, w, head, lines in specs:
            out.append(box(ax, x, y + 1.4, w, lh - 2.8, head, lines, hue=hue, hsize=10, bsize=8.4))
        return out

    L1 = row(ys[0], [
        (27, 34, "Open data, no account", ["GHS-BUILT-S, GHS-POP R2023A", "OpenStreetMap (Overpass API)"]),
        (64, 52, "Google Earth Engine", ["NOAA/VIIRS/DNB/ANNUAL_V21, _V22 · Sentinel-2 · Landsat 8/9",
                                         "MODIS · Dynamic World · Open Buildings · WorldCover",
                                         "SRTM · WorldPop"]),
        (119, 38, "Indian records", ["SHRUG: Census 2001 and 2011,", "2013 Economic Census",
                                     "UP district GDP (DES, Govt of UP)"]),
    ], BLUE)
    L2 = row(ys[1], [
        (27, 23, c("ghsl.py", "GHSL reader"), ["density-preserving", "reprojection"]),
        (52, 17, c("osm.py", "OSM reader"), ["POIs, roads"]),
        (71, 33, c("gee.py", "Earth Engine layers"),
         c(["cloud masks, composite-depth check,", "50 MB download ladder"],
           ["cloud and shadow masks,", "minimum-dates check"])),
        (106, 18, c("shrug.py", "Census joins"), ["town / village", "joins"]),
        (126, 31, c("aoi.py — one grid", "One common grid"), ["100 m analysis, UTM 44N", "500 m reporting, exact nesting"]),
    ], ORANGE)
    L3 = row(ys[2], [
        (27, 22, c("builtup.py", "Built-up change"), ["change, urban form"]),
        (51, 24, c("nightlights.py", "Night-light trend"), ["trend relative", "to the city"]),
        (77, 23, c("vegetation.py", "Green cover"), ["NDVI loss within", "built-up gain"]),
        (102, 22, c("thermal.py", "Heat island"), ["heat island,", "rural reference"]),
        (126, 31, c("ghost.py", "Ghost typology"), ["activity index, 6-class", "typology, 23 zones"]),
    ], AQUA)
    L4 = row(ys[3], [
        (27, 40, c("growth_model.py", "Growth model"), ["logistic regression vs random forest",
                                                        "cellular automaton, +5 / +10 years"]),
        (69, 22, c("validate_typology", "Typology check"), ["hold-out test"]),
        (93, 21, c("cross_checks", "Cross-checks"), ["6 built-up maps,", "MODIS"]),
        (116, 19, c("validate_population", "Population"), ["Census 2001/2011"]),
        (137, 20, c("validate_economy", "Economy"), ["EC 2013, GDP"]),
    ], YELLOW)
    L5 = row(ys[4], [
        (27, 40, c("outputs/", "Result layers"), c(["500 m grid GeoJSON · 61 rasters",
                                                    "summary and validation JSON"],
                                                   ["500 m grid · 61 map layers",
                                                    "summary and validation tables"])),
        (69, 27, "Dashboard", [c("Streamlit, 7 tabs", "interactive, 7 tabs")]),
        (98, 27, "Figures and zone cards", ["14 figures, 23 cards"]),
        (127, 30, "Report and deck", [c("REVIEW3_REPORT, PDF, slides", "report, PDF, slides")]),
    ], MAGENTA)

    arrow(ax, L1[0]["b"], L2[0]["t"], "HTTP, cached", loff=(6.5, 0))
    arrow(ax, L1[1]["b"], L2[2]["t"], "computed server-side, clipped to the study area",
          loff=(20, 0))
    arrow(ax, L1[2]["b"], L2[3]["t"], "zip archives", loff=(6.5, 0))
    arrow(ax, L2[4]["b"], L3[4]["t"], "every layer on one 100 m grid", loff=(-15, 0))
    arrow(ax, L3[0]["b"], L4[0]["t"], "built-up 2010/15/20, drivers", loff=(12, 0))
    yb, yt = L3[4]["b"][1], L4[1]["t"][1]
    route(ax, [L3[4]["b"], (L3[4]["b"][0], (yb + yt) / 2), (L4[1]["t"][0], (yb + yt) / 2),
               L4[1]["t"]], "typology, light series")
    arrow(ax, L4[0]["b"], L5[0]["t"], "suitability, 2025/2030 maps", loff=(12, 0))
    yb, yt = L4[3]["b"][1], L5[2]["t"][1]
    route(ax, [L4[3]["b"], (L4[3]["b"][0], (yb + yt) / 2), (L5[2]["t"][0], (yb + yt) / 2),
               L5[2]["t"]], c("validation JSON", "validation results"))
    arrow(ax, L5[0]["r"], L5[1]["l"])
    arrow(ax, L5[1]["r"], L5[2]["l"])
    arrow(ax, L5[2]["r"], L5[3]["l"])
    save(fig, "A1_system_architecture")


def a2_pipeline():
    fig, ax = canvas(16, 8.4)
    title(ax, "Pipeline data flow",
          c("python -m urbanintel.pipeline runs seven stages; arrows name what each stage hands to the next.",
            "Seven stages; each arrow names what one stage hands to the next."), 84)
    bw, bh = 25, 13
    st = {}
    # Left column: the three sources. Middle: vegetation over heat. Right: typology, export.
    st["builtup"] = box(ax, 4, 58, bw, bh, "1  Built-up", ["GHSL 2010 · 2015 · 2020",
                                                          "change, urban form"], hue=AQUA)
    st["gee"] = box(ax, 4, 36, bw, bh, "3  Earth Engine", ["VIIRS 2013-24, NDVI,",
                                                        "Dynamic World, LST"], hue=AQUA)
    st["osm"] = box(ax, 4, 14, bw, bh, "2  OpenStreetMap", ["POI density, road density"], hue=AQUA)
    st["veg"] = box(ax, 58, 47, bw, bh, "4  Vegetation", ["NDVI loss 2018-24 within",
                                                       "Dynamic World built gain"], hue=AQUA)
    st["heat"] = box(ax, 58, 25, bw, bh, "5  Heat", ["LST minus rural reference,",
                                                 "2013 and 2024"], hue=AQUA)
    st["ghost"] = box(ax, 97, 36, bw, bh, "6  Ghost typology", ["activity vs expected,",
                                                            "rising rule, zones"], hue=AQUA)
    st["export"] = box(ax, 131, 36, bw, bh, "7  Export", ["500 m grid, 61 rasters,",
                                                       "summary JSON"], hue=MAGENTA)

    b, g, o = st["builtup"], st["gee"], st["osm"]
    arrow(ax, b["b"], g["t"], "urban-in-2010 mask =\nreference for the light trend",
          loff=(1.8, 0), ha="left")
    route(ax, [(29, 66), (104, 66), (104, 49)], "built-up 2020 and its 2010-20 gain", seg=0)
    arrow(ax, (70.5, 66), st["veg"]["t"], "built fraction", loff=(6.5, 0))
    route(ax, [(29, 47), (44, 47), (44, 53.5), (58, 53.5)], "NDVI, DW built", seg=2, loff=(0, 1.9))
    arrow(ax, (29, 42.5), (97, 42.5), "light level 2022-24, relative trend", loff=(-20, 1.9))
    route(ax, [(29, 38), (44, 38), (44, 31.5), (58, 31.5)], "LST, water", seg=2, loff=(0, -1.9))
    route(ax, [(29, 20.5), (110, 20.5), (110, 36)], "POI density", seg=0)
    arrow(ax, st["veg"]["b"], st["heat"]["t"], "NDVI 2024", loff=(-5.8, 2.6))
    arrow(ax, st["ghost"]["r"], st["export"]["l"])
    ax.text(143.5, 32, "stage 7 writes every layer", size=8.2, color=INK2, ha="center")
    ax.text(143.5, 30, "from stages 1-6", size=8.2, color=INK2, ha="center")

    ax.text(131, 10, "After the pipeline:", size=9.5, weight="bold", color=INK)
    after = c(["run_growth_model.py", "validate_typology.py · cross_checks.py",
               "validate_population.py · validate_economy.py",
               "make_figures.py · make_zone_cards.py"],
              ["growth model, 2025 and 2030", "hold-out test · satellite cross-checks",
               "census and economy checks", "figures and zone evidence cards"])
    for i, t in enumerate(after):
        ax.text(131, 7.5 - i * 2.1, t, size=8.4, color=INK2)
    ax.text(4, 9.3, c("Epoch discipline: Config.check_epochs() runs first and refuses any GHSL epoch "
                      "after 2020 as a measurement.",
                      "Epoch discipline: a check runs first and refuses any GHSL epoch after 2020 "
                      "as a measurement."), size=8.8, color=INK2)
    save(fig, "A2_pipeline_dataflow")


def a3_ghost():
    fig, ax = canvas(16, 9.6)
    title(ax, "Ghost-growth typology: the algorithm",
          "Per 100 m cell. A cell is judged against comparably built land in the same city, not a fixed threshold.", 96)
    areas = val("typology.areas_km2", {}) or {}
    y1 = 70
    b_in = box(ax, 3, y1, 33, 14, "Inputs per cell", ["built-up 2010 and 2020 (GHSL)",
                                                     "night light, 2022-24 mean (VIIRS)",
                                                     "POI density (OSM), population 2020"], hue=BLUE)
    b_ai = box(ax, 42, y1, 36, 14, "Activity index", ["rank of each signal per km2 built,",
                                                     "weights: light 0.45, POIs 0.35,",
                                                     "population 0.20"], hue=AQUA)
    b_ex = box(ax, 84, y1, 34, 14, "Expected activity", ["median activity of cells with",
                                                        "similar built-up fraction",
                                                        "(20 quantile bins)"], hue=AQUA)
    b_rs = box(ax, 124, y1, 33, 14, "Residual", ["actual minus expected;", "negative = under-used",
                                                 "for how built it is"], hue=AQUA)
    arrow(ax, b_in["r"], b_ai["l"])
    arrow(ax, b_ai["r"], b_ex["l"])
    arrow(ax, b_ex["r"], b_rs["l"])

    yd = 46
    d1 = diamond(ax, 19, yd, 26, 15, ["Urban?", ">= 20% built", "in 2020"])
    d2 = diamond(ax, 55, yd, 26, 15, ["New?", ">= 50% of built-up", "added since 2010"])
    d3 = diamond(ax, 93, yd, 28, 15, ["Under-used?", "residual < 0 and in", "the bottom 25%"])
    d4 = diamond(ax, 134, yd, 36, 17, ["Light rising faster", "than the city?",
                                        "relative slope > 0, p <= 0.10"])
    arrow(ax, (19, y1), d1["t"], "for every cell", loff=(7, 0))
    route(ax, [b_rs["b"], (b_rs["b"][0], 63), (93, 63), d3["t"]], "residual", seg=1)
    ax.text(134, 58.4, "input: night-light trend relative", size=8.3, color=INK2, ha="center")
    ax.text(134, 56.4, c("to the city, 2013-2024 (see A4)", "to the city, 2013-2024"), size=8.3,
            color=INK2, ha="center")
    arrow(ax, d1["r"], d2["l"], "yes", loff=(0, 1.6))
    arrow(ax, d2["r"], d3["l"], "yes", loff=(0, 1.6))
    arrow(ax, d3["r"], d4["l"], "yes", loff=(0, 1.6))

    yc = 14
    def cls(x, w, label, name, note):
        a = areas.get(label)
        head = f"{name}" + (f"   {a:.2f} km2" if a is not None else "")
        return box(ax, x, yc, w, 12, head, [note], hue=CLASS_COLOUR[label],
                   fill=tint(CLASS_COLOUR[label], 0.16), hsize=9.8, bsize=8.3)
    c_und = cls(3, 30, "undeveloped", "Undeveloped", "below the urban cut")
    c_est = cls(36, 34, "established_active", "Established", "built before 2010")
    c_hea = cls(73, 30, "healthy_growth", "Healthy growth", "new, used as expected")
    c_eme = cls(106, 25, "emerging", "Emerging", "new, filling up")
    c_gho = cls(134, 24, "ghost_growth", "Ghost growth", "new, not filling up")
    arrow(ax, d1["b"], (19, yc + 12), "no", loff=(2.5, 0))
    arrow(ax, d2["b"], (55, yc + 12), "no", loff=(2.5, 0))
    arrow(ax, d3["b"], (93, yc + 12), "no", loff=(2.5, 0))
    ybr = 31
    route(ax, [d4["b"], (134, ybr), (c_eme["t"][0], ybr), c_eme["t"]], "yes", seg=2, loff=(2.4, 0))
    route(ax, [d4["b"], (134, ybr), (c_gho["t"][0], ybr), c_gho["t"]], "no", seg=2, loff=(2.2, 0))

    dec = areas.get("declining")
    ax.text(36, 8.8, "Established cells that are under-used AND significantly falling behind the city "
                     f"become Declining ({fmt(dec)} km2).", size=8.5, color=INK2)
    nz = val("typology.n_zones")
    ax.text(134, 8.8, f"Ghost cells then group into {nz} zones:", size=8.5, color=INK, weight="bold")
    ax.text(134, 6.6, "flagged at >= 2x the citywide", size=8.3, color=INK2)
    ax.text(134, 4.6, "rate, >= 0.25 km2 each", size=8.3, color=INK2)
    save(fig, "A3_ghost_typology_algorithm")


def a4_relative_trend():
    """Real series: established city vs emerging vs ghost cells, raw and relative."""
    try:
        import rasterio

        from urbanintel.aoi import AOI
        from urbanintel.config import load_config
        from urbanintel.data import gee
    except Exception as exc:  # noqa: BLE001
        print(f"  skip A4: {exc}")
        return
    cfg = load_config()
    rdir, raw = cfg.processed_dir / "rasters", cfg.raw_dir / "gee"
    if not (rdir / "typology.tif").exists():
        print("  skip A4: run the pipeline first")
        return
    fine, _ = AOI(cfg).frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    with rasterio.open(rdir / "typology.tif") as ds:
        typ = ds.read(1).astype(int)
    with rasterio.open(rdir / f"builtup_m2_{cfg.epoch_baseline}.tif") as ds:
        ref = np.nan_to_num(ds.read(1)) / fine.res**2 >= 0.2
    years = list(range(2013, 2025))
    stack = {y: np.nan_to_num(gee.to_frame(raw / f"ntl_{y}.tif", fine)) for y in years}
    groups = {"established city (urban in 2010)": (ref, BASE),
              "emerging cells": (typ == 3, YELLOW),
              "ghost-growth cells": (typ == 4, CRITICAL)}

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for (name, (mask, colour)) in groups.items():
        raw_series = [float(np.median(stack[y][mask])) for y in years]
        rel = [float(np.median(np.log1p(stack[y][mask])) - np.median(np.log1p(stack[y][ref])))
               for y in years]
        axes[0].plot(years, raw_series, color=colour if colour != BASE else INK2, lw=2,
                     marker="o", ms=4, label=name)
        axes[1].plot(years, rel, color=colour if colour != BASE else INK2, lw=2, marker="o", ms=4,
                     label=name)
    for a in axes:
        a.axvline(2021.5, color=MUTED, ls="--", lw=0.8)
        a.set_xticks([2013, 2016, 2019, 2022, 2024])
    axes[0].text(2021.6, axes[0].get_ylim()[1] * 0.97, "V21 | V22", size=8, color=MUTED, va="top")
    axes[0].set_title("1. Raw radiance: everything brightens", fontsize=11.5, loc="left",
                      color=INK, weight="bold")
    axes[0].set_ylabel("median radiance (nW/cm2/sr)")
    axes[1].axhline(0, color=INK2, lw=0.9)
    axes[1].set_title("2. Relative to the city: who is catching up", fontsize=11.5, loc="left",
                      color=INK, weight="bold")
    axes[1].set_ylabel("log radiance minus the city's median")
    axes[1].legend(fontsize=8.5, frameon=False, loc="lower right")
    fig.text(0.01, -0.03, "Rule: a new, under-used cell is 'emerging' when the trend in panel 2 is "
                          "positive with p <= 0.10; a citywide rise or a product-version step "
                          "cancels out. Medians over 100 m cells.", size=9, color=INK2)
    if not CLEAN:
        fig.suptitle("Why the night-light trend is measured relative to the city", x=0.01, ha="left",
                     fontsize=15, weight="bold", color=INK, y=1.03)
    fig.tight_layout()
    save(fig, "A4_relative_light_trend")


def a5_growth():
    fig, ax = canvas(16, 9.2)
    title(ax, "Growth-model architecture",
          "Learn where the city grew, test on a period the model never saw, then project forward.", 92)
    m = G.get("models", {})
    lr = m.get("logistic_regression", {})
    rf = m.get("random_forest", {})
    pr = G.get("projections", {})
    n_train = lr.get("n_train_cells", 113082)
    n_pos = lr.get("n_conversions_observed", 1382)

    d = box(ax, 3, 50, 34, 26, "8 drivers per cell", ["distance to centre", "built-up nearby, 500 m and 1.5 km",
                                                      "distance to the urban edge", "road density (OSM)",
                                                      "population (GHS-POP)", "built-up fraction",
                                                      "slope (SRTM)"], hue=BLUE, align="left")
    t = box(ax, 43, 57, 30, 14, "Training sample", [f"{n_train:,} cells not urban in 2010",
                                                   f"{n_pos:,} became urban by 2015"], hue=ORANGE)
    lrb = box(ax, 79, 64, 32, 12, "Logistic regression", ["straight-line, readable weights"], hue=AQUA)
    rfb = box(ax, 79, 49, 32, 12, "Random forest", ["300 trees, >= 20 cells per leaf"], hue=AQUA)
    s = box(ax, 117, 55, 40, 16, "Suitability map", ["probability each non-urban cell",
                                                     "becomes urban"], hue=AQUA)
    arrow(ax, d["r"], t["l"], "drivers at 2010")
    route(ax, [t["r"], (76, t["r"][1]), (76, lrb["l"][1]), lrb["l"]])
    route(ax, [t["r"], (76, t["r"][1]), (76, rfb["l"][1]), rfb["l"]])
    route(ax, [lrb["r"], (114, lrb["r"][1]), (114, 66), (s["x"], 66)])
    route(ax, [rfb["r"], (114, rfb["r"][1]), (114, 60), (s["x"], 60)])

    ca = box(ax, 117, 25, 40, 20, "Cellular automaton", ["demand N cells, placed in 8 rounds",
                                                         "score = 0.65 suitability",
                                                         "+ 0.35 built-up nearby",
                                                         "(growth accretes, not scatters)"], hue=YELLOW)
    arrow(ax, s["b"], ca["t"], "rank cells")
    v = box(ax, 64, 22, 46, 24, "Held-out test, 2015 -> 2020", [
        f"random forest: FoM {fmt(rf.get('validation', {}).get('figure_of_merit'), 3)}, "
        f"AUC {fmt(rf.get('auc_test'), 2)}",
        f"logistic regr.: FoM {fmt(lr.get('validation', {}).get('figure_of_merit'), 3)}, "
        f"AUC {fmt(lr.get('auc_test'), 2)}",
        f"random allocation: FoM {fmt(G.get('random_baseline', {}).get('mean_figure_of_merit'), 4)}",
        "demand = the 1,214 cells that really converted"], hue=YELLOW)
    arrow(ax, (ca["x"], v["r"][1]), v["r"], "allocated map vs reality", loff=(0, 1.9))
    dem = box(ax, 3, 22, 34, 20, "Demand for the future", ["urban extent grew",
                                                           f"{val('builtup.annual_urban_growth_pct', 1.86)}% a year, 2010-20;",
                                                           "continued forward:",
                                                           f"{pr.get('2025', {}).get('demand_cells', '-')} cells by 2025,",
                                                           f"{pr.get('2030', {}).get('demand_cells', '-')} by 2030"], hue=BLUE)
    p25 = pr.get("2025", {}).get("demand_km2")
    p30 = pr.get("2030", {}).get("demand_km2")
    y_p = 6
    b25 = box(ax, 43, y_p, 34, 11, f"2025:  +{fmt(p25)} km2", ["5-year step from 2020"], hue=MAGENTA,
              fill=tint(MAGENTA, 0.14))
    b30 = box(ax, 86, y_p, 34, 11, f"2030:  +{fmt(p30)} km2", ["starts from the 2025 map;",
                                                               "built-up drivers recomputed"], hue=MAGENTA,
              fill=tint(MAGENTA, 0.14))
    route(ax, [dem["b"], (dem["b"][0], b25["l"][1]), b25["l"]], "how much", seg=1)
    arrow(ax, (70, v["b"][1]), (70, b25["t"][1]),
          f"better model: {G.get('best_model', 'random_forest').replace('_', ' ')}",
          loff=(1.5, 0), ha="left")
    arrow(ax, b25["r"], b30["l"], "+5 yr", loff=(0, 1.9), lsize=7.8)
    ax.text(124, 12.5, "Predictions, not observations.", size=9.5, weight="bold", color=INK)
    ax.text(124, 10.2, "Roads and population held at", size=8.5, color=INK2)
    ax.text(124, 8.2, "2020 values; no road leakage", size=8.5, color=INK2)
    ax.text(124, 6.2, "(FoM identical without roads).", size=8.5, color=INK2)
    save(fig, "A5_growth_model")


def a6_heat():
    fig, ax = canvas(16, 7.8)
    title(ax, "Surface heat island: the method",
          "Land surface temperature minus a rural reference taken from the same scene.", 78)
    th = val("thermal", {}) or {}
    y = 46
    l1 = box(ax, 3, y, 30, 16, "Landsat 8 + 9", ["LANDSAT/LC08, LC09", "C02 T1_L2, band ST_B10",
                                                "March-May 2013, 2024"], hue=BLUE)
    l2 = box(ax, 39, y, 30, 16, "Quality gates", ["QA_PIXEL bits 1-4 masked", "(cloud, shadow, cirrus)",
                                                 ">= 4 acquisition dates"], hue=ORANGE)
    l3 = box(ax, 75, y, 26, 16, "LST, deg C", ["median composite", "on the 100 m grid"], hue=AQUA)
    rr = box(ax, 39, 12, 44, 20, "Rural reference cells", ["GHSL 2020 built surface < 2%",
                                                         "AND not water (Dynamic World)",
                                                         "AND not built by 2024 (DW < 0.2)",
                                                         f"median = {fmt(th.get('rural_reference_c'))} deg C (2024)"],
             hue=ORANGE)
    it = box(ax, 108, y, 49, 16, "Intensity = LST - rural median", ["hotspot: intensity >= +3 deg C",
                                                                   "mean taken over urban cells",
                                                                   "(>= 20% built)"], hue=AQUA)
    arrow(ax, l1["r"], l2["l"])
    arrow(ax, l2["r"], l3["l"])
    arrow(ax, l3["r"], it["l"])
    # Around the LST box, into the bottom of the intensity box.
    route(ax, [rr["r"], (104, rr["r"][1]), (104, 38), (118, 38), (118, y)],
          "rural median, subtracted", seg=0, loff=(0, 1.9))
    res = box(ax, 108, 8, 49, 22, "Result, March-May 2024", [
        f"mean over urban cells: {fmt(th.get('mean_urban_intensity_c'))} deg C",
        f"hotspots: {fmt(th.get('hotspot_area_km2'))} km2, 94% on rural land",
        "MODIS/061/MOD11A2 agrees: no daytime",
        "heat island (urban - rural +0.0 deg C, 1 km)"], hue=MAGENTA, fill=tint(MAGENTA, 0.12))
    arrow(ax, it["b"], res["t"])
    ax.text(3, 26, "Why the reference matters", size=10, weight="bold", color=INK)
    for i, line in enumerate(["The Ganga and recently built land used",
                              "to sit in the rural set; removing them",
                              "moved the reference 41.18 -> 41.42 deg C",
                              "and hotspots 28.2 -> 23.8 km2."]):
        ax.text(3, 23 - i * 2.2, line, size=8.6, color=INK2)
    save(fig, "A6_heat_island_method")


def a7_validation():
    fig, ax = canvas(16, 8.6)
    title(ax, "Validation framework",
          "Every headline claim is checked against evidence the method never used.", 86)
    t = val("typology_holdout.cells", {}) or {}
    tb = val("typology_holdout.blocks_500m", {}) or {}
    k = val("kappa_vs_ghsl", {}) or {}
    rows = [
        ("Emerging vs ghost split is real", "Night light 2021-24, unseen when", "one-sided Mann-Whitney",
         f"p = {fmt(t.get('p_value'), 3)} cells, {fmt(tb.get('p_value'), 3)} blocks", GOOD, "supports, modest effect",
         "classifying on 2013-20"),
        ("GHSL built-up is right", "WorldCover, Open Buildings,", "Cohen's kappa per cell",
         f"kappa {fmt(k.get('Open Buildings', {}).get('kappa'))} OB, {fmt(k.get('WorldCover', {}).get('kappa'))} WC, "
         f"{fmt(k.get('Dynamic World', {}).get('kappa'))} DW", GOOD, "supports; DW unreliable here",
         "Dynamic World, NDBI"),
        ("Flagged cells are built", "Open Buildings 2023", "share with buildings",
         "82% built; 26 of 144 empty", WARNING, "qualified", ""),
        ("Heat measurements", "MODIS/061/MOD11A2, 1 km", "R2, urban - rural contrast",
         "R2 0.33; no heat island in either", GOOD, "supports the direction", ""),
        ("Population inputs", "Census of India 2011 (71 districts)", "error vs census",
         "WorldPop -0.4%, GHS-POP +3.4% (+63% in city)", WARNING, "qualified: report a range",
         "and 2001-11 growth"),
        ("Night light = activity", "2013 Economic Census; UP district", "Spearman rho, elasticity",
         "rho 0.41 villages, 0.85 districts", WARNING, "holds at district scale", "GDP (DES)"),
    ]
    cols = [(3, 36, "What we claim"), (41, 36, "Independent evidence"), (79, 26, "Test"),
            (107, 32, "Result"), (141, 18, "Verdict")]
    y0 = 71
    for x, w, h in cols:
        ax.text(x + 0.5, y0, h, size=10, weight="bold", color=INK, va="center")
    ax.plot([3, 157], [y0 - 2.2, y0 - 2.2], color=BASE, lw=1)
    rh = 10.3
    for i, (claim, ev, test, result, st, verdict, ev2) in enumerate(rows):
        yc = y0 - 7.5 - i * rh
        ax.add_patch(Rectangle((3, yc - rh / 2 + 0.6), 154, rh - 1.2,
                               fc=tint(BLUE, 0.05) if i % 2 == 0 else "white", ec="none"))
        ax.text(3.5, yc, claim, size=9.6, weight="bold", color=INK, va="center")
        ax.text(41.5, yc + (1.1 if ev2 else 0), ev, size=8.8, color=INK2, va="center")
        if ev2:
            ax.text(41.5, yc - 1.4, ev2, size=8.8, color=INK2, va="center")
        ax.text(79.5, yc, test, size=8.8, color=INK2, va="center")
        ax.text(107.5, yc, result, size=8.8, color=INK, va="center")
        two = ";" in verdict or ":" in verdict
        chip(ax, 140.5, yc + (1.2 if two else 0), verdict.split(";")[0].split(":")[0], st, size=8.3)
        if two:
            rest = verdict.split(";")[1].strip() if ";" in verdict else verdict.split(":")[1].strip()
            ax.text(142.6, yc - 1.4, rest, size=7.8, color=INK2, va="center")
    ax.text(3, 3, "Green = the evidence supports the claim; amber = supports it with a stated "
                  "qualification. Colours always come with the verdict written out.", size=8.5,
            color=INK2)
    save(fig, "A7_validation_framework")


def a8_timeline():
    fig, ax = plt.subplots(figsize=(15, 8.4))
    rows = []  # (label, group, [(start, end, kind, text)])
    rows += [
        ("GHS-BUILT-S / GHS-POP", "data", [(2010, 2010, "pt", ""), (2015, 2015, "pt", ""),
                                           (2020, 2020, "pt", "observed"), (2025, 2025, "proj", ""),
                                           (2030, 2030, "proj", "projection, never used as data")]),
        ("VIIRS night light", "data", [(2013, 2022, "bar", "ANNUAL_V21"), (2022, 2025, "bar2", "V22")]),
        ("Sentinel-2 (NDVI)", "data", [(2018.75, 2019.25, "bar", "Oct-Mar"), (2024.75, 2025.25, "bar", "")]),
        ("Landsat 8/9 (LST)", "data", [(2013.17, 2013.42, "bar", "Mar-May"), (2024.17, 2024.42, "bar", "")]),
        ("Dynamic World / Open Buildings", "data", [(2016, 2016, "pt", ""), (2018, 2018, "pt", ""),
                                                    (2023, 2023, "pt", ""), (2024, 2024, "pt", "")]),
        ("Census / Economic Census", "india", [(2001, 2001, "pt", "Census"), (2011, 2011, "pt", "Census"),
                                               (2013, 2013, "pt", "EC")]),
        ("UP district GDP", "india", [(2020.25, 2022.25, "bar", "2020-21, 2021-22")]),
        ("Built-up change", "analysis", [(2010, 2020, "bar", "2010 -> 2020, observed")]),
        ("Growth model", "analysis", [(2010, 2015, "bar", "train"), (2015, 2020, "bar2", "test"),
                                      (2020, 2030, "projbar", "project +5, +10")]),
        ("Typology hold-out", "analysis", [(2013, 2021, "bar", "classify"), (2021, 2025, "bar2", "check")]),
        ("Activity level", "analysis", [(2022, 2025, "bar", "2022-24 mean")]),
    ]
    colour = {"data": BLUE, "india": ORANGE, "analysis": AQUA}
    n = len(rows)
    for i, (label, grp, spans) in enumerate(rows):
        y = n - i
        c = colour[grp]
        for s, e, kind, text in spans:
            if kind == "pt":
                ax.plot([s], [y], marker="o", ms=9, color=c, mec="white", mew=1.5, zorder=3)
            elif kind == "proj":
                ax.plot([s], [y], marker="o", ms=9, mfc="white", mec=c, mew=1.8, zorder=3)
            elif kind in ("bar", "bar2", "projbar"):
                fc = c if kind == "bar" else tint(c, 0.55) if kind == "bar2" else "white"
                ax.add_patch(Rectangle((s, y - 0.28), e - s, 0.56, fc=fc, ec=c, lw=1.2,
                                       hatch="///" if kind == "projbar" else None, zorder=2))
            if text:
                tx = e + 0.25 if kind in ("pt", "proj") else (s + e) / 2
                ha = "left" if kind in ("pt", "proj") else "center"
                ax.text(tx, y + (0 if kind in ("pt", "proj") else 0.5), text, size=8.3, color=INK2,
                        ha=ha, va="center" if kind in ("pt", "proj") else "bottom", zorder=4,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))
    ax.set_yticks(range(1, n + 1))
    ax.set_yticklabels([r[0] for r in rows][::-1], fontsize=9.5)
    ax.set_xlim(2000, 2031.5)
    ax.set_ylim(0.3, n + 0.9)
    ax.set_xticks(range(2000, 2031, 5))
    ax.axvline(2020, color=INK2, lw=1, ls="--", zorder=1)
    ax.text(2020.15, n + 0.65, "2020: last observed GHSL epoch", size=8.3, color=INK2)
    ax.grid(axis="y", visible=False)
    for grp, name in (("data", "satellite and gridded data"), ("india", "Indian records"),
                      ("analysis", "analysis windows")):
        ax.plot([], [], color=colour[grp], lw=8, label=name)
    ax.legend(loc="lower left", fontsize=9, frameon=False, ncol=3)
    if not CLEAN:
        ax.set_title("Temporal design: which years feed which step", loc="left", fontsize=15,
                     weight="bold", color=INK, pad=14)
    fig.tight_layout()
    save(fig, "A8_temporal_design")


def a9_grid():
    fig, ax = canvas(15, 7.4)
    title(ax, "Analysis grid and aggregation",
          "Analysis at 100 m keeps change detection sharp; the dashboard reports at 500 m, "
          "which VIIRS can actually support.", 74)
    x0, y0, s = 6, 12, 8.4
    for r in range(5):
        for col in range(5):
            code = 0
            if (r, col) in ((1, 1), (1, 2), (2, 1)):
                code = 1
            if (r, col) == (3, 3):
                code = 4
            if (r, col) == (2, 3):
                code = 3
            fc = TYPE_COLOURS[code]
            ax.add_patch(Rectangle((x0 + col * s, y0 + (4 - r) * s), s, s,
                                   fc=tint(fc, 0.9) if code else "white", ec=BASE, lw=0.8))
    ax.add_patch(Rectangle((x0, y0), 5 * s, 5 * s, fc="none", ec=INK, lw=2))
    ax.text(x0, y0 - 3, "one 500 m reporting cell = 25 cells of 100 m", size=9, color=INK2)
    ax.text(x0 + 3 * s + s / 2, y0 + 1 * s + s / 2, "ghost", size=7.5, color="white", ha="center",
            va="center", weight="bold")
    ax.text(x0 + 3 * s + s / 2, y0 + 2 * s + s / 2, "emerging", size=7.2, color=INK, ha="center",
            va="center", weight="bold")
    ax.text(x0 + 1.5 * s, y0 + 3 * s + s / 2, "established", size=7.2, color=INK, ha="center",
            va="center", weight="bold")
    ax.text(x0, y0 - 5.4, "priority -> ghost growth;  majority -> undeveloped", size=9, color=INK)
    rows = [("sum", "extensive totals", "built-up m2, population, POIs", "totals survive exactly"),
            ("mean", "intensive values", "NDVI, LST, indices", "average of the 25"),
            ("any", "yes/no findings", "new urban, hotspots", "yes if any cell is yes"),
            ("priority", "class maps", "typology, urban form",
             "most important class present - one ghost cell among 24 stays visible")]
    xt = 60
    ax.text(xt, 57, c("How each layer is aggregated (zonal.block_reduce)", "How each layer is aggregated"),
            size=11, weight="bold", color=INK)
    for i, (how, kind, ex, rule) in enumerate(rows):
        y = 49 - i * 9.5
        box(ax, xt, y - 3.4, 16, 6.8, how, (), hue=ORANGE, fill=tint(ORANGE, 0.12), hsize=10)
        ax.text(xt + 19, y + 1.2, f"{kind}: {ex}", size=9.2, color=INK, va="center")
        ax.text(xt + 19, y - 1.6, rule, size=8.6, color=INK2, va="center")
    ax.text(xt, 7, "Why 'priority' and not 'majority': a majority vote erased every ghost-growth "
                   "cell from the map, because findings are a minority by nature.", size=8.6, color=INK2)
    save(fig, "A9_grid_and_aggregation")


# ================================================================ progress ===

def legend_patches(ax, specs, **kw):
    """Legend from explicit patches: (face, edge, hatch, label)."""
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor=f, edgecolor=e, hatch=h, label=lab) for f, e, h, lab in specs],
              frameon=False, fontsize=9, **kw)


def p1_roadmap():
    import datetime as dt
    D = lambda s: dt.date.fromisoformat(s)  # noqa: E731
    today = D("2026-09-12")
    fig, ax = plt.subplots(figsize=(15, 6.6))
    phases = [  # (name, start, end, state, label side)
        ("Phase 1: pipeline, open data", "2026-07-10", "2026-07-28", "done", "r"),
        ("Earth Engine layers, dashboard", "2026-07-28", "2026-08-17", "done", "r"),
        ("Literature, 20 papers, Review 2 docs", "2026-08-10", "2026-08-19", "done", "r"),
        ("Mentor task: Sentinel + Landsat app", "2026-08-19", "2026-08-24", "done", "r"),
        ("Audit: 15 defects found", "2026-09-09", "2026-09-11", "done", "l"),
        ("Fixes, validation, Indian data", "2026-09-10", "2026-09-12", "done", "l"),
        ("Rehearsal, owners commit their packages", "2026-09-12", "2026-09-15", "now", "r"),
        ("City search, labels, planning data", "2026-09-17", "2026-10-12", "planned", "r"),
        ("Report chapters 1-5, paper submission", "2026-09-24", "2026-10-21", "planned", "r"),
    ]
    colours = {"done": GOOD, "now": WARNING, "planned": "white"}
    edges = {"done": GOOD, "now": "#b07a00", "planned": INK2}
    n = len(phases)
    reviews = [("R1", "2026-07-10", "5"), ("R2", "2026-08-19", "20"), ("R3", "2026-09-16", "20"),
               ("R4", "2026-10-14", "25"), ("R5", "2026-10-21", "25")]
    for rname, d, marks in reviews:
        ax.vlines(D(d), 0, n + 0.55, color=INK2 if D(d) <= today else MUTED, lw=1, ls="--", zorder=1)
        ax.text(D(d), n + 0.75, f"{rname}\n{marks} marks", ha="center", va="bottom", fontsize=8.5,
                color=INK)
    ax.vlines(today, 0, n + 0.55, color=INK, lw=1.8, zorder=1)
    ax.text(today, 0.15, " today, 12 Sep", color=INK, fontsize=8.5, va="bottom", weight="bold")
    for i, (name, s, e, state, side) in enumerate(phases):
        y = n - i
        ax.barh(y, (D(e) - D(s)).days, left=D(s), height=0.55, color=colours[state],
                edgecolor=edges[state], linewidth=1.1, hatch="///" if state == "planned" else None,
                zorder=2)
        x, ha = (D(e) + dt.timedelta(days=1.5), "left") if side == "r" else (D(s) - dt.timedelta(days=1), "right")
        ax.text(x, y, name, va="center", ha=ha, fontsize=9, color=INK, zorder=3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))
    ax.set_yticks([])
    ax.set_ylim(0, n + 1.8)
    ax.set_xlim(D("2026-07-05"), D("2026-11-20"))
    ax.grid(axis="y", visible=False)
    legend_patches(ax, [(GOOD, GOOD, None, "done"), (WARNING, edges["now"], None, "in progress"),
                        ("white", INK2, "///", "planned")], loc="lower left")
    if not CLEAN:
        ax.set_title("Project roadmap and reviews", loc="left", fontsize=15, weight="bold", color=INK,
                     pad=28)
    fig.tight_layout()
    save(fig, "P1_roadmap")


def p2_status():
    mods = [  # (module, lines of code, state, note)
        ("pipeline.py", "src/urbanintel/pipeline.py", "done", "7 stages"),
        ("growth_model.py", "src/urbanintel/analysis/growth_model.py", "done", "extended: RF, TOC, +5"),
        ("ghost.py", "src/urbanintel/analysis/ghost.py", "done", "rule revised"),
        ("gee.py", "src/urbanintel/data/gee.py", "done", "13 layers"),
        ("ghsl.py", "src/urbanintel/data/ghsl.py", "done", ""),
        ("osm.py", "src/urbanintel/data/osm.py", "done", ""),
        ("aoi.py", "src/urbanintel/aoi.py", "done", ""),
        ("nightlights.py", "src/urbanintel/analysis/nightlights.py", "done", "relative trend"),
        ("builtup.py", "src/urbanintel/analysis/builtup.py", "done", "recomputed"),
        ("config.py", "src/urbanintel/config.py", "done", "epoch checks"),
        ("zonal.py", "src/urbanintel/analysis/zonal.py", "done", ""),
        ("thermal.py", "src/urbanintel/analysis/thermal.py", "done", "corrected"),
        ("shrug.py", "src/urbanintel/data/shrug.py", "new", "new in R3"),
        ("vegetation.py", "src/urbanintel/analysis/vegetation.py", "done", "periods matched"),
        ("validation.py", "src/urbanintel/analysis/validation.py", "new", "new in R3"),
        ("dashboard/app.py", "dashboard/app.py", "done", "7 tabs"),
        ("tests/test_core.py", "tests/test_core.py", "done", "41 tests"),
    ]

    def loc(path):
        p = ROOT / path
        return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()) if p.exists() else 0

    data = sorted([(name, loc(path), state, note) for name, path, state, note in mods],
                  key=lambda r: r[1])
    data.append(("city search", 0, "planned", "Review 4"))
    data.append(("image labels", 0, "planned", "Review 4"))
    fig, ax = plt.subplots(figsize=(12.5, 7.6))
    for i, (name, n, state, note) in enumerate(data):
        colour = GOOD if state in ("done", "new") else "white"
        ax.barh(i, max(n, 8), color=colour, edgecolor=GOOD if state != "planned" else INK2,
                hatch="///" if state == "planned" else None, height=0.62, linewidth=1)
        label = f"{n:,} lines" if n else ""
        extra = f"  ·  {note}" if note else ""
        ax.text(max(n, 8) + 8, i, f"{label}{extra}", va="center", fontsize=8.6, color=INK2)
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels([d[0] for d in data], fontsize=9.2)
    ax.set_xlabel("non-blank lines of code")
    ax.grid(axis="y", visible=False)
    scripts = sum(1 for p in (ROOT / "scripts").glob("*.py")
                  for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
    ax.set_title(f"Implementation status by module  ·  plus {scripts:,} lines in scripts/",
                 loc="left", fontsize=14, weight="bold", color=INK, pad=12)
    legend_patches(ax, [(GOOD, GOOD, None, "implemented"),
                        ("white", INK2, "///", "planned (Review 4)")], loc="lower right")
    ax.set_xlim(0, max(d[1] for d in data) * 1.45)
    fig.tight_layout()
    save(fig, "P2_implementation_status")


def p3_corrections():
    items = [  # (label, unit, review 2, review 3, note)
        ("New built-up surface", "km2", 23.47, val("builtup.net_builtup_change_km2", 17.25), "2010-2025 vs 2010-2020"),
        ("Urban extent growth", "% / yr", 1.40, val("builtup.annual_urban_growth_pct", 1.86), ""),
        ("Leapfrog share of new urban land", "%", 48.8, 44.3, ""),
        ("Ghost-growth area", "km2", 0.35, val("typology.areas_km2.ghost_growth", 1.44), "stricter rising rule"),
        ("Low-activity new land filling up", "%", 95.0, 74.0, "hold-out p = 0.010"),
        ("Mean urban heat-island intensity", "deg C", 1.10, val("thermal.mean_urban_intensity_c", -1.66), "urban cells only"),
        ("Green cover lost to built-up", "km2", 0.05, 0.67, "matched years"),
        ("Growth-model AUC", "", 0.9901, 0.910, "training vs held-out"),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.4))
    for a, (label, unit, before, after, note) in zip(axes.ravel(), items):
        lo, hi = min(before, after, 0), max(before, after)
        span = hi - lo or 1
        a.plot([before, after], [0, 0], color=BASE, lw=3, zorder=1)
        a.scatter([before], [0], s=110, color="white", edgecolor=INK2, linewidth=1.6, zorder=2)
        a.scatter([after], [0], s=110, color=BLUE, edgecolor="white", linewidth=1.5, zorder=3)
        a.text(before, 0.35, f"{before:g}", ha="center", fontsize=9.5, color=INK2)
        a.text(after, -0.42, f"{after:g}", ha="center", fontsize=10.5, color=INK, weight="bold")
        a.set_xlim(lo - span * (0.25 if lo < 0 else 0.06), hi + span * 0.25)
        a.set_ylim(-1, 1)
        a.set_yticks([])
        a.grid(False)
        a.spines["left"].set_visible(False)
        if lo < 0 < hi:
            a.axvline(0, color=HAIR, lw=1)
        a.set_title(label + (f" ({unit})" if unit else ""), fontsize=9.8, color=INK, loc="left")
        if note:
            a.text(0.0, -0.18, note, transform=a.transAxes, fontsize=8.2, color=INK2)
        a.tick_params(axis="x", labelsize=8)
    if not CLEAN:
        fig.suptitle("What the audit changed: Review 2 (hollow) vs Review 3 (filled)", x=0.01,
                     ha="left", fontsize=15, weight="bold", color=INK)
    fig.tight_layout()
    save(fig, "P3_corrections_before_after")


def p4_run():
    steps = [("Unit tests", 2.5), ("Analysis pipeline", 76.4), ("Growth models", 20.7),
             ("Typology hold-out", 2.2), ("Satellite cross-checks", 2.5), ("Population vs Census", 32.7),
             ("Lights vs economy", 41.4), ("Figures + results pack", 7.9), ("Zone cards", 14.4)]
    fig, ax = plt.subplots(figsize=(12.5, 4.8))
    t = 0.0
    for i, (name, secs) in enumerate(steps):
        y = len(steps) - i
        ax.barh(y, secs, left=t, color=BLUE, height=0.6, edgecolor="white", linewidth=2)
        ax.text(t + secs + 1.5, y, f"{name}  {secs:.0f} s", va="center", fontsize=9, color=INK)
        t += secs
    ax.set_yticks([])
    ax.set_xlabel("seconds since start")
    ax.set_xlim(0, t * 1.28)
    ax.grid(axis="y", visible=False)
    ax.set_title(f"run_review3.bat: the whole chain in {int(t // 60)} min {int(t % 60)} s "
                 "(cached data)", loc="left", fontsize=14, weight="bold", color=INK, pad=10)
    fig.tight_layout()
    save(fig, "P4_run_timeline")


def p5_data():
    parts = [("GHSL archives", 337.1, "essential"), ("Indian statistics (SHRUG, UP DES)", 268.0, "essential"),
             ("Earth Engine exports", 134.0, "essential"), ("Processed rasters", 13.6, "essential"),
             ("Pipeline outputs", 14.3, "essential"), ("OpenStreetMap", 11.6, "essential"),
             ("SHRUG all-India polygons", 362.2, "full only"), ("GHSL extracted rasters", 340.8, "full only")]
    fig, ax = plt.subplots(figsize=(12.5, 5))
    for i, (name, mb, kind) in enumerate(parts):
        y = len(parts) - i
        ax.barh(y, mb, color=BLUE if kind == "essential" else "white", edgecolor=BLUE, height=0.62,
                hatch="///" if kind != "essential" else None, linewidth=1.2)
        ax.text(mb + 5, y, f"{name}  {mb:.0f} MB", va="center", fontsize=9, color=INK)
    ax.set_yticks([])
    ax.set_xlabel("MB")
    ax.set_xlim(0, 560)
    ax.grid(axis="y", visible=False)
    ess = sum(p[1] for p in parts if p[2] == "essential")
    legend_patches(ax, [(BLUE, BLUE, None, f"essential bundle, {ess:.0f} MB"),
                        ("white", BLUE, "///", "added by --full (rebuildable)")], loc="center right")
    ax.set_title("Data acquired and kept outside git (1.4 GB)", loc="left", fontsize=14,
                 weight="bold", color=INK, pad=10)
    fig.tight_layout()
    save(fig, "P5_data_inventory")


def p6_quality():
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1, 1.5]})
    a = axes[0]
    stages = ["Phase 1\n(Jul)", "Review 2\n(Aug)", "Review 3\n(Sep)"]
    counts = [20, 25, 41]
    a.bar(stages, counts, color=BLUE, width=0.55)
    for i, c in enumerate(counts):
        a.text(i, c + 0.8, str(c), ha="center", fontsize=10.5, color=INK, weight="bold")
    a.set_ylim(0, 48)
    a.set_title("Unit tests", loc="left", fontsize=12, weight="bold", color=INK)
    a.grid(axis="x", visible=False)
    b = axes[1]
    cats = [("Data or method correctness", 5, "D1 D2 D4 D10 D11"),
            ("Reporting and documents", 4, "D3 D7 D13 D14"),
            ("Model evaluation", 2, "D6 D8"), ("Scope gaps", 2, "D9 D12"),
            ("Code bug", 1, "D5"), ("Population inputs", 1, "D15")]
    for i, (name, n, ids) in enumerate(cats):
        y = len(cats) - i
        b.barh(y, n, color=BLUE, height=0.6)
        b.text(n + 0.1, y, f"{n}   {ids}", va="center", fontsize=9, color=INK2)
    b.set_yticks(range(len(cats), 0, -1))
    b.set_yticklabels([c[0] for c in cats], fontsize=9.2)
    b.set_xlim(0, 7.5)
    b.set_xticks(range(0, 7))
    b.grid(axis="y", visible=False)
    b.set_title("The 15 defects fixed for Review 3, by kind", loc="left", fontsize=12,
                weight="bold", color=INK)
    fig.suptitle("Quality evidence", x=0.01, ha="left", fontsize=15, weight="bold", color=INK)
    fig.tight_layout()
    save(fig, "P6_tests_and_defects")


ALL = {"A1": a1_system, "A2": a2_pipeline, "A3": a3_ghost, "A4": a4_relative_trend,
       "A5": a5_growth, "A6": a6_heat, "A7": a7_validation, "A8": a8_timeline, "A9": a9_grid,
       "P1": p1_roadmap, "P2": p2_status, "P3": p3_corrections, "P4": p4_run, "P5": p5_data,
       "P6": p6_quality}


TALK = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "P1", "P3"]


def main() -> int:
    global CLEAN
    args = [a for a in sys.argv[1:] if a != "--clean"]
    CLEAN = len(args) != len(sys.argv[1:])
    wanted = [a.upper() for a in args] or (TALK if CLEAN else list(ALL))
    if not R:
        print("note: outputs/review3_results.json not found; labels fall back to defaults")
    print("Diagrams ->", OUT)
    for key in wanted:
        ALL[key]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
