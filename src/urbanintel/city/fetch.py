from __future__ import annotations

import gzip
import io
import json
import logging
import math
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.crs import CRS

from ..aoi import AOI, AnalysisFrame
from ..config import Config
from ..data import gee, landsat
from ..data.osm import POI_GROUPS, ROAD_CLASSES

log = logging.getLogger(__name__)

GHSL_BUILT = "JRC/GHSL/P2023A/GHS_BUILT_S"
GHSL_POP = "JRC/GHSL/P2023A/GHS_POP"
# 1995 is needed for growth momentum (change over the previous five years) at the 2000 stopping period
GHSL_EPOCHS = [1995, 2000, 2005, 2010, 2015, 2020]
LANDSAT_YEARS = [1995, 2000, 2005, 2010, 2015, 2020]
# Candidate dry-season windows (start month in the previous year, end month); one is chosen per city
WINDOWS = {(10, 3): "October-March", (11, 4): "November-April", (12, 5): "December-May"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
WATER_YEAR = 2024
MOLLWEIDE = "ESRI:54009"
GHSL_ORIGIN = (-18041000.0, 9000000.0)
TILE_CELLS = 256
UA = "urbanintel/1.0 (academic urban growth research; VIT capstone)"


class FetchError(RuntimeError):
    pass


class Meter:
    def __init__(self, on_bytes: Callable[[int], None] | None = None):
        self.on_bytes = on_bytes
        self.total = 0
        self.lock = threading.Lock()

    def _add(self, n: int) -> None:
        with self.lock:
            self.total += n
        if self.on_bytes:
            self.on_bytes(n)

    def child(self) -> "Meter":
        return Meter(self._add)

    def fetch(self, url: str, *, method: str = "GET", data=None, params=None,
              timeout: int = 600, attempts: int = 4, retry_on=(429, 500, 502, 503, 504),
              trace: bool = False) -> bytes:
        headers = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                t0 = time.time()
                with requests.request(method, url, data=data, params=params, headers=headers,
                                      stream=True, timeout=timeout) as r:
                    # Wire bytes are counted before decompression, including failed attempts
                    chunks = []
                    for chunk in r.raw.stream(1 << 16, decode_content=False):
                        chunks.append(chunk)
                        self._add(len(chunk))
                    wire = sum(len(c) for c in chunks)
                    body = _decode(b"".join(chunks), r.headers.get("Content-Encoding", ""))
                    if trace:
                        log.info("%s HTTP %d: %.2f MB on the wire (%s), %.2f MB decoded, %.0f s",
                                 url.split("/")[2], r.status_code, wire / 1e6,
                                 r.headers.get("Content-Encoding", "identity"), len(body) / 1e6,
                                 time.time() - t0)
                    if r.status_code in retry_on:
                        raise FetchError(f"HTTP {r.status_code} from {url.split('?')[0]}")
                    if r.status_code >= 400:
                        raise PermanentError(f"HTTP {r.status_code}: {body[:400].decode('utf-8', 'replace')}")
                    return body
            except PermanentError:
                raise
            except (requests.RequestException, FetchError, OSError, zlib.error) as exc:
                last = exc
                if attempt < attempts - 1:
                    time.sleep(5 * (attempt + 1))
        raise FetchError(f"{url.split('?')[0]} failed after {attempts} attempts: {last}")


class PermanentError(FetchError):
    pass


def _decode(body: bytes, encoding: str) -> bytes:
    enc = encoding.lower()
    if "gzip" in enc:
        return gzip.decompress(body)
    if "deflate" in enc:
        return zlib.decompress(body) if body[:1] == b"x" else zlib.decompress(body, -zlib.MAX_WBITS)
    return body


# ---------------------------------------------------------------- Earth Engine


def _grid(frame: AnalysisFrame) -> list[float]:
    return [frame.res, 0.0, frame.minx, 0.0, -frame.res, frame.maxy]


def frame_tiles(frame: AnalysisFrame, size: int = TILE_CELLS) -> list[tuple[int, int, int, int]]:
    out = []
    for r0 in range(0, frame.height, size):
        for c0 in range(0, frame.width, size):
            out.append((r0, c0, min(size, frame.height - r0), min(size, frame.width - c0)))
    return out


def ee_on_frame(img, frame: AnalysisFrame, dest: Path, meter: Meter, *, dtype: str,
                nodata: float | None = None, workers: int = 3) -> Path:
    gee.ee_init()
    arr, count = None, None

    def one(tile):
        r0, c0, h, w = tile
        x0, y0 = frame.minx + c0 * frame.res, frame.maxy - r0 * frame.res
        url = img.getDownloadURL({"crs": frame.crs,
                                  "crs_transform": [frame.res, 0, x0, 0, -frame.res, y0],
                                  "dimensions": f"{w}x{h}", "format": "GEO_TIFF"})
        body = meter.fetch(url)
        with rasterio.MemoryFile(body) as mf, mf.open() as ds:
            if ds.width != w or ds.height != h:
                raise FetchError(f"tile came back {ds.width}x{ds.height}, asked for {w}x{h}")
            data = ds.read()
            nd = ds.nodata
        return tile, data, nd

    tiles = frame_tiles(frame)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(one, t) for t in tiles]):
            (r0, c0, h, w), data, nd = fut.result()
            if count is None:
                count = data.shape[0]
                arr = np.full((count,) + frame.shape, np.nan if nodata is None else nodata,
                              dtype=dtype)
            block = data.astype(dtype)
            if nd is not None and nodata is None:
                block = np.where(data == nd, np.nan, block)
            arr[:, r0:r0 + h, c0:c0 + w] = block
    dest.parent.mkdir(parents=True, exist_ok=True)
    prof = frame.profile(dtype, nodata=(np.nan if nodata is None else nodata), count=count)
    with rasterio.open(dest, "w", **prof) as ds:
        ds.write(arr)
    return dest


