from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
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
    """Everything the pipeline produces, in memory."""

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


def _km2(mask: np.ndarray, frame: AnalysisFrame) -> float:
    return float(mask.sum()) * (frame.res**2) / 1e6


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------

def stage_builtup(res: Result) -> None:
    """GHSL built-up: observed epochs, change, urban form, hotspots."""
    cfg, aoi, fr = res.cfg, res.aoi, res.fine
    epochs = cfg.observational_epochs
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")
    min_delta = cfg.get("thresholds.builtup.new_growth_min_delta_m2")

    log.info("[builtup] loading %d observed GHSL epochs", len(epochs))
    built: dict[int, np.ndarray] = {}
    pop: dict[int, np.ndarray] = {}
    for y in epochs:
        built[y] = ghsl.load_builtup(cfg, aoi, y, fr)
        pop[y] = ghsl.load_population(cfg, aoi, y, fr)
        res.add(f"builtup_m2_{y}", built[y])
        res.add(f"population_{y}", pop[y])
        log.info("  %d: built %.2f km2, pop %.0f",
                 y, float(np.nansum(built[y])) / 1e6, float(np.nansum(pop[y])))

    y0, y1 = cfg.epoch_baseline, cfg.epoch_current
    chg = A_built.change(
        built[y0], built[y1], fr,
        year_from=y0, year_to=y1,
        urban_threshold=thr, min_delta_m2=min_delta,
    )
    # Named by year, not "baseline"/"current": until Review 3 "current" meant
    # a GHSL projection, and a name that cannot be misread is the cheap fix.
    res.add(f"builtup_frac_{y0}", chg.frac_from)
    res.add(f"builtup_frac_{y1}", chg.frac_to)
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
        "urban_km2": {str(y): round(_km2(A_built.fraction(built[y], fr) >= thr, fr), 2)
                      for y in epochs},
        "population_total": {str(y): int(np.nansum(pop[y])) for y in epochs},
        "built_surface_km2": {str(y): round(float(np.nansum(built[y])) / 1e6, 2) for y in epochs},
        "new_builtup_km2": round(chg.total_new_km2, 2),
        "lost_builtup_km2": round(chg.total_lost_km2, 2),
        "net_builtup_change_km2": round(float(np.nansum(chg.delta_m2)) / 1e6, 2),
        "annual_urban_growth_pct": round(chg.annual_growth_rate(fr), 2),
        "urban_form": A_built.form_summary(form, fr),
        "period": f"{y0}-{y1}",
    }
    res.provenance["builtup"] = {
        "source": "GHSL GHS-BUILT-S R2023A (100 m), observed epochs "
                  + ", ".join(str(y) for y in epochs),
        "url": cfg.get("sources.ghsl.base_url"),
        "auth": "none",
    }
    res._chg = chg  # kept for later stages

    # The GHSL projection, kept apart and labelled. Nothing downstream reads it.
    projected = cfg.projected_epochs
    if projected:
        pstats: dict[str, Any] = {
            "note": "GHSL model projection, not an observation. Comparison only.",
            "built_surface_km2": {}, "urban_km2": {}, "population_total": {},
        }
        for y in projected:
            try:
                b = ghsl.load_builtup(cfg, aoi, y, fr)
                p = ghsl.load_population(cfg, aoi, y, fr)
            except Exception as exc:  # noqa: BLE001
                res.skipped[f"ghsl_projection_{y}"] = str(exc)
                continue
            res.add(f"builtup_m2_{y}_projected", b)
            res.add(f"population_{y}_projected", p)
            pstats["built_surface_km2"][str(y)] = round(float(np.nansum(b)) / 1e6, 2)
            pstats["urban_km2"][str(y)] = round(_km2(A_built.fraction(b, fr) >= thr, fr), 2)
            pstats["population_total"][str(y)] = int(np.nansum(p))
        res.stats["builtup"]["projection"] = pstats


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
    """Earth Engine layers: nightlights, NDVI, Dynamic World, LST. Optional."""
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
    thr = cfg.get("thresholds.builtup.surface_fraction_urban")

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
        years = sorted(ntl_stack)
        latest = years[-1]
        level_years = years[-int(cfg.get("timeseries.nightlights_level_years", 3)):]
        res.add("nightlights", ntl_stack[latest])
        res.add("nightlights_level", A_ntl.window_mean(ntl_stack, level_years))
        res.stats["nightlights"] = {
            "years": years,
            "level_years": level_years,
            "sum_of_lights": {str(y): round(A_ntl.sum_of_lights(a), 1)
                              for y, a in sorted(ntl_stack.items())},
            "lit_fraction_latest": round(
                A_ntl.lit_fraction(ntl_stack[latest],
                                   cfg.get("thresholds.nightlights.unlit_radiance")), 4),
        }
        if len(ntl_stack) >= 3:
            tr = A_ntl.trend(ntl_stack)
            growth = tr.significant_growth()
            res.add("nightlights_slope", tr.slope)
            res.add("nightlights_pvalue", tr.p_value)
            res.add("nightlights_growth", growth.astype("float32"))
            urban_now = res.layers[f"builtup_frac_{cfg.epoch_current}"] >= thr
            if urban_now.any():
                res.stats["nightlights"]["urban_cells_significant_growth_pct"] = round(
                    100.0 * float(growth[urban_now].mean()), 1)
            # Relative to the established city: cells already urban at the
            # baseline epoch. See nightlights.relative_trend for why.
            try:
                rt = A_ntl.relative_trend(ntl_stack, res._chg.was_urban)
                res.add("nightlights_rel_slope", rt.slope)
                res.add("nightlights_rel_pvalue", rt.p_value)
            except ValueError as exc:
                res.skipped["nightlights_relative_trend"] = str(exc)
        legacy = cfg.get("sources.gee.assets.viirs_annual_legacy", None)
        cut = int(cfg.get("sources.gee.assets.viirs_annual_legacy_last_year", 2021))
        current_asset = cfg.get("sources.gee.assets.viirs_annual")
        if legacy and years[0] <= cut < latest:
            source = f"{legacy} ({years[0]}-{cut}) + {current_asset} ({cut + 1}-{latest})"
        else:
            source = gee.viirs_annual_asset(cfg, latest)
        res.provenance["nightlights"] = {"source": source, "auth": "gee"}

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

    # --- Dynamic World: built probability (both NDVI years) and water ----
    # Built probability gives built-up gain over the same years as the NDVI
    # change; water keeps the Ganga out of the heat-island rural reference.
    v0 = cfg.get("timeseries.vegetation_start")
    v1 = cfg.get("timeseries.vegetation_end") - 1
    for y in sorted({v0, v1}):
        try:
            img = gee.dynamicworld_image(cfg, aoi, y)
            p = gee.download_image(img, aoi, raw / f"dw_{y}.tif", scale=60)
            res.add(f"dw_built_{y}", gee.to_frame(p, fr, band=1))
            if y == v1:
                res.add(f"dw_water_{y}", gee.to_frame(p, fr, band=4))
        except Exception as exc:
            log.warning("[gee] Dynamic World %d failed: %s", y, exc)
            res.skipped[f"dynamic_world_{y}"] = str(exc)
    if f"dw_built_{v1}" in res.layers:
        res.provenance["dynamic_world"] = {
            "source": cfg.get("sources.gee.assets.dynamic_world"), "auth": "gee"
        }

    # --- LST (pre-monsoon), latest year and first Landsat 8 year ----------
    t0 = cfg.get("timeseries.thermal_start")
    t1 = cfg.get("timeseries.thermal_end") - 1
    for key, year in (("lst", t1), (f"lst_{t0}", t0)):
        try:
            img = gee.lst_image(cfg, aoi, year, season="premonsoon")
            p = gee.download_image(img, aoi, raw / f"lst_{year}.tif", scale=scale)
            res.add(key, gee.to_frame(p, fr))
        except Exception as exc:
            log.warning("[gee] LST %d failed: %s", year, exc)
            res.skipped[key] = str(exc)
    if "lst" in res.layers:
        res.stats.setdefault("thermal", {})["year"] = t1
        res.provenance["lst"] = {
            "source": (f"{cfg.get('sources.gee.assets.landsat8')} + "
                       f"{cfg.get('sources.gee.assets.landsat9')} (band ST_B10)"),
            "auth": "gee",
        }


