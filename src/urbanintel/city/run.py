from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
import warnings
from pathlib import Path

import numpy as np

from ..aoi import AOI
from ..config import load_config
from . import catalog, charts, economy, fetch, llm, model, news, opportunity, prepare
from .progress import Status, StatusLogHandler

warnings.filterwarnings("ignore")
log = logging.getLogger("urbanintel.city")
NEWS_ARTICLES_EST = 140
DATASETS = [
    ("JRC/GHSL/P2023A/GHS_BUILT_S", "GHS-BUILT-S R2023A, European Commission JRC",
     "built-up surface per 100 m cell, 2000-2020; the labels the model learns from"),
    ("JRC/GHSL/P2023A/GHS_POP", "GHS-POP R2023A, European Commission JRC",
     "residential population per 100 m cell"),
    ("LANDSAT/LT05/C02/T1_L2", "Landsat 5 TM Collection 2 Level 2, USGS", "surface reflectance to 2011"),
    ("LANDSAT/LE07/C02/T1_L2", "Landsat 7 ETM+ Collection 2 Level 2, USGS", "surface reflectance 1999-2011"),
    ("LANDSAT/LC08/C02/T1_L2", "Landsat 8 OLI Collection 2 Level 2, USGS", "surface reflectance from 2013"),
    ("NOAA/VIIRS/DNB/ANNUAL_V21", "VIIRS annual night lights V2.1, NOAA / Colorado School of Mines",
     "night-time radiance 2013-2021, a proxy for economic activity"),
    ("NOAA/VIIRS/DNB/ANNUAL_V22", "VIIRS annual night lights V2.2, NOAA / Colorado School of Mines",
     "night-time radiance from 2022"),
    ("GOOGLE/DYNAMICWORLD/V1", "Dynamic World V1, Google and World Resources Institute",
     "water probability, for distance to water"),
    ("USGS/SRTMGL1_003", "SRTM 1 arc-second DEM, NASA / USGS", "terrain slope"),
    ("OpenStreetMap (Overpass API)", "OpenStreetMap contributors",
     "roads and points of interest, present-day snapshot"),
    ("Google News RSS, GDELT DOC 2.0", "news publishers via Google News and the GDELT Project",
     "headlines and snippets for the development-news layer"),
]


def parse(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fetch, prepare, train and score one city end to end.")
    ap.add_argument("--city", required=True)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--llm", choices=["auto", "claude", "ollama"], default="auto")
    ap.add_argument("--estimate-only", action="store_true")
    return ap.parse_args(argv)


def human(n: float) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} KB"


