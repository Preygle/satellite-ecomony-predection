from __future__ import annotations

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
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402

OUT = ROOT / "docs" / "diagrams"

INK, INK2, MUTED, RULE = "#1b2430", "#4a5563", "#8a94a3", "#d5dae1"
# one colour per kind of operation, used for the arrows and the legend
OPS = {
    "conv3": ("#1f3b73", "3 × 3 convolution → batch norm → ReLU"),
    "down": ("#c0392b", "3 × 3 convolution, stride 2 — halves the grid"),
    "conv1": ("#12856f", "1 × 1 convolution → ReLU — one cell at a time"),
    "up": ("#2e7d32", "bilinear upsampling × 2 — doubles the grid"),
    "copy": ("#7d8794", "copy and concatenate  (dashed: the skip connection)"),
    "sig": ("#c77c0e", "sigmoid → probability of becoming urban"),
}
# tensor fills by the path they belong to
FILL = {
    "input": ("#eceff3", "#5b6573"),
    "enc": ("#d9e6f7", "#2a5d9f"),
    "dec": ("#d6efe6", "#1d7a5f"),
    "cell": ("#fbe5cb", "#b8651b"),
    "out": ("#fdf1d6", "#c77c0e"),
}

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 10,
    "svg.fonttype": "none",
})


def usage() -> str:
    return "Draw the image model's architecture, with a real input patch and real output."


def width(ch: int) -> float:
    """Bar width for a channel count: square-root so 1 and 128 both stay readable."""
    return 0.10 + 0.045 * np.sqrt(ch)


