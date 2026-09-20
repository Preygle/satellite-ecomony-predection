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
import rasterio  # noqa: E402

from urbanintel.config import load_config  # noqa: E402

FIG = ROOT / "docs" / "figures" / "dl"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, NAVY, AMBER, RED, GREEN = "#2a78d6", "#104281", "#eda100", "#d03b3b", "#1baf7a"

# One colour per model, fixed everywhere, so a reader can follow a model from
# one figure to the next without re-reading the legend.
COLOUR = {
    "image_model": GREEN,
    "random_forest": NAVY,
    "xgboost": BLUE,
    "xgboost_with_image_components": AMBER,
    "stacked": RED,
    "logistic_regression": MUTED,
}
LABEL = {
    "image_model": "image model",
    "random_forest": "random forest",
    "xgboost": "XGBoost",
    "xgboost_with_image_components": "XGBoost + image",
    "stacked": "blend",
    "logistic_regression": "logistic regression",
}

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "legend.frameon": False, "figure.dpi": 100,
})


def usage() -> str:
    return "Draw the analytics for the deep models into docs/figures/dl."


def save(fig, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    if len(fig.axes) > 1:
        fig.tight_layout()
    fig.savefig(FIG / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote docs/figures/dl/{name}")


def note(ax, text: str) -> None:
    ax.annotate(text, xy=(0, -0.22), xycoords="axes fraction", fontsize=7.5,
                color=MUTED, va="top")


def read(cfg, name: str) -> np.ndarray | None:
    p = cfg.processed_dir / "rasters" / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def order(models: dict) -> list[str]:
    return [k for k in ["image_model", "random_forest", "xgboost_with_image_components",
                        "stacked", "xgboost", "logistic_regression"] if k in models]


# --------------------------------------------------------------------------

def fig_learning_curve(img: dict) -> None:
    hist = img["model"]["history"]
    ep = [h["epoch"] for h in hist]
    best = img["model"]["best_epoch"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.4, 5.6), sharex=True,
                                 gridspec_kw={"height_ratios": [1, 1]})
    a1.plot(ep, [h["train_loss"] for h in hist], color=NAVY, lw=2, label="training")
    a1.plot(ep, [h["val_loss"] for h in hist], color=AMBER, lw=2, label="validation blocks")
    a1.set_ylabel("focal + Dice loss")
    a1.set_title("The network learns, then starts memorising the training period")
    a1.legend(loc="upper right")

    a2.plot(ep, [h["val_average_precision"] for h in hist], color=GREEN, lw=2,
            label="average precision (watched)")
    a2.plot(ep, [h["val_auc"] for h in hist], color=MUTED, lw=1.6, ls="--", label="AUC")
    a2.set_xlabel("epoch")
    a2.set_ylabel("validation score")
    a2.set_ylim(0, 1)
    a2.legend(loc="lower right")
    for ax in (a1, a2):
        ax.axvline(best, color=RED, lw=1.2, ls=":")
    a2.annotate(f"kept epoch {best}", xy=(best, 0.06), xytext=(best + 0.6, 0.06),
                color=RED, fontsize=8.5)
    note(a2, "Validation blocks are whole 8 km squares held out of training, inside the "
             "training period.\nThe held-out 2015-2020 period is never touched here.")
    save(fig, "DL01_learning_curve.png")


def fig_toc(sysd: dict) -> None:
    rep = sysd["analytics"]
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    first = rep[next(iter(rep))]["toc"]
    n_e, n_o = first["n_eligible"], first["n_observed"]

    ax.plot([0, n_e], [0, n_o], color=MUTED, lw=1.4, ls="--", label="random")
    ax.plot([0, n_o, n_e], [0, n_o, n_o], color=INK2, lw=1.2, ls=":", label="perfect")
    for name in order(rep):
        t = rep[name]["toc"]
        ax.plot(t["flagged"], t["hits"], color=COLOUR[name], lw=2, label=LABEL[name])
    ax.axvline(n_o, color=RED, lw=1, alpha=0.5)
    ax.annotate(f"demand: {n_o:,} cells", xy=(n_o, n_o * 0.35), xytext=(n_o * 1.6, n_o * 0.3),
                color=RED, fontsize=8.5,
                arrowprops={"arrowstyle": "->", "color": RED, "lw": 0.8})
    ax.set_xlim(0, n_e * 0.35)
    ax.set_xlabel("cells flagged, most suitable first")
    ax.set_ylabel("conversions found")
    ax.set_title("Total Operating Characteristic, held-out 2015-2020")
    ax.legend(loc="lower right")
    note(ax, "Linear axes, so the random line really is the straight line between the "
             "corners.\nOnly the left third of the range is shown: no model is used "
             "beyond it.")
    save(fig, "DL02_toc_curves.png")


def fig_fom(sysd: dict) -> None:
    rows = sysd["comparison"]
    names = [r["model"] for r in rows]
    full = [r["figure_of_merit"] or 0 for r in rows]
    rank = [r["figure_of_merit_rank_only"] or 0 for r in rows]
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.6, 0.62 * len(names) + 2.0))
    ax.barh(y + 0.19, full, height=0.36, color=[COLOUR.get(n, BLUE) for n in names],
            label="with the cellular automaton")
    ax.barh(y - 0.19, rank, height=0.36, color="none", edgecolor=INK2, lw=1.1,
            label="suitability ranking alone")
    base = sysd["random_baseline"]["mean_figure_of_merit"]
    ax.axvline(base, color=RED, lw=1.2, ls="--")
    ax.annotate(f"random {base:.4f}", xy=(base, len(names) - 0.4), color=RED, fontsize=8.5,
                xytext=(base + 0.004, len(names) - 0.5))
    ax.set_yticks(y, [LABEL.get(n, n) for n in names])
    ax.invert_yaxis()
    ax.set_xlabel("Figure of Merit, held-out 2015-2020")
    ax.set_title("What the cellular automaton adds, model by model")
    ax.legend(loc="lower right")
    for i, (f, r) in enumerate(zip(full, rank)):
        ax.annotate(f"{f:.4f}", xy=(f, i + 0.19), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK)
    note(ax, "Hollow bars take the top cells by suitability alone. The automaton adds "
             "the neighbourhood\nterm and eight allocation rounds, which favours models "
             "whose surfaces are spatially smooth.")
    save(fig, "DL03_figure_of_merit.png")


