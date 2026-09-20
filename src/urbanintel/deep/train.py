from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .stacks import Normaliser, TemporalStack
from .tiles import Tiles, dihedral, symmetry, tile_origins


@dataclass
class TrainConfig:
    """Everything that decides what the fitted network is."""

    epochs: int = 40
    batch_size: int = 16
    lr: float = 1e-3                     # decoder, and a from-scratch encoder
    lr_encoder: float | None = None      # 1e-5 when fine-tuning pretrained weights
    weight_decay: float = 1e-4
    patience: int = 8
    focal_alpha: float = 0.25
    focal_gamma: float = 2.0
    dice_weight: float = 0.5
    dropout: float = 0.1
    oversample: float = 4.0
    steps_per_epoch: int | None = None
    monitor: str = "average_precision"   # what early stopping watches
    cache_encoder: bool = False          # only valid when the encoder is frozen
    seed: int = 0
    device: str = "auto"
    encoder: str = "local"
    widths: tuple[int, ...] = (32, 64, 128)
    decoder_width: int = 64
    freeze_encoder: bool = True
    encoder_checkpoint: str | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["widths"] = list(self.widths)
        return d


@dataclass
class ImageModel:
    """A fitted image model, with everything needed to reproduce its predictions."""

    net: object
    normaliser: Normaliser
    channels: list[str]
    n_dates: int
    tile_size: int
    source: str
    config: TrainConfig
    history: list[dict] = field(default_factory=list)
    best_epoch: int = 0
    val_score: float = float("nan")        # the monitored metric, at the best epoch
    val_auc: float = float("nan")
    val_average_precision: float = float("nan")
    n_parameters: int = 0
    n_trainable: int = 0
    encode_seconds: float = 0.0
    train_periods: list[tuple[int, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": f"image_model_{self.config.encoder}",
            "source": self.source,
            "channels": self.channels,
            "n_dates": self.n_dates,
            "tile_size": self.tile_size,
            "parameters": self.n_parameters,
            "trainable_parameters": self.n_trainable,
            "train_periods": [f"{a}-{b}" for a, b in self.train_periods],
            "best_epoch": self.best_epoch,
            "monitored_metric": self.config.monitor,
            "validation_auc": (None if np.isnan(self.val_auc)
                               else round(float(self.val_auc), 4)),
            "validation_average_precision": (
                None if np.isnan(self.val_average_precision)
                else round(float(self.val_average_precision), 4)),
            "encoder_seconds": round(self.encode_seconds, 1),
            "config": self.config.as_dict(),
            "history": self.history,
            "notes": self.notes,
        }

    def save(self, path: Path) -> None:
        import torch

        torch.save({
            "state_dict": self.net.state_dict(),
            "normaliser": self.normaliser.as_dict(),
            "channels": self.channels,
            "n_dates": self.n_dates,
            "tile_size": self.tile_size,
            "source": self.source,
            "config": self.config.as_dict(),
            "history": self.history,
            "best_epoch": self.best_epoch,
            "val_score": self.val_score,
            "val_auc": self.val_auc,
            "val_average_precision": self.val_average_precision,
            "train_periods": self.train_periods,
            "notes": self.notes,
        }, path)

    @classmethod
    def load(cls, path: Path) -> "ImageModel":
        import torch

        from .nets import GrowthNet

        blob = torch.load(path, map_location="cpu", weights_only=False)
        cfg = TrainConfig(**{**blob["config"], "widths": tuple(blob["config"]["widths"])})
        net = GrowthNet(n_channels=len(blob["channels"]), n_dates=blob["n_dates"],
                        encoder=cfg.encoder, widths=cfg.widths,
                        decoder_width=cfg.decoder_width, dropout=cfg.dropout,
                        freeze_encoder=cfg.freeze_encoder,
                        encoder_checkpoint=cfg.encoder_checkpoint)
        net.load_state_dict(blob["state_dict"])
        net.eval()
        return cls(net=net, normaliser=Normaliser.from_dict(blob["normaliser"]),
                   channels=blob["channels"], n_dates=blob["n_dates"],
                   tile_size=blob["tile_size"], source=blob["source"], config=cfg,
                   history=blob["history"], best_epoch=blob["best_epoch"],
                   val_score=blob.get("val_score", blob["val_auc"]),
                   val_auc=blob["val_auc"],
                   val_average_precision=blob.get("val_average_precision",
                                                  float("nan")),
                   n_parameters=net.n_parameters, n_trainable=net.n_trainable,
                   train_periods=[tuple(p) for p in blob["train_periods"]],
                   notes=blob["notes"])


def resolve_device(name: str):
    import torch

    if name != "auto":
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _pixel_scores(scores: np.ndarray, labels: np.ndarray, *,
                  max_negatives: int = 200_000, seed: int = 0) -> dict:
    """Ranking quality over the eligible validation pixels.

    Average precision is the one to watch. The cellular automaton takes the
    top cells and ignores the rest, so what matters is whether the first
    percent of the ranking is right. That is what average precision
    measures, and what AUC, dominated by the 99 percent of easy negatives,
    does not.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    y = labels.astype("int8")
    if y.min() == y.max():
        return {"auc": float("nan"), "average_precision": float("nan")}
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    if len(neg) > max_negatives:
        neg = rng.choice(neg, size=max_negatives, replace=False)
    idx = np.concatenate([pos, neg])
    return {"auc": float(roc_auc_score(y[idx], scores[idx])),
            "average_precision": float(average_precision_score(y[idx], scores[idx]))}


def fit_image_model(
    train_tiles: Tiles,
    val_tiles: Tiles,
    *,
    channels: list[str],
    n_dates: int,
    source: str,
    normaliser: Normaliser,
    config: TrainConfig | None = None,
    progress: Callable[[dict], None] | None = None,
    checkpoint: Path | None = None,
) -> ImageModel:
    """Train the conversion network, stopping on a spatially held-out score.

    Early stopping watches `config.monitor` — average precision by default —
    on validation blocks inside the *training* period, never on the test
    period, which the caller scores once afterwards. Tiles are drawn with
    replacement
    using `TileSet.sample_weights`, and each draw is randomly rotated or
    reflected, so no two epochs see quite the same data.
    """
    import torch

    from .nets import GrowthNet, combined_loss

    cfg = config or TrainConfig()
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    device = resolve_device(cfg.device)

    net = GrowthNet(n_channels=len(channels), n_dates=n_dates, encoder=cfg.encoder,
                    widths=cfg.widths, decoder_width=cfg.decoder_width,
                    dropout=cfg.dropout, freeze_encoder=cfg.freeze_encoder,
                    encoder_checkpoint=cfg.encoder_checkpoint).to(device)

    enc_lr = cfg.lr if cfg.lr_encoder is None else cfg.lr_encoder
    groups = [
        {"params": [p for p in net.encoder.parameters() if p.requires_grad], "lr": enc_lr},
        {"params": list(net.decoder.parameters()), "lr": cfg.lr},
    ]
    opt = torch.optim.AdamW([g for g in groups if g["params"]], weight_decay=cfg.weight_decay)

    # Caching only makes sense for a pretrained encoder. Freezing a
    # randomly initialised one and training the decoder on its output
    # would be a random-features model, not the model asked for.
    cache = cfg.cache_encoder and cfg.freeze_encoder and cfg.encoder != "local"
    if cache:
        # A frozen encoder returns the same features for the same tile every
        # epoch, so running the 300M transformer once and keeping its output
        # turns hours of repeated forward passes into minutes. Augmentation
        # then rotates the feature map rather than the image, which is the
        # same symmetry applied one stage later.
        def encode_all(tiles):
            out = []
            with torch.no_grad():
                for s in range(0, len(tiles), cfg.batch_size):
                    xn, _, _ = tiles.batch(range(s, min(s + cfg.batch_size,
                                                        len(tiles))))
                    feats = net.encode(torch.from_numpy(xn).to(device))
                    out.extend(zip(*[f.cpu().numpy() for f in feats]))
                    if progress and s % (cfg.batch_size * 10) == 0:
                        progress({"epoch": 0, "train_loss": float("nan"),
                                  "val_loss": float("nan"), "val_auc": None,
                                  "val_average_precision": None,
                                  "seconds": 0.0,
                                  "note": f"encoding tile {s}/{len(tiles)}"})
            return out

        net.eval()
        t_enc = time.time()
        feat_train = encode_all(train_tiles)
        feat_val = encode_all(val_tiles)
        enc_seconds = time.time() - t_enc
    else:
        feat_train = feat_val = None
        enc_seconds = 0.0

    weights = train_tiles.sample_weights(oversample=cfg.oversample)
    weights = weights / weights.sum()
    steps = cfg.steps_per_epoch or max(1, int(np.ceil(len(train_tiles) / cfg.batch_size)))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, cfg.epochs * steps))


    best_score, best_state, best_epoch, stale = -np.inf, None, 0, 0
    best_val: dict = {}
    history: list[dict] = []

    for epoch in range(1, cfg.epochs + 1):
        t0 = time.time()
        net.train()
        run_loss = run_focal = run_dice = 0.0
        for _ in range(steps):
            idx = rng.choice(len(train_tiles), size=cfg.batch_size, replace=True, p=weights)
            xb, yb, mb = [], [], []
            for i in idx:
                k = int(rng.integers(0, 8))
                if cache:
                    _, y0, m0 = train_tiles.get(int(i))
                    # The encoder returns one feature map per scale; the same
                    # symmetry is applied to each of them and to the labels.
                    x = symmetry(list(feat_train[int(i)]), k)
                    y, m = symmetry([y0, m0], k)
                else:
                    x, y, m = dihedral(*train_tiles.get(int(i)), k)
                xb.append(x), yb.append(y), mb.append(m)
            y = torch.from_numpy(np.stack(yb).astype("float32")).unsqueeze(1).to(device)
            m = torch.from_numpy(np.stack(mb).astype("float32")).unsqueeze(1).to(device)
            if cache:
                x = [torch.from_numpy(np.stack([s[j] for s in xb]).astype("float32")
                                      ).to(device) for j in range(len(xb[0]))]
            else:
                x = torch.from_numpy(np.stack(xb).astype("float32")).to(device)

            opt.zero_grad(set_to_none=True)
            out = (net.decode(x, y.shape[-2:]) if cache else net(x))
            loss, focal, dice = combined_loss(out, y, m, alpha=cfg.focal_alpha,
                                              gamma=cfg.focal_gamma,
                                              dice_weight=cfg.dice_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step()
            sched.step()
            run_loss += float(loss.detach())
            run_focal += focal
            run_dice += dice

        net.eval()
        with torch.no_grad():
            scores, labels, masks, losses = [], [], [], []
            for s in range(0, len(val_tiles), cfg.batch_size):
                xn, yn, mn = val_tiles.batch(range(s, min(s + cfg.batch_size,
                                                          len(val_tiles))))
                yb = torch.from_numpy(yn.astype("float32")).unsqueeze(1).to(device)
                mb = torch.from_numpy(mn.astype("float32")).unsqueeze(1).to(device)
                if cache:
                    rows = range(s, min(s + cfg.batch_size, len(val_tiles)))
                    n_scale = len(feat_val[0])
                    fx = [torch.from_numpy(
                        np.stack([feat_val[j][k] for j in rows]).astype("float32")
                    ).to(device) for k in range(n_scale)]
                    logit = net.decode(fx, yb.shape[-2:])
                else:
                    logit = net(torch.from_numpy(xn).to(device))
                vl, _, _ = combined_loss(logit, yb, mb, alpha=cfg.focal_alpha,
                                         gamma=cfg.focal_gamma, dice_weight=cfg.dice_weight)
                losses.append(float(vl))
                scores.append(torch.sigmoid(logit).squeeze(1).cpu().numpy())
                labels.append(yn), masks.append(mn)
        sc = np.concatenate(scores)
        elig = np.concatenate(masks)
        val = _pixel_scores(sc[elig], np.concatenate(labels)[elig], seed=cfg.seed)
        watched = val.get(cfg.monitor, val["average_precision"])

        row = {"epoch": epoch, "train_loss": round(run_loss / steps, 5),
               "train_focal": round(run_focal / steps, 5),
               "train_dice": round(run_dice / steps, 5),
               "val_loss": round(float(np.mean(losses)), 5),
               "val_auc": None if np.isnan(val["auc"]) else round(val["auc"], 4),
               "val_average_precision": (None if np.isnan(val["average_precision"])
                                         else round(val["average_precision"], 4)),
               "seconds": round(time.time() - t0, 1)}
        history.append(row)
        if progress:
            progress(row)

        if not np.isnan(watched) and watched > best_score + 1e-5:
            best_score, best_epoch, stale = watched, epoch, 0
            best_val = dict(val)
            best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
            if checkpoint is not None:
                # A long run should never be one crash away from nothing. The
                # best weights so far are written the moment they improve, so
                # an interrupted run still leaves a usable model behind.
                tmp = Path(checkpoint).with_suffix(".partial.pt")
                torch.save({"state_dict": best_state, "epoch": epoch,
                            "score": float(best_score), "metric": cfg.monitor,
                            "history": history}, tmp)
        else:
            stale += 1
            if stale >= cfg.patience:
                break

    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()

    return ImageModel(
        net=net, normaliser=normaliser, channels=list(channels), n_dates=n_dates,
        tile_size=int(train_tiles.size), source=source, config=cfg,
        history=history, best_epoch=best_epoch, val_score=float(best_score),
        encode_seconds=enc_seconds,
        n_parameters=net.n_parameters, n_trainable=net.n_trainable,
        train_periods=sorted(set(train_tiles.periods)),
        val_auc=float(best_val.get("auc", float("nan"))),
        val_average_precision=float(best_val.get("average_precision", float("nan"))),
        notes=[
            "Early stopping used validation blocks inside the training period only; "
            "the test period was scored once, after training finished.",
            f"Best epoch {best_epoch} of {len(history)} by validation {cfg.monitor}.",
        ],
    )


def predict_surface(
    model: ImageModel,
    stack: TemporalStack,
    *,
    tile: int | None = None,
    stride: int | None = None,
    batch_size: int = 8,
    device: str | None = None,
    mc_dropout: bool = False,
    seed: int = 0,
) -> np.ndarray:
    """Conversion probability for every pixel, by sliding window.

    Windows overlap and their logits are averaged before the sigmoid, so the
    seams between tiles do not show up as edges in the surface. With
    `mc_dropout` the dropout layers stay active, which turns one forward pass
    into one sample from the model's posterior — repeated draws give the
    uncertainty band reported in the analytics.
    """
    import torch

    dev = resolve_device(device or model.config.device)
    net = model.net.to(dev)
    net.eval()
    if mc_dropout:
        torch.manual_seed(seed)
        for mod in net.modules():
            if isinstance(mod, (torch.nn.Dropout, torch.nn.Dropout2d)):
                mod.train()

    data = model.normaliser.apply(stack).data
    h, w = stack.shape
    size = tile or model.tile_size
    step = stride or max(1, size // 2)
    origins = tile_origins((h, w), size, step)

    total = np.zeros((h, w), dtype="float64")
    count = np.zeros((h, w), dtype="float64")
    with torch.no_grad():
        for s in range(0, len(origins), batch_size):
            chunk = origins[s:s + batch_size]
            xb = np.stack([data[:, :, r:r + size, c:c + size] for r, c in chunk])
            logit = net(torch.from_numpy(xb).to(dev)).squeeze(1).cpu().numpy()
            for (r, c), lg in zip(chunk, logit):
                total[r:r + size, c:c + size] += lg
                count[r:r + size, c:c + size] += 1.0
    mean_logit = total / np.maximum(count, 1.0)
    return (1.0 / (1.0 + np.exp(-np.clip(mean_logit, -50, 50)))).astype("float32")


def dropout_ensemble(model: ImageModel, stack: TemporalStack, *, n: int = 20,
                     **kw) -> np.ndarray:
    """`n` suitability surfaces sampled with dropout left on. Shape (n, H, W)."""
    return np.stack([predict_surface(model, stack, mc_dropout=True, seed=i, **kw)
                     for i in range(n)])