class Diagram:
    def __init__(self, ax):
        self.ax = ax

    def bar(self, x, yc, ch, size, kind, *, split=None, dropout=False, label=True,
            label_at="centre"):
        """One tensor: height is the grid size, width is the number of channels."""
        h = 4.0 if size == 32 else 2.0
        w = width(ch)
        y0 = yc - h / 2
        ax = self.ax
        shadow = FancyBboxPatch((x + 0.05, y0 - 0.05), w, h, boxstyle="round,pad=0,rounding_size=0.03",
                                linewidth=0, facecolor="#000000", alpha=0.06, zorder=2)
        ax.add_patch(shadow)
        if split:
            # a concatenated tensor shows where each part came from
            x_cur = x
            for part_ch, part_kind in split:
                pw = w * part_ch / ch
                face, edge = FILL[part_kind]
                ax.add_patch(Rectangle((x_cur, y0), pw, h, facecolor=face, edgecolor=edge,
                                       linewidth=1.1, zorder=3))
                x_cur += pw
        else:
            face, edge = FILL[kind]
            ax.add_patch(Rectangle((x, y0), w, h, facecolor=face, edgecolor=edge,
                                   linewidth=1.1, zorder=3))
            if dropout:
                ax.add_patch(Rectangle((x, y0), w, h, facecolor="none", edgecolor=edge,
                                       linewidth=0, hatch="////", alpha=0.35, zorder=4))
        if label:
            # Where an arrow enters through the top of a bar, the channel count
            # moves aside so the line does not strike through it.
            lx, ha = {"centre": (x + w / 2, "center"), "left": (x - 0.06, "right"),
                      "right": (x + w + 0.06, "left")}[label_at]
            ax.text(lx, y0 + h + 0.14, str(ch), ha=ha, va="bottom",
                    fontsize=9.5, color=INK, fontweight="semibold", zorder=6)
        return {"l": x, "r": x + w, "t": y0 + h, "b": y0, "cx": x + w / 2, "cy": yc, "w": w}

    def arrow(self, pts, op, *, dashed=False, lw=1.7):
        """A polyline with an arrowhead on its last segment."""
        color = OPS[op][0]
        xs, ys = zip(*pts)
        if len(pts) > 2:
            self.ax.add_line(Line2D(xs[:-1], ys[:-1], color=color, linewidth=lw,
                                    linestyle=(0, (4, 3)) if dashed else "-", zorder=5,
                                    solid_capstyle="butt"))
        self.ax.annotate("", xy=pts[-1], xytext=pts[-2],
                         arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                         linestyle=(0, (4, 3)) if dashed else "-",
                                         shrinkA=0, shrinkB=0, mutation_scale=13),
                         zorder=5)

    def caption(self, x, y, head, sub=None, *, ha="center", color=INK):
        self.ax.text(x, y, head, ha=ha, va="top", fontsize=9.5, fontweight="semibold",
                     color=color, zorder=6)
        if sub:
            self.ax.text(x, y - 0.42, sub, ha=ha, va="top", fontsize=8.6, color=INK2, zorder=6)

    def image(self, arr, x0, y0, size, *, cmap=None, vmin=None, vmax=None, border=INK2):
        self.ax.imshow(arr, extent=(x0, x0 + size, y0, y0 + size), origin="upper",
                       cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest", zorder=3)
        self.ax.add_patch(Rectangle((x0, y0), size, size, facecolor="none", edgecolor=border,
                                    linewidth=1.0, zorder=4))


def real_patch():
    """A 32 x 32 cell patch on the growing fringe, from the held-out test period.

    Picked as the window with the most conversions between 2015 and 2020, so
    the picture shows the model doing its actual job. Everything in it is
    real: the Landsat composite, the change layers, the model's probability
    and what actually converted.
    """
    cfg = load_config()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    rdir = cfg.processed_dir / "rasters"

    def read(name):
        with rasterio.open(rdir / f"{name}.tif") as ds:
            return ds.read(1).astype("float32")

    b10, b15, b20 = (read(f"builtup_m2_{y}") / fine.res**2 for y in (2010, 2015, 2020))
    urban15 = b15 >= thr
    converted = (b20 >= thr) & ~urban15
    surface = read("growth_suitability_image_v5_ensemble")

    best, where = -1, (0, 0)
    for r in range(0, fine.height - 32, 4):
        for c in range(0, fine.width - 32, 4):
            n = int(converted[r:r + 32, c:c + 32].sum())
            if n > best:
                best, where = n, (r, c)
    r, c = where
    sl = (slice(r, r + 32), slice(c, c + 32))

    gee = cfg.raw_dir / "gee"
    now = ST.landsat_maps(gee / "landsat_2015.tif", fine)
    then = ST.landsat_maps(gee / "landsat_2010.tif", fine)
    rgb = np.stack([now[2], now[1], now[0]], axis=-1)[sl]
    lo, hi = np.percentile(rgb, 2), np.percentile(rgb, 98)
    rgb = np.clip((rgb - lo) / max(hi - lo, 1e-6), 0, 1)

    def ndbi(b):
        return (b[4] - b[3]) / np.maximum(b[4] + b[3], 1e-4)

    return {
        "rgb": rgb,
        "ndbi_change": (ndbi(now) - ndbi(then))[sl],
        "momentum": np.clip(b15 - b10, 0, None)[sl],
        "prob": surface[sl],
        "urban": urban15[sl],
        "converted": converted[sl],
        "n_converted": best,
    }


def main() -> int:
    data = real_patch()

    fig = plt.figure(figsize=(16, 9.6), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 32)
    ax.set_ylim(0, 19.2)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("white")
    d = Diagram(ax)

    # ---- title -------------------------------------------------------------
    ax.text(0.6, 18.75, "Urban-growth network", fontsize=20, fontweight="bold",
            color=INK, va="top")
    ax.text(0.6, 17.85, "A 32 × 32-cell patch (3.2 km) with 45 layers goes in; a probability "
            "of becoming urban comes out for every cell.  115,345 parameters.",
            fontsize=11, color=INK2, va="top")

    TOP, MID, CELL = 12.9, 8.4, 3.3

    # ---- input: real layers, fanned like a stack ---------------------------
    s = 2.55
    d.image(data["momentum"], 0.55, TOP - 1.55 + 0.7, s, cmap="Purples", vmin=0,
            vmax=max(float(data["momentum"].max()), 1e-3))
    d.image(data["ndbi_change"], 0.85, TOP - 1.55 + 0.35, s, cmap="RdBu_r",
            vmin=-0.15, vmax=0.15)
    d.image(data["rgb"], 1.15, TOP - 1.55, s)
    ax.text(2.45, TOP - 1.95, "real patch, Varanasi 2015", ha="center", va="top",
            fontsize=8.6, color=INK2)
    ax.text(2.45, TOP - 2.35, "Landsat colour, NDBI change,", ha="center", va="top",
            fontsize=8.6, color=INK2)
    ax.text(2.45, TOP - 2.70, "growth momentum … 45 layers", ha="center", va="top",
            fontsize=8.6, color=INK2)

    X = d.bar(4.25, TOP, 45, 32, "input")
    d.arrow([(3.74, TOP), (X["l"] - 0.02, TOP)], "copy")

    # ---- encoder -----------------------------------------------------------
    T1 = d.bar(5.65, TOP, 16, 32, "enc")
    T2 = d.bar(7.00, TOP, 16, 32, "enc", label_at="left")
    T3 = d.bar(8.45, MID, 32, 16, "enc")
    T4 = d.bar(9.80, MID, 32, 16, "enc", dropout=True)
    d.arrow([(X["r"], TOP), (T1["l"], TOP)], "conv3")
    d.arrow([(T1["r"], TOP), (T2["l"], TOP)], "conv3")
    d.arrow([(T2["cx"], T2["b"]), (T2["cx"], MID), (T3["l"], MID)], "down")
    d.arrow([(T3["r"], MID), (T4["l"], MID)], "conv3")

    # ---- decoder -----------------------------------------------------------
    T5 = d.bar(11.20, MID, 64, 16, "dec")
    T6 = d.bar(12.75, TOP, 64, 32, "dec")
    T7 = d.bar(14.15, TOP, 80, 32, "dec", split=[(64, "dec"), (16, "enc")],
               label_at="left")
    T8 = d.bar(15.70, TOP, 64, 32, "dec")
    T9 = d.bar(17.15, TOP, 64, 32, "dec", dropout=True)
    d.arrow([(T4["r"], MID), (T5["l"], MID)], "conv1")
    d.arrow([(T5["r"], MID), (T6["cx"], MID), (T6["cx"], T6["b"])], "up")
    d.arrow([(T6["r"], TOP), (T7["l"], TOP)], "copy")
    skip_x = T7["l"] + T7["w"] * 64 / 80 + T7["w"] * 16 / 80 / 2
    d.arrow([(T2["cx"], T2["t"]), (T2["cx"], 16.25), (skip_x, 16.25),
             (skip_x, T7["t"] + 0.02)], "copy", dashed=True)
    ax.text((T2["cx"] + skip_x) / 2, 16.38, "skip: the stem's full-resolution features",
            ha="center", va="bottom", fontsize=8.6, color=INK2)
    d.arrow([(T7["r"], TOP), (T8["l"], TOP)], "conv3")
    d.arrow([(T8["r"], TOP), (T9["l"], TOP)], "conv3")

    # ---- per-cell path -----------------------------------------------------
    P1 = d.bar(6.85, CELL, 64, 32, "cell")
    P2 = d.bar(8.40, CELL, 64, 32, "cell")
    d.arrow([(X["cx"], X["b"]), (X["cx"], CELL), (P1["l"], CELL)], "conv1")
    d.arrow([(P1["r"], CELL), (P2["l"], CELL)], "conv1")

    # ---- head --------------------------------------------------------------
    H = d.bar(19.55, MID, 128, 32, "dec", split=[(64, "dec"), (64, "cell")],
              label_at="right")
    ctx_x = H["l"] + H["w"] * 0.25
    cell_x = H["l"] + H["w"] * 0.75
    d.arrow([(T9["r"], TOP), (ctx_x, TOP), (ctx_x, H["t"] + 0.02)], "copy")
    d.arrow([(P2["r"], CELL), (cell_x, CELL), (cell_x, H["b"] - 0.02)], "copy")
    L = d.bar(21.15, MID, 1, 32, "out")
    d.arrow([(H["r"], MID), (L["l"], MID)], "conv1")

    # ---- output: the model's real probability, and what really happened ----
    size = 4.0
    ox, gx, oy = 22.45, 27.15, MID - size / 2
    d.arrow([(L["r"], MID), (ox - 0.03, MID)], "sig")
    prob = np.ma.masked_where(data["urban"], data["prob"])
    from matplotlib.colors import LinearSegmentedColormap, PowerNorm

    cmap = LinearSegmentedColormap.from_list(
        "growth", ["#f7f7f9", "#e9b7cf", "#b8457f", "#8c1c54"])
    cmap.set_bad("#c9ced6")
    vmax = float(np.nanpercentile(data["prob"][~data["urban"]], 99.5))
    ax.imshow(prob, extent=(ox, ox + size, oy, oy + size), origin="upper", cmap=cmap,
              norm=PowerNorm(gamma=0.5, vmin=0, vmax=vmax), interpolation="nearest",
              zorder=3)
    ax.add_patch(Rectangle((ox, oy), size, size, facecolor="none", edgecolor=INK2,
                           linewidth=1.0, zorder=4))
    obs = np.zeros(data["urban"].shape + (3,), dtype="float32") + np.array([0.97, 0.97, 0.98])
    obs[data["urban"]] = np.array([0.79, 0.81, 0.84])
    obs[data["converted"]] = np.array([0.55, 0.11, 0.33])
    d.image(obs, gx, oy, size)
    ax.text(ox + size / 2, oy + size + 0.42, "predicted probability", ha="center",
            va="bottom", fontsize=9.5, fontweight="semibold", color=INK)
    ax.text(ox + size / 2, oy + size + 0.12, "from the 2015 layers", ha="center",
            va="bottom", fontsize=8.6, color=INK2)
    ax.text(gx + size / 2, oy + size + 0.42, "what really converted", ha="center",
            va="bottom", fontsize=9.5, fontweight="semibold", color=INK)
    ax.text(gx + size / 2, oy + size + 0.12, f"by 2020 — {data['n_converted']} cells",
            ha="center", va="bottom", fontsize=8.6, color=INK2)
    ax.text((ox + gx + size) / 2, oy - 0.25, "grey: already urban in 2015  ·  "
            "held-out test period, never seen in training", ha="center", va="top",
            fontsize=8.6, color=INK2)

    # ---- captions under each stage -----------------------------------------
    d.caption(T1["cx"], TOP - 2.35, "stem", "8,848 params")
    d.caption((T3["l"] + T4["r"]) / 2, MID - 1.3, "downsample", "16 × 16 · 13,952")
    d.caption(T5["cx"], MID - 1.3, "project", "2,112")
    d.caption((T7["l"] + T9["r"]) / 2, TOP - 2.35, "merge", "83,200 params")
    d.caption((P1["l"] + P2["r"]) / 2, CELL - 2.3, "per-cell path", "7,104 params",
              color=FILL["cell"][1])
    d.caption(cell_x - 0.3, MID - 2.35, "head", "concatenate · 1 × 1 · 129", ha="right")

    # ---- section labels ----------------------------------------------------
    for x, text, color in ((6.4, "ENCODER", FILL["enc"][1]), (15.0, "DECODER", FILL["dec"][1])):
        ax.text(x, 17.15, text, ha="center", fontsize=9, color=color, fontweight="bold",
                va="bottom")
    ax.text(P2["r"] + 0.5, CELL + 0.22, "PER-CELL PATH", ha="left", fontsize=9,
            color=FILL["cell"][1], fontweight="bold", va="bottom")
    ax.text(P2["r"] + 0.5, CELL - 0.18, "skips the encoder entirely: every cell is judged "
            "on its own 45 numbers, at full resolution", ha="left", fontsize=8.6,
            color=INK2, va="top")

    # ---- legend ------------------------------------------------------------
    lx, ly = 22.45, 17.55
    ax.text(lx, ly, "OPERATIONS", fontsize=9, color=INK2, fontweight="bold", va="top")
    for i, key in enumerate(["conv3", "down", "conv1", "up", "copy", "sig"]):
        y = ly - 0.62 - i * 0.5
        d.arrow([(lx, y), (lx + 0.85, y)], key, dashed=(key == "copy" and False))
        ax.text(lx + 1.1, y, OPS[key][1], va="center", fontsize=9, color=INK)
    y = ly - 0.62 - 6 * 0.5
    ax.add_patch(Rectangle((lx + 0.2, y - 0.17), 0.45, 0.34, facecolor=FILL["dec"][0],
                           edgecolor=FILL["dec"][1], linewidth=1.0, zorder=3))
    ax.add_patch(Rectangle((lx + 0.2, y - 0.17), 0.45, 0.34, facecolor="none",
                           edgecolor=FILL["dec"][1], hatch="////", alpha=0.4, linewidth=0,
                           zorder=4))
    ax.text(lx + 1.1, y, "dropout 0.5 after this block", va="center", fontsize=9, color=INK)
    y -= 0.5
    ax.add_patch(Rectangle((lx + 0.33, y - 0.24), 0.2, 0.48, facecolor=FILL["enc"][0],
                           edgecolor=FILL["enc"][1], linewidth=1.0, zorder=3))
    ax.text(lx + 1.1, y, "a tensor: height = grid size, width = channels",
            va="center", fontsize=9, color=INK)

    # ---- the one-paragraph story -------------------------------------------
    bx, by, bw, bh = 22.45, 0.45, 9.0, 4.15
    ax.add_patch(FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor="#f6f8fa", edgecolor=RULE, linewidth=1.0, zorder=1))
    lines = [
        ("Why two paths", True, INK),
        ("The context path shrinks the patch to 16 × 16 and grows it", False, INK),
        ("back, so it sees the neighbourhood but every value is blurred.", False, INK),
        ("The per-cell path never shrinks anything, so it stays sharp.", False, INK),
        ("The score is decided by the top ~1,200 cells, where blur fails.", False, INK),
        ("", False, INK),
        ("Figure of Merit 0.0813 → 0.1166 with the per-cell path,", True, FILL["cell"][1]),
        ("→ 0.1507 with growth momentum (5-model ensemble).", True, FILL["cell"][1]),
    ]
    for i, (text, bold, color) in enumerate(lines):
        ax.text(bx + 0.3, by + bh - 0.35 - i * 0.44, text, va="top", fontsize=9.2,
                fontweight="semibold" if bold else "normal", color=color)

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "dl5_network_detail.png", dpi=200, facecolor="white")
    fig.savefig(OUT / "dl5_network_detail.svg", facecolor="white")
    plt.close(fig)
    print(f"wrote {OUT / 'dl5_network_detail.png'} and .svg "
          f"(patch with {data['n_converted']} conversions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