def stage_vegetation(res: Result) -> None:
    """Green cover change, if NDVI is present."""
    if "ndvi_baseline" not in res.layers or "ndvi_current" not in res.layers:
        res.skipped["vegetation"] = "NDVI layers unavailable (needs Earth Engine)"
        return
    cfg, fr = res.cfg, res.fine
    v0 = cfg.get("timeseries.vegetation_start")
    v1 = cfg.get("timeseries.vegetation_end") - 1
    g = A_veg.change(
        res.layers["ndvi_baseline"], res.layers["ndvi_current"],
        year_from=v0, year_to=v1,
        green_threshold=cfg.get("thresholds.vegetation.ndvi_green_threshold"),
        min_delta=cfg.get("thresholds.vegetation.green_loss_min_delta"),
    )
    res.add("ndvi_delta", g.delta)
    res.add("green_lost", g.lost.astype("float32"))
    res.add("green_gained", g.gained.astype("float32"))
    res.add("green_deficit", A_veg.green_deficit(
        res.layers["ndvi_current"], res.layers[f"builtup_frac_{cfg.epoch_current}"]))

    # "Lost to built-up" needs built-up gain over the SAME years as the NDVI
    # change. GHSL has no 2018 or 2024 epoch, so Dynamic World's built
    # probability is used; GHSL is only the fallback, with the mismatch noted.
    b0, b1 = res.layers.get(f"dw_built_{v0}"), res.layers.get(f"dw_built_{v1}")
    if b0 is not None and b1 is not None:
        gain = A_veg.built_gain(
            b0, b1,
            min_rise=cfg.get("thresholds.vegetation.dw_built_min_rise", 0.15),
            min_end=cfg.get("thresholds.vegetation.dw_built_min_end", 0.30),
        )
        res.add("dw_built_gain", gain.astype("float32"))
        s = A_veg.conversion_summary(g, gain, fr)
        s["built_gain_source"] = (f"{cfg.get('sources.gee.assets.dynamic_world')} built "
                                  f"probability {v0}-{v1} (same years as the NDVI change)")
        s["dw_built_gain_km2"] = round(_km2(gain, fr), 3)
    else:
        s = A_veg.conversion_summary(g, res.layers["new_urban"], fr)
        s["built_gain_source"] = f"GHSL new urban {cfg.epoch_baseline}-{cfg.epoch_current}"
        s["caveat"] = "built-up gain and NDVI change cover different periods"
    s["period"] = f"{v0}-{v1}"
    res.stats["vegetation"] = s


