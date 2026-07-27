"""Green cover and its loss to urban expansion.

Two questions this answers for a planner:

* How much vegetated land did the city lose, and where?
* How much of that loss was *converted to built-up* rather than lost to
  seasonal or agricultural variation?

The second question is the one that matters, and it is why green loss is
always intersected with built-up gain here. Varanasi sits in intensively
cropped Gangetic plain; a naive year-on-year NDVI difference mostly measures
the cropping calendar, not urbanisation. Requiring co-located built-up gain
isolates genuine, permanent green loss.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..aoi import AnalysisFrame


@dataclass
class GreenChange:
    year_from: int
    year_to: int
    ndvi_from: np.ndarray
    ndvi_to: np.ndarray
    delta: np.ndarray
    green_from: np.ndarray      # bool: vegetated at baseline
    green_to: np.ndarray        # bool: vegetated at end
    lost: np.ndarray            # bool: green -> non-green
    gained: np.ndarray          # bool: non-green -> green

    def lost_km2(self, frame: AnalysisFrame) -> float:
        return float(self.lost.sum()) * (frame.res**2) / 1e6

    def gained_km2(self, frame: AnalysisFrame) -> float:
        return float(self.gained.sum()) * (frame.res**2) / 1e6

    def net_km2(self, frame: AnalysisFrame) -> float:
        return self.gained_km2(frame) - self.lost_km2(frame)


def change(
    ndvi_from: np.ndarray,
    ndvi_to: np.ndarray,
    *,
    year_from: int,
    year_to: int,
    green_threshold: float = 0.30,
    min_delta: float = -0.10,
) -> GreenChange:
    """Classify green cover gain/loss between two NDVI composites."""
    a = ndvi_from.astype("float32")
    b = ndvi_to.astype("float32")
    d = b - a

    green_a = a >= green_threshold
    green_b = b >= green_threshold
    lost = green_a & (~green_b) & (d <= min_delta)
    gained = (~green_a) & green_b & (d >= abs(min_delta))

    return GreenChange(
        year_from=year_from, year_to=year_to,
        ndvi_from=a, ndvi_to=b, delta=d,
        green_from=green_a, green_to=green_b,
        lost=lost, gained=gained,
    )


def loss_to_builtup(green: GreenChange, new_builtup: np.ndarray) -> np.ndarray:
    """Green loss co-located with built-up gain — permanent conversion.

    This is the defensible "green cover lost to urbanisation" number.
    Unqualified NDVI decline is not.
    """
    return green.lost & np.nan_to_num(new_builtup, nan=0.0).astype(bool)


def conversion_summary(
    green: GreenChange, new_builtup: np.ndarray, frame: AnalysisFrame
) -> dict[str, float]:
    """Headline green-cover figures with the urbanisation attribution split out."""
    cell_km2 = (frame.res**2) / 1e6
    converted = loss_to_builtup(green, new_builtup)
    lost_km2 = green.lost_km2(frame)
    conv_km2 = float(converted.sum()) * cell_km2

    return {
        "green_lost_km2": round(lost_km2, 3),
        "green_gained_km2": round(green.gained_km2(frame), 3),
        "green_net_km2": round(green.net_km2(frame), 3),
        "lost_to_builtup_km2": round(conv_km2, 3),
        "lost_to_builtup_share_pct": round(100.0 * conv_km2 / lost_km2, 1) if lost_km2 > 0 else 0.0,
        "green_cover_pct_from": round(100.0 * float(green.green_from.mean()), 1),
        "green_cover_pct_to": round(100.0 * float(green.green_to.mean()), 1),
    }


def green_deficit(
    ndvi: np.ndarray, builtup_frac: np.ndarray, *, green_threshold: float = 0.30,
) -> np.ndarray:
    """Per-cell green deficit in [0, 1]: how under-vegetated a built cell is.

    Weighted by how built-up the cell is, so the output ranks *inhabited*
    places needing greening rather than flagging bare rural land the city
    has no reason to plant.
    """
    veg = np.clip(np.nan_to_num(ndvi, nan=0.0) / green_threshold, 0.0, 1.0)
    return (np.clip(builtup_frac, 0, 1) * (1.0 - veg)).astype("float32")
