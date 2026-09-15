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

# GHS-BUILT-S / GHS-POP R2023A: epochs 1975-2020 are derived from satellite
# observation; 2025 and 2030 are the GHSL model's own projections.
GHSL_LAST_OBSERVED_EPOCH = 2020


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
    def observational_epochs(self) -> list[int]:
        """GHSL epochs that are measurements — the only ones analysis may use."""
        return sorted(int(y) for y in self.get("sources.ghsl.epochs"))

    @property
    def projected_epochs(self) -> list[int]:
        """GHSL epochs that are model projections — comparison only."""
        return sorted(int(y) for y in self.get("sources.ghsl.projected_epochs", []))

    def check_epochs(self) -> None:
        """Refuse a configuration that would treat a projection as a measurement.

        Until Review 3 the "current" epoch was 2025, a GHSL projection, and
        every change figure was silently computed against it. This check makes
        that mistake impossible to repeat without an error.
        """
        obs = self.observational_epochs
        late = [y for y in obs if y > GHSL_LAST_OBSERVED_EPOCH]
        if late:
            raise ConfigError(
                f"sources.ghsl.epochs contains {late}, but GHSL R2023A epochs after "
                f"{GHSL_LAST_OBSERVED_EPOCH} are model projections; list them under "
                f"sources.ghsl.projected_epochs instead")
        for key in ("baseline", "mid", "current"):
            y = self.get(f"epochs.{key}", None)
            if y is not None and y not in obs:
                raise ConfigError(
                    f"epochs.{key} = {y} is not one of the observational GHSL epochs {obs}")

    @property
    def cell_size_m(self) -> int:
        return self.get("grid.cell_size_m")

    # ---------------------------------------------------------------- paths
    def path_for(self, key: str) -> Path:
        """Resolve a configured directory, creating it if needed.

        `key` is one of: data_raw, data_interim, data_processed, outputs.
        Relative paths resolve against the repo root; absolute paths are used
        as-is (so `data/` can be a junction onto another drive).

        An environment variable wins over the file: `URBANINTEL_DATA_RAW`,
        `URBANINTEL_DATA_INTERIM`, `URBANINTEL_DATA_PROCESSED`,
        `URBANINTEL_OUTPUTS`. Together with `config/local.yaml` this keeps
        machine-specific locations out of tracked files — see
        scripts/external_data.py.
        """
        rel = os.environ.get(f"URBANINTEL_{key.upper()}") or self.get(f"paths.{key}")
        p = Path(rel).expanduser()
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


# A machine-specific override file, deliberately NOT tracked by git. It is how
# one teammate can keep the large data folders on a D: drive or a copied
# pendrive folder while another keeps them inside the repo, without either of
# them editing a tracked file and colliding on the next merge.
LOCAL_CONFIG = REPO_ROOT / "config" / "local.yaml"


def _deep_merge(base: dict, over: dict) -> dict:
    """Return `base` with `over` merged into it, recursing into nested maps."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load the study-area config.

    Resolution order: explicit `path` -> $URBANINTEL_CONFIG -> config/varanasi.yaml.
    If `config/local.yaml` exists, it is merged on top (see LOCAL_CONFIG), and
    individual paths can still be overridden by environment variables — see
    `Config.path_for`.
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

    if LOCAL_CONFIG.exists():
        with LOCAL_CONFIG.open("r", encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
        if not isinstance(local, dict):
            raise ConfigError(f"local config did not parse to a mapping: {LOCAL_CONFIG}")
        raw = _deep_merge(raw, local)
    return Config(raw=raw, path=p)
