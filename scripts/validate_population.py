from __future__ import annotations

import json
import logging
import sys
import warnings
import zipfile
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

from urbanintel.analysis import validation as VAL  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee, shrug  # noqa: E402

log = logging.getLogger("validate_population")

GHS_POP = "JRC/GHSL/P2023A/GHS_POP"     # one image per epoch, band population_count
WORLDPOP = "WorldPop/GP/100m/pop"        # annual 2000-2020, band population
REGION = ("varanasi", "chandauli", "jaunpur", "ghazipur", "mirzapur", "bhadohi")


def ghs_pop(year: int):
    """GHS-POP for any year, interpolated linearly between five-yearly epochs."""
    ee = gee.ee_init()
    lo = (year // 5) * 5
    a = ee.Image(f"{GHS_POP}/{lo}").select("population_count")
    if year == lo:
        return a
    b = ee.Image(f"{GHS_POP}/{lo + 5}").select("population_count")
    w = (year - lo) / 5.0
    return a.multiply(1 - w).add(b.multiply(w))


def worldpop(year: int):
    ee = gee.ee_init()
    return (ee.ImageCollection(WORLDPOP).filter(ee.Filter.eq("country", "IND"))
            .filter(ee.Filter.eq("year", year)).first().select("population"))


def native(name: str):
    """The grid a dataset is published on — sums must be taken on it so counts stay counts."""
    ee = gee.ee_init()
    img = ee.Image(f"{GHS_POP}/2010") if name == "ghs_pop" else worldpop(2011)
    proj = img.projection()
    return proj, proj.nominalScale().getInfo()


def zonal_sums(img, feats, grid) -> dict[int, float]:
    ee = gee.ee_init()
    proj, scale = grid
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry(mapping(g)), {"uid": int(u)})
                               for u, g in feats])
    res = img.reduceRegions(collection=fc, reducer=ee.Reducer.sum(), crs=proj,
                            scale=scale, tileScale=4).getInfo()
    return {int(f["properties"]["uid"]): f["properties"].get("sum") for f in res["features"]}


