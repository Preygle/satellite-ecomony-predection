from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn



class ConvBlock(nn.Module):
    """Two 3x3 convolutions with batch normalisation, optionally halving the grid."""

    def __init__(self, c_in: int, c_out: int, *, stride: int = 1, dropout: float = 0.0):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(c_in, c_out, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
            nn.Conv2d(c_out, c_out, 3, padding=1, bias=False),
            nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
        )
        self.drop = nn.Dropout2d(dropout) if dropout > 0 else nn.Identity()

    def forward(self, x):
        return self.drop(self.body(x))


class LocalEncoder(nn.Module):
    """A small convolutional encoder trained from scratch.

    Deliberately small — around a hundred thousand parameters — because the
    training period contains roughly 1,400 conversions. It is the default
    encoder: it needs no download, trains on a laptop, and is the honest
    baseline a pretrained encoder has to beat.
    """

    def __init__(self, in_channels: int, widths: tuple[int, ...] = (32, 64, 128),
                 dropout: float = 0.1):
        super().__init__()
        self.stem = ConvBlock(in_channels, widths[0])
        self.downs = nn.ModuleList([
            ConvBlock(widths[i], widths[i + 1], stride=2, dropout=dropout)
            for i in range(len(widths) - 1)
        ])
        self.out_channels = list(widths)
        self.expects_time_axis = False

    def forward(self, x):
        feats = [self.stem(x)]
        for down in self.downs:
            feats.append(down(feats[-1]))
        return feats                       # finest first


class UNetDecoder(nn.Module):
    """Upsamples encoder features back to the input grid, one logit per pixel."""

    def __init__(self, feat_channels: list[int], *, width: int = 64,
                 out_channels: int = 1, dropout: float = 0.1, n_refine: int = 4):
        super().__init__()
        coarse_first = list(reversed(feat_channels))
        self.project = nn.Conv2d(coarse_first[0], width, 1)
        self.skips = nn.ModuleList([
            ConvBlock(width + c, width, dropout=dropout) for c in coarse_first[1:]
        ])
        # With a single feature map (a transformer encoder) there is nothing to
        # concatenate, so the decoder refines as it upsamples instead.
        self.refine = nn.ModuleList([
            ConvBlock(width, width, dropout=dropout) for _ in range(n_refine)
        ]) if len(feat_channels) == 1 else nn.ModuleList()
        self.head = nn.Conv2d(width, out_channels, 1)

    def forward(self, feats, out_size):
        f = list(reversed(feats))
        x = self.project(f[0])
        for block, skip in zip(self.skips, f[1:]):
            x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
            x = block(torch.cat([x, skip], dim=1))
        for block in self.refine:
            x = block(F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False))
        if x.shape[-2:] != tuple(out_size):
            x = F.interpolate(x, size=out_size, mode="bilinear", align_corners=False)
        return self.head(x)


class GrowthNet(nn.Module):
    """Encoder plus decoder: bi-temporal input in, one conversion logit per pixel out."""

    def __init__(self, *, n_channels: int, n_dates: int, encoder: str = "local",
                 widths: tuple[int, ...] = (32, 64, 128), decoder_width: int = 64,
                 dropout: float = 0.1, freeze_encoder: bool = True,
                 encoder_checkpoint: str | None = None):
        super().__init__()
        self.encoder_kind = encoder
        if encoder == "local":
            self.encoder = LocalEncoder(n_channels * n_dates, widths, dropout)
        elif encoder == "prithvi":
            from .prithvi import PrithviEncoder

            self.encoder = PrithviEncoder(n_dates=n_dates, freeze=freeze_encoder,
                                          checkpoint=encoder_checkpoint)
        else:
            raise ValueError(f"unknown encoder {encoder!r}; use 'local' or 'prithvi'")
        self.decoder = UNetDecoder(self.encoder.out_channels, width=decoder_width,
                                   dropout=dropout)

    def encode(self, x):                             # (B, T, C, H, W)
        b, t, c, h, w = x.shape
        z = x if self.encoder.expects_time_axis else x.reshape(b, t * c, h, w)
        return self.encoder(z)

    def decode(self, feats, out_size):
        return self.decoder(feats, out_size)

    def forward(self, x):                            # (B, T, C, H, W)
        return self.decoder(self.encode(x), (x.shape[-2], x.shape[-1]))

    @property
    def n_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    @property
    def n_trainable(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# --------------------------------------------------------------------------
# Losses
# --------------------------------------------------------------------------

def masked_focal_bce(logits, target, mask, *, alpha: float = 0.25,
                     gamma: float = 2.0):
    """Focal cross-entropy over eligible pixels only.

    About one eligible cell in a hundred converts. Plain cross-entropy would
    be dominated by the easy negatives; the focal term down-weights pixels the
    model already gets right, so the gradient keeps coming from the edge of
    the built-up area where the decision is actually difficult.
    """
    t = target.float()
    w = mask.float()
    bce = F.binary_cross_entropy_with_logits(logits, t, reduction="none")
    p = torch.sigmoid(logits)
    p_t = p * t + (1 - p) * (1 - t)
    a_t = alpha * t + (1 - alpha) * (1 - t)
    loss = a_t * (1 - p_t).pow(gamma) * bce
    return (loss * w).sum() / w.sum().clamp(min=1.0)


def masked_dice(logits, target, mask, *, eps: float = 1.0):
    """Soft overlap between predicted and observed conversion, over eligible pixels.

    Cross-entropy scores pixels one at a time; this scores the predicted
    *set* against the observed set, which is closer to the Figure of Merit the
    model is finally judged on.
    """
    p = torch.sigmoid(logits) * mask.float()
    t = target.float() * mask.float()
    dims = tuple(range(1, p.dim()))
    inter = (p * t).sum(dims)
    denom = p.sum(dims) + t.sum(dims)
    return 1.0 - ((2 * inter + eps) / (denom + eps)).mean()


def combined_loss(logits, target, mask, *, alpha: float = 0.25, gamma: float = 2.0,
                  dice_weight: float = 0.5):
    focal = masked_focal_bce(logits, target, mask, alpha=alpha, gamma=gamma)
    dice = masked_dice(logits, target, mask)
    return focal + dice_weight * dice, float(focal.detach()), float(dice.detach())