def landsat_image(cfg: Config, aoi: AOI, year: int, frame: AnalysisFrame, months=(10, 3), seasons=1):
    ee = gee.ee_init()
    merged, _ = landsat.merged_collection(cfg, aoi, year, months=tuple(months), seasons=seasons)
    # The median is evaluated on a 30 m grid and averaged to the 100 m frame by area, on the server
    comp = merged.median().setDefaultProjection(frame.crs, None, 30)
    return (comp.reduceResolution(ee.Reducer.mean(), maxPixels=1024)
            .reproject(crs=frame.crs, crsTransform=_grid(frame))
            .multiply(10_000).round().toInt16().clip(gee.aoi_geometry(aoi)))


def landsat_depth(cfg: Config, aoi: AOI, year: int, months=(10, 3), seasons=1) -> int:
    ee = gee.ee_init()
    merged, _ = landsat.merged_collection(cfg, aoi, year, months=tuple(months), seasons=seasons)
    return int(merged.aggregate_array("system:time_start")
               .map(lambda t: ee.Number(t).divide(86_400_000).floor())
               .distinct().size().getInfo())


def nightlights_image(cfg: Config, aoi: AOI, year: int, frame: AnalysisFrame):
    return gee.nightlights_image(cfg, aoi, year).reproject(crs=frame.crs, crsTransform=_grid(frame))


def water_image(cfg: Config, aoi: AOI, year: int, frame: AnalysisFrame):
    # Dynamic World probabilities are pyramided by mean, so a 100 m request reads the 80 m level
    img = gee.dynamicworld_image(cfg, aoi, year).select("water")
    return (img.reproject(crs=frame.crs, crsTransform=_grid(frame))
            .multiply(100).round().unmask(255).toUint8())


def slope_image(cfg: Config, aoi: AOI, frame: AnalysisFrame):
    ee = gee.ee_init()
    return (gee.slope_image(cfg, aoi).reduceResolution(ee.Reducer.mean(), maxPixels=1024)
            .reproject(crs=frame.crs, crsTransform=_grid(frame)).toFloat())


def ghsl_window(frame: AnalysisFrame, margin_cells: int = 3) -> tuple[list[float], int, int]:
    # The window must cover the whole analysis frame, which reaches beyond the lon/lat box
    t = Transformer.from_crs(frame.crs, MOLLWEIDE, always_xy=True)
    ex = np.linspace(frame.minx, frame.maxx, 41)
    ey = np.linspace(frame.miny, frame.maxy, 41)
    pts = ([(x, y) for x in ex for y in (frame.miny, frame.maxy)]
           + [(x, y) for y in ey for x in (frame.minx, frame.maxx)])
    xs, ys = zip(*(t.transform(x, y) for x, y in pts))
    ox, oy = GHSL_ORIGIN
    c0 = math.floor((min(xs) - ox) / 100.0) - margin_cells
    c1 = math.ceil((max(xs) - ox) / 100.0) + margin_cells
    r0 = math.floor((oy - max(ys)) / 100.0) - margin_cells
    r1 = math.ceil((oy - min(ys)) / 100.0) + margin_cells
    return [100.0, 0.0, ox + c0 * 100.0, 0.0, -100.0, oy - r0 * 100.0], c1 - c0, r1 - r0


