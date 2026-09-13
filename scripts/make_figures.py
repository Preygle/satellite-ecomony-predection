"""Results pack for Review 3: every figure, and every number the deck quotes.

    python scripts/make_figures.py

Reads the JSON outputs of the pipeline, the growth model and the validation
scripts (plus a few rasters for the maps) and writes

    docs/figures/F01_growth_index.png ... docs/figures/F14_open_buildings.png
    outputs/review3_results.json     every headline number, in one place

Run it after the pipeline, run_growth_model, validate_typology, cross_checks,
validate_population and validate_economy. A figure whose input is missing is
skipped with a message rather than stopping the others.
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
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402

from urbanintel.analysis import validation as VAL  # noqa: E402
from urbanintel.analysis.ghost import TYPE_COLOURS, TYPE_LABELS  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

FIG = ROOT / "docs" / "figures"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, NAVY, AMBER, RED, GREEN = "#2a78d6", "#104281", "#eda100", "#d03b3b", "#1baf7a"
CLASS_COLOUR = {label: TYPE_COLOURS[code] for code, label in TYPE_LABELS.items()}
CLASS_NAME = {"established_active": "established", "healthy_growth": "healthy growth",
              "emerging": "emerging", "ghost_growth": "ghost growth", "declining": "declining"}
RULE_NAME = {"raw": "raw sign\n(Review 2)", "significant": "significant",
             "relative": "faster than\nthe city",
             "relative_significant": "faster than the city,\nsignificant (Review 3)"}

# Review 2 figures, computed against the GHSL 2025 projection — kept only so
# the corrections can be shown side by side.
REVIEW2_FORM = {"infill": 0.95, "edge_expansion": 5.94, "leapfrog": 6.56}
# Liang et al. (2021), CEUS 85:101569 — different city, period and land classes,
# so a reference level, not a like-for-like score.
LIANG_FOM = 0.2642

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "legend.frameon": False, "figure.dpi": 100,
})


def load(cfg, suffix: str) -> dict | None:
    p = cfg.outputs_dir / f"{cfg.city_slug}_{suffix}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(fig, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    if len(fig.axes) > 1:
        fig.tight_layout()          # keeps neighbouring panels' titles and labels apart
    fig.savefig(FIG / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote docs/figures/{name}")


def read(cfg, name: str) -> np.ndarray | None:
    p = cfg.processed_dir / "rasters" / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def source_note(ax, text: str) -> None:
    ax.annotate(text, xy=(0, -0.2), xycoords="axes fraction", fontsize=7.5,
                color=MUTED, va="top")


# ---------------------------------------------------------------- figures --

def f01_growth_index(S, P):
    b = S["stats"]["builtup"]
    proj = b.get("projection", {})
    yrs = sorted(int(y) for y in b["built_surface_km2"])
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for label, key, c, m in (("Built-up surface (GHSL)", "built_surface_km2", BLUE, "o"),
                             ("Urban extent, cells >= 20% built (GHSL)", "urban_km2", NAVY, "s"),
                             ("Population (GHS-POP)", "population_total", AMBER, "^")):
        d = b[key]
        base = d[str(yrs[0])]
        ax.plot(yrs, [100 * d[str(y)] / base for y in yrs], marker=m, color=c, lw=2, label=label)
        p = proj.get(key, {}).get("2025")
        if p:
            ax.plot([yrs[-1], 2025], [100 * d[str(yrs[-1])] / base, 100 * p / base],
                    ls=(0, (4, 3)), color=c, lw=1.4, marker=m, mfc="white")
    if P:
        wp = P["study_area_2010_2020"]["worldpop"]
        ax.plot([2010, 2020], [100, 100 * wp["2020"] / wp["2010"]], marker="D", color=GREEN,
                lw=2, label="Population (WorldPop)")
    ax.axvspan(2020.5, 2025.5, color="#f0efec", zorder=0)
    ax.text(2023, ax.get_ylim()[0] + 1, "GHSL 2025 = model\nprojection, not observed",
            ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks([2010, 2015, 2020, 2025])
    ax.set_ylabel("Index, 2010 = 100")
    ax.set_title("Built-up area grew faster than population, 2010-2020")
    ax.legend(loc="upper left", fontsize=8.5)
    source_note(ax, "Sources: GHS-BUILT-S and GHS-POP R2023A (JRC), WorldPop/GP/100m/pop. "
                    "Study area 1,206 km2.")
    save(fig, "F01_growth_index.png")


def f02_urban_form(S):
    form = S["stats"]["builtup"]["urban_form"]
    names = ["infill", "edge_expansion", "leapfrog"]
    new = [form[n]["area_km2"] for n in names]
    old = [REVIEW2_FORM[n] for n in names]
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.barh(y + 0.2, old, 0.38, color="#c3c2b7", label="Review 2: 2010-2025 (GHSL projection)")
    ax.barh(y - 0.2, new, 0.38, color=BLUE, label="Review 3: 2010-2020 (observed)")
    for i, n in enumerate(names):
        ax.text(new[i] + 0.08, i - 0.2, f"{new[i]:.2f} km2  ({form[n]['share_pct']}%)",
                va="center", fontsize=8.5)
        ax.text(old[i] + 0.08, i + 0.2, f"{old[i]:.2f}", va="center", fontsize=8, color=MUTED)
    ax.set_yticks(y, ["Infill", "Edge expansion", "Leapfrog"])
    ax.set_xlabel("New urban land, km2")
    ax.set_title("Form of new urban land")
    ax.set_xlim(0, max(new + old) * 1.22)       # room for the value labels
    ax.legend(loc="upper right", fontsize=8)    # infill bars are short: that corner is empty
    ax.invert_yaxis()
    save(fig, "F02_urban_form.png")


def f03_sum_of_lights(S):
    sol = S["stats"]["nightlights"]["sum_of_lights"]
    yrs = sorted(int(y) for y in sol)
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    ax.plot(yrs, [sol[str(y)] / 1e3 for y in yrs], marker="o", color=BLUE, lw=2)
    ax.axvline(2021.5, color=RED, ls="--", lw=1)
    top = max(sol.values()) / 1e3
    ax.text(2021.4, top, "ANNUAL_V21", ha="right", va="top", fontsize=8, color=RED)
    ax.text(2021.6, top, "ANNUAL_V22", ha="left", va="top", fontsize=8, color=RED)
    ax.set_ylabel("Sum of Lights (thousand nW/cm2/sr)")
    ax.set_title("Night-time light over the study area, 2013-2024")
    source_note(ax, "NOAA/VIIRS/DNB/ANNUAL_V21 (2013-2021) and ANNUAL_V22 (2022-2024), "
                    "band average_masked. A proxy for activity, not a measurement of it.")
    save(fig, "F03_sum_of_lights.png")


def f04_rule_sensitivity(S):
    sens = S["stats"]["ghost"].get("rule_sensitivity_km2")
    if not sens:
        print("  skip F04: no rule sensitivity in the summary")
        return
    rules = [r for r in RULE_NAME if r in sens]
    classes = ["emerging", "ghost_growth", "declining"]
    x = np.arange(len(rules))
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, c in enumerate(classes):
        vals = [sens[r][c] for r in rules]
        bars = ax.bar(x + (i - 1) * 0.26, vals, 0.25, color=CLASS_COLOUR[c], label=CLASS_NAME[c])
        for bx, v in zip(bars, vals):
            ax.text(bx.get_x() + bx.get_width() / 2, v + 0.1, f"{v:.2f}", ha="center",
                    fontsize=7.5)
    ax.set_xticks(x, [RULE_NAME[r] for r in rules], fontsize=8.5)
    ax.set_ylabel("Area, km2")
    ax.set_title("How the typology depends on the definition of 'activity rising'")
    ax.legend(fontsize=8.5)
    save(fig, "F04_rule_sensitivity.png")


def f05_holdout(T):
    if not T:
        print("  skip F05: run scripts/validate_typology.py")
        return
    prim = T["primary_rule"]
    r = T["results"][prim]
    order = ["established_active", "healthy_growth", "emerging", "ghost_growth", "declining"]
    stats_, colours = [], []
    for c in order:
        q = r["classes"][c]["outcome"]
        if q:
            stats_.append({"med": q["median"], "q1": q["q1"], "q3": q["q3"], "whislo": q["p5"],
                           "whishi": q["p95"], "label": f"{CLASS_NAME[c]}\n(n={q['n']})",
                           "fliers": []})
            colours.append(CLASS_COLOUR[c])
    fig, ax = plt.subplots(figsize=(8, 4.2))
    bp = ax.bxp(stats_, showfliers=False, patch_artist=True, widths=0.55)
    for patch, c in zip(bp["boxes"], colours):
        patch.set_facecolor(c)
        patch.set_edgecolor(INK2)
    for m in bp["medians"]:
        m.set_color(INK)
    ax.axhline(0, color=MUTED, lw=0.8)
    cell, blk = r["emerging_vs_ghost_cells"], r["emerging_vs_ghost_500m_blocks"]
    ax.set_title("Hold-out: did 'emerging' cells keep catching up after 2020?")
    ax.set_ylabel("Change in log radiance relative to the city,\n2018-20 to 2022-24")
    ax.text(0.99, 0.97, f"emerging > ghost growth\n100 m cells: p = {cell['p_value']:.3f}\n"
                        f"500 m blocks: p = {blk['p_value']:.3f}", transform=ax.transAxes,
            ha="right", va="top", fontsize=8.5,
            bbox=dict(boxstyle="round", fc="white", ec=GRID))
    source_note(ax, "Classified with 2013-2020 night lights only (ANNUAL_V21); outcome never seen "
                    "by the classifier. Boxes: quartiles; whiskers: 5th-95th percentile.")
    save(fig, "F05_holdout.png")


def f06_toc(G):
    toc = G["toc"]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    n_obs = toc["random"]["n_observed"]
    n_e = toc["random"]["n_eligible"]
    ax.plot([0, n_obs, n_e], [0, n_obs, n_obs], color=MUTED, ls=":", lw=1, label="perfect")
    ax.plot(toc["random"]["flagged"], toc["random"]["hits"], color=MUTED, ls="--", lw=1.2,
            label="random")
    for key, c, lab in (("logistic_regression", BLUE, "logistic regression"),
                        ("random_forest", RED, "random forest")):
        m = G["models"][key]
        ax.plot(toc[key]["flagged"], toc[key]["hits"], color=c, lw=2,
                label=f"{lab} (AUC {m['auc_test']:.2f})")
    ax.set_xscale("symlog", linthresh=1000)
    ax.set_xlabel("Cells flagged as converting (most suitable first)")
    ax.set_ylabel("Of which really converted, 2015-2020")
    ax.set_title("TOC curve on the held-out period")
    ax.legend(fontsize=8.5, loc="lower right")
    save(fig, "F06_toc.png")


def f07_fom(G):
    names = [("logistic_regression", "Logistic regression"),
             ("logistic_regression_no_roads", "Logistic regression,\nno roads"),
             ("random_forest", "Random forest")]
    vals = [G["models"][k]["validation"]["figure_of_merit"] for k, _ in names]
    labels = [n for _, n in names] + ["Random allocation"]
    vals.append(G["random_baseline"]["mean_figure_of_merit"])
    colours = [BLUE, "#6da7ec", RED, MUTED]
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    bars = ax.bar(labels, vals, color=colours)
    for bx, v in zip(bars, vals):
        ax.text(bx.get_x() + bx.get_width() / 2, v + 0.002, f"{v:.3f}", ha="center", fontsize=9)
    # Published benchmark on the same measure (docs/PAPER_SUMMARIES.md, paper 15).
    ax.axhline(LIANG_FOM, color=INK2, ls="--", lw=1)
    ax.text(len(labels) - 0.5, LIANG_FOM + 0.004, f"PLUS model, Wuhan (Liang et al. 2021): "
            f"{LIANG_FOM}", ha="right", fontsize=8, color=INK2)
    ax.set_ylim(0, LIANG_FOM * 1.18)
    ax.set_ylabel("Figure of Merit, 2015-2020")
    ax.set_title("Where did the models put the growth that really happened?")
    cross = G.get("cross_check_vs_ghsl_2025_projection")
    if cross:
        source_note(ax, f"Agreement with GHSL's own 2025 projection (equal demand): FoM "
                        f"{cross['equal_demand']['figure_of_merit']:.3f} — two projections, "
                        "not an accuracy.")
    save(fig, "F07_figure_of_merit.png")


def f08_drivers(G):
    lr = G["models"]["logistic_regression"]["coefficients"]
    rf = G["models"]["random_forest"].get("permutation_importance_auc_drop", {})
    names = list(lr)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=True)
    y = np.arange(len(names))
    axes[0].barh(y, [lr[n] for n in names], color=[BLUE if lr[n] >= 0 else AMBER for n in names])
    axes[0].set_yticks(y, [n.replace("_", " ") for n in names], fontsize=8.5)
    axes[0].axvline(0, color=MUTED, lw=0.8)
    axes[0].set_title("Logistic regression:\nstandardised coefficients")
    axes[1].barh(y, [rf.get(n, 0) for n in names], color=RED)
    axes[1].axvline(0, color=MUTED, lw=0.8)
    axes[1].set_title("Random forest: drop in held-out\nAUC when the driver is shuffled")
    for ax in axes:
        ax.invert_yaxis()
    save(fig, "F08_drivers.png")


def f09_projection_map(cfg, G):
    urban = read(cfg, f"builtup_frac_{cfg.epoch_current}")
    p25, p30 = read(cfg, "pred_new_urban_2025"), read(cfg, "pred_new_urban_2030")
    if urban is None or p25 is None or p30 is None:
        print("  skip F09: projection rasters missing")
        return
    img = np.ones(urban.shape + (3,))
    def paint(mask, hexc):
        rgb = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        img[mask] = rgb
    paint(np.nan_to_num(urban) >= cfg.get("thresholds.builtup.surface_fraction_urban"), "#9d9c96")
    paint((p30 > 0) & ~(p25 > 0), RED)
    paint(p25 > 0, AMBER)
    h, w = urban.shape
    fig, ax = plt.subplots(figsize=(7.2, 7.2 * h / w + 0.6))
    ax.imshow(img, extent=(0, w * 0.1, 0, h * 0.1), interpolation="nearest")
    ax.grid(False)
    ax.set_xlabel("km east")
    ax.set_ylabel("km north")
    from matplotlib.patches import Patch
    pr = G["projections"]
    ax.legend(handles=[Patch(color="#9d9c96", label="urban 2020 (observed)"),
                       Patch(color=AMBER, label=f"predicted by 2025 (+{pr['2025']['demand_km2']} km2)"),
                       Patch(color=RED, label=f"predicted 2025-2030 (+{pr['2030']['demand_km2'] - pr['2025']['demand_km2']:.2f} km2)")],
              loc="lower left", fontsize=8.5, frameon=True)
    ax.set_title(f"Predicted new urban land ({G['best_model'].replace('_', ' ')}) — a prediction, "
                 "not an observation", fontsize=10)
    save(fig, "F09_projection_map.png")


def f10_population(cfg, P):
    csv = cfg.outputs_dir / "validation_population_districts.csv"
    if not P or not csv.exists():
        print("  skip F10: run scripts/validate_population.py")
        return
    d = pd.read_csv(csv)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    ax = axes[0]
    for col, c, lab in (("ghs_pop_2011", BLUE, "GHS-POP"), ("worldpop_2011", GREEN, "WorldPop")):
        ax.scatter(d.pc11_pca_tot_p / 1e6, d[col] / 1e6, s=18, color=c, alpha=0.75, label=lab)
    lim = [0.8, 8]
    ax.plot(lim, lim, color=MUTED, lw=1, ls="--", label="equal to Census")
    for name in ("Varanasi", "Chandauli"):
        r = d[d.district_name == name].iloc[0]
        ax.annotate(name, (r.pc11_pca_tot_p / 1e6, r.ghs_pop_2011 / 1e6), fontsize=8,
                    xytext=(6, -10), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_yscale("log")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    for axis in (ax.xaxis, ax.yaxis):           # plain "1 2 3 4 6", not "2 x 10^0"
        axis.set_major_locator(FixedLocator([1, 2, 3, 4, 6]))
        axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        axis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Census 2011 population (million)")
    ax.set_ylabel("Gridded estimate, 2011 (million)")
    ax.set_title("71 districts of Uttar Pradesh")
    ax.legend(fontsize=8.5)
    ax = axes[1]
    s01 = P["study_area_2001_2011"]
    s10 = P["study_area_2010_2020"]
    labels = ["Census", "GHS-POP", "WorldPop"]
    v01 = [s01["census"]["growth_pct"], s01["ghs_pop"]["growth_pct"], s01["worldpop"]["growth_pct"]]
    v10 = [None, s10["ghs_pop"]["growth_pct"], s10["worldpop"]["growth_pct"]]
    x = np.arange(3)
    ax.bar(x - 0.2, v01, 0.38, color=[INK2, BLUE, GREEN], label="2001-2011")
    ax.bar(x[1:] + 0.2, v10[1:], 0.38, color=[BLUE, GREEN], alpha=0.45, hatch="//",
           label="2010-2020 (no census)")
    for i, v in enumerate(v01):
        ax.text(i - 0.2, v + 0.3, f"{v:.1f}%", ha="center", fontsize=8.5)
    for i, v in enumerate(v10):
        if v is not None:
            ax.text(i + 0.2, v + 0.3, f"{v:.1f}%", ha="center", fontsize=8.5)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Population growth over the decade, %")
    ax.set_title("Study area: population growth")
    ax.legend(fontsize=8.5)
    save(fig, "F10_population.png")


def f11_builtup_definitions(C):
    if not C:
        print("  skip F11: run scripts/cross_checks.py")
        return
    a = C["builtup_definitions"]["areas"]
    km = C["builtup_definitions"]["kappa_matrix"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    names = list(a)
    vals = [a[n]["km2"] for n in names]
    ax.barh(names, vals, color=[BLUE, NAVY, GREEN, AMBER, RED, MUTED][:len(names)])
    for i, v in enumerate(vals):
        ax.text(v + 5, i, f"{v:,.0f}", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.12)
    ax.invert_yaxis()
    ax.set_xlabel("km2 counted as built")
    ax.set_title("Six datasets, six answers to 'how much is built?'")
    ax.tick_params(axis="y", labelsize=8)
    ax = axes[1]
    k = np.array([[np.nan if v is None else v for v in row] for row in km["values"]])
    im = ax.imshow(k, cmap="Blues", vmin=0, vmax=1)
    ax.grid(False)
    ax.set_xticks(range(len(km["names"])), km["names"], rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(km["names"])), km["names"], fontsize=8)
    for i in range(len(k)):
        for j in range(len(k)):
            ax.text(j, i, f"{k[i, j]:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if k[i, j] > 0.6 else INK)
    ax.set_title("Cell-by-cell agreement (Cohen's kappa)")
    fig.colorbar(im, ax=ax, fraction=0.046)
    save(fig, "F11_builtup_definitions.png")


def f12_lst(cfg, aoi, C, S):
    if not C:
        print("  skip F12: run scripts/cross_checks.py")
        return
    raw = cfg.raw_dir / "gee"
    yr = cfg.get("timeseries.thermal_end") - 1
    f1k = aoi.frame(1000)
    ls = gee.to_frame(raw / f"lst_{yr}.tif", f1k)
    md = gee.to_frame(raw / f"modis_lst_{yr}.tif", f1k)
    ok = np.isfinite(ls) & np.isfinite(md)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.5))
    ax = axes[0]
    ax.scatter(md[ok], ls[ok], s=6, color=BLUE, alpha=0.5)
    lo, hi = np.nanpercentile(md[ok], 1) - 1, np.nanpercentile(ls[ok], 99) + 1
    ax.plot([lo, hi], [lo, hi], color=MUTED, ls="--", lw=1)
    c = C["lst_landsat_vs_modis"]["comparison"]
    ax.set_xlabel("MODIS LST, °C")
    ax.set_ylabel("Landsat LST, °C")
    ax.set_title(f"Landsat vs MODIS on a 1 km grid\nR² {c['r2']:.2f}, bias {c['bias']:+.1f} °C")
    ax = axes[1]
    con = C["lst_landsat_vs_modis"]["urban_rural_contrast"]
    th = S["stats"]["thermal"]
    labels = ["Landsat\n1 km", "MODIS\n1 km", "Landsat 100 m\nurban cells"]
    vals = [con["landsat"]["urban_minus_rural_c"], con["modis"]["urban_minus_rural_c"],
            th["mean_urban_intensity_c"]]
    ax.bar(labels, vals, color=[BLUE, GREEN, NAVY])
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylim(min(vals) - 0.6, max(0.5, max(vals) + 0.5))
    for i, v in enumerate(vals):
        ax.text(i, v + (0.06 if v >= 0 else -0.06), f"{v:+.2f}", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_ylabel("Urban minus rural, °C")
    ax.set_title("No daytime heat island\nMarch-May 2024")
    ax = axes[2]
    hs = C["heat_island_by_class"]["hotspot_km2_by_setting"]
    ax.bar(["urban\n>=20% built", "peri-urban\n2-20% built", "rural\n<2% built"],
           list(hs.values()), color=[RED, AMBER, "#c3c2b7"])
    for i, v in enumerate(hs.values()):
        ax.text(i, v + 0.3, f"{v:.2f}", ha="center", fontsize=9)
    ax.set_ylabel("Hotspot area (>= +3 °C), km2")
    ax.set_title("Where the hottest surfaces are")
    save(fig, "F12_land_surface_temperature.png")


def f13_economy(cfg, E):
    shr_csv = cfg.outputs_dir / "validation_economy_shrids.csv"
    dist_csv = cfg.outputs_dir / "validation_economy_districts.csv"
    if not E or not shr_csv.exists() or not dist_csv.exists():
        print("  skip F13: run scripts/validate_economy.py")
        return
    s = pd.read_csv(shr_csv)
    d = pd.read_csv(dist_csv)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    ax = axes[0]
    ok = (s.sol_2013 > 0) & (s.ec13_emp_all > 0)
    v = ok & ~s.is_town.astype(bool)
    t = ok & s.is_town.astype(bool)
    ax.scatter(s.sol_2013[v], s.ec13_emp_all[v], s=5, color=BLUE, alpha=0.35, label="villages")
    ax.scatter(s.sol_2013[t], s.ec13_emp_all[t], s=22, color=RED, alpha=0.9, label="towns")
    ax.set_xscale("log")
    ax.set_yscale("log")
    st = E["towns_and_villages_2013"]["lights_vs_employment"]
    ax.set_xlabel("VIIRS 2013 radiance x area (nW/cm²/sr · km²)")
    ax.set_ylabel("Economic Census 2013 employment")
    ax.set_title(f"Towns and villages, 6 districts\nSpearman ρ {st['spearman_rho']}")
    ax.legend(fontsize=8.5)
    ax = axes[1]
    rel = "2020_21" if "gddp_2020_21" in d else "2021_22"
    yr = 2020 if rel == "2020_21" else 2021
    ax.scatter(d[f"sol_{yr}"], d[f"gddp_{rel}"], s=22, color=BLUE)
    var = d[d.district_name == "Varanasi"].iloc[0]
    ax.scatter([var[f"sol_{yr}"]], [var[f"gddp_{rel}"]], s=60, color=RED, zorder=3)
    ax.annotate("Varanasi", (var[f"sol_{yr}"], var[f"gddp_{rel}"]), xytext=(6, 4),
                textcoords="offset points", fontsize=9)
    ax.set_xscale("log")
    ax.set_yscale("log")
    g = E["districts"]["gddp"][rel]["levels"]
    ax.set_xlabel(f"VIIRS Sum of Lights, {yr}")
    ax.set_ylabel(f"Gross District Domestic Product {rel.replace('_', '-')} (Rs crore)")
    ax.set_title(f"Districts of Uttar Pradesh\nρ {g['spearman_rho']}, elasticity {g['elasticity']}, "
                 f"R² {g['r2_loglog']}")
    save(fig, "F13_lights_vs_economy.png")


def f14_open_buildings(C):
    if not C:
        print("  skip F14: run scripts/cross_checks.py")
        return
    ob = C["open_buildings_by_class"]["classes"]
    order = [c for c in ["established_active", "healthy_growth", "emerging", "ghost_growth",
                         "declining"] if c in ob]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.8))
    for ax, key, title, fmt in (
            (axes[0], "share_with_buildings_2023", "Cells with buildings\n2023", "{:.0%}"),
            (axes[1], "presence_change", "Change in building presence\n2016-2023", "{:+.3f}"),
            (axes[2], "height_change_m", "Change in modelled height\n2016-2023 (m)", "{:+.2f}")):
        vals = [ob[c][key] for c in order]
        ax.bar([CLASS_NAME[c] for c in order], vals, color=[CLASS_COLOUR[c] for c in order])
        for i, v in enumerate(vals):
            ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=8.5)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", labelsize=8, rotation=20)
    save(fig, "F14_open_buildings.png")


# ----------------------------------------------------------- results pack --

def results_pack(cfg, S, G, T, C, P, E) -> dict:
    st = S["stats"]
    b, th, g = st["builtup"], st.get("thermal", {}), st.get("ghost", {})
    R: dict = {
        "generated_from": {"pipeline": S.get("generated"), "method_version": S.get("method_version")},
        "epochs": S.get("epochs"),
        "builtup": {k: b[k] for k in ("built_surface_km2", "urban_km2", "net_builtup_change_km2",
                                      "annual_urban_growth_pct", "urban_form", "period")},
        "ghsl_2025_projection": b.get("projection"),
        "population_ghs_pop": b["population_total"],
        "nightlights": {k: st["nightlights"].get(k) for k in
                        ("sum_of_lights", "level_years", "urban_cells_significant_growth_pct")},
        "thermal": {k: th.get(k) for k in ("year", "rural_reference_c", "mean_urban_intensity_c",
                                           "mean_positive_intensity_c", "hotspot_area_km2",
                                           "rural_reference_rule", "rural_rule_sensitivity",
                                           "change")},
        "vegetation": st.get("vegetation"),
        "typology": {"rule": g.get("rising_rule"), "areas_km2": g.get("typology_areas_km2"),
                     "rule_sensitivity_km2": g.get("rule_sensitivity_km2"),
                     "n_zones": g.get("n_zones")},
    }
    if G:
        R["growth_models"] = {
            k: {"auc_train": m.get("auc_train", m.get("auc_train_out_of_bag")),
                "auc_test": m["auc_test"], "figure_of_merit": m["validation"]["figure_of_merit"],
                "skill_vs_random": G["skill_vs_random"][k]}
            for k, m in G["models"].items()}
        R["growth_models"]["random"] = {"figure_of_merit": G["random_baseline"]["mean_figure_of_merit"]}
        R["best_model"] = G["best_model"]
        R["projections"] = G["projections"]
        R["road_leakage_check"] = G["road_leakage_check"]
        R["slope_driver"] = G.get("slope_driver")
        R["cross_check_ghsl_2025"] = (G.get("cross_check_vs_ghsl_2025_projection") or {}).get("equal_demand")
    if T:
        r = T["results"][T["primary_rule"]]
        R["typology_holdout"] = {"rule": T["primary_rule"],
                                 "cells": r["emerging_vs_ghost_cells"],
                                 "blocks_500m": r["emerging_vs_ghost_500m_blocks"],
                                 "all_rules_p_cells": {k: v["emerging_vs_ghost_cells"]["p_value"]
                                                       for k, v in T["results"].items()}}
    if C:
        R["builtup_definitions"] = C["builtup_definitions"]["areas"]
        R["kappa_vs_ghsl"] = C["builtup_definitions"]["vs_ghsl_urban_extent"]
        R["open_buildings"] = C["open_buildings_by_class"]
        R["lst_landsat_vs_modis"] = C["lst_landsat_vs_modis"]
        R["heat_island_by_class"] = C["heat_island_by_class"]
        R["green_lost_to_builtup"] = C["green_lost_to_builtup"]
    if P:
        R["population_validation"] = P
    if E:
        R["economy_validation"] = E
    p = cfg.outputs_dir / "review3_results.json"
    p.write_text(json.dumps(R, indent=2, default=float), encoding="utf-8")
    print(f"  wrote {p}")
    return R


def main() -> int:
    cfg = load_config()
    aoi = AOI(cfg)
    S = load(cfg, "summary")
    if S is None:
        print("no pipeline summary; run the pipeline first")
        return 2
    G, T = load(cfg, "growth_model"), load(cfg, "typology_validation")
    C, P, E = load(cfg, "cross_checks"), load(cfg, "population_validation"), load(cfg, "economy_validation")
    print("Figures ->", FIG)
    f01_growth_index(S, P)
    f02_urban_form(S)
    f03_sum_of_lights(S)
    f04_rule_sensitivity(S)
    f05_holdout(T)
    if G:
        f06_toc(G)
        f07_fom(G)
        f08_drivers(G)
        f09_projection_map(cfg, G)
    f10_population(cfg, P)
    f11_builtup_definitions(C)
    f12_lst(cfg, aoi, C, S)
    f13_economy(cfg, E)
    f14_open_buildings(C)
    results_pack(cfg, S, G, T, C, P, E)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
