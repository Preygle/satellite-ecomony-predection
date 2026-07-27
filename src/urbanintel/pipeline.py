"""End-to-end Phase 1 pipeline.

Runs on the open data path alone (GHSL + OSM). Earth Engine layers —
nightlights, NDVI, land surface temperature — are folded in automatically
when available and skipped with a recorded reason when not, so the pipeline
always produces a complete, self-describing result rather than failing half
way.

    python -m urbanintel.pipeline
    python -m urbanintel.pipeline --no-gee
    python -m urbanintel.pipeline --config config/varanasi.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .aoi import AOI, AnalysisFrame, distance_to_centre
from .analysis import builtup as A_built
from .analysis import ghost as A_ghost
from .analysis import nightlights as A_ntl
from .analysis import thermal as A_thermal
from .analysis import vegetation as A_veg
from .analysis import zonal as A_zonal
from .config import Config, load_config
from .data import ghsl, osm

log = logging.getLogger("pipeline")


@dataclass
class Result:
    """Everything Phase 1 produces, in memory."""

    cfg: Config
    aoi: AOI
    fine: AnalysisFrame
    coarse: AnalysisFrame
    layers: dict[str, np.ndarray] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, arr: np.ndarray) -> None:
        self.layers[name] = arr


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------

def stage_builtup(res: Result) -> None:
    """GHSL built-up: epochs, change, urban form, hotspots."""
    cfg, aoi, fr = res.cfg, res.aoi, res.fine
    epochs = cfg.get("sources.ghsl.epochs")
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    min_delta = cfg.get("thresholds.builtup.new_growth_min_delta_m2")

    log.info("[builtup] loading %d GHSL epochs", len(epochs))
    built: dict[int, np.ndarray] = {}
    pop: dict[int, np.ndarray] = {}
    for y in epochs:
        built[y] = ghsl.load_builtup(cfg, aoi, y, fr)
        pop[y] = ghsl.load_population(cfg, aoi, y, fr)
        res.add(f"builtup_m2_{y}", built[y])
        res.add(f"population_{y}", pop[y])
        log.info("  %d: built %.2f km2, pop %.0f",
                 y, float(np.nansum(built[y])) / 1e6, float(np.nansum(pop[y])))

    y0, y1 = min(epochs), max(epochs)
    chg = A_built.change(
        built[y0], built[y1], fr,
        year_from=y0, year_to=y1,
        urban_threshold=thr, min_delta_m2=min_delta,
    )
    res.add("builtup_frac_baseline", chg.frac_from)
    res.add("builtup_frac_current", chg.frac_to)
    res.add("builtup_delta_m2", chg.delta_m2)
    res.add("builtup_delta_frac", chg.delta_frac)
    res.add("new_urban", chg.new_urban.astype("float32"))

    form = A_built.expansion_form(chg, fr)
    res.add("expansion_form", form.astype("float32"))

    intensity, hotspots = A_built.growth_hotspots(chg, fr)
    res.add("growth_intensity", intensity)
    res.add("growth_hotspot", hotspots.astype("float32"))

    dist = distance_to_centre(aoi, fr)
    res.add("distance_km", dist)

    res.stats["builtup"] = {
        "epochs": epochs,
        "urban_km2": {str(y): round(
            float((A_built.fraction(built[y], fr) >= thr).sum()) * (fr.res**2) / 1e6, 2
        ) for y in epochs},
        "population_total": {str(y): int(np.nansum(pop[y])) for y in epochs},
        "built_surface_km2": {str(y): round(float(np.nansum(built[y])) / 1e6, 2) for y in epochs},
        "new_builtup_km2": round(chg.total_new_km2, 2),
        "lost_builtup_km2": round(chg.total_lost_km2, 2),
        "annual_urban_growth_pct": round(chg.annual_growth_rate(fr), 2),
        "urban_form": A_built.form_summary(form, fr),
        "period": f"{y0}-{y1}",
    }
    res.provenance["builtup"] = {
        "source": "GHSL GHS-BUILT-S R2023A (100 m)",
        "url": cfg.get("sources.ghsl.base_url"),
        "auth": "none",
    }
    res._chg = chg  # kept for later stages


def stage_osm(res: Result) -> None:
    """OSM POIs and roads -> activity and infrastructure surfaces."""
    cfg, aoi, fr = res.cfg, res.aoi, res.fine
    try:
        pois = osm.fetch_pois(cfg)
    except Exception as exc:
        res.skipped["osm_pois"] = str(exc)
        log.warning("[osm] POIs unavailable: %s", exc)
        pois = {}

    if pois:
        density = osm.poi_density(aoi, pois, fr)
        res.add("poi_density", density)
        for group in pois:
            res.add(f"poi_{group}", osm.poi_density(aoi, pois, fr, groups=[group]))
        commercial = osm.poi_density(
            aoi, pois, fr, groups=["retail", "food_hospitality", "finance_office"]
        )
        res.add("poi_commercial", commercial)
        res.stats["osm_pois"] = {g: len(v) for g, v in pois.items()}
        res.stats["osm_pois"]["_total"] = sum(len(v) for v in pois.values())
        res.provenance["osm"] = {"source": "OpenStreetMap via Overpass", "auth": "none"}

    try:
        roads = osm.fetch_roads(cfg)
        rd = osm.road_density(aoi, roads, fr, weighted=True)
        res.add("road_density", rd)
        res.stats["osm_roads"] = {"ways": len(roads.get("features", []))}
    except Exception as exc:
        res.skipped["osm_roads"] = str(exc)
        log.warning("[osm] roads unavailable: %s", exc)


def stage_gee(res: Result, enabled: bool = True) -> None:
    """Earth Engine layers: nightlights, NDVI, LST. Optional."""
    if not enabled:
        res.skipped["gee"] = "disabled by --no-gee"
        return

    cfg, aoi, fr = res.cfg, res.aoi, res.fine
    from .data import gee

    try:
        gee.ee_init(cfg.get("sources.gee.project", None))
    except gee.GEEUnavailable as exc:
        res.skipped["gee"] = str(exc).split("\n")[0]
        log.warning("[gee] unavailable — nightlights/NDVI/LST will be skipped")
        log.warning("      %s", str(exc).splitlines()[0])
        return

    raw = cfg.raw_dir / "gee"
    scale = cfg.get("sources.gee.export_scale_m")

    # --- nightlights: full annual series for the trend -------------------
    y0 = cfg.get("timeseries.nightlights_start")
    y1 = cfg.get("timeseries.nightlights_end")
    ntl_stack: dict[int, np.ndarray] = {}
    for y in range(y0, y1 + 1):
        try:
            img = gee.nightlights_image(cfg, aoi, y)
            p = gee.download_image(img, aoi, raw / f"ntl_{y}.tif", scale=scale)
            ntl_stack[y] = gee.to_frame(p, fr)
        except Exception as exc:
            log.warning("[gee] nightlights %d failed: %s", y, exc)
    if ntl_stack:
        latest = max(ntl_stack)
        res.add("nightlights", ntl_stack[latest])
        res.stats["nightlights"] = {
            "years": sorted(ntl_stack),
            "sum_of_lights": {str(y): round(A_ntl.sum_of_lights(a), 1)
                              for y, a in sorted(ntl_stack.items())},
            "lit_fraction_latest": round(
                A_ntl.lit_fraction(ntl_stack[latest],
                                   cfg.get("thresholds.nightlights.unlit_radiance")), 4),
        }
        if len(ntl_stack) >= 3:
            tr = A_ntl.trend(ntl_stack)
            res.add("nightlights_slope", tr.slope)
            res.add("nightlights_pvalue", tr.p_value)
            res.add("nightlights_growth", tr.significant_growth().astype("float32"))
        res.provenance["nightlights"] = {
            "source": cfg.get("sources.gee.assets.viirs_annual"), "auth": "gee"
        }

    # --- NDVI at the two epochs ------------------------------------------
    for label, year in (("baseline", cfg.get("timeseries.vegetation_start")),
                        ("current", cfg.get("timeseries.vegetation_end") - 1)):
        try:
            img = gee.ndvi_image(cfg, aoi, year)
            p = gee.download_image(img, aoi, raw / f"ndvi_{year}.tif", scale=scale)
            res.add(f"ndvi_{label}", gee.to_frame(p, fr))
            res.provenance["ndvi"] = {
                "source": cfg.get("sources.gee.assets.s2_sr"), "auth": "gee"
            }
        except Exception as exc:
            log.warning("[gee] NDVI %d failed: %s", year, exc)
            res.skipped[f"ndvi_{label}"] = str(exc)

    # --- LST (pre-monsoon) ------------------------------------------------
    lst_year = cfg.get("timeseries.thermal_end") - 1
    try:
        img = gee.lst_image(cfg, aoi, lst_year, season="premonsoon")
        p = gee.download_image(img, aoi, raw / f"lst_{lst_year}.tif", scale=scale)
        res.add("lst", gee.to_frame(p, fr))
        res.stats.setdefault("thermal", {})["year"] = lst_year
        res.provenance["lst"] = {
            "source": "LANDSAT/LC08+LC09 C02 T1_L2 ST_B10", "auth": "gee"
        }
    except Exception as exc:
        log.warning("[gee] LST %d failed: %s", lst_year, exc)
        res.skipped["lst"] = str(exc)


def stage_vegetation(res: Result) -> None:
    """Green cover change, if NDVI is present."""
    if "ndvi_baseline" not in res.layers or "ndvi_current" not in res.layers:
        res.skipped["vegetation"] = "NDVI layers unavailable (needs Earth Engine)"
        return
    cfg, fr = res.cfg, res.fine
    g = A_veg.change(
        res.layers["ndvi_baseline"], res.layers["ndvi_current"],
        year_from=cfg.get("timeseries.vegetation_start"),
        year_to=cfg.get("timeseries.vegetation_end") - 1,
        green_threshold=cfg.get("thresholds.vegetation.ndvi_green_threshold"),
        min_delta=cfg.get("thresholds.vegetation.green_loss_min_delta"),
    )
    res.add("ndvi_delta", g.delta)
    res.add("green_lost", g.lost.astype("float32"))
    res.add("green_gained", g.gained.astype("float32"))
    res.add("green_deficit", A_veg.green_deficit(
        res.layers["ndvi_current"], res.layers["builtup_frac_current"]))
    res.stats["vegetation"] = A_veg.conversion_summary(g, res.layers["new_urban"], fr)


def stage_thermal(res: Result) -> None:
    """Surface urban heat island, if LST is present."""
    if "lst" not in res.layers:
        res.skipped["thermal"] = "LST unavailable (needs Earth Engine)"
        return
    cfg, fr = res.cfg, res.fine
    rural = ghsl.rural_reference_mask_from_builtup(
        res.layers[f"builtup_m2_{cfg.epoch_current}"], fr
    )
    try:
        s = A_thermal.compute_suhi(
            res.layers["lst"], rural,
            year=res.stats.get("thermal", {}).get("year", cfg.epoch_current),
            hotspot_delta_c=cfg.get("thresholds.thermal.suhi_hotspot_delta_c"),
            smooth_m=300.0, frame=fr,
        )
    except ValueError as exc:
        res.skipped["thermal"] = str(exc)
        return

    res.add("suhi_intensity", s.intensity)
    res.add("suhi_hotspot", s.hotspots.astype("float32"))
    res.add("heat_vulnerability", A_thermal.heat_vulnerability(
        s, res.layers[f"population_{cfg.epoch_current}"],
        ndvi=res.layers.get("ndvi_current")))
    if "ndvi_current" in res.layers:
        res.add("cooling_potential", A_thermal.cooling_potential(
            s, res.layers["ndvi_current"], res.layers["builtup_frac_current"]))
    res.stats["thermal"] = {**res.stats.get("thermal", {}), **A_thermal.summary(s, fr)}


def stage_ghost(res: Result) -> None:
    """Composite activity index, ghost-growth screen, growth typology."""
    cfg, fr = res.cfg, res.fine
    # Threshold is configured as a fraction of cell area so it stays correct
    # whatever resolution the analysis frame runs at.
    min_built = cfg.get("grid.min_builtup_fraction_for_analysis") * (fr.res**2)

    act = A_ghost.activity_index(
        res.layers[f"builtup_m2_{cfg.epoch_current}"], fr,
        nightlights=res.layers.get("nightlights"),
        poi_density=res.layers.get("poi_density"),
        population=res.layers.get(f"population_{cfg.epoch_current}"),
        min_builtup_m2=min_built,
    )
    res.add("activity_index", act.value)
    for name, arr in act.components.items():
        res.add(f"activity_{name}", arr)

    new_frac = np.clip(res.layers["builtup_delta_frac"], 0, None)
    g = A_ghost.analyse(
        act, res.layers["builtup_frac_current"], new_frac, fr,
        activity_trend=res.layers.get("nightlights_slope"),
        min_new_share=cfg.get("thresholds.ghost_growth.min_new_share"),
        min_new_builtup_frac=cfg.get("thresholds.ghost_growth.min_new_builtup_fraction"),
        residual_percentile=cfg.get("thresholds.ghost_growth.max_activity_percentile"),
        urban_threshold=cfg.get("thresholds.builtup.surface_fraction_urban"),
    )
    res.add("activity_expected", g.expected)
    res.add("activity_residual", g.residual)
    res.add("ghost_score", g.ghost_score)
    res.add("new_builtup_share", g.new_share)
    res.add("typology", g.typology.astype("float32"))

    zones_raster, zones = A_ghost.cluster_zones(
        g, fr,
        min_area_km2=cfg.get("thresholds.ghost_growth.zone_min_area_km2", 0.25),
        neighbourhood_m=cfg.get("thresholds.ghost_growth.zone_neighbourhood_m", 600.0),
        density_ratio=cfg.get("thresholds.ghost_growth.zone_density_ratio", 2.0),
    )
    res.add("ghost_zone_id", zones_raster.astype("float32"))

    # Attach lon/lat to each zone for the dashboard.
    for z in zones:
        lon, lat = res.aoi.to_lonlat(z["centroid_x"], z["centroid_y"])
        z["lon"], z["lat"] = round(lon, 5), round(lat, 5)

    res.stats["ghost"] = {
        "activity_sources": act.sources,
        "activity_weights": {k: round(v, 3) for k, v in act.weights.items()},
        "typology_areas_km2": g.areas_km2(fr),
        "typology_counts": g.counts(),
        "n_zones": len(zones),
        "zones": zones[:25],
        "ghost_area_km2": g.areas_km2(fr)["ghost_growth"],
    }
    if "nightlights_slope" not in res.layers:
        res.stats["ghost"]["caveat"] = (
            "No nightlight time series available, so 'emerging' (filling up) "
            "could not be separated from 'ghost_growth' (not filling up). "
            "Ghost figures are therefore an upper bound."
        )


def stage_export(res: Result) -> None:
    """Aggregate to the reporting grid and write all outputs."""
    cfg, aoi, fine, coarse = res.cfg, res.aoi, res.fine, res.coarse
    out = cfg.outputs_dir

    # How each layer should aggregate from 100 m to 500 m.
    #
    # Findings rasters (typology, urban form, zone id) use `priority`, not
    # `majority`: findings are a minority of cells by nature, and a majority
    # vote erases them entirely. The reporting cell must show the most
    # significant class it contains.
    priorities = {
        "typology": [A_ghost.TYPE_GHOST_GROWTH, A_ghost.TYPE_DECLINING,
                     A_ghost.TYPE_EMERGING, A_ghost.TYPE_HEALTHY_GROWTH,
                     A_ghost.TYPE_ESTABLISHED, A_ghost.TYPE_UNDEVELOPED],
        "expansion_form": [A_built.FORM_LEAPFROG, A_built.FORM_EDGE,
                           A_built.FORM_INFILL, A_built.FORM_NONE],
    }

    how: dict[str, A_zonal.AggHow] = {}
    for name in res.layers:
        if name.startswith(("builtup_m2", "population_", "poi_", "road_density")):
            how[name] = "sum"
        elif name in ("new_urban", "green_lost", "green_gained",
                      "growth_hotspot", "suhi_hotspot", "nightlights_growth"):
            how[name] = "any"
        elif name in priorities:
            how[name] = "priority"
        elif name == "ghost_zone_id":
            how[name] = "max"
        else:
            how[name] = "mean"

    layers = {n: (a, how[n]) for n, a in res.layers.items()}
    gdf = A_zonal.to_grid(aoi, layers, fine, coarse, priorities=priorities)

    # Count of flagged 100 m cells per reporting cell — lets the dashboard
    # show how much of a 500 m cell is actually flagged, rather than implying
    # the whole cell is.
    ghost_mask = (res.layers["typology"] == A_ghost.TYPE_GHOST_GROWTH).astype("float64")
    factor = int(round(coarse.res / fine.res))
    counts = A_zonal.block_reduce(ghost_mask, factor, "sum")[: coarse.height, : coarse.width]
    gdf["ghost_cells"] = counts.reshape(-1)

    # Drop cells with no development and no signal — keeps the GeoJSON small.
    keep = (gdf.get("builtup_m2_%d" % cfg.epoch_current, 0) > 0)
    gdf_out = gdf[keep].copy() if hasattr(keep, "sum") else gdf
    log.info("[export] grid %d cells -> %d with signal", len(gdf), len(gdf_out))

    A_zonal.export(gdf_out, out / f"{aoi.slug}_grid.geojson")
    gdf_out.drop(columns="geometry").to_csv(out / f"{aoi.slug}_grid.csv", index=False)

    res.stats["grid"] = A_zonal.summarise(gdf_out)

    # Rasters, for GIS users and Phase 2 modelling.
    import rasterio

    rdir = cfg.processed_dir / "rasters"
    rdir.mkdir(parents=True, exist_ok=True)
    for name, arr in res.layers.items():
        with rasterio.open(rdir / f"{name}.tif", "w", **fine.profile("float32")) as ds:
            ds.write(arr.astype("float32"), 1)
    log.info("[export] wrote %d rasters to %s", len(res.layers), rdir)

    payload = {
        "city": cfg.city,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "phase": 1,
        "aoi": {
            "bbox": cfg.bbox, "area_km2": round(aoi.area_km2(), 1),
            "crs": aoi.crs_m,
            "analysis_res_m": fine.res, "reporting_res_m": coarse.res,
        },
        "stats": res.stats,
        "provenance": res.provenance,
        "skipped": res.skipped,
        "layers": sorted(res.layers),
    }
    (out / f"{aoi.slug}_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    log.info("[export] summary -> %s", out / f"{aoi.slug}_summary.json")


# --------------------------------------------------------------------------

def run(cfg: Config, *, use_gee: bool = True) -> Result:
    aoi = AOI(cfg)
    # Exactly-nested frames — see AOI.frame_pair for why this cannot be two
    # independent frame() calls.
    fine, coarse = aoi.frame_pair(
        cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m
    )
    res = Result(cfg=cfg, aoi=aoi, fine=fine, coarse=coarse)

    log.info("=" * 68)
    log.info("%s — Phase 1 pipeline", cfg.city)
    log.info("AOI %.0f km2 | analysis %dx%d @%dm | reporting %dx%d @%dm",
             aoi.area_km2(), fine.width, fine.height, fine.res,
             coarse.width, coarse.height, coarse.res)
    log.info("=" * 68)

    for name, fn in [
        ("builtup", lambda: stage_builtup(res)),
        ("osm", lambda: stage_osm(res)),
        ("gee", lambda: stage_gee(res, use_gee)),
        ("vegetation", lambda: stage_vegetation(res)),
        ("thermal", lambda: stage_thermal(res)),
        ("ghost", lambda: stage_ghost(res)),
        ("export", lambda: stage_export(res)),
    ]:
        t0 = time.time()
        log.info("--- stage: %s", name)
        fn()
        log.info("    %.1fs", time.time() - t0)

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Urban growth intelligence — Phase 1")
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-gee", action="store_true", help="skip Earth Engine layers")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    res = run(cfg, use_gee=not args.no_gee)

    print("\n" + "=" * 68)
    print(f"{cfg.city} — Phase 1 complete")
    print("=" * 68)
    b = res.stats.get("builtup", {})
    print(f"  Built-up {b.get('period','')}: "
          f"{b.get('built_surface_km2',{})}")
    print(f"  New built-up: {b.get('new_builtup_km2')} km2 "
          f"({b.get('annual_urban_growth_pct')}%/yr urban extent)")
    if "urban_form" in b:
        for k, v in b["urban_form"].items():
            if not k.startswith("_"):
                print(f"    {k:16s} {v['area_km2']:8.2f} km2  ({v['share_pct']}%)")
    gh = res.stats.get("ghost", {})
    if gh:
        print(f"  Ghost-growth area: {gh.get('ghost_area_km2')} km2 "
              f"in {gh.get('n_zones')} zones")
        print(f"  Activity signals used: {', '.join(gh.get('activity_sources', []))}")
    if res.skipped:
        print("\n  Skipped:")
        for k, v in res.skipped.items():
            print(f"    {k}: {v[:100]}")
    print(f"\n  Outputs -> {cfg.outputs_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