def ghsl_native(asset: str, band: str, epoch: int, frame: AnalysisFrame, dest: Path,
                meter: Meter) -> Path:
    ee = gee.ee_init()
    img = (ee.ImageCollection(asset).filter(ee.Filter.eq("system:index", str(epoch)))
           .first().select(band).unmask(0))
    if band != "built_surface":
        img = img.toFloat()
    wkt = img.projection().getInfo()["wkt"]
    transform, w, h = ghsl_window(frame)
    # Earth Engine cannot write a GeoTIFF in Mollweide, so the native grid comes back as NumPy
    url = img.getDownloadURL({"crs": wkt, "crs_transform": transform,
                              "dimensions": f"{w}x{h}", "format": "NPY"})
    arr = np.load(io.BytesIO(meter.fetch(url)), allow_pickle=False)
    data = np.asarray(arr[arr.dtype.names[0]] if arr.dtype.names else arr, dtype="float32")
    if data.shape != (h, w):
        raise FetchError(f"GHSL window came back {data.shape}, asked for {(h, w)}")
    tr = rasterio.Affine(*transform)
    # Same pixel grid as the JRC bulk tiles, written under the same CRS so ghsl.to_frame treats both alike
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dest, "w", driver="GTiff", width=data.shape[1], height=data.shape[0],
                       count=1, dtype="float32", crs=CRS.from_string(MOLLWEIDE), transform=tr,
                       compress="deflate") as ds:
        ds.write(data, 1)
    return dest


# -------------------------------------------------------------- OpenStreetMap


OVERPASS_LOCK = threading.Lock()
COOLDOWN: dict[str, float] = {}


def wait_for_slot(ep: str, meter: Meter, *, cap: float = 150.0) -> None:
    # Overpass grants each IP a few slots, each with a cool-down; ask the server instead of retrying blind
    if "overpass-api.de" not in ep:
        return
    try:
        text = meter.fetch(ep.replace("/interpreter", "/status"), timeout=20, attempts=1).decode("utf-8", "replace")
    except FetchError:
        return
    if "slots available now" in text and not text.strip().startswith("0 slots"):
        return
    waits = [int(x) for x in re.findall(r"in (\d+) seconds", text)]
    if waits:
        time.sleep(min(cap, min(waits) + 2))


def overpass(cfg: Config, query: str, meter: Meter, *, rounds: int = 4) -> dict:
    last: Exception | None = None
    with OVERPASS_LOCK:
        for rnd in range(rounds):
            for ep in cfg.get("sources.osm.overpass_endpoints"):
                if COOLDOWN.get(ep, 0) > time.time():
                    continue
                try:
                    wait_for_slot(ep, meter)
                    body = meter.fetch(ep, method="POST", data={"data": query}, timeout=420, attempts=1,
                                       trace=True)
                    payload = json.loads(body)
                    if "elements" not in payload:
                        raise FetchError(f"unexpected Overpass response from {ep}")
                    if payload.get("remark") and "error" in payload["remark"].lower():
                        raise FetchError(payload["remark"][:200])
                    return payload
                except (FetchError, json.JSONDecodeError) as exc:
                    last = exc
                    if "SSL" in str(exc) or "Connection" in str(exc) or "429" in str(exc):
                        COOLDOWN[ep] = time.time() + 90
                    log.warning("overpass %s: %s", ep.split("/")[2], str(exc)[:120])
            time.sleep(30 * (rnd + 1))
    raise FetchError(f"all Overpass endpoints failed: {last}")


def bbox_tiles(bbox: tuple[float, float, float, float], n: int) -> list[tuple[float, float, float, float]]:
    lon0, lat0, lon1, lat1 = bbox
    xs, ys = np.linspace(lon0, lon1, n + 1), np.linspace(lat0, lat1, n + 1)
    return [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(n) for j in range(n)]


