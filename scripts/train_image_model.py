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

LABEL_EPOCHS = list(range(1975, 2026, 5))


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
    ap.add_argument("--finetune", action="store_true",
                    help="also train the pretrained encoder, not just the decoder")
    ap.add_argument("--cache-encoder", action="store_true",
                    help="run a frozen encoder once and reuse its features "
                         "(minutes instead of hours for the 300M transformer)")
    ap.add_argument("--prithvi-checkpoint",
                    default="data/raw/models/prithvi/Prithvi_EO_V2_300M_TL.pt",
                    help="local copy of the published weights; downloaded from "
                         "Hugging Face if this path does not exist")
    ap.add_argument("--pixel-m", type=float, default=30.0,
                    help="working resolution for the Landsat source")
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
    ap.add_argument("--single-transition", action="store_true",
                    help="train on the latest transition only, as the first run did")
    ap.add_argument("--max-dates", type=int, default=2,
                    help="how many input dates to use when the data allows it")
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
        args.block_km = 16.0 if args.source == "landsat" else 8.0
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
    test_period = tuple(int(y) for y in cfg.get("growth_model.test", [2015, 2020]))
    rdir = cfg.processed_dir / "rasters"

    if args.encoder == "prithvi" and args.source != "landsat":
        log.error("the pretrained encoder reads six satellite bands; use --source landsat")
        return 2

    # ---- which transitions can be labelled at all? ------------------------
    have_labels = [y for y in LABEL_EPOCHS
                   if (rdir / f"builtup_m2_{y}.tif").exists() and y <= 2020]
    pairs = [(t, t + 5) for t in have_labels if (t + 5) in have_labels]
    train_periods = [p for p in pairs if p[1] <= test_period[0]]
    if args.single_transition:
        train_periods = train_periods[-1:]
    if test_period not in pairs:
        log.error("no labels for the test period %s", test_period)
        return 2
    if not train_periods:
        log.error("no labelled training transition before %d", test_period[0])
        return 2

    built = {y: read(rdir, f"builtup_m2_{y}") / fine.res**2 for y in have_labels}
    pop = {y: read(rdir, f"population_{y}") for y in have_labels
           if (rdir / f"population_{y}.tif").exists()}
    dist = read(rdir, "distance_km")
    roads = read(rdir, "road_density")
    slope = None
    slope_p = cfg.raw_dir / "gee" / "slope.tif"
    if slope_p.exists():
        slope = np.nan_to_num(gee.to_frame(slope_p, fine), nan=0.0)

    # ---- the grid the network actually works on ---------------------------
    if args.source == "landsat":
        mframe = aoi.frame(args.pixel_m)
        lut = TL.cell_lookup(mframe, fine)
        paths = {y: cfg.raw_dir / "gee" / f"landsat_{y}.tif" for y in LABEL_EPOCHS}
        have_input = {y for y, p in paths.items() if p.exists()}
    else:
        mframe, lut, paths = fine, None, {}
        have_input = set(built)

    needed = [p[0] for p in train_periods] + [test_period[0]]
    missing = [y for y in needed if y not in have_input]
    if missing:
        log.error("%s stack missing for %s", args.source, missing)
        return 2
    n_dates = (min(args.max_dates, 2)
               if all((t0 - 5) in have_input for t0 in needed) else 1)
    input_years = {t0: ([t0 - 5, t0] if n_dates == 2 else [t0]) for t0 in needed}

    log.info("labels available: %s", have_labels)
    log.info("train on %s | test on %d-%d (held out)",
             ", ".join(f"{a}-{b}" for a, b in train_periods), *test_period)
    log.info("channel source %s at %d m on a %s grid | %d input date(s) per sample",
             args.source, int(mframe.res), mframe.shape, n_dates)

    # Drivers are optional in the tabular model — a year without population
    # simply gets no population column. An image model cannot do that: every
    # transition has to present the same channels in the same order, or the
    # filters mean different things at different dates. So a driver is used
    # only if every date the model will see has it.
    years_used = sorted({y for t0 in needed for y in input_years[t0]})
    use_pop = all(y in pop for y in years_used)
    if not use_pop and args.source == "drivers":
        log.info("population excluded: no GHS-POP raster for %s, and every "
                 "transition must show the model the same channels",
                 [y for y in years_used if y not in pop])

    def stack_for(t0: int) -> ST.TemporalStack:
        years = input_years[t0]
        if args.source == "landsat":
            return ST.landsat_stack(paths, mframe, years=years)
        return ST.driver_stack(built, mframe, years=years, distance_km=dist,
                               road_density=roads, population=pop if use_pop else None,
                               slope=slope, urban_threshold=thr)

    raw = {t0: stack_for(t0) for t0 in needed}
    log.info("channels: %s", ", ".join(raw[needed[0]].names))

    # ---- normalisation ----------------------------------------------------
    if args.encoder == "prithvi":
        from urbanintel.deep import prithvi as PR

        local = Path(args.prithvi_checkpoint)
        if local.exists() and (local.parent / "config.json").exists():
            import json as _json

            pcfg = _json.loads((local.parent / "config.json").read_text(encoding="utf-8"))
            log.info("pretrained weights: %s (%.0f MB)", local,
                     local.stat().st_size / 1e6)
        else:
            local, pcfg = PR.fetch()
            log.info("pretrained weights downloaded to %s", local)
        mean, std = PR.band_statistics(pcfg)
        normaliser = ST.Normaliser(mean, std, ST.LANDSAT_BANDS)
        log.info("normalising with the pretrained model's own band statistics")
    else:
        normaliser = ST.Normaliser.fit([raw[t0] for t0, _ in train_periods])

    # ---- labels, painted onto the working grid ----------------------------
    def transition(t0: int, t1: int) -> TL.Transition:
        label, eligible = ST.transition_labels(built[t0], built[t1], urban_threshold=thr)
        if lut is not None:
            ok = lut >= 0
            idx = np.clip(lut, 0, None)
            label = np.where(ok, label.ravel()[idx], 0).astype("uint8")
            eligible = np.where(ok, eligible.ravel()[idx], False)
        return TL.Transition(normaliser.apply(raw[t0]), label, eligible, (t0, t1))

    trs = {p: transition(*p) for p in train_periods + [test_period]}
    for p, tr in trs.items():
        log.info("transition %d-%d: %d eligible, %d conversions (%.2f%%)%s",
                 p[0], p[1], int(tr.eligible.sum()), int(tr.label.sum()),
                 100 * tr.label.sum() / max(tr.eligible.sum(), 1),
                 "   <- held out" if p == test_period else "")

    # ---- spatial blocks ---------------------------------------------------
    ids = TL.block_ids(mframe.shape, mframe, block_m=args.block_km * 1000.0)
    val_mask, val_blocks = TL.block_split(ids, val_fraction=args.val_fraction,
                                          seed=args.seed, min_span=args.tile)
    origins = TL.tile_origins(mframe.shape, args.tile, args.stride)
    tr_origins = TL.select_origins(origins, args.tile, val_mask, want="train")
    va_origins = TL.select_origins(origins, args.tile, val_mask, want="val")
    log.info("blocks %d km: %d held out of %d | tile positions %d train, %d validation "
             "(%d dropped as buffer)", int(args.block_km), len(val_blocks),
             len(np.unique(ids)), len(tr_origins), len(va_origins),
             len(origins) - len(tr_origins) - len(va_origins))
    if not va_origins or not tr_origins:
        log.error("no tile fits inside a held-out block; raise --block-km or lower --tile")
        return 2

    train_list = [trs[p] for p in train_periods]
    train_tiles = TL.build_tiles(train_list, tr_origins, size=args.tile)
    val_tiles = TL.build_tiles(train_list, va_origins, size=args.tile)
    log.info("training on %d tiles (%d converted cells), validating on %d",
             len(train_tiles), train_tiles.n_positive, len(val_tiles))

    # ---- train ------------------------------------------------------------
    conf = TrainConfig(
        epochs=3 if args.quick else args.epochs, batch_size=args.batch_size,
        lr=args.lr, lr_encoder=args.lr_encoder, patience=args.patience,
        dropout=args.dropout, seed=args.seed, device=args.device,
        encoder=args.encoder, monitor=args.monitor,
        freeze_encoder=not args.finetune,
        cache_encoder=args.cache_encoder and not args.finetune,
        encoder_checkpoint=(str(local) if args.encoder == "prithvi" else None),
        widths=tuple(args.widths) if args.widths
        else ((16, 32, 64) if args.quick else (32, 64, 128)),
    )

    def show(row: dict) -> None:
        if row.get("note"):
            print(f"  {row['note']}", flush=True)
            return
        print(f"  epoch {row['epoch']:>3d}/{conf.epochs}   loss {row['train_loss']:.4f}   "
              f"val loss {row['val_loss']:.4f}   "
              f"val AUC {row['val_auc'] or float('nan'):.4f}   "
              f"val AP {row['val_average_precision'] or float('nan'):.4f}   "
              f"{row['seconds']:.1f}s", flush=True)

    mdir = cfg.processed_dir / "models"
    mdir.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    ckpt = Path(args.out) if args.out else mdir / f"image_model_{args.source}{tag}.pt"

    print(f"\nTRAINING - {args.encoder} encoder, {args.source} at {int(mframe.res)} m, "
          f"{len(train_tiles)} tiles of {args.tile}x{args.tile}")
    model = fit_image_model(train_tiles, val_tiles, channels=raw[needed[0]].names,
                            n_dates=n_dates, source=args.source, normaliser=normaliser,
                            config=conf, progress=show, checkpoint=ckpt)
    log.info("network: %s parameters (%s trainable), best epoch %d, "
             "validation AUC %.4f / AP %.4f", f"{model.n_parameters:,}",
             f"{model.n_trainable:,}", model.best_epoch, model.val_auc,
             model.val_average_precision)

    # ---- score once on the held-out period --------------------------------
    surface = predict_surface(model, raw[test_period[0]], tile=args.tile,
                              stride=max(1, args.tile // 4), device=args.device,
                              batch_size=max(1, args.batch_size // 2))
    if lut is not None:
        surface = np.nan_to_num(TL.aggregate_to_cells(surface, lut, fine), nan=0.0)
        log.info("aggregated %d m predictions onto the %d m analysis grid",
                 int(mframe.res), int(fine.res))

    sm = SurfaceModel(surface=surface, kind=f"image_model_{args.encoder}")
    _, predicted, observed, eligible = GM.validate(sm, built, None, fine,
                                                   test=test_period, urban_threshold=thr)
    cell_ids = TL.block_ids(fine.shape, fine, block_m=args.block_km * 1000.0)
    folds = TL.block_folds(cell_ids, n_folds=5, seed=args.seed)
    edge = GM.build_drivers(built[test_period[0]], fine, distance_km=dist,
                            urban_threshold=thr)[0][:, 3].reshape(fine.shape)
    bands = [("distance_centre_km", dist, [0, 3, 6, 9, 12, 30]),
             ("distance_to_urban_edge_km", edge, [0, 0.3, 0.6, 1.0, 2.0, 30])]
    report = AN.summarise(f"image_model_{args.encoder}", score=surface,
                          predicted=predicted, observed=observed, eligible=eligible,
                          folds=folds, bands=bands, seed=args.seed)
    baseline = AN.random_allocation_baseline(observed, eligible, seed=args.seed)
    report["skill_vs_random"] = (
        round(report["validation"]["figure_of_merit"] / baseline["mean_figure_of_merit"], 1)
        if baseline["mean_figure_of_merit"] else None)

    # ---- write ------------------------------------------------------------
    model.save(ckpt)
    Path(ckpt).with_suffix(".partial.pt").unlink(missing_ok=True)
    with rasterio.open(rdir / f"growth_suitability_image{tag}.tif", "w",
                       **fine.profile("float32")) as ds:
        ds.write(surface.astype("float32"), 1)

    payload = {
        "model": model.as_dict(),
        "input": raw[needed[0]].as_dict(),
        "working_grid": {"resolution_m": mframe.res, "shape": list(mframe.shape),
                         "aggregated_to_m": fine.res if lut is not None else None},
        "transitions": {f"{a}-{b}": trs[(a, b)].as_dict()
                        for a, b in train_periods + [test_period]},
        "training_transitions": [f"{a}-{b}" for a, b in train_periods],
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
    print("\n" + "=" * 72)
    print(f"IMAGE MODEL - {args.encoder} encoder on {args.source} at {int(mframe.res)} m")
    print("=" * 72)
    print(f"  training transitions   {', '.join(f'{a}-{b}' for a, b in train_periods)}")
    print(f"  test period            {test_period[0]}-{test_period[1]} (held out)")
    print(f"  input dates per sample {n_dates}")
    print(f"  parameters             {model.n_parameters:,} "
          f"({model.n_trainable:,} trainable)")
    print(f"  validation AUC / AP    {model.val_auc:.4f} / "
          f"{model.val_average_precision:.4f}")
    print(f"  test AUC               {report['auc_test']:.4f}")
    print(f"  average precision      {report['average_precision']:.4f}   "
          f"({report['average_precision_lift']}x the base rate)")
    print(f"  Figure of Merit        {v['figure_of_merit']:.4f}   "
          f"({report['skill_vs_random']}x random)")
    print(f"  hits / misses / false  {v['hits']} / {v['misses']} / {v['false_alarms']}")
    print(f"  runtime                {payload['runtime_s'] / 60:.1f} min")
    print(f"\n  checkpoint  {ckpt}")
    print(f"  summary     {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
