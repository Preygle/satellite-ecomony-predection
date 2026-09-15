from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.config import LOCAL_CONFIG, REPO_ROOT, load_config  # noqa: E402

# What goes in a bundle. "target" is the path inside the bundle, which mirrors
# the repository layout so `import` and `link` both work without questions.
#
# The GHSL .tif files are left out of the essential bundle because the code
# extracts them from the .zip archives next to them, and the SHRUG all-India
# polygon archive is left out because the only thing it is needed for — the
# Varanasi-region subset — is already in data/raw/india/shrug/cache.
RULES = [
    # (label, source key, sub-path, target path, include globs, exclude names, essential?)
    ("GHSL built-up and population", "data_raw", "ghsl", "data/raw/ghsl",
     ["*.zip"], [], True),
    ("GHSL extracted rasters", "data_raw", "ghsl", "data/raw/ghsl",
     ["*.tif"], [], False),
    ("Earth Engine exports", "data_raw", "gee", "data/raw/gee", ["*"], [], True),
    ("OpenStreetMap extracts", "data_raw", "osm", "data/raw/osm", ["*"], [], True),
    ("Indian statistical data", "data_raw", "india", "data/raw/india",
     ["*"], ["shrug-shrid-poly-gpkg.zip"], True),
    ("SHRUG all-India polygons", "data_raw", "india", "data/raw/india",
     ["shrug-shrid-poly-gpkg.zip"], [], False),
    ("WorldPop bulk raster", "data_raw", "worldpop", "data/raw/worldpop", ["*"], [], False),
    ("Processed rasters", "data_processed", "", "data/processed", ["*"], [], True),
    ("Pipeline outputs", "outputs", "", "outputs", ["*"], [], True),
]

KEYS = ("data_raw", "data_interim", "data_processed", "outputs")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit in ("B", "KB") else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def walk(root: Path, includes: list[str], excludes: list[str]):
    """Files under `root` matching any include glob and no exclude name."""
    if not root.exists():
        return
    for p in root.rglob("*"):
        if not p.is_file() or p.name in excludes:
            continue
        if any(fnmatch.fnmatch(p.name, g) for g in includes):
            yield p


def selected(cfg, essential_only: bool):
    """Yield (label, source root, target relative path, files, bytes)."""
    for label, key, sub, target, inc, exc, essential in RULES:
        if essential_only and not essential:
            continue
        root = cfg.path_for(key) / sub if sub else cfg.path_for(key)
        files = list(walk(root, inc, exc))
        if files:
            yield label, root, target, files, sum(f.stat().st_size for f in files)


def cmd_check(cfg) -> int:
    print("Where this project reads and writes its data\n")
    local = "yes" if LOCAL_CONFIG.exists() else "no"
    print(f"  config/local.yaml present : {local}")
    for key in KEYS:
        env = os.environ.get(f"URBANINTEL_{key.upper()}")
        if env:
            print(f"  environment override      : URBANINTEL_{key.upper()} = {env}")
    print()
    for key in KEYS:
        p = cfg.path_for(key)
        files = [f for f in p.rglob("*") if f.is_file()] if p.exists() else []
        size = sum(f.stat().st_size for f in files)
        inside = "inside the repo" if REPO_ROOT in p.parents or p == REPO_ROOT else "outside the repo"
        print(f"  {key:15s} {str(p):58s} {len(files):6,} files  {human(size):>10s}  ({inside})")

    print("\nWhat a bundle would contain\n")
    total_e = total_f = 0
    for label, _root, target, files, size in selected(cfg, essential_only=False):
        essential = any(r[0] == label and r[6] for r in RULES)
        total_f += size
        total_e += size if essential else 0
        mark = "essential" if essential else "full only"
        print(f"  {label:32s} {target:22s} {len(files):5,} files  {human(size):>10s}  {mark}")
    print(f"\n  essential bundle: {human(total_e)}      full bundle: {human(total_f)}")

    missing = []
    for name, path in (("pipeline summary", cfg.outputs_dir / f"{cfg.city_slug}_summary.json"),
                       ("processed rasters", cfg.processed_dir / "rasters"),
                       ("Indian data manifest", cfg.raw_dir / "india" / "MANIFEST.json")):
        if not path.exists():
            missing.append(f"{name} ({path})")
    print("\n  " + ("everything the pipeline needs is present"
                    if not missing else "missing: " + "; ".join(missing)))
    return 0


def copy_files(files, root: Path, dest_root: Path) -> int:
    copied = 0
    for f in files:
        rel = f.relative_to(root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size == f.stat().st_size:
            continue
        shutil.copy2(f, dest)
        copied += 1
    return copied


def cmd_export(cfg, target: Path, full: bool) -> int:
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"created": date.today().isoformat(), "bundle": "full" if full else "essential",
                "city": cfg.city, "parts": []}
    total = 0
    for label, root, rel, files, size in selected(cfg, essential_only=not full):
        dest = target / rel
        print(f"  {label:32s} -> {rel:22s} {len(files):5,} files  {human(size):>10s}")
        copy_files(files, root, dest)
        manifest["parts"].append({"label": label, "path": rel, "files": len(files),
                                  "bytes": size})
        total += size
    (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "README.txt").write_text(README_TXT, encoding="utf-8")
    print(f"\nwrote {human(total)} to {target}")
    print("Next, on the other machine, from inside the repository:")
    print(f"    python scripts/external_data.py import {target}      (copy it in), or")
    print(f"    python scripts/external_data.py link {target}        (use it where it is)")
    return 0