def _ov_bbox(b) -> str:
    return f"{b[1]:.6f},{b[0]:.6f},{b[3]:.6f},{b[2]:.6f}"


def osm_tiling(aoi: AOI) -> int:
    return 1 if aoi.area_km2() <= 1500 else (2 if aoi.area_km2() <= 4500 else 3)


HEAVY_CLASSES = ["residential", "unclassified", "service"]
MAJOR = [c for c in ROAD_CLASSES if c not in HEAVY_CLASSES]


def road_queries(aoi: AOI) -> list[tuple[str, tuple]]:
    out = [("|".join(MAJOR), aoi.bbox_ll)]
    for cls in HEAVY_CLASSES:
        out += [(cls, b) for b in bbox_tiles(aoi.bbox_ll, osm_tiling(aoi))]
    return out


def fetch_roads(cfg: Config, aoi: AOI, meter: Meter, *, on_step: Callable[[str], None] | None = None) -> dict:
    seen: dict[int, dict] = {}
    for cls, b in road_queries(aoi):
        if "|" in cls:
            # Arterial classes are few, so one query with tags is cheaper than five without
            q = f'[out:json][timeout:400];way["highway"~"^({cls})$"]({_ov_bbox(b)});out tags geom qt;'
        else:
            q = f'[out:json][timeout:400];way["highway"="{cls}"]({_ov_bbox(b)});out skel geom qt;'
        payload = overpass(cfg, q, meter)
        for el in payload["elements"]:
            geom = el.get("geometry")
            if el.get("type") != "way" or not geom or len(geom) < 2:
                continue
            hw = el.get("tags", {}).get("highway", cls)
            seen[el["id"]] = {"highway": hw, "coords": [(p["lon"], p["lat"]) for p in geom]}
        if on_step:
            on_step(f"roads: {cls.split('|')[0] if '|' not in cls else 'arterial'} ({len(seen):,} ways so far)")
    return {"features": list(seen.values())}


def fetch_pois(cfg: Config, aoi: AOI, meter: Meter, *, on_step: Callable[[str], None] | None = None) -> dict:
    out: dict[str, list] = {}
    bb = _ov_bbox(aoi.bbox_ll)
    for group, selectors in POI_GROUPS.items():
        body = "".join(f"{sel}({bb});" for sel in selectors)
        payload = overpass(cfg, f"[out:json][timeout:300];({body});out skel center qt;", meter)
        pts = []
        for el in payload["elements"]:
            if el.get("type") == "node" and "lat" in el:
                pts.append((el["lon"], el["lat"]))
            elif "center" in el:
                pts.append((el["center"]["lon"], el["center"]["lat"]))
        out[group] = pts
        if on_step:
            on_step(f"POIs: {group} ({len(pts):,})")
        time.sleep(1.0)
    return out




# --------------------------------------------------------- availability + plan


@dataclass
class Item:
    key: str
    label: str
    dataset: str
    group: str
    est_bytes: int
    dest: Path
    essential: bool
    run: Callable[[Meter], None] = field(repr=False, default=None)
    actual_bytes: int | None = None

    def cached(self) -> bool:
        return self.dest.exists() and self.dest.stat().st_size > 0


def viirs_years(cfg: Config) -> list[int]:
    ee = gee.ee_init()
    cut = int(cfg.get("sources.gee.assets.viirs_annual_legacy_last_year", 2021))
    years: set[int] = set()
    for key, keep in (("viirs_annual_legacy", lambda y: y <= cut),
                      ("viirs_annual", lambda y: y > cut)):
        asset = cfg.get(f"sources.gee.assets.{key}", None)
        if asset:
            starts = ee.ImageCollection(asset).aggregate_array("system:time_start").getInfo()
            years |= {y for y in (time.gmtime(t / 1000).tm_year for t in starts) if keep(y)}
    return sorted(y for y in years if y >= 2013)


OHSOME = "https://api.ohsome.org/v1/elements/count"
OHSOME_POI = ("shop=* or office=* or amenity in (marketplace, restaurant, cafe, fast_food, bar, food_court, "
              "bank, atm, bureau_de_change, hospital, clinic, doctors, pharmacy, school, college, "
              "university, fuel, bus_station, taxi) or tourism in (hotel, guest_house, hostel) or "
              "landuse=industrial or industrial=* or man_made=works or railway in (station, halt) or "
              "public_transport=station")
