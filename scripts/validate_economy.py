"""Does night-time light track economic activity here? Two tests with Indian data.

    python scripts/validate_economy.py

The project uses VIIRS night-time radiance as a proxy for economic activity.
This checks that proxy against two Indian sources:

1. **Towns and villages, 2013.** Employment in the 2013 Economic Census (the
   6th Economic Census) for every town and village in Varanasi and the five
   surrounding districts, from SHRUG, against VIIRS 2013 radiance over each
   town/village polygon. Same year, so there is no timing mismatch.
2. **Districts, 2020-21 and 2021-22.** Gross District Domestic Product for
   every district of Uttar Pradesh (Directorate of Economics & Statistics,
   Government of Uttar Pradesh) against VIIRS Sum of Lights per district.
   The 2013 Economic Census district totals are tested the same way.

Spearman rank correlation answers "are the brighter places the ones with more
jobs / output?"; the slope of the log-log line (the elasticity) answers "by
how much?". The night-light literature (Henderson, Storeygard & Weil 2012)
works with the same two quantities.
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.warp import reproject  # noqa: E402
from shapely.geometry import box, mapping  # noqa: E402

from urbanintel.analysis import validation as VAL  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee, shrug  # noqa: E402

log = logging.getLogger("validate_economy")

REGION = ("varanasi", "chandauli", "jaunpur", "ghazipur", "mirzapur", "bhadohi")

# District names in the UP DES tables -> 2011 Census names. Four districts
# were created after the Census froze its boundaries (Shamli, Hapur, Sambhal,
# Amethi); their output is added back to the district they were carved from.
DDP_TO_CENSUS = {
    "Muzaffar Nagar": "Muzaffarnagar", "Shamli": "Muzaffarnagar",
    "Sambhal": "Moradabad", "Amroha": "Jyotiba Phule Nagar",
    "Hapur": "Ghaziabad", "Gautambudh Nagar": "Gautam Buddha Nagar",
    "Buland Shahar": "Bulandshahr", "Hathras": "Mahamaya Nagar",
    "Kasganj": "Kanshiram Nagar", "Badaun": "Budaun", "Auraiyya": "Auraiya",
    "Raebareilly": "Rae Bareli", "Barabanki": "Bara Banki",
    "Prayagraj": "Allahabad", "Ayodhya": "Faizabad", "Amethi": "Sultanpur",
    "Shravasti": "Shrawasti", "Siddharth Nagar": "Siddharthnagar",
    "Sant Kabeer Nagar": "Sant Kabir Nagar", "Maharajganj": "Mahrajganj",
    "Kushi Nagar": "Kushinagar", "Bhadohi": "Sant Ravidas Nagar (Bhadohi)",
}


def viirs(cfg, year: int):
    """VIIRS annual average_masked radiance for `year`, and its native grid."""
    ee = gee.ee_init()
    col = (ee.ImageCollection(gee.viirs_annual_asset(cfg, year))
           .filterDate(f"{year}-01-01", f"{year}-12-31").select("average_masked"))
    proj = col.first().projection()
    return col.mean().unmask(0), (proj, proj.nominalScale().getInfo())


def zonal_sums(img, feats, grid) -> dict[int, float]:
    ee = gee.ee_init()
    proj, scale = grid
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry(mapping(g)), {"uid": int(u)})
                               for u, g in feats])
    res = img.reduceRegions(collection=fc, reducer=ee.Reducer.sum(), crs=proj,
                            scale=scale, tileScale=4).getInfo()
    return {int(f["properties"]["uid"]): f["properties"].get("sum") for f in res["features"]}


def download_region(img, grid, bounds, dest: Path) -> Path:
    """Fetch `img` on its native grid over a lon/lat box (cached)."""
    import requests

    if dest.exists():
        return dest
    ee = gee.ee_init()
    proj, scale = grid
    url = img.reproject(proj).getDownloadURL({
        "region": ee.Geometry.Rectangle(list(bounds), proj="EPSG:4326", geodesic=False),
        "crs": "EPSG:4326", "scale": scale, "format": "GEO_TIFF"})
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def radiance_per_polygon(tif: Path, polys, crs_m: str, res_m: float = 100.0):
    """Mean radiance and radiance x area (km2) for every polygon.

    Villages here are 1-3 km2, only a handful of ~463 m VIIRS pixels each, so
    both layers are laid on a common 100 m grid: VIIRS by nearest neighbour
    (keeping its values), polygons by rasterising their row number.
    """
    g = polys.to_crs(crs_m)
    minx, miny, maxx, maxy = g.total_bounds
    w, h = int(np.ceil((maxx - minx) / res_m)), int(np.ceil((maxy - miny) / res_m))
    transform = from_origin(minx, maxy, res_m, res_m)
    ids = rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)),
                    out_shape=(h, w), transform=transform, fill=0, dtype="int32")
    rad = np.zeros((h, w), dtype="float64")
    with rasterio.open(tif) as ds:
        reproject(source=rasterio.band(ds, 1), destination=rad, dst_transform=transform,
                  dst_crs=crs_m, resampling=Resampling.nearest)
    n = len(g) + 1
    total = np.bincount(ids.ravel(), weights=np.nan_to_num(rad).ravel(), minlength=n)[1:]
    cells = np.bincount(ids.ravel(), minlength=n)[1:]
    cell_km2 = (res_m**2) / 1e6
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(cells > 0, total / cells, np.nan)
    return mean, total * cell_km2, cells * cell_km2


def parse_ddp(path: Path) -> dict[str, float]:
    """District -> Gross District Domestic Product (Rs crore) from a UP DES sheet."""
    df = pd.read_excel(path, header=None)
    names = df.iloc[1]
    label = df.iloc[:, 1].astype(str)
    row = df[label.str.contains("GROSS DISTRICT DOMESTIC PRODUCT", case=False)].iloc[-1]
    out: dict[str, float] = {}
    for j in range(2, df.shape[1]):
        n = names.iloc[j]
        if not isinstance(n, str):
            continue
        n = " ".join(n.split())
        if "region" in n.lower() or n.lower() == "uttar pradesh":
            continue
        out[n] = float(row.iloc[j])
    return out


def stats(x, y) -> dict:
    ll = VAL.loglog_fit(x, y)
    rc = VAL.rank_correlation(x, y)
    return {"n": rc["n"], "spearman_rho": None if rc["rho"] is None else round(rc["rho"], 3),
            "spearman_p": rc["p_value"],
            "elasticity": None if ll["elasticity"] is None else round(ll["elasticity"], 3),
            "elasticity_se": None if ll.get("stderr") is None else round(ll["stderr"], 3),
            "r2_loglog": None if ll["r2"] is None else round(ll["r2"], 3),
            "n_loglog": ll["n"]}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    aoi = AOI(cfg)
    gee.ee_init(cfg.get("sources.gee.project", None))
    out: dict = {}

    # --------------------------------------------- 1. towns and villages, 2013
    d = shrug.district_polygons(cfg).merge(shrug.district_table(cfg),
                                           on=["pc11_state_id", "pc11_district_id"])
    ids = d[d.district_name.str.lower().str.contains("|".join(REGION))].pc11_district_id.tolist()
    shr = shrug.shrids_for_districts(cfg, ids, name="varanasi_region")
    shr = shr[shr.geometry.notna() & ~shr.geometry.is_empty].reset_index(drop=True)
    log.info("%d towns and villages in %d districts", len(shr), len(ids))

    img13, grid = viirs(cfg, 2013)
    b = shr.total_bounds
    tif = download_region(img13, grid, (b[0] - 0.02, b[1] - 0.02, b[2] + 0.02, b[3] + 0.02),
                          cfg.raw_dir / "gee" / "ntl_2013_varanasi_region.tif")
    mean_rad, sol, area = radiance_per_polygon(tif, shr, cfg.crs_projected)
    shr["ntl_mean_2013"], shr["sol_2013"], shr["area_km2"] = mean_rad, sol, area
    emp = shr.ec13_emp_all.astype(float)
    pop = shr.pc11_pca_tot_p.astype(float)
    ok = emp.notna() & pop.notna() & (shr.area_km2 > 0)
    pc = ok & (pop >= 500)
    villages = ok & ~shr.is_town
    out["towns_and_villages_2013"] = {
        "districts": sorted(d[d.pc11_district_id.isin(ids)].district_name.tolist()),
        "n_units": int(ok.sum()), "n_towns": int((ok & shr.is_town).sum()),
        "datasets": ["NOAA/VIIRS/DNB/ANNUAL_V21 (2013, average_masked)",
                     "SHRUG: 2013 Economic Census employment (ec13_emp_all)",
                     "SHRUG: 2011 Population Census (pc11_pca_tot_p)"],
        "lights_vs_employment": stats(shr.sol_2013[ok], emp[ok]),
        "lights_vs_population": stats(shr.sol_2013[ok], pop[ok]),
        "population_vs_employment": stats(pop[ok], emp[ok]),
        "per_person_lights_vs_jobs": stats((shr.sol_2013 / pop)[pc], (emp / pop)[pc]),
        "villages_only_lights_vs_employment": stats(shr.sol_2013[villages], emp[villages]),
        "units_with_zero_lights": int((ok & (shr.sol_2013 <= 0)).sum()),
    }
    shr.drop(columns="geometry").to_csv(cfg.outputs_dir / "validation_economy_shrids.csv",
                                        index=False)

    # -------------------------------------------------- 2. districts of UP
    log.info("district GDP and Economic Census vs Sum of Lights")
    feats = [(u, g.simplify(0.005, preserve_topology=True))
             for u, g in zip(d.pc11_district_id, d.geometry)]
    for y in (2013, 2020, 2021):
        img_y, grid_y = viirs(cfg, y)
        d[f"sol_{y}"] = d.pc11_district_id.map(zonal_sums(img_y, feats, grid_y))

    ghs20 = gee.ee_init().Image("JRC/GHSL/P2023A/GHS_POP/2020").select("population_count")
    gproj = ghs20.projection()
    d["ghs_pop_2020"] = d.pc11_district_id.map(
        zonal_sums(ghs20, feats, (gproj, gproj.nominalScale().getInfo())))

    ddp_dir = cfg.raw_dir / "india" / "updes"
    by_name = {n.lower(): u for n, u in zip(d.district_name, d.pc11_district_id)}
    results, unmatched = {}, set()
    for release, year in (("2020_21", 2020), ("2021_22", 2021)):
        p = ddp_dir / f"{release}_GDDP_Current.xlsx"
        if not p.exists():
            continue
        g = {}
        for name, val in parse_ddp(p).items():
            census_name = DDP_TO_CENSUS.get(name, name)
            uid = by_name.get(census_name.lower())
            if uid is None:
                unmatched.add(name)
                continue
            g[uid] = g.get(uid, 0.0) + val
        col = f"gddp_{release}"
        d[col] = d.pc11_district_id.map(g)
        m = d[col].notna() & d[f"sol_{year}"].notna()
        fit = VAL.loglog_fit(d.loc[m, f"sol_{year}"], d.loc[m, col])
        var = d[d.district_name == "Varanasi"].iloc[0]
        pred = np.exp(fit["intercept"] + fit["elasticity"] * np.log(var[f"sol_{year}"]))
        results[release] = {
            "gddp": "Gross District Domestic Product at current prices (Rs crore)",
            "lights_year": year,
            "levels": stats(d.loc[m, f"sol_{year}"], d.loc[m, col]),
            "per_person": stats((d[f"sol_{year}"] / d.ghs_pop_2020)[m],
                                (d[col] / d.ghs_pop_2020)[m]),
            "varanasi": {"gddp_crore": round(float(var[col]), 1),
                         "predicted_from_lights_crore": round(float(pred), 1),
                         "actual_over_predicted": round(float(var[col] / pred), 2)},
        }
    ec_ok = d.ec13_emp_all.notna() & d.sol_2013.notna()
    out["districts"] = {
        "n": int(len(d)),
        "source": ("District Domestic Product (base year 2011-12), Directorate of Economics "
                   "& Statistics, Government of Uttar Pradesh"),
        "merged_new_districts": "Shamli->Muzaffarnagar, Hapur->Ghaziabad, "
                                "Sambhal->Moradabad, Amethi->Sultanpur (2011 boundaries)",
        "unmatched_names": sorted(unmatched),
        "gddp": results,
        "economic_census_2013_employment": stats(d.sol_2013[ec_ok], d.ec13_emp_all[ec_ok]),
    }
    d.drop(columns="geometry").to_csv(cfg.outputs_dir / "validation_economy_districts.csv",
                                      index=False)

    p = cfg.outputs_dir / f"{aoi.slug}_economy_validation.json"
    p.write_text(json.dumps(out, indent=2, default=float), encoding="utf-8")
    log.info("summary -> %s", p)

    print("\n" + "=" * 70)
    print("NIGHT LIGHTS vs INDIAN ECONOMIC DATA")
    print("=" * 70)
    t = out["towns_and_villages_2013"]
    for k in ("lights_vs_employment", "lights_vs_population", "population_vs_employment",
              "per_person_lights_vs_jobs", "villages_only_lights_vs_employment"):
        s = t[k]
        print(f"  {k:36s} n={s['n']:6d}  rho={s['spearman_rho']}  elasticity={s['elasticity']}")
    for rel, v in results.items():
        s, pp = v["levels"], v["per_person"]
        print(f"  GDDP {rel}: n={s['n']} rho={s['spearman_rho']} elasticity={s['elasticity']} "
              f"R2={s['r2_loglog']} | per person rho={pp['spearman_rho']} | "
              f"Varanasi actual/predicted {v['varanasi']['actual_over_predicted']}")
    s = out["districts"]["economic_census_2013_employment"]
    print(f"  districts EC13 employment: rho={s['spearman_rho']} elasticity={s['elasticity']}")
    if unmatched:
        print(f"  unmatched DDP names: {sorted(unmatched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
