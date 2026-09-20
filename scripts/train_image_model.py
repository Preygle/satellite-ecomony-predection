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
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402
from urbanintel.deep import analytics as AN  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402
from urbanintel.deep import tiles as TL  # noqa: E402
from urbanintel.deep.boost import SurfaceModel  # noqa: E402

log = logging.getLogger("image_model")


def usage() -> str:
    return "Train the image model for urban growth and score it on the held-out period."


def read(rdir: Path, name: str) -> np.ndarray | None:
    p = rdir / f"{name}.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as ds:
        return ds.read(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--source", choices=["drivers", "landsat"], default="drivers",
                    help="channel stack: the model's own driver maps, or Landsat bands")
    ap.add_argument("--encoder", choices=["local", "prithvi"], default="local")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--tile", type=int, default=None,
                    help="tile side in pixels (default 32 for drivers, 224 for Landsat)")
    ap.add_argument("--stride", type=int, default=None,
                    help="spacing between tile corners (default a quarter of the tile)")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--block-km", type=float, default=None,
                    help="side of the spatial blocks held out for early stopping")
    ap.add_argument("--val-fraction", type=float, default=0.25)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--lr-encoder", type=float, default=None)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--monitor", choices=["average_precision", "auc"],
                    default="average_precision",
                    help="what early stopping watches on the validation blocks")
    ap.add_argument("--widths", type=int, nargs="+", default=None,
                    help="encoder widths; narrower stages regularise harder")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--quick", action="store_true", help="short run for a smoke test")
    ap.add_argument("--out", default=None, help="checkpoint path")
    ap.add_argument("--tag", default="",
                    help="suffix for the checkpoint and summary, for seed sweeps")
    args = ap.parse_args(argv)
    # A validation tile has to fit wholly inside a held-out block, so the tile,
    # the stride and the block size are one decision, not three.
    if args.tile is None:
        args.tile = 224 if args.source == "landsat" else 32
    if args.stride is None:
        args.stride = max(1, args.tile // 4)
    if args.block_km is None:
        args.block_km = 12.0 if args.source == "landsat" else 8.0
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    t_start = time.time()

    from urbanintel.deep.train import TrainConfig, fit_image_model, predict_surface

    cfg = load_config()
    cfg.check_epochs()
    aoi = AOI(cfg)
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    obs = cfg.observational_epochs
    train_period = tuple(int(y) for y in cfg.get("growth_model.train", [2010, 2015]))
    test_period = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))

    rdir = cfg.processed_dir / "rasters"
    if read(rdir, f"builtup_m2_{obs[-1]}") is None:
        log.error("no processed rasters; run the pipeline first")
        return 2

    cell = fine.res**2
    built = {y: read(rdir, f"builtup_m2_{y}") / cell for y in obs}
    pop = {y: read(rdir, f"population_{y}") for y in obs}
    dist = read(rdir, "distance_km")
    roads = read(rdir, "road_density")
    slope = None
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    if slope_p.exists():
        slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0)

    # ---- how many dates can every transition supply? ----------------------
    periods = [train_period, test_period]
    if args.source == "landsat":
        paths = {y: cfg.raw_dir / "gee" / f"landsat_{y}.tif" for y in range(1995, 2031, 5)}
        have = {y for y, p in paths.items() if p.exists()}
    else:
        have = set(obs)
    n_dates = 2 if all((t0 - 5) in have and t0 in have for t0, _ in periods) else 1
    if not all(t0 in have for t0, _ in periods):
        log.error("%s stack missing for %s", args.source,
                  [t0 for t0, _ in periods if t0 not in have])
        return 2
    input_years = {t0: ([t0 - 5, t0] if n_dates == 2 else [t0]) for t0, _ in periods}
    log.info("channel source %s | %d input date(s) per sample | frame %s at %d m",
             args.source, n_dates, fine.shape, int(fine.res))
    if n_dates == 1:
        log.info("  only one date available for every transition (needs GHSL %d); "
                 "the model sees a single snapshot", train_period[0] - 5)

    def stack_for(t0: int) -> ST.TemporalStack:
        years = input_years[t0]
        if args.source == "landsat":
            return ST.landsat_stack(paths, fine, years=years)
        return ST.driver_stack(built, fine, years=years, distance_km=dist,
                               road_density=roads, population=pop, slope=slope,
                               urban_threshold=thr)

    raw_train = stack_for(train_period[0])
    raw_test = stack_for(test_period[0])
    normaliser = ST.Normaliser.fit([raw_train])       # training dates only
    log.info("channels: %s", ", ".join(raw_train.names))

    def transition(t0: int, t1: int, raw: ST.TemporalStack) -> TL.Transition:
        label, eligible = ST.transition_labels(built[t0], built[t1], urban_threshold=thr)
        return TL.Transition(normaliser.apply(raw), label, eligible, (t0, t1))

    tr_train = transition(*train_period, raw_train)
    tr_test = transition(*test_period, raw_test)
    for tr in (tr_train, tr_test):
        log.info("transition %d-%d: %d eligible cells, %d conversions (%.2f%%)",
                 tr.period[0], tr.period[1], int(tr.eligible.sum()), int(tr.label.sum()),
                 100 * tr.label.sum() / max(tr.eligible.sum(), 1))

    # ---- spatial blocks ---------------------------------------------------
    ids = TL.block_ids(fine.shape, fine, block_m=args.block_km * 1000.0)
    val_mask, val_blocks = TL.block_split(ids, val_fraction=args.val_fraction,
                                          seed=args.seed)
    origins = TL.tile_origins(fine.shape, args.tile, args.stride)
    tr_origins = TL.select_origins(origins, args.tile, val_mask, want="train")
    va_origins = TL.select_origins(origins, args.tile, val_mask, want="val")
    log.info("blocks %d km: %d held out of %d | tiles %d train, %d validation "
             "(%d dropped as buffer)", int(args.block_km), len(val_blocks),
             len(np.unique(ids)), len(tr_origins), len(va_origins),
             len(origins) - len(tr_origins) - len(va_origins))
    if not va_origins:
        log.error("no validation tile fits inside a held-out block; raise --block-km "
                  "or lower --tile")
        return 2

    train_tiles = TL.build_tiles([tr_train], tr_origins, size=args.tile)
    val_tiles = TL.build_tiles([tr_train], va_origins, size=args.tile)
    log.info("training on %d tiles (%d cells converted), validating on %d",
             len(train_tiles), train_tiles.n_positive, len(val_tiles))

    # ---- train ------------------------------------------------------------
    conf = TrainConfig(
        epochs=3 if args.quick else args.epochs, batch_size=args.batch_size,
        lr=args.lr, lr_encoder=args.lr_encoder, patience=args.patience,
        dropout=args.dropout, seed=args.seed, device=args.device,
        encoder=args.encoder, monitor=args.monitor,
        widths=tuple(args.widths) if args.widths
        else ((16, 32, 64) if args.quick else (32, 64, 128)),
    )

    def show(row: dict) -> None:
        print(f"  epoch {row['epoch']:>3d}/{conf.epochs}   loss {row['train_loss']:.4f}   "
              f"val loss {row['val_loss']:.4f}   "
              f"val AUC {row['val_auc'] or float('nan'):.4f}   "
              f"val AP {row['val_average_precision'] or float('nan'):.4f}   "
              f"{row['seconds']:.1f}s", flush=True)

    print(f"\nTRAINING — {args.encoder} encoder on {len(train_tiles)} tiles "
          f"of {args.tile}x{args.tile} cells")
    model = fit_image_model(train_tiles, val_tiles, channels=raw_train.names,
                            n_dates=n_dates, source=args.source, normaliser=normaliser,
                            config=conf, progress=show)
    log.info("network: %s parameters (%s trainable), best epoch %d, "
             "validation AUC %.4f / AP %.4f", f"{model.n_parameters:,}",
             f"{model.n_trainable:,}", model.best_epoch, model.val_auc,
             model.val_average_precision)

    # ---- score once on the held-out period --------------------------------
    surface = predict_surface(model, raw_test, tile=args.tile,
                              stride=max(1, args.tile // 4), device=args.device)
    sm = SurfaceModel(surface=surface, kind=f"image_model_{args.encoder}")
    _, predicted, observed, eligible = GM.validate(sm, built, None, fine,
                                                   test=test_period, urban_threshold=thr)
    folds = TL.block_folds(ids, n_folds=5, seed=args.seed)
    bands = [("distance_centre_km", dist, [0, 3, 6, 9, 12, 30]),
             ("distance_to_urban_edge_km", GM.build_drivers(
                 built[test_period[0]], fine, distance_km=dist,
                 urban_threshold=thr)[0][:, 3].reshape(fine.shape),
              [0, 0.3, 0.6, 1.0, 2.0, 30])]
    report = AN.summarise(f"image_model_{args.encoder}", score=surface,
                          predicted=predicted, observed=observed, eligible=eligible,
                          folds=folds, bands=bands, seed=args.seed)
    baseline = AN.random_allocation_baseline(observed, eligible, seed=args.seed)
    report["skill_vs_random"] = (
        round(report["validation"]["figure_of_merit"] / baseline["mean_figure_of_merit"], 1)
        if baseline["mean_figure_of_merit"] else None)

    # ---- write ------------------------------------------------------------
    mdir = cfg.processed_dir / "models"
    mdir.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    ckpt = Path(args.out) if args.out else mdir / f"image_model_{args.source}{tag}.pt"
    model.save(ckpt)
    with rasterio.open(rdir / "growth_suitability_image.tif", "w",
                       **fine.profile("float32")) as ds:
        ds.write(surface, 1)

    payload = {
        "model": model.as_dict(),
        "input": raw_train.as_dict(),
        "transitions": {"train": tr_train.as_dict(), "test": tr_test.as_dict()},
        "spatial_blocks": {"block_km": args.block_km, "n_blocks": int(len(np.unique(ids))),
                           "validation_blocks": len(val_blocks),
                           "train_tiles": len(train_tiles),
                           "validation_tiles": len(val_tiles),
                           "tiles_dropped_as_buffer": len(origins) - len(tr_origins)
                           - len(va_origins),
                           "rule": ("a tile is used for training only if it contains no "
                                    "validation pixel, and for validation only if every "
                                    "pixel is one; the rest are the buffer")},
        "analytics": report,
        "random_baseline": baseline,
        "checkpoint": str(ckpt),
        "runtime_s": round(time.time() - t_start, 1),
    }
    out = cfg.outputs_dir / f"{aoi.slug}_image_model{tag}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    v = report["validation"]
    print("\n" + "=" * 70)
    print(f"IMAGE MODEL — train {train_period[0]}-{train_period[1]}, "
          f"test {test_period[0]}-{test_period[1]} (held out)")
    print("=" * 70)
    print(f"  parameters          {model.n_parameters:,} ({model.n_trainable:,} trainable)")
    print(f"  validation AUC      {model.val_auc:.4f}   "
          f"(spatial blocks, same period)")
    print(f"  validation AP       {model.val_average_precision:.4f}   "
          f"(monitored: {conf.monitor})")
    print(f"  test AUC            {report['auc_test']:.4f}")
    print(f"  average precision   {report['average_precision']:.4f}   "
          f"({report['average_precision_lift']}x the base rate)")
    print(f"  Figure of Merit     {v['figure_of_merit']:.4f}   "
          f"({report['skill_vs_random']}x random)")
    print(f"  hits / misses / false alarms   {v['hits']} / {v['misses']} / "
          f"{v['false_alarms']}")
    print(f"\n  checkpoint  {ckpt}")
    print(f"  summary     {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