DEFAULT_BYTES_PER_WAY = 90.0


def osm_counts(cfg: Config, aoi: AOI, meter: Meter) -> dict:
    # ohsome (HeiGIT) answers counts in seconds, so the estimate does not depend on a busy Overpass server
    bb = ",".join(f"{v:.5f}" for v in aoi.bbox_ll)
    roads = f"type:way and highway in ({', '.join(ROAD_CLASSES)})"
    try:
        out = {}
        for key, flt in (("road_ways", roads), ("pois", OHSOME_POI)):
            body = meter.fetch(OHSOME, method="POST", data={"bboxes": bb, "filter": flt}, timeout=180,
                               attempts=2)
            out[key] = int(json.loads(body)["result"][0]["value"])
        out["source"] = "ohsome API (HeiGIT)"
        return out
    except (FetchError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("ohsome counts failed (%s); asking Overpass", str(exc)[:100])
    ob = _ov_bbox(aoi.bbox_ll)
    classes = "|".join(ROAD_CLASSES)
    payload = overpass(cfg, f'[out:json][timeout:300];way["highway"~"^({classes})$"]({ob});out count;', meter)
    c = [e["tags"] for e in payload["elements"] if e.get("type") == "count"]
    poi_body = "".join(f"{sel}({ob});" for sels in POI_GROUPS.values() for sel in sels)
    p = overpass(cfg, f"[out:json][timeout:300];({poi_body});out count;", meter)
    pc = [e["tags"] for e in p["elements"] if e.get("type") == "count"]
    return {"road_ways": int(c[0]["ways"]), "pois": int(pc[0]["total"]) if pc else 0,
            "source": "Overpass API"}


def overpass_sample(cfg: Config, aoi: AOI, meter: Meter) -> dict:
    lon, lat = aoi.cfg.centre
    d = 0.01
    bb = _ov_bbox((lon - d, lat - d, lon + d, lat + d))
    classes = "|".join(ROAD_CLASSES)
    before = meter.total
    try:
        payload = overpass(cfg, f'[out:json][timeout:60];way["highway"~"^({classes})$"]({bb});'
                                f'out skel geom qt;', meter, rounds=1)
    except FetchError:
        return {"bytes_per_way": DEFAULT_BYTES_PER_WAY, "source": "default (Overpass busy)"}
    n = len(payload["elements"])
    return {"ways": n, "wire_bytes": meter.total - before, "source": "measured",
            "bytes_per_way": max(DEFAULT_BYTES_PER_WAY * 0.5, (meter.total - before) / max(n, 1))}


def availability(cfg: Config, aoi: AOI, meter: Meter, *,
                 on_step: Callable[[str], None] | None = None) -> dict:
    step = on_step or (lambda m: None)
    gee.ee_init(cfg.get("sources.gee.project", None))
    floor = int(cfg.get("sources.gee.min_composite_dates_landsat", 4))
    out: dict = {"min_landsat_dates": floor}
    depth: dict[tuple, dict[int, int]] = {w: {} for w in WINDOWS}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(landsat_depth, cfg, aoi, y, w): (w, y) for w in WINDOWS for y in LANDSAT_YEARS}
        for fut in as_completed(futs):
            w, y = futs[fut]
            try:
                depth[w][y] = fut.result()
            except Exception as exc:  # noqa: BLE001
                depth[w][y] = 0
                log.warning("Landsat %d (%s) search failed: %s", y, WINDOWS[w], exc)
            step(f"Landsat {y}, {WINDOWS[w]}: {depth[w][y]} clear acquisition dates")
    # One window for every year keeps a city's composites comparable: most years above the floor, then deepest worst year
    best = max(WINDOWS, key=lambda w: (sum(d >= floor for d in depth[w].values()),
                                       min(depth[w].values()), w == (10, 3)))
    out["landsat_window"] = list(best)
    out["landsat_window_name"] = WINDOWS[best]
    out["landsat"] = dict(sorted(depth[best].items()))
    out["landsat_by_window"] = {WINDOWS[w]: dict(sorted(d.items())) for w, d in depth.items()}
    step(f"Landsat window chosen: {WINDOWS[best]} (clear dates per year {out['landsat']})")
    # A year below the floor combines two consecutive dry seasons of the same window
    out["landsat_seasons"] = {y: 1 for y in out["landsat"]}
    for y, d in list(out["landsat"].items()):
        if d < floor:
            d2 = landsat_depth(cfg, aoi, y, best, seasons=2)
            step(f"Landsat {y}: {d} clear dates in one dry season, {d2} in two")
            if d2 >= floor:
                out["landsat"][y], out["landsat_seasons"][y] = d2, 2
    out["viirs_years"] = viirs_years(cfg)
    step(f"VIIRS annual composites: {out['viirs_years'][0]}-{out['viirs_years'][-1]}")
    ee = gee.ee_init()
    out["dw_images"] = int(ee.ImageCollection(cfg.get("sources.gee.assets.dynamic_world"))
                           .filterDate(f"{WATER_YEAR}-01-01", f"{WATER_YEAR}-12-31")
                           .filterBounds(gee.aoi_geometry(aoi)).size().getInfo())
    step(f"Dynamic World {WATER_YEAR}: {out['dw_images']} images")
    out["osm"] = osm_counts(cfg, aoi, meter)
    step(f"OpenStreetMap: {out['osm']['road_ways']:,} road ways, {out['osm']['pois']:,} POIs")
    out["osm_sample"] = overpass_sample(cfg, aoi, meter)
    return out


