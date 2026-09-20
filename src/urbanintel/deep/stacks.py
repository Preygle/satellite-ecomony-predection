from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..analysis import growth_model as GM
from ..aoi import AnalysisFrame

# Landsat Collection 2 Level 2 surface-reflectance bands, in the order
# Prithvi-EO-2.0 was pretrained on (NASA HLS band order).
LANDSAT_BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]


@dataclass
class TemporalStack:
    """Model input: `(dates, channels, height, width)` on the analysis frame."""

    data: np.ndarray            # (T, C, H, W) float32
    names: list[str]
    years: list[int]
    source: str                 # "drivers" or "landsat"

    @property
    def n_dates(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_channels(self) -> int:
        return int(self.data.shape[1])

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.data.shape[2]), int(self.data.shape[3]))

    def as_dict(self) -> dict:
        return {"source": self.source, "years": self.years, "channels": self.names,
                "n_dates": self.n_dates, "n_channels": self.n_channels}


def driver_maps(
    builtup_frac: np.ndarray,
    frame: AnalysisFrame,
    *,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    urban_threshold: float = 0.20,
) -> tuple[np.ndarray, list[str]]:
    """The tabular model's drivers, kept as maps instead of as a table.

    `growth_model.build_drivers` already computes these layers for the random
    forest, one row per cell. Reshaping its design matrix back onto the frame
    hands the image model *exactly the same information* the forest gets, so
    any difference in skill comes from reading spatial pattern rather than
    from extra inputs. That equivalence is the whole point of the comparison,
    so the two must keep sharing one implementation.
    """
    X, names = GM.build_drivers(
        builtup_frac, frame, distance_km=distance_km, road_density=road_density,
        population=population, slope=slope, urban_threshold=urban_threshold,
    )
    maps = np.stack([X[:, i].reshape(frame.shape) for i in range(X.shape[1])])
    return np.nan_to_num(maps, nan=0.0).astype("float32"), names


def driver_stack(
    builtup: dict[int, np.ndarray],
    frame: AnalysisFrame,
    *,
    years: list[int],
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: dict[int, np.ndarray] | None = None,
    slope: np.ndarray | None = None,
    urban_threshold: float = 0.20,
) -> TemporalStack:
    """Driver maps for one or more dates, oldest first."""
    dates, names = [], None
    for y in years:
        m, names = driver_maps(
            builtup[y], frame, distance_km=distance_km, road_density=road_density,
            population=(population or {}).get(y), slope=slope,
            urban_threshold=urban_threshold,
        )
        dates.append(m)
    return TemporalStack(np.stack(dates), list(names or []), list(years), "drivers")


def landsat_maps(path: Path, frame: AnalysisFrame, *, scale: bool = True) -> np.ndarray:
    """Read a six-band Landsat export onto the analysis frame, as reflectance.

    `scripts/export_landsat_stack.py` writes surface reflectance multiplied
    by 10,000 as signed integers, the same convention the Landsat and
    Harmonized Landsat and Sentinel-2 products use, which also keeps the
    export under Earth Engine's download limit. Dividing it back out here
    means every model sees plain reflectance.
    """
    from ..data import gee

    bands = [gee.to_frame(path, frame, band=i + 1) for i in range(len(LANDSAT_BANDS))]
    arr = np.stack(bands).astype("float32")
    if scale and np.nanmax(arr) > 10.0:
        arr = arr / 10_000.0
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def landsat_stack(paths: dict[int, Path], frame: AnalysisFrame, *,
                  years: list[int]) -> TemporalStack:
    """Landsat surface reflectance for one or more dates, oldest first."""
    missing = [y for y in years if y not in paths or not Path(paths[y]).exists()]
    if missing:
        raise FileNotFoundError(
            f"no Landsat export for {missing}; run scripts/export_landsat_stack.py"
        )
    dates = [landsat_maps(Path(paths[y]), frame) for y in years]
    return TemporalStack(np.stack(dates), list(LANDSAT_BANDS), list(years), "landsat")


@dataclass
class Normaliser:
    """Per-channel mean and standard deviation, fitted on training dates only."""

    mean: np.ndarray            # (C,)
    std: np.ndarray             # (C,)
    names: list[str]

    @classmethod
    def fit(cls, stacks: list[TemporalStack]) -> "Normaliser":
        if not stacks:
            raise ValueError("need at least one stack to fit normalisation")
        names = stacks[0].names
        flat = np.concatenate([s.data.reshape(s.n_dates, s.n_channels, -1) for s in stacks],
                              axis=2).reshape(stacks[0].n_channels, -1) \
            if len({s.n_channels for s in stacks}) == 1 else None
        if flat is None:
            raise ValueError("stacks have different channel counts")
        mean = flat.mean(axis=1)
        std = flat.std(axis=1)
        std[std < 1e-6] = 1.0
        return cls(mean.astype("float32"), std.astype("float32"), list(names))

    def apply(self, stack: TemporalStack) -> TemporalStack:
        m = self.mean[None, :, None, None]
        s = self.std[None, :, None, None]
        return TemporalStack(((stack.data - m) / s).astype("float32"), stack.names,
                             stack.years, stack.source)

    def as_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist(), "names": self.names}

    @classmethod
    def from_dict(cls, d: dict) -> "Normaliser":
        return cls(np.asarray(d["mean"], dtype="float32"),
                   np.asarray(d["std"], dtype="float32"), list(d["names"]))


def transition_labels(builtup_frac_t0: np.ndarray, builtup_frac_t1: np.ndarray, *,
                      urban_threshold: float = 0.20) -> tuple[np.ndarray, np.ndarray]:
    """(label, eligible) for one transition, on the same rule as the tabular model.

    Eligible = not urban at t0; label = urban at t1. Cells already urban at t0
    are excluded everywhere — from the loss, from the metrics and from the
    allocation — because they cannot convert.
    """
    urban0 = builtup_frac_t0 >= urban_threshold
    urban1 = builtup_frac_t1 >= urban_threshold
    eligible = ~urban0
    label = (urban1 & eligible).astype("uint8")
    return label, eligible
