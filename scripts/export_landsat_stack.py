from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee, ghsl  # noqa: E402

log = logging.getLogger("landsat_stack")


def resume_download(url: str, dest: Path, *, attempts: int = 8,
                    timeout: int = 180) -> Path:
    """Fetch a large file, continuing where an interrupted attempt stopped.

    The JRC open-data server delivers these 40 MB tiles at a few hundred
    kilobytes a second and drops the connection often. The shared
    downloader discards its partial file and starts again, which never
    finishes; asking for the remaining byte range instead does.
    """
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "urbanintel-varanasi/0.1 (academic research)"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with requests.get(url, headers=headers, stream=True,
                              timeout=timeout) as r:
                if r.status_code not in (200, 206):
                    r.raise_for_status()
                if r.status_code == 200 and have:
                    have, mode = 0, "wb"      # the server ignored the range
                else:
                    mode = "ab" if have else "wb"
                total = int(r.headers.get("Content-Length", 0)) + have
                with part.open(mode) as fh:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            fh.write(chunk)
                            have += len(chunk)
            if total and have < total:
                raise OSError(f"short read {have}/{total}")
            part.replace(dest)
            log.info("  %s: %.1f MB", dest.name, dest.stat().st_size / 1e6)
            return dest
        except Exception as exc:                          # noqa: BLE001
            log.warning("  %s: attempt %d/%d stopped at %.1f MB (%s)", dest.name,
                        attempt, attempts, have / 1e6, type(exc).__name__)
    raise OSError(f"could not download {url} in {attempts} attempts")

# Roy et al. (2016), Table 2, ordinary-least-squares coefficients that put
# Landsat TM and ETM+ surface reflectance onto the OLI scale, in the band
# order blue, green, red, near infrared, shortwave infrared 1 and 2.
# Without this the model would read the sensor change of 2013 as a change on
# the ground, exactly in the middle of the record it is trained on.
ROY_SLOPE = [0.8474, 0.8483, 0.9047, 0.8462, 0.8937, 0.9071]
ROY_INTERCEPT = [0.0003, 0.0088, 0.0061, 0.0412, 0.0254, 0.0172]

TM_BANDS = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]
OLI_BANDS = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
OUT_BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]


def usage() -> str:
    return ("Export six-band dry-season Landsat composites at 30 m, one per epoch, "
            "harmonised across sensors.")


def collections(cfg, year: int) -> list[tuple[str, list[str], bool]]:
    """(asset, band names, needs harmonising) for the sensors flying in `year`."""
    a = cfg.get("sources.gee.assets")
    if year <= 2011:
        out = [(a.get("landsat5", "LANDSAT/LT05/C02/T1_L2"), TM_BANDS, True)]
        if year >= 1999:
            # Landsat 7 fills gaps, but its scan-line corrector failed in May
            # 2003, leaving wedge-shaped holes. A median over a whole season
            # fills them; a single scene would not.
            out.append((a.get("landsat7", "LANDSAT/LE07/C02/T1_L2"), TM_BANDS, True))
        return out
    out = [(a.get("landsat8", "LANDSAT/LC08/C02/T1_L2"), OLI_BANDS, False)]
    if year >= 2022:
        out.append((a.get("landsat9", "LANDSAT/LC09/C02/T1_L2"), OLI_BANDS, False))
    return out


