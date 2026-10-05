from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from urbanintel.analysis import growth_model as GM  # noqa: E402
from urbanintel.aoi import AOI, AnalysisFrame  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402
from urbanintel.deep import analytics as AN  # noqa: E402
from urbanintel.deep import features as FE  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402
from urbanintel.deep import tiles as TL  # noqa: E402
from urbanintel.deep.boost import SurfaceModel  # noqa: E402

log = logging.getLogger("image_v2")

LABEL_EPOCHS = list(range(1975, 2026, 5))


def usage() -> str:
    return ("Train the image model against the label it is actually scored on, "
            "with change and index channels supplied rather than learned.")


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def nested_frame(cell: AnalysisFrame, factor: int) -> AnalysisFrame:
    """A finer frame sharing the analysis grid's origin exactly.

    `AOI.frame_pair` would build its own coarse grid, which is not the one the
    rest of the project uses. Deriving the fine frame from the existing cell
    frame keeps every pixel inside exactly one cell, so pooling the network's
    output is the same operation as the scoring code's aggregation.
    """
    if factor == 1:
        return cell
    return AnalysisFrame(crs=cell.crs, res=cell.res / factor, minx=cell.minx,
                         miny=cell.maxy - cell.height * cell.res,
                         maxx=cell.minx + cell.width * cell.res, maxy=cell.maxy,
                         width=cell.width * factor, height=cell.height * factor)


def indices(bands: np.ndarray) -> np.ndarray:
    """NDVI, NDBI, NDWI and brightness from the six-band stack.

    These are the standard built-up and vegetation discriminators. A network
    with half a million parameters and about 1,400 positive cells should not
    have to rediscover a band ratio from scratch; handing it over leaves the
    capacity for what it cannot be told.
    """
    blue, green, red, nir, swir1, _swir2 = bands

    def nd(a, b):
        return np.clip((a - b) / np.maximum(a + b, 1e-4), -1, 1)

    return np.stack([
        nd(nir, red),                                   # vegetation
        nd(swir1, nir),                                 # built-up
        nd(green, nir),                                 # water
        bands.mean(axis=0),                             # brightness
    ]).astype("float32")