def stage_thermal(res: Result) -> None:
    """Surface urban heat island, if LST is present."""
    if "lst" not in res.layers:
        res.skipped["thermal"] = "LST unavailable (needs Earth Engine)"
        return
    cfg, fr = res.cfg, res.fine
    cur = cfg.epoch_current
    dw_year = cfg.get("timeseries.vegetation_end") - 1

    water = res.layers.get(f"dw_water_{dw_year}")
    dw_built = res.layers.get(f"dw_built_{dw_year}")
    water_mask = (None if water is None else
                  np.nan_to_num(water, nan=0.0) >= cfg.get("thresholds.thermal.water_probability", 0.5))
    recent_built = (None if dw_built is None else
                    np.nan_to_num(dw_built, nan=0.0) >= cfg.get("thresholds.thermal.rural_max_dw_built", 0.2))

    base_rural = ghsl.rural_reference_mask_from_builtup(res.layers[f"builtup_m2_{cur}"], fr)
    rural = ghsl.rural_reference_mask_from_builtup(
        res.layers[f"builtup_m2_{cur}"], fr, water=water_mask, exclude=recent_built)
    urban = res.layers[f"builtup_frac_{cur}"] >= cfg.get("thresholds.builtup.surface_fraction_urban")

    year = res.stats.get("thermal", {}).get("year", cur)
    hot = cfg.get("thresholds.thermal.suhi_hotspot_delta_c")
    try:
        s = A_thermal.compute_suhi(res.layers["lst"], rural, year=year, hotspot_delta_c=hot,
                                   smooth_m=300.0, frame=fr, urban_mask=urban)
    except ValueError as exc:
        res.skipped["thermal"] = str(exc)
        return

    res.add("suhi_intensity", s.intensity)
    res.add("suhi_hotspot", s.hotspots.astype("float32"))
    res.add("heat_vulnerability", A_thermal.heat_vulnerability(
        s, res.layers[f"population_{cur}"], ndvi=res.layers.get("ndvi_current")))
    if "ndvi_current" in res.layers:
        res.add("cooling_potential", A_thermal.cooling_potential(
            s, res.layers["ndvi_current"], res.layers[f"builtup_frac_{cur}"]))

    rule = [f"GHSL {cur} built surface < 2%"]
    if recent_built is not None:
        rule.append(f"Dynamic World {dw_year} built probability < "
                    f"{cfg.get('thresholds.thermal.rural_max_dw_built', 0.2)}")
    rule.append("water excluded (Dynamic World water probability >= "
                f"{cfg.get('thresholds.thermal.water_probability', 0.5)})"
                if water_mask is not None else "water NOT excluded (Dynamic World unavailable)")
    th = {**res.stats.get("thermal", {}), **A_thermal.summary(s, fr)}
    th["rural_reference_rule"] = "; ".join(rule)

    # Before/after for the corrections log: the same scene under the Review 2
    # rural rule (GHSL only), with water removed, and with both exclusions.
    variants = {"ghsl_only": base_rural}
    if water_mask is not None:
        variants["ghsl_minus_water"] = base_rural & ~water_mask
    variants["final"] = rural
    sens = {}
    for name, mask in variants.items():
        try:
            sv = A_thermal.compute_suhi(res.layers["lst"], mask, year=year, hotspot_delta_c=hot,
                                        smooth_m=300.0, frame=fr, urban_mask=urban)
        except ValueError:
            continue
        sm = A_thermal.summary(sv, fr)
        sens[name] = {k: sm[k] for k in ("rural_reference_c", "rural_reference_cells",
                                         "mean_urban_intensity_c", "mean_positive_intensity_c",
                                         "hotspot_area_km2")}
    th["rural_rule_sensitivity"] = sens
    th["urban_cells"] = int(urban.sum())
    if water_mask is not None:
        th["rural_cells_removed_as_water"] = int((base_rural & water_mask).sum())
    if recent_built is not None:
        th["rural_cells_removed_as_recently_built"] = int(
            (base_rural & recent_built & ~(water_mask if water_mask is not None else False)).sum())

    # Heat-island change: same rural and urban cells, first Landsat 8 year.
    # Absolute LST depends on the day's weather; the urban-minus-rural
    # difference within each scene largely does not, so change is measured
    # on intensity, never on raw temperature.
    t0 = cfg.get("timeseries.thermal_start")
    if f"lst_{t0}" in res.layers:
        try:
            s0 = A_thermal.compute_suhi(res.layers[f"lst_{t0}"], rural, year=t0,
                                        hotspot_delta_c=hot, smooth_m=300.0, frame=fr,
                                        urban_mask=urban)
            res.add(f"suhi_intensity_{t0}", s0.intensity)
            res.add("suhi_change", (s.intensity - s0.intensity).astype("float32"))
            first = A_thermal.summary(s0, fr)
            th["change"] = {
                "year_from": t0, "year_to": year,
                "from": first,
                "mean_urban_intensity_change_c": (
                    None if first["mean_urban_intensity_c"] is None or th["mean_urban_intensity_c"] is None
                    else round(th["mean_urban_intensity_c"] - first["mean_urban_intensity_c"], 2)),
                "note": "Same rural and urban cells in both years; intensity, not raw LST.",
            }
        except ValueError as exc:
            res.skipped["thermal_change"] = str(exc)
    res.stats["thermal"] = th