def pct(a, b) -> float | None:
    return None if not b else round(100.0 * (a - b) / b, 2)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    gee.ee_init(cfg.get("sources.gee.project", None))
    grids = {"ghs_pop": native("ghs_pop"), "worldpop": native("worldpop")}
    out: dict = {}

    # ------------------------------------------------ 1-2. district totals
    log.info("district totals: 71 districts of Uttar Pradesh")
    d = shrug.district_polygons(cfg).merge(shrug.district_table(cfg),
                                           on=["pc11_state_id", "pc11_district_id"])
    feats = [(u, g.simplify(0.005, preserve_topology=True))
             for u, g in zip(d.pc11_district_id, d.geometry)]
    d["ghs_pop_2011"] = d.pc11_district_id.map(zonal_sums(ghs_pop(2011), feats, grids["ghs_pop"]))
    d["worldpop_2011"] = d.pc11_district_id.map(zonal_sums(worldpop(2011), feats, grids["worldpop"]))
    census = d.pc11_pca_tot_p.astype(float)
    per_ds = {}
    for c in ("ghs_pop_2011", "worldpop_2011"):
        err = 100.0 * (d[c] - census) / census
        d[c + "_error_pct"] = err
        per_ds[c] = {
            "median_error_pct": round(float(err.median()), 2),
            "mean_absolute_error_pct": round(float(err.abs().mean()), 2),
            "districts_within_10pct": int((err.abs() <= 10).sum()),
            "state_total_error_pct": pct(float(d[c].sum()), float(census.sum())),
            "loglog": {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in VAL.loglog_fit(census, d[c]).items()},
        }
    focus = {}
    for name in ("Varanasi", "Chandauli"):
        row = d[d.district_name.str.lower() == name.lower()].iloc[0]
        focus[name] = {"census_2011": int(row.pc11_pca_tot_p),
                       "ghs_pop_2011": int(round(row.ghs_pop_2011)),
                       "ghs_pop_error_pct": round(float(row.ghs_pop_2011_error_pct), 2),
                       "worldpop_2011": int(round(row.worldpop_2011)),
                       "worldpop_error_pct": round(float(row.worldpop_2011_error_pct), 2)}
    out["districts"] = {"n": int(len(d)), "census_total_2011": int(census.sum()),
                        "datasets": per_ds, "study_area_districts": focus}
    d.drop(columns="geometry").to_csv(cfg.outputs_dir / "validation_population_districts.csv",
                                      index=False)

    # ------------------------------------------ 3. the city and the study area
    ids = d[d.district_name.str.lower().str.contains("|".join(REGION))].pc11_district_id.tolist()
    shr = shrug.shrids_for_districts(cfg, ids, name="varanasi_region")

    towns = shr[(shr.district_name.str.lower() == "varanasi") & shr.is_town]
    city = towns.sort_values("pc11_pca_tot_p", ascending=False).iloc[0]
    geom = [(1, city.geometry.simplify(0.0005, preserve_topology=True))]
    g_city = zonal_sums(ghs_pop(2011), geom, grids["ghs_pop"])[1]
    w_city = zonal_sums(worldpop(2011), geom, grids["worldpop"])[1]
    out["city"] = {"town": str(city.town_name), "census_2011": int(city.pc11_pca_tot_p),
                   "ghs_pop_2011": int(round(g_city)), "ghs_pop_error_pct": pct(g_city, city.pc11_pca_tot_p),
                   "worldpop_2011": int(round(w_city)), "worldpop_error_pct": pct(w_city, city.pc11_pca_tot_p)}

    # Census 2001 for the same towns and villages -> decadal growth over the study area.
    with zipfile.ZipFile(shrug.shrug_dir(cfg) / "shrug-pca01-csv.zip") as z:
        member = next(n for n in z.namelist() if n.endswith("_shrid.csv"))
    p01 = shrug.read_csv(cfg, "shrug-pca01-csv.zip", member,
                         usecols=["shrid2", "pc01_pca_tot_p"],
                         keep=shrug.in_districts(shrug.UP_STATE_ID, set(ids)))
    inside = shr.geometry.representative_point().within(aoi.geom_ll)
    sa = shr[inside].merge(p01, on="shrid2", how="left")
    c01, c11 = float(sa.pc01_pca_tot_p.sum()), float(sa.pc11_pca_tot_p.sum())
    union = sa.geometry.union_all().simplify(0.001, preserve_topology=True)
    ug = [(1, union)]
    g01 = zonal_sums(ghs_pop(2001), ug, grids["ghs_pop"])[1]
    g11 = zonal_sums(ghs_pop(2011), ug, grids["ghs_pop"])[1]
    w01 = zonal_sums(worldpop(2001), ug, grids["worldpop"])[1]
    w11 = zonal_sums(worldpop(2011), ug, grids["worldpop"])[1]
    out["study_area_2001_2011"] = {
        "towns_and_villages": int(len(sa)),
        "missing_2001_record": int(sa.pc01_pca_tot_p.isna().sum()),
        "census": {"2001": int(c01), "2011": int(c11), "growth_pct": pct(c11, c01)},
        "ghs_pop": {"2001": int(round(g01)), "2011": int(round(g11)), "growth_pct": pct(g11, g01)},
        "worldpop": {"2001": int(round(w01)), "2011": int(round(w11)), "growth_pct": pct(w11, w01)},
    }

    # ------------------------------------ 4. study area 2010-2020 and the headline
    fine, _ = aoi.frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
    rdir, raw = cfg.processed_dir / "rasters", cfg.raw_dir / "gee"
    with rasterio.open(rdir / "population_2010.tif") as a, rasterio.open(rdir / "population_2020.tif") as b:
        gh10, gh20 = float(np.nansum(a.read(1))), float(np.nansum(b.read(1)))
    wp10 = float(np.nansum(gee.to_frame(raw / "worldpop_2010.tif", fine)))
    wp20 = float(np.nansum(gee.to_frame(raw / "worldpop_2020.tif", fine)))
    summ = json.loads((cfg.outputs_dir / f"{aoi.slug}_summary.json").read_text(encoding="utf-8"))
    b = summ["stats"]["builtup"]
    built_g = pct(b["built_surface_km2"]["2020"], b["built_surface_km2"]["2010"])
    urban_g = pct(b["urban_km2"]["2020"], b["urban_km2"]["2010"])
    pop_g = {"ghs_pop": pct(gh20, gh10), "worldpop": pct(wp20, wp10)}
    out["study_area_2010_2020"] = {
        "ghs_pop": {"2010": int(gh10), "2020": int(gh20), "growth_pct": pop_g["ghs_pop"]},
        "worldpop": {"2010": int(wp10), "2020": int(wp20), "growth_pct": pop_g["worldpop"]},
        "built_surface_growth_pct": built_g,
        "urban_extent_growth_pct": urban_g,
        "built_to_population_growth_ratio": {
            k: round(built_g / v, 2) if v else None for k, v in pop_g.items()},
        "note": ("Review 2 quoted a single ratio (2.3x) from GHS-POP. The Census 2001-2011 "
                 "check above shows which dataset's growth is credible."),
    }

    p = cfg.outputs_dir / f"{aoi.slug}_population_validation.json"
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("summary -> %s", p)

    print("\n" + "=" * 70)
    print("POPULATION vs CENSUS OF INDIA")
    print("=" * 70)
    for k, v in per_ds.items():
        print(f"  {k:14s} 71 UP districts: median error {v['median_error_pct']:+.1f}%, "
              f"mean |error| {v['mean_absolute_error_pct']:.1f}%, "
              f"{v['districts_within_10pct']} within 10%")
    for k, v in focus.items():
        print(f"  {k:10s} census {v['census_2011']:,}  GHS-POP {v['ghs_pop_error_pct']:+.1f}%  "
              f"WorldPop {v['worldpop_error_pct']:+.1f}%")
    c = out["city"]
    print(f"  {c['town']}: census {c['census_2011']:,}  GHS-POP {c['ghs_pop_error_pct']:+.1f}%  "
          f"WorldPop {c['worldpop_error_pct']:+.1f}%")
    s = out["study_area_2001_2011"]
    print(f"  study area growth 2001-2011: census {s['census']['growth_pct']}%  "
          f"GHS-POP {s['ghs_pop']['growth_pct']}%  WorldPop {s['worldpop']['growth_pct']}%")
    t = out["study_area_2010_2020"]
    print(f"  study area growth 2010-2020: GHS-POP {t['ghs_pop']['growth_pct']}%  "
          f"WorldPop {t['worldpop']['growth_pct']}%  built surface {built_g}%")
    print(f"  built-up / population growth ratio: {t['built_to_population_growth_ratio']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