def channel_stack(paths: dict[int, Path], frame: AnalysisFrame, *,
                  year: int, lag: int = 5) -> tuple[np.ndarray, list[str]]:
    """Reflectance and indices at two dates, plus the change between them.

    The change channels are the point. Growth momentum -- what happened here
    over the previous five years -- is the strongest single feature in the
    tabular model, and a difference of two reflectance dates is the imagery's
    version of it. The network could in principle learn to subtract, but with
    this few positives it is better handed the subtraction already done.
    """
    now = ST.landsat_maps(paths[year], frame)
    then = ST.landsat_maps(paths[year - lag], frame)
    i_now, i_then = indices(now), indices(then)
    layers = [now, i_now, then, i_then, now - then, i_now - i_then]
    names = ([f"{b}_t" for b in ST.LANDSAT_BANDS]
             + ["ndvi_t", "ndbi_t", "ndwi_t", "brightness_t"]
             + [f"{b}_prev" for b in ST.LANDSAT_BANDS]
             + ["ndvi_prev", "ndbi_prev", "ndwi_prev", "brightness_prev"]
             + [f"{b}_change" for b in ST.LANDSAT_BANDS]
             + ["ndvi_change", "ndbi_change", "ndwi_change", "brightness_change"])
    return np.concatenate(layers).astype("float32"), names


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--factor", type=int, choices=[1, 5], default=1,
                    help="pixels per analysis cell: 1 works on the 100 m grid the "
                         "model is scored on, 5 works at 20 m and pools")
    ap.add_argument("--tile", type=int, default=None)
    ap.add_argument("--stride", type=int, default=None)
    ap.add_argument("--steps", type=int, default=None,
                    help="batches per epoch (default: one pass over the tiles)")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--block-km", type=float, default=16.0)
    ap.add_argument("--widths", type=int, nargs="+", default=[32, 64, 128])
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--with-drivers", action="store_true",
                    help="append the tabular driver maps as extra channels, so the "
                         "network reads imagery and drivers together")
    ap.add_argument("--pixel-loss", action="store_true",
                    help="score the loss per pixel, as the first version did, "
                         "instead of per analysis cell")
    ap.add_argument("--no-tta", action="store_true",
                    help="predict once instead of averaging over the eight symmetries")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="v2")
    args = ap.parse_args(argv)
    if args.tile is None:
        args.tile = 32 if args.factor == 1 else 120
    if args.stride is None:
        args.stride = 8 if args.factor == 1 else 60
    if args.tile % args.factor or args.stride % args.factor:
        ap.error(f"--tile and --stride must be multiples of {args.factor}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    t_start = time.time()

    import torch
    import torch.nn.functional as F

    from urbanintel.deep.nets import GrowthNet, combined_loss

    cfg = load_config()
    aoi = AOI(cfg)
    cell_frame, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    FACTOR = args.factor
    px = nested_frame(cell_frame, FACTOR)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    test_period = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))
    v0, v1 = test_period
    rdir = cfg.processed_dir / "rasters"

    paths = {y: cfg.raw_dir / "gee" / f"landsat_{y}.tif" for y in LABEL_EPOCHS}
    have_img = {y for y, p in paths.items() if p.exists()}
    have_lab = [y for y in LABEL_EPOCHS if (rdir / f"builtup_m2_{y}.tif").exists()
                and y <= 2020]
    built = {y: read(rdir, f"builtup_m2_{y}") / cell_frame.res**2 for y in have_lab}

    # A transition is usable when it has a label at both ends and imagery at
    # its start and five years before it.
    usable = [(a, a + 5) for a in have_lab
              if a + 5 in built and a in have_img and (a - 5) in have_img]
    train_period = max(p for p in usable if p[1] <= v0)       # the most recent
    stop_period = min(p for p in usable if p[1] <= v0 and p != train_period)
    log.info("train on %d-%d, stop on %d-%d, test on %d-%d (held out)",
             *train_period, *stop_period, *test_period)
    log.info("grid: %s at %d m inside %s cells at %d m (%d x %d pixels per cell)",
             px.shape, int(px.res), cell_frame.shape, int(cell_frame.res), FACTOR, FACTOR)

    driver_maps = {}
    if args.with_drivers:
        if FACTOR != 1:
            log.error("--with-drivers needs --factor 1: the drivers are 100 m layers")
            return 2
        from urbanintel.data import osm

        roads_osm = osm.fetch_roads(cfg)
        water = read(rdir, "dw_water_2024")
        dist = read(rdir, "distance_km")
        road_r = read(rdir, "road_density")
        slope_p = cfg.raw_dir / "gee" / "slope.tif"
        slope = (np.nan_to_num(gee.to_frame(slope_p, cell_frame), nan=0.0)
                 if slope_p.exists() else None)
        pop = {y: read(rdir, f"population_{y}") for y in have_lab
               if (rdir / f"population_{y}.tif").exists()}
        common = None
        for a, _ in (train_period, stop_period, test_period):
            X, nm = FE.extended_drivers(built, cell_frame, year=a, aoi=aoi,
                                        distance_km=dist, road_density=road_r,
                                        population=pop, slope=slope, roads=roads_osm,
                                        water=water, urban_threshold=thr)
            driver_maps[a] = (X, nm)
            common = set(nm) if common is None else (common & set(nm))
        order = [n for n in driver_maps[train_period[0]][1] if n in common]
        for a in list(driver_maps):
            X, nm = driver_maps[a]
            driver_maps[a] = np.stack([X[:, nm.index(n)].reshape(cell_frame.shape)
                                       for n in order]).astype("float32")
        log.info("%d driver channels alongside the imagery: %s", len(order),
                 ", ".join(order))

    stacks, names = {}, None
    for a, _ in (train_period, stop_period, test_period):
        stacks[a], names = channel_stack(paths, px, year=a)
        if args.with_drivers:
            stacks[a] = np.concatenate([stacks[a], driver_maps[a]])
    if args.with_drivers:
        names = names + order
    log.info("%d channels in total", len(names))

    # Normalisation from the training date only.
    flat = stacks[train_period[0]].reshape(len(names), -1)
    mean, std = flat.mean(axis=1), flat.std(axis=1)
    std[std < 1e-6] = 1.0
    norm = ST.Normaliser(mean.astype("float32"), std.astype("float32"), names)

    normed_cache: dict[int, np.ndarray] = {}

    def normed(a: int) -> np.ndarray:
        if a not in normed_cache:
            normed_cache[a] = ((stacks[a] - mean[:, None, None])
                               / std[:, None, None]).astype("float32")
        return normed_cache[a]

    def cell_label(a: int, b: int) -> tuple[np.ndarray, np.ndarray]:
        lab, elig = ST.transition_labels(built[a], built[b], urban_threshold=thr)
        return lab.astype("float32"), elig.astype("float32")

    # ---- tiles -------------------------------------------------------------
    ids = TL.block_ids(px.shape, px, block_m=args.block_km * 1000.0)
    val_mask, val_blocks = TL.block_split(ids, val_fraction=0.25, seed=args.seed,
                                          min_span=args.tile)
    origins = TL.tile_origins(px.shape, args.tile, args.stride)
    log.info("blocks %d km: %d of %d held out | %d tile positions", int(args.block_km),
             len(val_blocks), len(np.unique(ids)), len(origins))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = GrowthNet(n_channels=len(names), n_dates=1, encoder="local",
                    widths=tuple(args.widths), dropout=args.dropout).to(device)
    log.info("network: %s parameters", f"{net.n_parameters:,}")
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.epochs))

    cells = args.tile // FACTOR

    def batch(period, origin_list, idx):
        a, b = period
        lab, elig = cell_label(a, b)
        data = normed(a)
        xs, ys, ms = [], [], []
        for i in idx:
            r, c = origin_list[i]
            xs.append(data[:, r:r + args.tile, c:c + args.tile])
            ys.append(lab[r // FACTOR:r // FACTOR + cells,
                          c // FACTOR:c // FACTOR + cells])
            ms.append(elig[r // FACTOR:r // FACTOR + cells,
                           c // FACTOR:c // FACTOR + cells])
        return (np.stack(xs), np.stack(ys), np.stack(ms))

    def to_cells(logits):
        """Average the pixel logits inside each analysis cell."""
        return logits if FACTOR == 1 else F.avg_pool2d(logits, FACTOR)

    tr_origins = TL.select_origins(origins, args.tile, val_mask, want="train")
    va_origins = TL.select_origins(origins, args.tile, val_mask, want="val")
    # The stopping transition is scored over the whole frame: it is a different
    # period, so no spatial separation is needed on top of the temporal one.
    log.info("%d training tiles, %d validation tiles (within the training period), "
             "stopping signal from the whole %d-%d frame", len(tr_origins),
             len(va_origins), *stop_period)

    pos = np.array([
        cell_label(*train_period)[0][r // FACTOR:r // FACTOR + cells,
                                     c // FACTOR:c // FACTOR + cells].sum()
        for r, c in tr_origins])
    weights = np.where(pos > 0, 4.0, 1.0)
    weights = weights / weights.sum()
    steps = args.steps or max(1, int(np.ceil(len(tr_origins) / args.batch_size)))
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)

    stop_origins = TL.tile_origins(px.shape, args.tile, args.tile)   # no overlap

    best, best_state, best_epoch, stale, history = -np.inf, None, 0, 0, []
    print(f"\nTRAINING - {len(names)} channels, loss on "
          f"{'pixels' if args.pixel_loss else 'analysis cells'}, "
          f"{len(tr_origins)} tiles of {args.tile}x{args.tile}")

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        net.train()
        run = 0.0
        for _ in range(steps):
            idx = rng.choice(len(tr_origins), size=args.batch_size, replace=True,
                             p=weights)
            xb, yb, mb = batch(train_period, tr_origins, idx)
            k = int(rng.integers(0, 8))
            xb = TL.symmetry(list(xb), k)
            yb, mb = TL.symmetry([yb, mb], k)
            x = torch.from_numpy(np.stack(xb)).to(device)
            y = torch.from_numpy(yb).unsqueeze(1).to(device)
            m = torch.from_numpy(mb).unsqueeze(1).to(device)

            opt.zero_grad(set_to_none=True)
            logits = net(x.unsqueeze(1))
            out = logits if args.pixel_loss else to_cells(logits)
            if args.pixel_loss:
                y = F.interpolate(y, size=out.shape[-2:], mode="nearest")
                m = F.interpolate(m, size=out.shape[-2:], mode="nearest")
            loss, _, _ = combined_loss(out, y, m, dice_weight=0.5)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step()
            run += float(loss.detach())
        sched.step()

        # ---- stop on a different period, scored at cell level ---------------
        net.eval()
        scores, labels, masks = [], [], []
        with torch.no_grad():
            for s in range(0, len(stop_origins), args.batch_size):
                sel = list(range(s, min(s + args.batch_size, len(stop_origins))))
                xb, yb, mb = batch(stop_period, stop_origins, sel)
                out = to_cells(net(torch.from_numpy(xb).to(device).unsqueeze(1)))
                scores.append(torch.sigmoid(out).squeeze(1).cpu().numpy())
                labels.append(yb), masks.append(mb)
        sc, lb, mk = (np.concatenate(scores), np.concatenate(labels),
                      np.concatenate(masks))
        keep = mk > 0.5
        from sklearn.metrics import average_precision_score

        ap = float(average_precision_score(lb[keep].astype(int), sc[keep])) \
            if lb[keep].max() > 0 else float("nan")
        row = {"epoch": epoch, "train_loss": round(run / steps, 5),
               "stop_average_precision": round(ap, 4),
               "seconds": round(time.time() - t0, 1)}
        history.append(row)
        print(f"  epoch {epoch:>3d}/{args.epochs}   loss {row['train_loss']:.4f}   "
              f"stop AP {ap:.4f}   {row['seconds']:.1f}s", flush=True)

        if ap > best + 1e-5:
            best, best_epoch, stale = ap, epoch, 0
            best_state = {k2: v.detach().cpu().clone() for k2, v in net.state_dict().items()}
        else:
            stale += 1
            if stale >= args.patience:
                break

    if best_state:
        net.load_state_dict(best_state)
    net.eval()
    log.info("best epoch %d, stopping average precision %.4f", best_epoch, best)

    # ---- predict the test period, over the whole frame ---------------------
    data = normed(v0)
    total = np.zeros(cell_frame.shape, dtype="float64")
    count = np.zeros(cell_frame.shape, dtype="float64")
    turns = 1 if args.no_tta else 4
    pred_origins = TL.tile_origins(px.shape, args.tile, args.tile // 2)
    with torch.no_grad():
        for k in range(turns):
            for s in range(0, len(pred_origins), args.batch_size):
                chunk = pred_origins[s:s + args.batch_size]
                xb = np.stack([data[:, r:r + args.tile, c:c + args.tile]
                               for r, c in chunk])
                xb = np.stack(TL.symmetry(list(xb), k))
                out = to_cells(net(torch.from_numpy(xb).to(device).unsqueeze(1)))
                out = out.squeeze(1).cpu().numpy()
                # Rotate the prediction back. Only the four rotations are used
                # here: a rotation composed with a reflection has an inverse
                # this helper cannot express, and getting that subtly wrong
                # would smear every prediction across the map.
                out = np.stack(TL.symmetry(list(out), (4 - k) % 4))
                for (r, c), o in zip(chunk, out):
                    rr, cc = r // FACTOR, c // FACTOR
                    total[rr:rr + cells, cc:cc + cells] += o
                    count[rr:rr + cells, cc:cc + cells] += 1.0
    surface = (1.0 / (1.0 + np.exp(-np.clip(total / np.maximum(count, 1), -50, 50)))
               ).astype("float32")

    sm = SurfaceModel(surface=surface, kind="image_model_v2")
    _, predicted, observed, eligible = GM.validate(sm, built, None, cell_frame,
                                                   test=test_period,
                                                   urban_threshold=thr)
    cell_ids = TL.block_ids(cell_frame.shape, cell_frame, block_m=args.block_km * 1000.0)
    folds = TL.block_folds(cell_ids, n_folds=5, seed=args.seed)
    rep = AN.summarise("image_model_v2", score=surface, predicted=predicted,
                       observed=observed, eligible=eligible, folds=folds,
                       seed=args.seed)
    demand = int((observed & eligible).sum())
    rep["neighbourhood_weight_sweep"] = AN.neighbourhood_weight_sweep(
        surface, built[v0], observed, eligible, cell_frame, demand,
        urban_threshold=thr, seed=args.seed)
    base = AN.random_allocation_baseline(observed, eligible, seed=args.seed)

    mdir = cfg.processed_dir / "models"
    mdir.mkdir(parents=True, exist_ok=True)
    ckpt = mdir / f"image_model_{args.tag}.pt"
    torch.save({"state_dict": net.state_dict(), "normaliser": norm.as_dict(),
                "channels": names, "history": history, "best_epoch": best_epoch}, ckpt)
    with rasterio.open(rdir / f"growth_suitability_image_{args.tag}.tif", "w",
                       **cell_frame.profile("float32")) as ds:
        ds.write(surface, 1)

    sw = rep["neighbourhood_weight_sweep"]
    payload = {"design": {"train": f"{train_period[0]}-{train_period[1]}",
                          "stop": f"{stop_period[0]}-{stop_period[1]}",
                          "test": f"{v0}-{v1}",
                          "pixel_m": px.res, "cell_m": cell_frame.res,
                          "channels": names,
                          "loss_on": "pixels" if args.pixel_loss else "cells",
                          "test_time_augmentation": not args.no_tta,
                          "parameters": net.n_parameters,
                          "best_epoch": best_epoch, "epochs_run": len(history)},
               "analytics": rep, "random_baseline": base, "history": history,
               "runtime_s": round(time.time() - t_start, 1)}
    out = cfg.outputs_dir / f"{cfg.city_slug}_image_model_{args.tag}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    v = rep["validation"]
    print("\n" + "=" * 72)
    print(f"IMAGE MODEL v2 - loss on {'pixels' if args.pixel_loss else 'cells'}, "
          f"{len(names)} channels")
    print("=" * 72)
    print(f"  test AUC            {rep['auc_test']:.4f}")
    print(f"  average precision   {rep['average_precision']:.4f}")
    print(f"  Figure of Merit     {v['figure_of_merit']:.4f}   "
          f"({round(v['figure_of_merit'] / base['mean_figure_of_merit'], 1)}x random)")
    print(f"  best weight         {sw['best_figure_of_merit']:.4f} at w={sw['best_weight']}")
    print(f"  hits                {v['hits']} / {demand}")
    print(f"  runtime             {payload['runtime_s'] / 60:.1f} min")
    print(f"\n  previous image model: FoM 0.0635 (0.0898 best variant)")
    print(f"  summary  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
