from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap, PowerNorm, to_rgb  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle  # noqa: E402

OUT = ROOT / "docs" / "figures" / "paper"

# IEEE two-column page: text width and column width, in inches.
TEXTWIDTH, COLUMN = 7.16, 3.5

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "STIXGeneral", "DejaVu Serif"],
    "font.monospace": ["Consolas", "Courier New", "DejaVu Sans Mono"],
    "mathtext.fontset": "stix",
    "font.size": 8,
    "axes.linewidth": 0.5,
    "hatch.linewidth": 0.35,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
})

INK, INK2, RULE = "#1a1a1a", "#4d4d4d", "#bfbfbf"
# Tensor colours, one per path. Muted so the arrows carry the contrast.
C_INPUT, C_ENC, C_DEC, C_CELL, C_HEAD = "#c4c8ce", "#9dbbe0", "#a9d6bd", "#f3c08e", "#e9d48b"
# Arrow colours follow the U-Net convention: blue convolution, red
# downsampling, green upsampling, grey copy, teal 1 x 1.
A = {
    "conv3": "#1f3d7a",
    "down": "#c0392b",
    "conv1": "#14806b",
    "up": "#3a8a2e",
    "copy": "#7a7f87",
    "sig": "#b86e00",
}
# Allocation outcome, Okabe-Ito colours: distinguishable under the common
# forms of colour blindness.
OUTCOME = ListedColormap(["#ffffff", "#d9d9d9", "#009e73", "#d55e00", "#0072b2"])
OUTCOME_NAMES = ["non-urban", "urban in 2015", "hit", "miss", "false alarm"]


def usage() -> str:
    return "Publication figures for the image model: framework, network, protocol, results."


def shade(c, f: float):
    r = np.array(to_rgb(c))
    return tuple(np.clip(r + (1 - r) * f, 0, 1)) if f >= 0 else tuple(np.clip(r * (1 + f), 0, 1))


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", facecolor="white")
    fig.savefig(OUT / f"{name}.png", dpi=600, facecolor="white")
    plt.close(fig)
    print(f"  {name}: pdf, svg, png")


def canvas(w: float, h: float):
    """A figure whose data coordinates are inches, so layout is arithmetic."""
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def arrow(ax, pts, color, *, lw=0.8, dashed=False, head=True, z=6):
    ls = (0, (3, 2)) if dashed else "-"
    if len(pts) > 2 or not head:
        xs, ys = zip(*(pts[:-1] if head else pts))
        ax.add_line(Line2D(xs, ys, color=color, lw=lw, ls=ls, zorder=z,
                           solid_capstyle="butt", solid_joinstyle="miter"))
    if head:
        ax.annotate("", xy=pts[-1], xytext=pts[-2], zorder=z,
                    arrowprops=dict(arrowstyle="-|>,head_length=0.45,head_width=0.18",
                                    color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0))


def bracket(ax, x0, x1, y, text, *, above=False, size=7):
    t = 0.035 if above else -0.035
    ax.add_line(Line2D([x0, x0, x1, x1], [y - t, y, y, y - t], color=INK2, lw=0.45, zorder=5))
    ax.text((x0 + x1) / 2, y + (0.04 if above else -0.045), text, ha="center",
            va="bottom" if above else "top", fontsize=size, style="italic", color=INK)


# ---------------------------------------------------------------------------
# data: everything real, read from the processed rasters
# ---------------------------------------------------------------------------

@dataclass
class Data:
    rgb: np.ndarray
    ndbi_change: np.ndarray
    momentum: np.ndarray
    surface: np.ndarray
    urban: np.ndarray
    observed: np.ndarray
    eligible: np.ndarray
    predicted: np.ndarray
    fom: float
    auc: float
    res: float