def reverse_names(rows: list[dict], aoi: AOI, cache_path: Path) -> None:
    import requests

    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for r in rows:
        lon, lat = aoi.to_lonlat(r["x"], r["y"])
        r["lon"], r["lat"] = round(lon, 5), round(lat, 5)
        key = f"{lat:.4f},{lon:.4f}"
        if key not in cache:
            try:
                resp = requests.get(f"{catalog.NOMINATIM}/reverse", timeout=30,
                                    headers={"User-Agent": catalog.USER_AGENT},
                                    params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 15})
                a = resp.json().get("address", {}) if resp.ok else {}
                cache[key] = (a.get("suburb") or a.get("neighbourhood") or a.get("quarter")
                              or a.get("village") or a.get("town") or a.get("city_district") or "")
            except Exception:  # noqa: BLE001
                cache[key] = ""
            time.sleep(1.1)
        r["locality"] = cache[key]
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    args = parse(argv)
    city = catalog.resolve(args.city)
    cdir = catalog.city_dir(city)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    status = Status(cdir / "status.json", city=city.name, run_id=run_id)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", force=True,
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(cdir / "run.log", encoding="utf-8")])
    logging.getLogger().addHandler(StatusLogHandler(status))
    for noisy in ("urllib3", "googleapiclient", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    meter = fetch.Meter(status.add_bytes)
    t0 = time.time()
    results: dict = {"run_id": run_id, "city": city.as_dict()}
    try:
        status.begin("resolve", module="urbanintel.city.catalog.resolve",
                     detail=f"{city.display} (OpenStreetMap {city.osm})")
        cfg_path = catalog.write_config(city)
        cfg = load_config(cfg_path)
        cfg.check_epochs()
        aoi = AOI(cfg)
        fine, coarse = aoi.frame_pair(100, cfg.cell_size_m)
        w_km, h_km = city.aoi_km()
        log.info("%s: AOI %.0f x %.0f km (%s), %s cells of 100 m, %s", city.name, w_km, h_km,
                 f"boundary + {city.buffer_km():.1f} km", f"{fine.width * fine.height:,}",
                 f"EPSG:{city.utm_epsg}")
        status.end("resolve", note=f"{w_km:.0f} x {h_km:.0f} km, {fine.width * fine.height:,} cells")

        status.begin("search", module="urbanintel.city.fetch.availability",
                     detail="checking Earth Engine archives and OpenStreetMap counts")
        avail = fetch.availability(cfg, aoi, meter, on_step=lambda m: (
            status.update("search", detail=m), log.info("search: %s", m)))
        if avail["viirs_years"]:
            cfg_path = catalog.write_config(city, nightlights_end=avail["viirs_years"][-1])
            cfg = load_config(cfg_path)
        items = fetch.plan(cfg, aoi, fine, avail)
        est = fetch.estimate(items, news_articles=0 if args.no_news else NEWS_ARTICLES_EST)
        plan = {"availability": {k: v for k, v in avail.items() if k != "osm_sample"},
                "estimate": est, "aoi_km": [round(w_km, 1), round(h_km, 1)],
                "cells": fine.width * fine.height,
                "items": [{"key": i.key, "label": i.label, "dataset": i.dataset, "group": i.group,
                           "est_bytes": i.est_bytes, "essential": i.essential, "cached": i.cached()}
                          for i in items]}
        (cdir / "plan.json").write_text(json.dumps(plan, indent=1, default=str), encoding="utf-8")
        status.set(estimated_bytes=est["total_bytes"], plan_rows=est["rows"],
                   downloads_total=len(items))
        status.end("search", note=f"{len(items)} downloads, about {human(est['total_bytes'])} "
                                  f"({est['cached']} already cached)")
        if args.estimate_only:
            for key in ("download", "process", "train", "evaluate", "forecast", "economy",
                        "news_fetch", "news_process", "opportunity", "charts"):
                status.skip(key, "estimate only")
            status.finish("estimated")
            print(json.dumps(est, indent=1))
            return 0

        status.begin("download", total=len(items), module="urbanintel.city.fetch.execute",
                     detail="Earth Engine and OpenStreetMap downloads")

        def done(it, err):
            status.update("download", advance=1, detail=f"{'FAILED ' if err else ''}{it.label}",
                          module=f"{it.dataset}")
            log.info("download %s: %s", "failed" if err else "ok", it.label)

        failed = fetch.execute(items, meter, on_done=done)
        bad = [i.label for i in items if i.key in failed and i.essential]
        if bad:
            raise RuntimeError(f"essential downloads failed: {', '.join(bad)}")
        status.end("download", note=f"{human(meter.total)} downloaded, {len(failed)} optional failed")
        results["downloads"] = {"bytes": meter.total, "failed": failed, "items": [
            {"key": i.key, "label": i.label, "dataset": i.dataset, "group": i.group,
             "estimated_bytes": i.est_bytes, "actual_bytes": i.actual_bytes, "cached": i.actual_bytes is None}
            for i in items]}

        status.begin("process", module="urbanintel.city.prepare",
                     detail="putting every layer onto the 100 m analysis grid")
        stats = prepare.prepare(cfg, aoi, fine, on_step=lambda mod, m: status.update(
            "process", module=mod, detail=m))
        results["stats"] = stats
        status.end("process", note=f"{stats['area_km2']:,} km2, urban 2020 "
                                   f"{stats['urban_km2'].get(2020, 0):,} km2")

        design = model.check_design(cfg)
        seeds = list(range(args.seeds))
        status.begin("train", total=len(seeds), module="scripts/train_image_v2.py",
                     detail=f"train {design['train']}, stop on {design['stop']}, test {design['test']}")

        def on_line(i, seed, line, info):
            if info:
                status.update("train", done=i, detail=(
                    f"seed {i + 1}/{len(seeds)} - epoch {info['epoch']} - stopping AP "
                    f"{info['stop_ap']:.3f} (best {info['best_ap']:.3f} at epoch {info['best_epoch']}; "
                    f"stops by epoch {info['stops_by']} unless it improves)"),
                    module=f"scripts/train_image_v2.py --seed {seed}")
            elif "INFO" in line:
                log.info("seed %d: %s", seed, line.split("INFO", 1)[1].strip()[:150])

        model.train_seeds(cfg_path, seeds, on_line=on_line)
        status.end("train", note=f"{len(seeds)} seeds trained")

        status.begin("evaluate", module="urbanintel.city.model.evaluate",
                     detail="ensemble scored once on 2015-2020")
        ev = model.evaluate(cfg, fine, seeds)
        ev["design"] = design
        results["evaluation"] = ev
        status.end("evaluate", note=f"Figure of Merit {ev['ensemble']['figure_of_merit']:.4f}, "
                                    f"AUC {ev['ensemble']['auc']:.3f}")

        status.begin("forecast", module="urbanintel.city.model.forecast",
                     detail="2020 inputs, five seeds, constrained allocation")
        fc = model.forecast(cfg, fine, seeds)
        results["forecast"] = fc
        status.end("forecast", note=f"{fc['new_urban_km2']} km2 of new urban land by 2025")

        status.begin("economy", module="urbanintel.city.economy.analyse",
                     detail="night-light trend and four-year growth model on the 500 m grid")
        econ = economy.analyse(cfg, fine, coarse)
        results["economy"] = econ
        gb = econ.get("forecast", {}).get("models", {}).get("gradient_boosting", {})
        status.end("economy", note=(f"growth model Spearman {gb.get('spearman_rho')} on "
                                    f"{econ.get('forecast', {}).get('test', '')}") if gb else "trend only")

        news_zone = None
        # A layer from an earlier run must not appear as this run's news
        for stale in ("news_index.tif", "opportunity_score_news.tif"):
            (cfg.processed_dir / "rasters" / stale).unlink(missing_ok=True)
        results.pop("news", None)
        if args.no_news:
            status.skip("news_fetch", "turned off for this run")
            status.skip("news_process", "turned off for this run")
        else:
            try:
                extractor = llm.make(args.llm)
            except llm.LLMUnavailable as exc:
                extractor = None
                status.skip("news_fetch", f"no LLM available: {exc}")
                status.skip("news_process", "no LLM available")
            if extractor is not None:
                status.begin("news_fetch", module="urbanintel.city.news.collect",
                             detail="Google News RSS and GDELT, balanced topic queries")
                got = news.fetch_stage(city.name, lambda u: meter.fetch(u, timeout=60, attempts=2),
                                       on_step=lambda i, n, m: status.update("news_fetch", done=i,
                                                                             total=n, detail=m))
                status.end("news_fetch", note=f"{got['unique']} unique articles from {got['retrieved']}")
                status.begin("news_process", total=got["unique"],
                             module=f"urbanintel.city.news ({extractor.name}: {getattr(extractor, 'model', '')})",
                             detail="structured extraction, fixed scoring table, neutrality audit")
                nres, news_zone = news.process_stage(
                    city.name, aoi, coarse, extractor, got, cache_path=cdir / "geocode_cache.json",
                    on_step=lambda i, n, m: status.update("news_process", done=i, total=n, detail=m))
                prepare.write(cfg.processed_dir / "rasters" / "news_index.tif", news_zone, coarse)
                nres["llm_payload_bytes"] = getattr(extractor, "payload_bytes", 0)
                results["news"] = nres
                status.end("news_process", note=f"{len(nres['events'])} events "
                                                f"({nres['positive_events']} positive, "
                                                f"{nres['negative_events']} negative)")

        status.begin("opportunity", module="urbanintel.city.opportunity",
                     detail="five components, 2,000 random weightings")
        opp = opportunity.score(cfg, fine, coarse, econ)
        opp = opportunity.apply_news(cfg, coarse, opp, news_zone)
        reverse_names(opp["top"][:15], aoi, cdir / "reverse_cache.json")
        if opp.get("top_with_news"):
            reverse_names(opp["top_with_news"][:15], aoi, cdir / "reverse_cache.json")
        results["opportunity"] = opp
        status.end("opportunity", note=f"{opp['candidates']:,} candidate zones")

        status.begin("charts", module="urbanintel.city.charts.build_overlays",
                     detail="map layers reprojected to latitude/longitude")
        thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
        ov = charts.build_overlays(cfg.processed_dir / "rasters", cdir / "results", fine, coarse, thr,
                                   econ["years"][-1] if econ.get("years") else None)
        results.update(overlays=list(ov), datasets=[{"id": a, "name": b, "use": c} for a, b, c in DATASETS],
                       aoi={"bbox": list(city.aoi_bbox()), "km": [round(w_km, 1), round(h_km, 1)],
                            "epsg": city.utm_epsg, "cells": fine.width * fine.height},
                       runtime_s=round(time.time() - t0, 1),
                       bytes_downloaded=meter.total)
        (cdir / "results").mkdir(exist_ok=True)
        (cdir / "results" / "results.json").write_text(
            json.dumps(results, indent=1, default=_json_default), encoding="utf-8")
        status.end("charts", note=f"{len(ov)} map layers")
        status.finish("done")
        log.info("finished %s in %.1f min, %s downloaded", city.name, (time.time() - t0) / 60,
                 human(meter.total))
        return 0
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        log.error("run failed: %s", exc)
        (cdir / "error.txt").write_text(tb, encoding="utf-8")
        status.finish("failed", error=f"{type(exc).__name__}: {str(exc)[:400]}")
        return 1


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())