def fig_precision_at_k(sysd: dict) -> None:
    rep = sysd["analytics"]
    names = order(rep)
    fracs = [r["top_fraction"] for r in rep[names[0]]["precision_at_k"]]
    x = np.arange(len(fracs))
    w = 0.8 / len(names)
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    for i, name in enumerate(names):
        vals = [r["precision"] for r in rep[name]["precision_at_k"]]
        ax.bar(x + i * w - 0.4 + w / 2, vals, width=w * 0.92, color=COLOUR[name],
               label=LABEL[name])
    base = rep[names[0]]["precision_at_k"][0]
    rate = sysd["design"]["demand_cells"] / sysd["design"]["eligible_cells"]
    ax.axhline(rate, color=RED, lw=1.2, ls="--")
    ax.annotate(f"base rate {rate:.3f}", xy=(len(fracs) - 0.6, rate * 1.1), color=RED,
                fontsize=8.5)
    ax.set_xticks(x, [f"top {int(f * 100)}%" for f in fracs])
    ax.set_ylabel("share that really converted")
    ax.set_title("Precision at the top of the ranking")
    ax.legend(ncol=2, loc="upper right")
    note(ax, f"Of the {base['cells']:,} cells each model ranks first, how many converted "
             f"by 2020.")
    save(fig, "DL04_precision_at_k.png")


def fig_calibration(sysd: dict) -> None:
    rep = sysd["analytics"]
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    ax.plot([0, 0.35], [0, 0.35], color=MUTED, lw=1.2, ls="--", label="honest")
    for name in order(rep):
        b = rep[name]["calibration"]["bins"]
        ax.plot([r["mean_predicted"] for r in b], [r["observed_rate"] for r in b],
                "o-", ms=4.5, lw=1.6, color=COLOUR[name],
                label=f"{LABEL[name]}  (Brier {rep[name]['calibration']['brier_score']:.4f})")
    ax.set_xlabel("predicted probability of conversion")
    ax.set_ylabel("share that converted")
    ax.set_title("Are the probabilities honest?")
    ax.legend(loc="upper left", fontsize=8.5)
    note(ax, "Deciles of predicted probability. Above the line the model is too "
             "cautious, below it too confident.\nThe allocation only ranks cells, so "
             "this matters for the dashboard, not for the Figure of Merit.")
    save(fig, "DL05_calibration.png")