def landsat_dataset(year: int) -> str:
    if year <= 2011:
        return "LANDSAT/LT05/C02/T1_L2" + (" + LANDSAT/LE07/C02/T1_L2" if year >= 1999 else "")
    return "LANDSAT/LC08/C02/T1_L2" + (" + LANDSAT/LC09/C02/T1_L2" if year >= 2022 else "")


def plan(cfg: Config, aoi: AOI, fine: AnalysisFrame, avail: dict) -> list[Item]:
    raw = cfg.raw_dir
    gdir, hdir, odir = raw / "gee", raw / "ghsl_ee", raw / "osm"
    cells = fine.width * fine.height
    _, gw, gh = ghsl_window(fine)
    items: list[Item] = []
    for y in GHSL_EPOCHS:
        items.append(Item(f"ghsl_built_{y}", f"GHS-BUILT-S {y}", "JRC/GHSL/P2023A/GHS_BUILT_S",
                          "GHSL built-up surface", gw * gh * 2 + 200, hdir / f"built_{y}.tif",
                          True,
                          lambda m, y=y: ghsl_native(GHSL_BUILT, "built_surface", y, fine,
                                                     hdir / f"built_{y}.tif", m)))
        items.append(Item(f"ghsl_pop_{y}", f"GHS-POP {y}", "JRC/GHSL/P2023A/GHS_POP",
                          "GHSL population", gw * gh * 4 + 200, hdir / f"pop_{y}.tif", True,
                          lambda m, y=y: ghsl_native(GHSL_POP, "population_count", y, fine,
                                                     hdir / f"pop_{y}.tif", m)))
    floor = avail["min_landsat_dates"]
    win = tuple(avail.get("landsat_window", (10, 3)))
    for y, depth in avail["landsat"].items():
        y = int(y)
        if depth < floor:
            continue
        ns = int(avail.get("landsat_seasons", {}).get(y, avail.get("landsat_seasons", {}).get(str(y), 1)))
        span = f"{MONTHS[win[0] - 1]} {y - ns}-{MONTHS[win[1] - 1]} {y}" + (" (two dry seasons)" if ns > 1 else "")
        items.append(Item(f"landsat_{y}", f"Landsat composite {span}",
                          " + ".join(dict.fromkeys(landsat_dataset(y - k) for k in range(ns))),
                          "Landsat surface reflectance", int(BYTES_PER_CELL["landsat"] * cells),
                          gdir / f"landsat_{y}.tif", y in (2000, 2005, 2010, 2015, 2020),
                          lambda m, y=y, ns=ns: ee_on_frame(landsat_image(cfg, aoi, y, fine, win, ns), fine,
                                                     gdir / f"landsat_{y}.tif", m,
                                                     dtype="float32")))
    for y in avail["viirs_years"]:
        items.append(Item(f"ntl_{y}", f"VIIRS night lights {y}", gee.viirs_annual_asset(cfg, y),
                          "VIIRS night-time lights", int(BYTES_PER_CELL["viirs"] * cells),
                          gdir / f"ntl_{y}.tif", False,
                          lambda m, y=y: ee_on_frame(nightlights_image(cfg, aoi, y, fine), fine,
                                                     gdir / f"ntl_{y}.tif", m, dtype="float32")))
    items.append(Item("dw_water", f"Dynamic World water {WATER_YEAR}", "GOOGLE/DYNAMICWORLD/V1",
                      "Water", int(BYTES_PER_CELL["water"] * cells), gdir / f"dw_water_{WATER_YEAR}.tif",
                      True, lambda m: ee_on_frame(water_image(cfg, aoi, WATER_YEAR, fine), fine,
                                                  gdir / f"dw_water_{WATER_YEAR}.tif", m,
                                                  dtype="uint8", nodata=255)))
    items.append(Item("slope", "Terrain slope", "USGS/SRTMGL1_003", "Terrain",
                      int(BYTES_PER_CELL["slope"] * cells), gdir / "slope.tif", True,
                      lambda m: ee_on_frame(slope_image(cfg, aoi, fine), fine, gdir / "slope.tif",
                                            m, dtype="float32")))
    osm_c, sample = avail["osm"], avail["osm_sample"]
    # The calibration sample is the dense centre, so bytes per way there is an upper-end figure
    per_way = sample["bytes_per_way"] * 1.15
    items.append(Item("osm_roads", "Road network (8 classes)", "OpenStreetMap via Overpass API",
                      "OpenStreetMap", int(osm_c["road_ways"] * per_way), odir / "roads.json",
                      True, lambda m: _write_json(odir / "roads.json", fetch_roads(cfg, aoi, m))))
    items.append(Item("osm_pois", "Points of interest (6 groups)", "OpenStreetMap via Overpass API",
                      "OpenStreetMap", int(osm_c["pois"] * 60 + 3000), odir / "pois.json", False,
                      lambda m: _write_json(odir / "pois.json", fetch_pois(cfg, aoi, m))))
    return items


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    tmp.replace(path)


