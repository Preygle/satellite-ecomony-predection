"""Configuration loading and path resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Repo root = two levels up from src/urbanintel/config.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "varanasi.yaml"

# Sentinel distinguishing "no default supplied" from an explicit default of None.
_MISSING = object()


class ConfigError(RuntimeError):
    """Raised when the configuration is missing or malformed."""


@dataclass
class Config:
    """Typed accessor over the YAML study-area configuration.

    Nested values are reachable with dotted keys, e.g.
    ``cfg.get("thresholds.builtup.surface_fraction_urban")``.
    """

    raw: dict[str, Any]
    path: Path
    root: Path = field(default=REPO_ROOT)

    # ---------------------------------------------------------------- lookup
    def get(self, dotted: str, default: Any = _MISSING) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise ConfigError(f"missing config key: {dotted!r} (in {self.path})")
                return default
            node = node[part]
        return node

    def __getitem__(self, dotted: str) -> Any:
        return self.get(dotted)

    # ------------------------------------------------------------ shortcuts
    @property
    def city(self) -> str:
        return self.get("city.name")

    @property
    def city_slug(self) -> str:
        return self.city.lower().replace(" ", "_")

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """AOI as (min_lon, min_lat, max_lon, max_lat) in EPSG:4326."""
        b = self.get("aoi.bbox")
        return (b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])

    @property
    def centre(self) -> tuple[float, float]:
        """City centre as (lon, lat)."""
        c = self.get("city.centre")
        return (c["lon"], c["lat"])

    @property
    def crs_geographic(self) -> str:
        return self.get("crs.geographic")

    @property
    def crs_projected(self) -> str:
        return self.get("crs.projected")

    @property
    def epochs(self) -> list[int]:
        """Analysis epochs in ascending order."""
        return sorted(self.get("epochs").values())

    @property
    def epoch_baseline(self) -> int:
        return self.get("epochs.baseline")

    @property
    def epoch_current(self) -> int:
        return self.get("epochs.current")

    @property
    def cell_size_m(self) -> int:
        return self.get("grid.cell_size_m")

    # ---------------------------------------------------------------- paths
    def path_for(self, key: str) -> Path:
        """Resolve a configured directory, creating it if needed.

        `key` is one of: data_raw, data_interim, data_processed, outputs.
        Relative paths resolve against the repo root; absolute paths are used
        as-is (so `data/` can be a junction onto another drive).
        """
        rel = self.get(f"paths.{key}")
        p = Path(rel)
        if not p.is_absolute():
            p = self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def raw_dir(self) -> Path:
        return self.path_for("data_raw")

    @property
    def interim_dir(self) -> Path:
        return self.path_for("data_interim")

    @property
    def processed_dir(self) -> Path:
        return self.path_for("data_processed")

    @property
    def outputs_dir(self) -> Path:
        return self.path_for("outputs")


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load the study-area config.

    Resolution order: explicit `path` -> $URBANINTEL_CONFIG -> config/varanasi.yaml
    """
    if path is None:
        path = os.environ.get("URBANINTEL_CONFIG", DEFAULT_CONFIG)
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.exists():
        raise ConfigError(f"config not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"config did not parse to a mapping: {p}")
    return Config(raw=raw, path=p)