def load() -> Data:
    from urbanintel.analysis import growth_model as GM
    from urbanintel.aoi import AOI
    from urbanintel.config import load_config
    from urbanintel.deep import stacks as ST
    from urbanintel.deep.boost import SurfaceModel
    import rasterio

    cfg = load_config()
    aoi = AOI(cfg)
    frame, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    rdir = cfg.processed_dir / "rasters"

    def read(name):
        with rasterio.open(rdir / f"{name}.tif") as ds:
            arr = ds.read(1).astype("float32")
        assert arr.shape == frame.shape, (name, arr.shape, frame.shape)
        return arr

    built = {y: read(f"builtup_m2_{y}") / frame.res**2 for y in (2010, 2015, 2020)}
    surface = read("growth_suitability_image_v5_ensemble")
    _, predicted, observed, eligible = GM.validate(
        SurfaceModel(surface=surface, kind="image_v5_ensemble"), built, None, frame,
        test=(2015, 2020), urban_threshold=thr)
    m = GM.change_metrics(predicted, observed, eligible).as_dict()

    gee = cfg.raw_dir / "gee"
    now = ST.landsat_maps(gee / "landsat_2015.tif", frame)
    then = ST.landsat_maps(gee / "landsat_2010.tif", frame)
    rgb = np.stack([now[2], now[1], now[0]], axis=-1)
    lo, hi = np.nanpercentile(rgb, 2), np.nanpercentile(rgb, 98)
    rgb = np.clip((np.nan_to_num(rgb) - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.85

    def ndbi(b):
        return (b[4] - b[3]) / np.maximum(b[4] + b[3], 1e-4)

    return Data(rgb=rgb, ndbi_change=np.nan_to_num(ndbi(now) - ndbi(then)),
                momentum=np.clip(built[2015] - built[2010], 0, None),
                surface=surface, urban=built[2015] >= thr, observed=observed,
                eligible=eligible, predicted=predicted,
                fom=float(m["figure_of_merit"]),
                auc=float(GM.roc_auc(surface[eligible], observed[eligible])),
                res=float(frame.res))


def outcome(d: Data) -> np.ndarray:
    o = np.zeros(d.urban.shape, dtype="uint8")
    o[d.urban] = 1
    o[d.predicted & d.observed] = 2
    o[~d.predicted & d.observed] = 3
    o[d.predicted & ~d.observed] = 4
    return o


def windows(score: np.ndarray, size: int, n: int, step: int = 4):
    """The `n` non-overlapping windows with the highest total of `score`."""
    c = np.cumsum(np.cumsum(np.pad(score.astype("float64"), ((1, 0), (1, 0))), 0), 1)
    picks = []
    cands = []
    for r in range(0, score.shape[0] - size + 1, step):
        for q in range(0, score.shape[1] - size + 1, step):
            s = c[r + size, q + size] - c[r, q + size] - c[r + size, q] + c[r, q]
            cands.append((s, r, q))
    for s, r, q in sorted(cands, reverse=True):
        if all(abs(r - r2) >= size or abs(q - q2) >= size for _, r2, q2 in picks):
            picks.append((s, r, q))
        if len(picks) == n:
            break
    return [(r, q) for _, r, q in picks]


def suit_norm(d: Data):
    vmax = float(np.nanpercentile(d.surface[d.eligible], 99.5))
    return PowerNorm(gamma=0.5, vmin=0.0, vmax=vmax)


def suit_image(d: Data, sl=np.s_[:, :]):
    return np.ma.masked_where(d.urban[sl], d.surface[sl])


# White at zero, then the magma ramp: lightness falls monotonically with
# probability, and a map that is mostly near zero prints as paper.
SUIT_CMAP = matplotlib.colors.LinearSegmentedColormap.from_list(
    "probability", ["#ffffff"] + [matplotlib.colors.to_hex(plt.get_cmap("magma_r")(v))
                                  for v in np.linspace(0.12, 1.0, 9)]
).with_extremes(bad="#d0d0d0")


# ---------------------------------------------------------------------------
# Figure 2: the network
# ---------------------------------------------------------------------------

DEPTH = (0.40, 0.30)       # oblique projection of the depth axis
H32, H16 = 0.60, 0.30      # drawn size of a 32 x 32 and a 16 x 16 grid


def chan_w(c: int) -> float:
    return max(0.022, 0.018 * np.sqrt(c))


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    ox: float
    oy: float

    @property
    def right(self):
        return self.x + self.w + self.ox

    @property
    def mid(self):
        """Height for a horizontal arrow that meets the front face and leaves the side face."""
        return self.y + self.h / 2 + self.oy / 2

    @property
    def top_c(self):
        return (self.x + self.w / 2 + self.ox / 2, self.y + self.h + self.oy / 2)

    @property
    def bottom_c(self):
        return (self.x + self.w / 2, self.y)


def cuboid(ax, x, y, c, size, color, *, dropout=False, z=3) -> Box:
    w, h = chan_w(c), (H32 if size == 32 else H16)
    ox, oy = h * DEPTH[0], h * DEPTH[1]
    edge = shade(color, -0.5)
    front = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    top = [(x, y + h), (x + w, y + h), (x + w + ox, y + h + oy), (x + ox, y + h + oy)]
    side = [(x + w, y), (x + w + ox, y + oy), (x + w + ox, y + h + oy), (x + w, y + h)]
    for pts, f in ((side, -0.16), (top, 0.4), (front, 0.0)):
        ax.add_patch(Polygon(pts, closed=True, facecolor=shade(color, f), edgecolor=edge,
                             linewidth=0.45, joinstyle="round", zorder=z))
    if dropout:
        ax.add_patch(Polygon(side, closed=True, facecolor="none", edgecolor=edge,
                             linewidth=0.45, hatch="//////", zorder=z + 0.1))
    return Box(x, y, w, h, ox, oy)


def chan_label(ax, b: Box, text, *, dx=0.0):
    ax.text(b.x + b.w / 2 + dx, b.y - 0.035, text, ha="center", va="top", fontsize=6.5,
            color=INK)


def size_label(ax, b: Box, text, *, frac=0.5):
    ax.text(b.x - 0.03, b.y + b.h * frac, text, ha="right", va="center", rotation=90,
            fontsize=6.5, color=INK2)


def stacked_image(ax, img, x, y, s, *, layers=2, cmap=None, norm=None, step=(0.045, 0.034)):
    for k in range(layers, 0, -1):
        ax.add_patch(Rectangle((x + k * step[0], y + k * step[1]), s, s, facecolor="white",
                               edgecolor=INK2, lw=0.45, zorder=2 + (layers - k) * 0.1))
    ax.imshow(img, extent=(x, x + s, y, y + s), origin="upper", cmap=cmap, norm=norm,
              interpolation="nearest", zorder=3)
    ax.add_patch(Rectangle((x, y), s, s, facecolor="none", edgecolor=INK, lw=0.5, zorder=4))


def fig_network(d: Data) -> None:
    W, H = TEXTWIDTH, 3.77
    fig, ax = canvas(W, H)
    YM, YL, YP = 1.62, 0.80, 2.75     # bottoms of the 32x32 row, 16x16 row, per-cell row
    G = 0.15                          # gap between one tensor and the next
    ox32, oy32 = H32 * DEPTH[0], H32 * DEPTH[1]
    cw16, cw64 = chan_w(16), chan_w(64)

    r, q = windows(d.observed, 32, 1)[0]
    sl = np.s_[r:r + 32, q:q + 32]

    # input patch
    S = H32
    stacked_image(ax, d.rgb[sl], 0.10, YM, S)
    ax.text(0.10 + S / 2, YM - 0.05, "input patch", ha="center", va="top", fontsize=7,
            style="italic")
    ax.text(0.10 + S / 2, YM - 0.20, r"$\mathbf{x}\in\mathbb{R}^{45\times32\times32}$",
            ha="center", va="top", fontsize=7.5)

    x0 = 0.10 + S + 2 * 0.045 + 0.16
    X = cuboid(ax, x0, YM, 45, 32, C_INPUT)
    arrow(ax, [(0.10 + S + 2 * 0.045 + 0.02, X.mid), (x0, X.mid)], A["copy"])
    size_label(ax, X, r"$32\times32$", frac=0.24)
    chan_label(ax, X, "45")

    # encoder stem
    s1 = cuboid(ax, X.right + G, YM, 16, 32, C_ENC)
    s2 = cuboid(ax, s1.right + G, YM, 16, 32, C_ENC)
    arrow(ax, [(X.right, X.mid), (s1.x, X.mid)], A["conv3"])
    arrow(ax, [(s1.right, s1.mid), (s2.x, s1.mid)], A["conv3"])
    chan_label(ax, s1, "16")
    chan_label(ax, s2, "16")

    # stride-2 block and projection, one row down; the down arrow leaves the
    # foot of the side face so it clears the channel count
    xd = s2.x + s2.w + s2.ox / 2
    w32, h16 = chan_w(32), H16
    st1 = cuboid(ax, xd - w32 / 2 - h16 * DEPTH[0] / 2, YL, 32, 16, C_ENC)
    st2 = cuboid(ax, st1.right + G, YL, 32, 16, C_ENC, dropout=True)
    p = cuboid(ax, st2.right + G, YL, 64, 16, C_DEC)
    arrow(ax, [(xd, YM + s2.oy / 2), (xd, st1.top_c[1])], A["down"])
    arrow(ax, [(st1.right, st1.mid), (st2.x, st1.mid)], A["conv3"])
    arrow(ax, [(st2.right, st2.mid), (p.x, st2.mid)], A["conv1"])
    size_label(ax, st1, r"$16\times16$")
    for b, t in ((st1, "32"), (st2, "32"), (p, "64")):
        chan_label(ax, b, t)

    # concatenation in the order the code uses, torch.cat([upsampled, skip]):
    # the upsampled 64 rise into the front slab, the copied stem output drops
    # into the back slab over the top
    xu = p.top_c[0]
    cx = xu - cw64 / 2
    u = cuboid(ax, cx, YM, 64, 32, C_DEC)
    cp = cuboid(ax, cx + cw64, YM, 16, 32, C_ENC)
    arrow(ax, [(xu, p.top_c[1]), (xu, YM)], A["up"])
    yk = YM + H32 + oy32 + 0.09
    arrow(ax, [s2.top_c, (s2.top_c[0], yk), (cp.top_c[0], yk), cp.top_c], A["copy"])
    ax.text(xu + 0.03, YM - 0.035, "64+16", ha="left", va="top", fontsize=6.5)
    m1 = cuboid(ax, cp.right + G, YM, 64, 32, C_DEC)
    m2 = cuboid(ax, m1.right + G, YM, 64, 32, C_DEC, dropout=True)
    arrow(ax, [(cp.right, cp.mid), (m1.x, cp.mid)], A["conv3"])
    arrow(ax, [(m1.right, m1.mid), (m2.x, m1.mid)], A["conv3"])
    chan_label(ax, m1, "64")
    chan_label(ax, m2, "64")

    # head: context and per-cell features side by side, 1 x 1 to one channel
    hx = m2.right + G
    hc = cuboid(ax, hx, YM, 64, 32, C_DEC)
    hp = cuboid(ax, hx + cw64, YM, 64, 32, C_CELL)
    arrow(ax, [(m2.right, m2.mid), (hc.x, m2.mid)], A["copy"])
    ax.text(hx + cw64, YM - 0.035, "64+64", ha="center", va="top", fontsize=6.5)
    o = cuboid(ax, hp.right + G, YM, 1, 32, C_HEAD)
    arrow(ax, [(hp.right, hp.mid), (o.x, hp.mid)], A["conv1"])
    chan_label(ax, o, "1")

    # per-cell path, one row up
    pc1 = cuboid(ax, s2.x + 0.30, YP, 64, 32, C_CELL)
    pc2 = cuboid(ax, pc1.right + G, YP, 64, 32, C_CELL)
    xb = X.top_c[0]
    arrow(ax, [(xb, X.top_c[1]), (xb, pc1.mid), (pc1.x, pc1.mid)], A["conv1"])
    arrow(ax, [(pc1.right, pc1.mid), (pc2.x, pc1.mid)], A["conv1"])
    tx = hp.top_c[0]
    arrow(ax, [(pc2.right, pc2.mid), (tx, pc2.mid), (tx, hp.top_c[1])], A["copy"])
    chan_label(ax, pc1, "64")
    chan_label(ax, pc2, "64")

    # output: the ensemble's probability for this patch
    yx = o.right + 0.24
    arrow(ax, [(o.right, o.mid), (yx, o.mid)], A["sig"])
    ax.imshow(suit_image(d, sl), extent=(yx, yx + S, YM, YM + S), origin="upper",
              cmap=SUIT_CMAP, norm=suit_norm(d), interpolation="nearest", zorder=3)
    ax.add_patch(Rectangle((yx, YM), S, S, facecolor="none", edgecolor=INK, lw=0.5, zorder=4))
    ax.text(yx + S / 2, YM - 0.05, "conversion probability", ha="center", va="top",
            fontsize=7, style="italic")
    ax.text(yx + S / 2, YM - 0.20, r"$\hat{\mathbf{y}}\in[0,1]^{32\times32}$", ha="center",
            va="top", fontsize=7.5)
    ax.text(yx + S / 2, YM - 0.38,
            r"$\mathcal{L}=\mathcal{L}_{\mathrm{focal}}+0.5\,\mathcal{L}_{\mathrm{Dice}}$",
            ha="center", va="top", fontsize=7.5)

    # block names
    by = YM - 0.24
    bracket(ax, s1.x, s2.x + s2.w, by, "stem")
    bracket(ax, st1.x, st2.x + st2.w, YL - 0.20, "stride-2 block")
    bracket(ax, p.x, p.x + p.w, YL - 0.20, "project")
    bracket(ax, m1.x, m2.x + m2.w, by, "merge")
    bracket(ax, hc.x, o.x + o.w, by, "head")
    ytop = YP + H32 + oy32 + 0.05
    bracket(ax, pc1.x, pc2.x + pc2.w + pc2.ox, ytop, "per-cell path (full resolution)",
            above=True)

    # legend: operations in two rows, then dropout and the three paths
    ly0 = 0.30
    cols = [0.10, 1.70, 3.50]
    items = [
        ("conv3", r"conv $3\times3$, BN, ReLU"),
        ("down", r"conv $3\times3$, stride 2, BN, ReLU"),
        ("conv1", r"conv $1\times1$ (ReLU in per-cell path)"),
        ("up", r"bilinear upsampling $\times2$"),
        ("copy", "copy / concatenate"),
        ("sig", "sigmoid"),
    ]
    for i, (k, text) in enumerate(items):
        cx_, cy_ = cols[i % 3], ly0 - 0.17 * (i // 3)
        arrow(ax, [(cx_, cy_), (cx_ + 0.22, cy_)], A[k])
        ax.text(cx_ + 0.27, cy_, text, va="center", fontsize=6.8)
    hx0 = 5.45
    ax.add_patch(Polygon([(hx0, ly0 - 0.05), (hx0 + 0.07, ly0 - 0.0), (hx0 + 0.07, ly0 + 0.07),
                          (hx0, ly0 + 0.02)], closed=True, facecolor=shade(C_DEC, -0.16),
                         edgecolor=shade(C_DEC, -0.5), lw=0.45, hatch="//////"))
    ax.text(hx0 + 0.13, ly0, r"Dropout2d, $p=0.5$", va="center", fontsize=6.8)
    for i, (c, t) in enumerate([(C_ENC, "encoder"), (C_DEC, "decoder"), (C_CELL, "per-cell")]):
        xx, yy = hx0 + i * 0.56, ly0 - 0.17
        ax.add_patch(Rectangle((xx, yy - 0.04), 0.07, 0.08, facecolor=c,
                               edgecolor=shade(c, -0.5), lw=0.45))
        ax.text(xx + 0.11, yy, t, va="center", fontsize=6.8)
    ax.add_line(Line2D([0.10, W - 0.10], [ly0 + 0.14, ly0 + 0.14], color=RULE, lw=0.5))
    save(fig, "fig2_network")


# ---------------------------------------------------------------------------
# Figure 1: the framework
# ---------------------------------------------------------------------------

def fig_framework(d: Data) -> None:
    W, H = TEXTWIDTH, 1.94
    fig, ax = canvas(W, H)
    widths = [1.50, 1.10, 1.00, 1.06, 1.05, 1.07]
    gap = (W - 0.06 - sum(widths)) / (len(widths) - 1)
    heads = ["(a) Data sources", "(b) Pre-processing", "(c) Input tensor",
             "(d) Dual-path CNN", "(e) CA allocation", "(f) Evaluation"]
    top, bot, hh = H - 0.04, 0.04, 0.21
    T = 0.80                                  # thumbnail size
    ty = top - hh - 0.07 - T                  # thumbnail bottom
    xs, x = [], 0.03
    for w, t in zip(widths, heads):
        ax.add_patch(FancyBboxPatch((x, bot), w, top - bot,
                                    boxstyle="round,pad=0,rounding_size=0.035",
                                    facecolor="#fafafa", edgecolor=RULE, lw=0.6, zorder=1))
        ax.add_patch(FancyBboxPatch((x, top - hh), w, hh,
                                    boxstyle="round,pad=0,rounding_size=0.035",
                                    facecolor="#e6e9ed", edgecolor=RULE, lw=0.6, zorder=1.5))
        ax.text(x + 0.06, top - hh / 2, t, va="center", fontsize=7.3, weight="bold", zorder=2)
        xs.append(x)
        x += w + gap
    for i in range(len(widths) - 1):
        xa, ym = xs[i] + widths[i], ty + T / 2
        ax.add_patch(Polygon([(xa - 0.012, ym + 0.065), (xa + gap + 0.012, ym),
                              (xa - 0.012, ym - 0.065)], closed=True, facecolor="#5b6470",
                             edgecolor="none", zorder=6))

    def lines(x, y, rows, *, size=6.2, dy=0.112):
        for row in rows:
            text, kind = row if isinstance(row, tuple) else (row, "text")
            kw = dict(fontsize=size, va="top", color=INK, zorder=3)
            step = dy
            if kind == "id":
                kw.update(family="monospace", fontsize=5.3, color="#203a6b")
                step = dy * 0.9
            elif kind == "head":
                kw.update(weight="bold")
            elif kind == "note":
                kw.update(color=INK2, style="italic")
            ax.text(x, y, text, **kw)
            y -= step
        return y

    # (a) data, exactly as the providers name it
    xa = xs[0] + 0.07
    y = top - hh - 0.07
    y = lines(xa, y, [("Landsat surface reflectance", "head"),
                      ("USGS · Collection 2, Level 2 · 30 m", "note"),
                      ("LANDSAT/LT05/C02/T1_L2", "id"), ("LANDSAT/LE07/C02/T1_L2", "id"),
                      ("LANDSAT/LC08/C02/T1_L2", "id")])
    y = lines(xa, y - 0.035, [("Built-up surface, population", "head"),
                              ("European Commission JRC · 100 m", "note"),
                              ("GHS-BUILT-S R2023A", "id"), ("GHS-POP R2023A", "id")])
    lines(xa, y - 0.035, [("Roads, terrain, water", "head"),
                          ("OpenStreetMap (Overpass API)", "note"),
                          ("USGS/SRTMGL1_003", "id"), ("GOOGLE/DYNAMICWORLD/V1", "id")])

    def thumb(i, img, *, cmap=None, norm=None):
        x = xs[i] + (widths[i] - T) / 2
        ax.imshow(img, extent=(x, x + T, ty, ty + T), origin="upper", cmap=cmap, norm=norm,
                  interpolation="antialiased", zorder=3)
        ax.add_patch(Rectangle((x, ty), T, T, facecolor="none", edgecolor=INK2, lw=0.5,
                               zorder=4))
        return xs[i] + 0.07, ty - 0.06

    # (b) pre-processing
    x, y = thumb(1, d.rgb)
    lines(x, y, ["Oct–Mar median composites", "every 5 years, 1995–2020",
                 "QA_PIXEL cloud mask", "TM/ETM+ → OLI (Roy 2016)",
                 "125,925 cells of 100 m", "urban: built-up ≥ 0.20"])

    # (c) the tensor, as a stack of real layers
    rr, qq = windows(d.observed, 32, 1)[0]
    sl = np.s_[rr:rr + 32, qq:qq + 32]
    s, step = 0.56, 0.11
    xc = xs[2] + (widths[2] - s - 2 * step) / 2
    for k, (img, cmap, norm) in enumerate([
            (d.momentum[sl], "Purples", None),
            (d.ndbi_change[sl], "RdBu_r", matplotlib.colors.Normalize(-0.15, 0.15)),
            (d.rgb[sl], None, None)]):
        off = (2 - k) * step
        x0, y0 = xc + off, ty + off * (T - s) / (2 * step)
        ax.imshow(img, extent=(x0, x0 + s, y0, y0 + s), origin="upper", cmap=cmap, norm=norm,
                  interpolation="nearest", zorder=3 + k)
        ax.add_patch(Rectangle((x0, y0), s, s, facecolor="none", edgecolor=INK2, lw=0.45,
                               zorder=3.5 + k))
    lines(xs[2] + 0.07, ty - 0.06, [r"$45\times32\times32$ patches",
                                    "10 bands, indices at $t$", "10 at $t-5$, 10 changes",
                                    "15 place drivers", "stride 8, z-scored"])

    # (d) the network's output surface
    x, y = thumb(3, suit_image(d), cmap=SUIT_CMAP, norm=suit_norm(d))
    lines(x, y, ["115,345 parameters", "focal + 0.5 Dice loss", "5 seeds × 4 rotations",
                 ("→ suitability $S$", "note")])

    # (e) allocation
    alloc = np.zeros(d.urban.shape, dtype="uint8")
    alloc[d.urban] = 1
    alloc[d.predicted] = 2
    x, y = thumb(4, alloc, cmap=ListedColormap(["#ffffff", "#d0d0d0", "#b86e00"]),
                 norm=matplotlib.colors.NoNorm())
    lines(x, y, [r"$s=0.65\,S+0.35\,n_{300}$", "8 iterations", "demand = observed count",
                 ("→ new urban cells", "note")])

    # (f) evaluation
    x, y = thumb(5, outcome(d), cmap=OUTCOME, norm=matplotlib.colors.NoNorm())
    y = lines(x, y, ["test 2015→2020, unseen", "reference: GHS-BUILT-S",
                     f"FoM {d.fom:.3f} · AUC {d.auc:.3f}"])
    for c, t, dx in zip(OUTCOME.colors[2:], OUTCOME_NAMES[2:], (0.0, 0.23, 0.49)):
        ax.add_patch(Rectangle((x + dx, y - 0.075), 0.05, 0.05, facecolor=c, edgecolor="none",
                               zorder=3))
        ax.text(x + dx + 0.07, y - 0.05, t, fontsize=5.8, va="center", zorder=3)
    save(fig, "fig1_framework")


# ---------------------------------------------------------------------------
# Figure 3: three periods
# ---------------------------------------------------------------------------

def fig_protocol() -> None:
    fig, ax = plt.subplots(figsize=(COLUMN, 1.75))
    fig.subplots_adjust(left=0.235, right=0.80, bottom=0.15, top=0.79)
    rows = [("early stopping", 2000, "AP"), ("training", 2010, "loss"),
            ("test (held out)", 2015, "FoM, AUC,\nAP, $\\kappa$")]
    for i, (name, t, metric) in enumerate(rows):
        yy = len(rows) - 1 - i
        ax.add_patch(Rectangle((t - 5, yy - 0.17), 5, 0.34, facecolor=C_ENC,
                               edgecolor=shade(C_ENC, -0.5), lw=0.5))
        ax.add_patch(Rectangle((t, yy - 0.17), 5, 0.34, facecolor=C_CELL,
                               edgecolor=shade(C_CELL, -0.5), lw=0.5, hatch="////"))
        for yr in (t - 5, t):
            ax.plot(yr, yy, marker="o", ms=3.2, color=INK, zorder=4)
        ax.plot(t + 5, yy, marker="o", ms=3.2, mfc="white", mec=INK, mew=0.7, zorder=4)
        ax.text(1993.2, yy, name, ha="right", va="center", fontsize=7.5,
                weight="bold" if "test" in name else "normal")
        ax.text(2022.0, yy, metric, ha="left", va="center", fontsize=6.8, color=INK2)
    ax.set_xlim(1993, 2021.5)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xticks([1995, 2000, 2005, 2010, 2015, 2020])
    ax.tick_params(axis="x", labelsize=7, length=2.5, width=0.5)
    ax.set_yticks([])
    for sp in ("left", "right", "top"):
        ax.spines[sp].set_visible(False)
    for yr in range(1995, 2021, 5):
        ax.axvline(yr, color="#e3e3e3", lw=0.5, zorder=0)
    ax.text(2022.0, len(rows) - 0.68, "scored by", ha="left", va="bottom", fontsize=6.8,
            style="italic", color=INK2)
    h1 = Rectangle((0, 0), 1, 1, facecolor=C_ENC, edgecolor=shade(C_ENC, -0.5), lw=0.5)
    h2 = Rectangle((0, 0), 1, 1, facecolor=C_CELL, edgecolor=shade(C_CELL, -0.5), lw=0.5,
                   hatch="////")
    m1 = Line2D([], [], marker="o", ms=3.2, color=INK, lw=0)
    m2 = Line2D([], [], marker="o", ms=3.2, mfc="white", mec=INK, mew=0.7, lw=0)
    fig.legend([h1, m1, h2, m2],
               ["inputs, $t-5$ to $t$", "imagery epoch", "label, $t$ to $t+5$", "label epoch"],
               loc="upper center", ncol=2, fontsize=6.6, frameon=False,
               bbox_to_anchor=(0.52, 1.0), handlelength=1.4, columnspacing=1.2,
               handletextpad=0.5)
    save(fig, "fig3_protocol")


# ---------------------------------------------------------------------------
# Figure 4: results on the held-out period
# ---------------------------------------------------------------------------

def scalebar(ax, x, y, length_cells, label, *, color=INK):
    """A scale bar on an image axis, where y grows downwards."""
    t = max(length_cells * 0.03, 0.4)
    ax.add_patch(Rectangle((x, y), length_cells, t, facecolor=color, edgecolor="none",
                           zorder=6))
    ax.text(x + length_cells / 2, y + t + 0.6, label, ha="center", va="top", fontsize=6.3,
            color=color, zorder=6)


def north_arrow(ax, x, y, length):
    ax.annotate("", xy=(x, y), xytext=(x, y + length),
                arrowprops=dict(arrowstyle="-|>,head_length=0.5,head_width=0.22", lw=0.7,
                                color=INK))
    ax.text(x, y - 1, "N", ha="center", va="bottom", fontsize=7, weight="bold")


def fig_results(d: Data) -> None:
    size = 40
    wins = windows(d.observed, size, 3)
    out = outcome(d)
    rows_, cols_ = out.shape

    W, z, g = TEXTWIDTH, 0.90, 0.06
    top_pad, bot_pad = 0.30, 0.50
    mh = 3 * z + 2 * g
    mw = mh * cols_ / rows_
    H = bot_pad + mh + top_pad
    fig = plt.figure(figsize=(W, H))
    zx0 = W - 0.10 - (4 * z + 3 * g)
    mx0 = (zx0 - 0.16 - mw) / 2 + 0.02

    def axes_at(x, y, w, h):
        return fig.add_axes([x / W, y / H, w / W, h / H])

    axm = axes_at(mx0, bot_pad, mw, mh)
    axm.imshow(out, cmap=OUTCOME, norm=matplotlib.colors.NoNorm(), interpolation="nearest")
    for k, (r, q) in enumerate(wins):
        axm.add_patch(Rectangle((q - 0.5, r - 0.5), size, size, facecolor="none",
                                edgecolor=INK, lw=0.9))
        axm.text(q + size + 3, r + 1, "ABC"[k], fontsize=8, weight="bold", va="top")
    axm.set_xticks([])
    axm.set_yticks([])
    for sp in axm.spines.values():
        sp.set_linewidth(0.5)
    km = 5000 / d.res
    scalebar(axm, cols_ - km - 12, rows_ - 22, km, "5 km")
    north_arrow(axm, 14, 12, 22)
    axm.set_title(f"(a) Allocation outcome, 2015→2020 (FoM {d.fom:.3f})", fontsize=8, pad=4)

    titles = ["(b) Landsat, 2015", "(c) ΔNDBI, 2010→2015", "(d) Suitability $S$",
              "(e) Outcome"]
    norm_s = suit_norm(d)
    ims, last = {}, {}
    for k, (r, q) in enumerate(wins):
        sl = np.s_[r:r + size, q:q + size]
        o = out[sl]
        hits, miss, fa = int((o == 2).sum()), int((o == 3).sum()), int((o == 4).sum())
        local = hits / max(hits + miss + fa, 1)
        panels = [
            (d.rgb[sl], {}),
            (d.ndbi_change[sl], dict(cmap="RdBu_r", vmin=-0.15, vmax=0.15)),
            (suit_image(d, sl), dict(cmap=SUIT_CMAP, norm=norm_s)),
            (o, dict(cmap=OUTCOME, norm=matplotlib.colors.NoNorm())),
        ]
        for c, (img, kw) in enumerate(panels):
            a = axes_at(zx0 + c * (z + g), bot_pad + (2 - k) * (z + g), z, z)
            ims[c] = a.imshow(img, interpolation="nearest", **kw)
            last[c] = a
            a.set_xticks([])
            a.set_yticks([])
            for sp in a.spines.values():
                sp.set_linewidth(0.5)
            if k == 0:
                a.set_title(titles[c], fontsize=7.5, pad=3)
            if c == 0:
                a.text(1.2, 1.2, "ABC"[k], color="white", fontsize=7.5, weight="bold",
                       va="top", bbox=dict(boxstyle="square,pad=0.15", fc=INK, ec="none"))
                if k == 2:
                    scalebar(a, size - 12.5, size - 7.5, 10, "1 km", color="white")
            if c == 3:
                a.text(size - 1.5, size - 1.5, f"FoM {local:.2f}", ha="right", va="bottom",
                       fontsize=6.3, bbox=dict(boxstyle="square,pad=0.15", fc="white",
                                               ec="none", alpha=0.9))

    def cbar(col, label, ticks=None):
        p = last[col].get_position()
        cax = fig.add_axes([p.x0 + 0.08 * p.width, 0.30 / H, 0.84 * p.width, 0.055 / H])
        cb = fig.colorbar(ims[col], cax=cax, orientation="horizontal", ticks=ticks)
        cb.ax.tick_params(labelsize=6, length=2, width=0.4, pad=1)
        cb.outline.set_linewidth(0.4)
        cb.set_label(label, fontsize=6.3, labelpad=1)

    cbar(1, "ΔNDBI", ticks=[-0.15, 0, 0.15])
    vmax = norm_s.vmax
    top_tick = np.floor(vmax * 100) / 100
    cbar(2, "conversion probability", ticks=[0, round(top_tick / 4, 2), top_tick])

    # outcome key: one row under the map, shared by (a) and (e)
    names = OUTCOME_NAMES[1:]
    widths_ = [0.0, 0.85, 1.25, 1.70]
    for c, t, dx in zip(OUTCOME.colors[1:], names, widths_):
        xx = mx0 + 0.05 + dx
        yy = bot_pad - 0.17
        fig.patches.append(Rectangle((xx / W, (yy - 0.04) / H), 0.08 / W, 0.08 / H,
                                     facecolor=c, lw=0.4,
                                     edgecolor="#9a9a9a" if c == "#d9d9d9" else "none",
                                     transform=fig.transFigure, figure=fig))
        fig.text((xx + 0.11) / W, yy / H, t, fontsize=6.6, va="center")
    save(fig, "fig4_results")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--only", nargs="*", type=int, help="figure numbers to draw")
    args = ap.parse_args(argv)
    want = set(args.only or [1, 2, 3, 4])
    d = load() if want & {1, 2, 4} else None
    if d is not None:
        print(f"ensemble on 2015-2020: FoM {d.fom:.4f}")
    if 1 in want:
        fig_framework(d)
    if 2 in want:
        fig_network(d)
    if 3 in want:
        fig_protocol()
    if 4 in want:
        fig_results(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