def fig_shap(sysd: dict) -> None:
    m = sysd["models"].get("xgboost_with_image_components") or sysd["models"].get("xgboost")
    shap = m.get("mean_absolute_shap")
    if not shap:
        return
    items = sorted(shap.items(), key=lambda kv: kv[1])
    names = [k for k, _ in items]
    vals = [v for _, v in items]
    cols = [AMBER if n.startswith("image_pc") else NAVY for n in names]
    fig, ax = plt.subplots(figsize=(7.2, 0.3 * len(names) + 1.6))
    ax.barh(np.arange(len(names)), vals, color=cols)
    ax.set_yticks(np.arange(len(names)),
                  [n.replace("_", " ").replace("image pc", "image component ")
                   for n in names], fontsize=8.5)
    ax.set_xlabel("mean absolute contribution to the score (log-odds)")
    ax.set_title("What the boosted model actually used")
    handles = [plt.Rectangle((0, 0), 1, 1, color=NAVY),
               plt.Rectangle((0, 0), 1, 1, color=AMBER)]
    ax.legend(handles, ["driver", "image component"], loc="lower right")
    note(ax, "Exact TreeSHAP contributions, averaged over the training cells. Not an "
             "approximation of\nthe model: this is what the trees did.")
    save(fig, "DL06_shap.png")


def fig_bands(sysd: dict) -> None:
    rep = sysd["analytics"]
    names = order(rep)
    band = next((b for b in rep[names[0]].get("error_by_band", [])
                 if b["variable"] == "distance_to_urban_edge_km"), None)
    if not band:
        return
    labels = [f"{r['from']:g}-{r['to']:g}" for r in band["bands"]]
    x = np.arange(len(labels))
    w = 0.8 / len(names)
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    for i, name in enumerate(names):
        b = next(bb for bb in rep[name]["error_by_band"]
                 if bb["variable"] == "distance_to_urban_edge_km")
        ax.bar(x + i * w - 0.4 + w / 2, [r["figure_of_merit"] for r in b["bands"]],
               width=w * 0.92, color=COLOUR[name], label=LABEL[name])
    ax.set_xticks(x, labels)
    ax.set_xlabel("distance to the existing built-up edge (km)")
    ax.set_ylabel("Figure of Merit within the band")
    ax.set_title("Every model is good at the edge and blind further out")
    ax.legend(ncol=2)
    counts = [r["observed"] for r in band["bands"]]
    note(ax, "Conversions observed in each band: " +
         ", ".join(f"{lab} km {c}" for lab, c in zip(labels, counts)) +
         ".\nBands with few conversions carry little weight in the overall score.")
    save(fig, "DL07_error_by_band.png")


def fig_stability(sysd: dict) -> None:
    rep = sysd["analytics"]
    names = order(rep)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, name in enumerate(names):
        st = rep[name].get("block_stability")
        if not st:
            continue
        aucs = [f["auc"] for f in st["folds"]]
        ax.scatter([i] * len(aucs), aucs, s=34, color=COLOUR[name], zorder=3)
        ax.plot([i - 0.22, i + 0.22], [st["mean_auc"]] * 2, color=INK, lw=2, zorder=4)
    ax.set_xticks(np.arange(len(names)), [LABEL[n] for n in names], rotation=18,
                  ha="right", fontsize=9)
    ax.set_ylabel("AUC within one fifth of the city")
    ax.set_title("Does the skill hold up across the study area?")
    note(ax, "Each dot is one fifth of the study area, scored on its own; the bar is "
             "the mean.\nA wide spread means the overall score is carried by part of "
             "the city.")
    save(fig, "DL08_block_stability.png")