def estimate(items: list[Item], *, news_articles: int = 0) -> dict:
    rows: dict[str, dict] = {}
    for it in items:
        r = rows.setdefault(it.group, {"group": it.group, "dataset": it.dataset, "items": 0,
                                       "bytes": 0, "cached": 0})
        for d in it.dataset.split(" + "):
            if d not in r["dataset"].split(" + "):
                r["dataset"] += f" + {d}"
        r["items"] += 1
        if it.cached():
            r["cached"] += 1
        else:
            r["bytes"] += it.est_bytes + EE_OVERHEAD
    out = list(rows.values())
    if news_articles:
        out.append({"group": "News headlines", "dataset": "Google News RSS + GDELT DOC 2.0 API",
                    "items": 1, "bytes": NEWS_BYTES, "cached": 0})
        out.append({"group": "LLM requests", "dataset": "news extraction (text only)",
                    "items": news_articles, "bytes": news_articles * LLM_BYTES_PER_ARTICLE,
                    "cached": 0})
    return {"rows": out, "total_bytes": int(sum(r["bytes"] for r in out)),
            "downloads": len(items), "cached": sum(r["cached"] for r in out)}


def execute(items: list[Item], meter: Meter, *, workers: int = 3,
            on_done: Callable[[Item, str | None], None] | None = None) -> dict[str, str]:
    failed: dict[str, str] = {}
    todo = [it for it in items if not it.cached()]
    for it in items:
        if it.cached() and on_done:
            on_done(it, None)

    def go(it: Item):
        sub = meter.child()
        try:
            it.run(sub)
        finally:
            it.actual_bytes = sub.total
        return it

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(go, it): it for it in todo}
        for fut in as_completed(futs):
            it = futs[fut]
            err = None
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                err = str(exc).splitlines()[0][:300]
                failed[it.key] = err
                log.warning("%s failed: %s", it.label, err)
            if on_done:
                on_done(it, err)
    return failed


# Measured on the Varanasi frame: bytes per 100 m cell of each deflate-compressed GeoTIFF
BYTES_PER_CELL = {"landsat": 9.2, "viirs": 0.6, "water": 0.6, "slope": 3.0}
EE_OVERHEAD = 6_000
NEWS_BYTES = 3_000_000
LLM_BYTES_PER_ARTICLE = 4_000
