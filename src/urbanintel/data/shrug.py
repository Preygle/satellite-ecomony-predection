"""SHRUG — Indian census and economic-census data by town and village.

SHRUG (the Socioeconomic High-resolution Rural-Urban Geographic Platform for
India, from the Development Data Lab) links the Population Census, the
Economic Census and other sources to one set of town and village identifiers,
called *shrids*. Four parts of it are used here:

* 2011 Population Census Abstract — population per town/village and district
* 2013 Economic Census (the 6th Economic Census, MoSPI) — non-farm
  establishments and employment per town/village and district
* shrid location names — state, district, sub-district, town and village
* open polygons — shrid and 2011 district boundaries (EPSG:4326)

Data: https://www.devdatalab.org/shrug, CC BY-NC-SA 4.0. Cite Asher, Lunt,
Matsuura & Novosad (2021), *The World Bank Economic Review* 35(4). The files
are downloaded by ``scripts/fetch_indian_data.py`` into
``data/raw/india/shrug/``.

A shrid2 code reads ``11-SS-DDD-TTTTT-VVVVVV``: census year (2011), then the
2011 Census codes for state, district, sub-district and town or village.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd

from ..config import Config

log = logging.getLogger(__name__)

UP_STATE_ID = 9          # Uttar Pradesh in the 2011 Census


def shrug_dir(cfg: Config) -> Path:
    return cfg.raw_dir / "india" / "shrug"


def _zip(cfg: Config, name: str) -> Path:
    p = shrug_dir(cfg) / name
    if not p.exists():
        raise FileNotFoundError(f"{p} is missing — run scripts/fetch_indian_data.py first")
    return p


def read_csv(cfg: Config, zip_name: str, member: str, *, usecols=None,
             keep=None, chunksize: int = 250_000) -> pd.DataFrame:
    """Read one CSV out of a SHRUG archive, optionally keeping only some rows.

    `keep` is a function chunk -> boolean Series. The shrid-level tables run
    to hundreds of MB for all of India, so they are filtered chunk by chunk
    rather than loaded whole.
    """
    with zipfile.ZipFile(_zip(cfg, zip_name)) as z, z.open(member) as fh:
        if keep is None:
            return pd.read_csv(fh, usecols=usecols)
        parts = [c[keep(c)] for c in pd.read_csv(fh, usecols=usecols, chunksize=chunksize)]
    return pd.concat(parts, ignore_index=True)


def district_polygons(cfg: Config, state_id: int = UP_STATE_ID):
    """2011 Census district boundaries for one state, as a GeoDataFrame."""
    import geopandas as gpd

    gp = shrug_dir(cfg) / "district.gpkg"
    if not gp.exists():
        with zipfile.ZipFile(_zip(cfg, "shrug-pc11dist-poly-gpkg.zip")) as z:
            z.extract("district.gpkg", shrug_dir(cfg))
    g = gpd.read_file(gp)
    g["pc11_state_id"] = g["pc11_state_id"].astype(int)
    g["pc11_district_id"] = g["pc11_district_id"].astype(int)
    return g[g["pc11_state_id"] == state_id].reset_index(drop=True)


def district_table(cfg: Config, state_id: int = UP_STATE_ID) -> pd.DataFrame:
    """Census 2011 population and Economic Census 2013 employment per district."""
    key = ["pc11_state_id", "pc11_district_id"]
    pca = read_csv(cfg, "shrug-pca11-csv.zip", "pc11_pca_clean_pc11dist.csv",
                   usecols=key + ["pc11_pca_tot_p", "pc11_pca_tot_work_p"])
    ec = read_csv(cfg, "shrug-ec13-csv.zip", "ec13_pc11dist.csv",
                  usecols=key + ["ec13_emp_all", "ec13_count_all"])
    pca, ec = pca[pca.pc11_state_id == state_id], ec[ec.pc11_state_id == state_id]
    return pca.merge(ec, on=key, how="left").reset_index(drop=True)


def in_districts(state_id: int, district_ids: set[int]):
    """Row filter for `read_csv`: shrids whose 2011 district code is in `district_ids`."""
    prefix = f"11-{state_id:02d}-"

    def keep(chunk: pd.DataFrame) -> pd.Series:
        s = chunk["shrid2"].astype(str)
        dist = pd.to_numeric(s.str.slice(6, 9), errors="coerce")
        return s.str.startswith(prefix) & dist.isin(district_ids)
    return keep


def shrids_for_districts(cfg: Config, district_ids, *, name: str,
                         state_id: int = UP_STATE_ID):
    """Town and village polygons with names, 2011 population and 2013 employment.

    The result is cached as ``data/raw/india/shrug/cache/<name>.gpkg``. Building
    it needs the all-India shrid polygon file (about 0.9 GB unpacked); that is
    unpacked, read for the districts' bounding box only, and deleted again.
    """
    import geopandas as gpd

    cache = shrug_dir(cfg) / "cache" / f"{name}.gpkg"
    if cache.exists():
        return gpd.read_file(cache)

    ids = {int(i) for i in district_ids}
    keep = in_districts(state_id, ids)
    log.info("reading SHRUG tables for %d districts", len(ids))
    names = read_csv(cfg, "shrug-shrid-keys-csv.zip", "shrid_loc_names.csv",
                     usecols=["shrid2", "district_name", "subdistrict_name",
                              "town_name", "village_name", "place_name"], keep=keep)
    pca = read_csv(cfg, "shrug-pca11-csv.zip", "pc11_pca_clean_shrid.csv",
                   usecols=["shrid2", "pc11_pca_tot_p", "pc11_pca_tot_work_p"], keep=keep)
    ec = read_csv(cfg, "shrug-ec13-csv.zip", "ec13_shrid.csv",
                  usecols=["shrid2", "ec13_emp_all", "ec13_count_all",
                           "ec13_emp_manuf", "ec13_emp_services"], keep=keep)

    bounds = district_polygons(cfg, state_id)
    bounds = bounds[bounds.pc11_district_id.isin(ids)].total_bounds
    tmp = shrug_dir(cfg) / "_unpacked"
    gp = tmp / "shrid2_open.gpkg"
    if not gp.exists():
        log.info("unpacking shrid polygons (temporary)")
        with zipfile.ZipFile(_zip(cfg, "shrug-shrid-poly-gpkg.zip")) as z:
            z.extract("shrid2_open.gpkg", tmp)
    try:
        poly = gpd.read_file(gp, bbox=tuple(bounds))
    finally:
        gp.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass
    poly = poly[keep(poly)][["shrid2", "geometry"]]

    out = (poly.merge(names, on="shrid2", how="left")
               .merge(pca, on="shrid2", how="left")
               .merge(ec, on="shrid2", how="left"))
    out["pc11_district_id"] = pd.to_numeric(out["shrid2"].str.slice(6, 9), errors="coerce")
    out["is_town"] = out["town_name"].notna()
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(cache, driver="GPKG")
    log.info("cached %d shrids -> %s", len(out), cache)
    return out