def composite(cfg, aoi: AOI, year: int, *, months: tuple[int, int] = (10, 3)):
    """Dry-season median surface reflectance for one epoch, six bands, on the OLI scale.

    October to March is the same window the project already uses for
    Sentinel-2: the monsoon is over, skies are clearest, and the ground is not
    hidden by flood water or peak vegetation. The window straddles the new
    year, so it starts in `year - 1`.
    """
    ee = gee.ee_init(cfg.get("sources.gee.project", None))
    geom = gee.aoi_geometry(aoi)
    start, end = f"{year - 1}-{months[0]:02d}-01", f"{year}-{months[1]:02d}-31"

    parts = []
    for asset, bands, harmonise in collections(cfg, year):
        col = (ee.ImageCollection(asset).filterDate(start, end).filterBounds(geom))

        def prep(img, bands=bands, harmonise=harmonise):
            sr = img.select(bands).multiply(0.0000275).add(-0.2)
            if harmonise:
                sr = sr.multiply(ee.Image.constant(ROY_SLOPE)) \
                       .add(ee.Image.constant(ROY_INTERCEPT))
            return (sr.rename(OUT_BANDS)
                    .updateMask(gee.landsat_clear_mask(img))
                    .copyProperties(img, ["system:time_start"]))

        parts.append(col.map(prep))

    merged = parts[0]
    for p in parts[1:]:
        merged = merged.merge(p)
    depth = gee.require_composite_depth(
        cfg, merged, f"Landsat {year}",
        floor=int(cfg.get("sources.gee.min_composite_dates_landsat", 4)))
    log.info("  %d: %d clear acquisition dates in %s to %s", year, depth, start, end)
    # Earth Engine refuses a direct download over 50 MB, and six float32
    # bands at 30 m over this area come to about 72 MB. Surface reflectance
    # is published as scaled integers anyway, and the pretrained model's
    # own band statistics are quoted in those units, so the composite is
    # written the same way and divided back on read.
    return (merged.median().rename(OUT_BANDS).multiply(10_000).toInt16()
            .clip(geom))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2000, 2005, 2010, 2015, 2020, 2025],
                    help="epochs to export; each is the start of a five-year transition")
    ap.add_argument("--scale", type=int, default=30)
    ap.add_argument("--ghsl", action="store_true",
                    help="also download the GHSL built-up and population epochs "
                         "needed to label the earlier transitions")
    ap.add_argument("--force", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    dest_dir = cfg.raw_dir / "gee"
    dest_dir.mkdir(parents=True, exist_ok=True)

    if args.ghsl:
        # GHS-BUILT-S and GHS-POP publish observed epochs every five years back
        # to 1975. Every extra epoch is another labelled transition, which is
        # the cheapest way to enlarge a training set of about 1,400 positives.
        import rasterio

        fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
        rdir = cfg.processed_dir / "rasters"
        rdir.mkdir(parents=True, exist_ok=True)
        for epoch in [y for y in args.years if y <= 2020]:
            for kind, loader, stem in (
                ("built_surface", ghsl.load_builtup, "builtup_m2"),
                ("population", ghsl.load_population, "population"),
            ):
                dest = rdir / f"{stem}_{epoch}.tif"
                if dest.exists() and not args.force:
                    log.info("GHSL %s %d: already on the frame (%s)", kind, epoch, dest.name)
                    continue
                try:
                    for tile in ghsl.tiles_for_bbox(cfg.bbox):
                        prod = cfg.get(f"sources.ghsl.products.{kind}")
                        url = ghsl.build_url(cfg, prod, epoch, tile)
                        resume_download(url, cfg.raw_dir / "ghsl" / url.rsplit("/", 1)[-1])
                    arr = loader(cfg, aoi, epoch, fine)
                    with rasterio.open(dest, "w", **fine.profile("float32")) as ds:
                        ds.write(arr.astype("float32"), 1)
                    log.info("GHSL %s %d -> %s", kind, epoch, dest.name)
                except Exception as exc:                      # noqa: BLE001
                    log.warning("GHSL %s %d unavailable: %s", kind, epoch, exc)

    failed = []
    for year in args.years:
        dest = dest_dir / f"landsat_{year}.tif"
        if dest.exists() and not args.force:
            log.info("  %d: already exported (%s)", year, dest.name)
            continue
        try:
            img = composite(cfg, aoi, year)
            gee.download_image(img, aoi, dest, scale=args.scale, force=args.force)
            log.info("  %d -> %s", year, dest)
        except Exception as exc:                              # noqa: BLE001
            failed.append((year, str(exc).splitlines()[0]))
            log.error("  %d failed: %s", year, exc)

    print("\n" + "=" * 70)
    print(f"LANDSAT STACK — {args.scale} m, six bands on the OLI scale")
    print("=" * 70)
    for year in args.years:
        p = dest_dir / f"landsat_{year}.tif"
        size = f"{p.stat().st_size / 1e6:.1f} MB" if p.exists() else "missing"
        print(f"  {year}   {size}")
    if failed:
        print("\n  failed: " + ", ".join(f"{y} ({m})" for y, m in failed))
        return 1
    print("\n  next: python scripts/train_image_model.py --source landsat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