def stage_ghost(res: Result) -> None:
    """Composite activity index, ghost-growth screen, growth typology."""
    cfg, fr = res.cfg, res.fine
    cur = cfg.epoch_current
    # Threshold is configured as a fraction of cell area so it stays correct
    # whatever resolution the analysis frame runs at.
    min_built = cfg.get("grid.min_builtup_fraction_for_analysis") * (fr.res**2)

    # Development observed to 2020, activity level from the latest years
    # (2022-2024 mean): new building has had time to be occupied.
    ntl_level = res.layers.get("nightlights_level", res.layers.get("nightlights"))
    act = A_ghost.activity_index(
        res.layers[f"builtup_m2_{cur}"], fr,
        nightlights=ntl_level,
        poi_density=res.layers.get("poi_density"),
        population=res.layers.get(f"population_{cur}"),
        min_builtup_m2=min_built,
    )
    res.add("activity_index", act.value)
    for name, arr in act.components.items():
        res.add(f"activity_{name}", arr)

    evidence = None
    if "nightlights_slope" in res.layers:
        evidence = A_ghost.TrendEvidence(
            slope=res.layers["nightlights_slope"],
            p_value=res.layers.get("nightlights_pvalue"),
            rel_slope=res.layers.get("nightlights_rel_slope"),
            rel_p_value=res.layers.get("nightlights_rel_pvalue"),
        )
    rule = cfg.get("thresholds.ghost_growth.trend_rule", "relative_significant")
    alpha = float(cfg.get("thresholds.ghost_growth.trend_alpha", 0.10))
    if evidence is not None and rule.startswith("relative") and evidence.rel_slope is None:
        log.warning("[ghost] relative trend unavailable; using rule 'significant'")
        rule = "significant"

    new_frac = np.clip(res.layers["builtup_delta_frac"], 0, None)
    frac_now = res.layers[f"builtup_frac_{cur}"]
    common = dict(
        min_new_share=cfg.get("thresholds.ghost_growth.min_new_share"),
        min_new_builtup_frac=cfg.get("thresholds.ghost_growth.min_new_builtup_fraction"),
        residual_percentile=cfg.get("thresholds.ghost_growth.max_activity_percentile"),
        urban_threshold=cfg.get("thresholds.builtup.surface_fraction_urban"),
    )
    g = A_ghost.analyse(act, frac_now, new_frac, fr, activity_trend=evidence,
                        rising_rule=rule, trend_alpha=alpha, **common)
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
        "nightlight_level_years": res.stats.get("nightlights", {}).get("level_years"),
        "development_period": f"{cfg.epoch_baseline}-{cur}",
        "rising_rule": g.rising_rule,
        "trend_alpha": alpha if evidence is not None else None,
        "typology_areas_km2": g.areas_km2(fr),
        "typology_counts": g.counts(),
        "n_zones": len(zones),
        "zones": zones[:25],
        "ghost_area_km2": g.areas_km2(fr)["ghost_growth"],
    }
    if evidence is None:
        res.stats["ghost"]["caveat"] = (
            "No nightlight time series available, so 'emerging' (filling up) "
            "could not be separated from 'ghost_growth' (not filling up). "
            "Ghost figures are therefore an upper bound."
        )
    else:
        # How much the emerging/ghost split depends on the definition of
        # "rising" — reported for every rule, not only the one chosen.
        sens = {}
        for r in A_ghost.RISING_RULES:
            if r.startswith("relative") and evidence.rel_slope is None:
                continue
            gr = A_ghost.analyse(act, frac_now, new_frac, fr, activity_trend=evidence,
                                 rising_rule=r, trend_alpha=alpha, **common)
            sens[r] = gr.areas_km2(fr)
        res.stats["ghost"]["rule_sensitivity_km2"] = sens


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
        elif name in ("new_urban", "green_lost", "green_gained", "dw_built_gain",
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

    # Rasters, for GIS users and the growth model.
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
        "method_version": "review3",
        "epochs": {
            "observational": cfg.observational_epochs,
            "projected": cfg.projected_epochs,
            "baseline": cfg.epoch_baseline,
            "current": cfg.epoch_current,
        },
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
    cfg.check_epochs()
    aoi = AOI(cfg)
    # Exactly-nested frames — see AOI.frame_pair for why this cannot be two
    # independent frame() calls.
    fine, coarse = aoi.frame_pair(
        cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m
    )
    res = Result(cfg=cfg, aoi=aoi, fine=fine, coarse=coarse)

    log.info("=" * 68)
    log.info("%s — analysis pipeline (observed epochs %s)", cfg.city, cfg.observational_epochs)
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
    ap = argparse.ArgumentParser(description="Urban growth intelligence — analysis pipeline")
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
    print(f"{cfg.city} — pipeline complete (observed epochs only)")
    print("=" * 68)
    b = res.stats.get("builtup", {})
    print(f"  Built-up surface {b.get('period','')}: {b.get('built_surface_km2',{})} km2")
    print(f"  Net built-up change: {b.get('net_builtup_change_km2')} km2; "
          f"urban extent {b.get('annual_urban_growth_pct')} %/yr")
    if "urban_form" in b:
        for k, v in b["urban_form"].items():
            if not k.startswith("_"):
                print(f"    {k:16s} {v['area_km2']:8.2f} km2  ({v['share_pct']}%)")
    if "projection" in b:
        print(f"  GHSL projection (comparison only): {b['projection']['built_surface_km2']} km2")
    th = res.stats.get("thermal", {})
    if th.get("mean_urban_intensity_c") is not None:
        print(f"  Heat island {th.get('year')}: mean urban +{th['mean_urban_intensity_c']} C, "
              f"hotspots {th.get('hotspot_area_km2')} km2")
    gh = res.stats.get("ghost", {})
    if gh:
        print(f"  Ghost-growth area: {gh.get('ghost_area_km2')} km2 "
              f"in {gh.get('n_zones')} zones (rule: {gh.get('rising_rule')})")
        print(f"  Activity signals used: {', '.join(gh.get('activity_sources', []))}")
    if res.skipped:
        print("\n  Skipped:")
        for k, v in res.skipped.items():
            print(f"    {k}: {v[:100]}")
    print(f"\n  Outputs -> {cfg.outputs_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