def cmd_import(cfg, source: Path) -> int:
    if not source.exists():
        print(f"not found: {source}")
        return 2
    total = 0
    for label, _root, rel, _files, _size in selected(cfg, essential_only=False):
        src = source / rel
        if not src.exists():
            continue
        key = next(r[1] for r in RULES if r[0] == label)
        sub = next(r[2] for r in RULES if r[0] == label)
        dest = cfg.path_for(key) / sub if sub else cfg.path_for(key)
        files = [f for f in src.rglob("*") if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        print(f"  {rel:22s} -> {dest}  {len(files):5,} files  {human(size):>10s}")
        copy_files(files, src, dest)
        total += size
    print(f"\ncopied {human(total)} into the project's own folders")
    print("Check it with:  python scripts/external_data.py check")
    return 0


def cmd_link(target: Path) -> int:
    if not target.exists():
        print(f"not found: {target}")
        return 2
    base = target.resolve()
    try:                                    # keep it relative when we can
        rel = Path(os.path.relpath(base, REPO_ROOT)).as_posix()
    except ValueError:                      # different drive on Windows
        rel = base.as_posix()
    lines = [
        "# Machine-specific paths. NOT tracked by git, so this file can never",
        "# conflict when you merge someone else's branch. Written by",
        "# scripts/external_data.py link; remove it with `unlink`.",
        "paths:",
        f"  data_raw: {rel}/data/raw",
        f"  data_interim: {rel}/data/interim",
        f"  data_processed: {rel}/data/processed",
        f"  outputs: {rel}/outputs",
        "",
    ]
    LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {LOCAL_CONFIG}")
    print(f"  the project now reads its data from {rel}/")
    print("Check it with:  python scripts/external_data.py check")
    return 0


def cmd_unlink() -> int:
    if LOCAL_CONFIG.exists():
        LOCAL_CONFIG.unlink()
        print(f"removed {LOCAL_CONFIG}; the project is back to the paths in config/varanasi.yaml")
    else:
        print("no config/local.yaml; the project already uses the paths in config/varanasi.yaml")
    return 0


README_TXT = """Urban growth project - data bundle
==================================

These folders are the large files that are NOT in the git repository: the
satellite downloads, the Indian census and economic-census archives, and the
pipeline's own outputs. The code and documents come from git; this bundle is
everything else.

    data/raw/ghsl     GHSL built-up surface and population (zip archives)
    data/raw/gee      Earth Engine exports: night lights, NDVI, temperature,
                      Dynamic World, Open Buildings, WorldCover, SRTM, MODIS
    data/raw/osm      OpenStreetMap points of interest and roads
    data/raw/india    SHRUG census and economic census, UP district GDP
    data/processed    the 100 m analysis rasters
    outputs           grid, summary and validation results

To use it, clone the repository, then from inside it run ONE of:

    python scripts/external_data.py import  <path to this folder>
        copies everything into the project's own data/ and outputs/ folders.

    python scripts/external_data.py link  <path to this folder>
        leaves the files where they are and writes config/local.yaml, which is
        not tracked by git, so it cannot conflict when you merge.

Then check it with:

    python scripts/external_data.py check
    run_review3.bat

Anything missing can be re-downloaded with scripts/prefetch.py (open data),
scripts/export_review3_layers.py (Earth Engine, needs an account) and
scripts/fetch_indian_data.py (SHRUG and the UP government spreadsheets).
"""


def usage() -> None:
    print("Move the large data folders between machines, and point the project at them.")
    print()
    print("usage: python scripts/external_data.py check")
    print("       python scripts/external_data.py export <target folder> [--full]")
    print("       python scripts/external_data.py import <bundle folder>")
    print("       python scripts/external_data.py link <bundle folder>")
    print("       python scripts/external_data.py unlink")
    print()
    print("'link' writes config/local.yaml (not tracked by git), so each machine can keep")
    print("its data wherever it likes without a merge conflict. See docs/DATA_TRANSFER.md.")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        usage()
        return 0
    cmd, rest = args[0], args[1:]
    cfg = load_config()
    if cmd == "check":
        return cmd_check(cfg)
    if cmd == "export":
        if not rest:
            print("usage: external_data.py export <target folder> [--full]")
            return 2
        return cmd_export(cfg, Path(rest[0]).expanduser(), full="--full" in rest)
    if cmd == "import":
        if not rest:
            print("usage: external_data.py import <bundle folder>")
            return 2
        return cmd_import(cfg, Path(rest[0]).expanduser())
    if cmd == "link":
        if not rest:
            print("usage: external_data.py link <bundle folder>")
            return 2
        return cmd_link(Path(rest[0]).expanduser())
    if cmd == "unlink":
        return cmd_unlink()
    print(f"unknown command: {cmd}")
    usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
