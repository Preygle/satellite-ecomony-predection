"""Download every open-path input for the configured city, in parallel.

The JRC server throttles hard per connection (~30 KB/s observed), so the
eight GHSL tiles are fetched concurrently rather than in sequence. OSM is
fetched on the main thread afterwards because the public Overpass endpoints
rate-limit aggressively and parallel queries get refused.

    python scripts/prefetch.py                # everything
    python scripts/prefetch.py --skip-osm
    python scripts/prefetch.py --workers 4
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import ghsl, osm  # noqa: E402
from urbanintel.data.download import DownloadError  # noqa: E402

log = logging.getLogger("prefetch")


def _one(cfg, product: str, epoch: int) -> tuple[str, int, str]:
    try:
        paths = ghsl.download_product(cfg, product, epoch)
        return (product, epoch, f"ok: {paths[0].name}")
    except DownloadError as exc:
        return (product, epoch, f"FAILED: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-ghsl", action="store_true")
    ap.add_argument("--skip-osm", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config(args.config)
    log.info("city=%s  raw=%s", cfg.city, cfg.raw_dir)

    t0 = time.time()
    failures: list[str] = []

    if not args.skip_ghsl:
        # Observed epochs plus the GHSL projection, which the pipeline loads
        # as a labelled comparison layer.
        epochs = (list(cfg.get("sources.ghsl.epochs"))
                  + list(cfg.get("sources.ghsl.projected_epochs", [])))
        jobs = [
            (cfg.get("sources.ghsl.products.built_surface"), e) for e in epochs
        ] + [
            (cfg.get("sources.ghsl.products.population"), e) for e in epochs
        ]
        log.info("GHSL: %d products x epochs, %d workers", len(jobs), args.workers)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_one, cfg, p, e): (p, e) for p, e in jobs}
            for fut in as_completed(futs):
                product, epoch, status = fut.result()
                log.info("  %-14s %s  %s", product, epoch, status)
                if status.startswith("FAILED"):
                    failures.append(f"{product} {epoch}: {status}")

    if not args.skip_osm:
        log.info("OSM: POIs")
        try:
            pois = osm.fetch_pois(cfg)
            log.info("  total POIs: %d", sum(len(v) for v in pois.values()))
        except Exception as exc:
            log.error("  POI fetch failed: %s", exc)
            failures.append(f"osm pois: {exc}")

        log.info("OSM: roads")
        try:
            roads = osm.fetch_roads(cfg)
            log.info("  road ways: %d", len(roads.get("features", [])))
        except Exception as exc:
            log.error("  road fetch failed: %s", exc)
            failures.append(f"osm roads: {exc}")

    dt = time.time() - t0
    log.info("done in %.1f min", dt / 60)
    if failures:
        log.error("%d failure(s):", len(failures))
        for f in failures:
            log.error("  %s", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