def fig_seeds(cfg) -> None:
    runs = sorted(cfg.outputs_dir.glob(f"{cfg.city_slug}_image_model*.json"))
    rows = []
    for p in runs:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append({"seed": d["model"]["config"]["seed"],
                     "fom": d["analytics"]["validation"]["figure_of_merit"],
                     "auc": d["analytics"]["auc_test"],
                     "epoch": d["model"]["best_epoch"]})
    if len(rows) < 2:
        return
    rows.sort(key=lambda r: r["seed"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.0, 4.0))
    x = [r["seed"] for r in rows]
    for ax, key, title in ((a1, "fom", "Figure of Merit"), (a2, "auc", "test AUC")):
        vals = [r[key] for r in rows]
        ax.bar(x, vals, color=GREEN, width=0.55)
        ax.axhline(float(np.mean(vals)), color=INK, lw=1.4, ls="--")
        ax.set_xticks(x, [f"seed {s}" for s in x])
        ax.set_title(title)
        for xi, v in zip(x, vals):
            ax.annotate(f"{v:.4f}", xy=(xi, v), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8.5)
        ax.set_ylim(0, max(vals) * 1.25)
    sd = float(np.std([r["fom"] for r in rows]))
    note(a1, f"Same data, same settings, different random seed. Spread of the Figure of "
             f"Merit: {sd:.4f}.\nDifferences smaller than that are noise, not skill.")
    save(fig, "DL09_seed_spread.png")


def fig_ca_sweep(sysd: dict) -> None:
    rep = sysd["analytics"]
    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    for name in order(rep):
        sw = rep[name].get("neighbourhood_weight_sweep")
        if not sw:
            continue
        xs = [r["neighbourhood_weight"] for r in sw["sweep"]]
        ys = [r["figure_of_merit"] for r in sw["sweep"]]
        ax.plot(xs, ys, "o-", ms=5, lw=2, color=COLOUR[name], label=LABEL[name])
    ax.axvline(0.35, color=RED, lw=1.3, ls="--")
    top = ax.get_ylim()[1]
    ax.annotate("0.35 in use since Review 3", xy=(0.345, top), xytext=(0.34, top),
                color=RED, fontsize=8.5, ha="right", va="top")
    ax.set_xlabel("weight on the neighbourhood term in the cellular automaton")
    ax.set_ylabel("Figure of Merit, held-out 2015-2020")
    ax.set_title("Insisting on contiguity costs accuracy in a city that leapfrogs")
    ax.legend(ncol=2, loc="lower left", fontsize=9)
    note(ax, "Weight 0 means allocate purely by suitability. Every tabular model "
             "scores best at or near 0;\nonly the image model, whose surface is "
             "already smooth, prefers the value in use.")
    save(fig, "DL11_neighbourhood_weight.png")


def fig_maps(cfg, sysd: dict) -> None:
    layers = [("growth_suitability_rf", "random forest suitability", "viridis"),
              ("growth_suitability_image", "image model suitability", "viridis"),
              ("deep_conversion_probability", "probability of conversion", "magma"),
              ("deep_conversion_entropy", "uncertainty (bits)", "cividis")]
    have = [(n, t, c) for n, t, c in layers if read(cfg, n) is not None]
    if not have:
        return
    fig, axes = plt.subplots(1, len(have), figsize=(3.6 * len(have), 4.2))
    axes = np.atleast_1d(axes)
    for ax, (name, title, cmap) in zip(axes, have):
        arr = read(cfg, name)
        im = ax.imshow(np.where(np.isfinite(arr), arr, np.nan), cmap=cmap)
        ax.set_title(title, fontsize=10)
        ax.set_xticks([]), ax.set_yticks([])
        ax.grid(False)
        fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    fig.suptitle("Where the models expect growth, and how sure they are",
                 fontsize=11, fontweight="bold")
    save(fig, "DL10_maps.png")


def main() -> int:
    cfg = load_config()
    img_p = cfg.outputs_dir / f"{cfg.city_slug}_image_model.json"
    sys_p = cfg.outputs_dir / f"{cfg.city_slug}_deep_system.json"
    if not img_p.exists() or not sys_p.exists():
        print("run scripts/train_image_model.py and scripts/run_deep_system.py first")
        return 2
    img = json.loads(img_p.read_text(encoding="utf-8"))
    sysd = json.loads(sys_p.read_text(encoding="utf-8"))

    print("Deep-model analytics")
    fig_learning_curve(img)
    fig_toc(sysd)
    fig_fom(sysd)
    fig_precision_at_k(sysd)
    fig_calibration(sysd)
    fig_shap(sysd)
    fig_bands(sysd)
    fig_stability(sysd)
    fig_seeds(cfg)
    fig_ca_sweep(sysd)
    fig_maps(cfg, sysd)
    print(f"\n  {len(list(FIG.glob('*.png')))} figures in docs/figures/dl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
