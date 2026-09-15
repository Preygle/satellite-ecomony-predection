from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import requests

from ..aoi import AOI, AnalysisFrame
from ..config import Config

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Tag taxonomy
# --------------------------------------------------------------------------
# Grouped so the dashboard can show *which kind* of activity a zone has,
# not merely how much.
POI_GROUPS: dict[str, list[str]] = {
    "retail": [
        'node["shop"]', 'way["shop"]',
        'node["amenity"="marketplace"]', 'way["amenity"="marketplace"]',
    ],
    "food_hospitality": [
        'node["amenity"~"^(restaurant|cafe|fast_food|bar|food_court)$"]',
        'node["tourism"~"^(hotel|guest_house|hostel)$"]',
        'way["tourism"~"^(hotel|guest_house|hostel)$"]',
    ],
    "finance_office": [
        'node["amenity"~"^(bank|atm|bureau_de_change)$"]',
        'node["office"]', 'way["office"]',
    ],
    "health_education": [
        'node["amenity"~"^(hospital|clinic|doctors|pharmacy|school|college|university)$"]',
        'way["amenity"~"^(hospital|clinic|school|college|university)$"]',
    ],
    "industrial": [
        'way["landuse"="industrial"]',
        'node["industrial"]', 'way["industrial"]',
        'way["man_made"="works"]',
    ],
    "transport": [
        'node["amenity"~"^(fuel|bus_station|taxi)$"]',
        'node["railway"~"^(station|halt)$"]',
        'node["public_transport"="station"]',
    ],
}

# Road classes, ordered by significance for infrastructure-led growth.
ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "service",
]
# Weight used when building a single "arterial road density" layer.
ROAD_WEIGHTS = {
    "motorway": 5.0, "trunk": 4.0, "primary": 3.0, "secondary": 2.0,
    "tertiary": 1.5, "residential": 0.5, "unclassified": 0.5, "service": 0.25,
}


class OverpassError(RuntimeError):
    pass


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    """Overpass wants (south, west, north, east)."""
    lon0, lat0, lon1, lat1 = bbox
    return f"{lat0},{lon0},{lat1},{lon1}"


def _run_query(cfg: Config, query: str, *, retries: int = 2) -> dict:
    """Execute an Overpass QL query, rotating endpoints on failure.

    Overpass instances routinely return 429/504 under load and reject
    requests without a User-Agent, so both are handled explicitly.
    """
    endpoints = cfg.get("sources.osm.overpass_endpoints")
    ua = cfg.get("sources.osm.user_agent")
    timeout = cfg.get("sources.osm.timeout_s")
    last: Exception | None = None

    for attempt in range(retries + 1):
        for ep in endpoints:
            try:
                log.info("overpass: %s (attempt %d)", ep, attempt + 1)
                r = requests.post(
                    ep, data={"data": query},
                    headers={"User-Agent": ua}, timeout=timeout,
                )
                if r.status_code in (429, 504, 503):
                    log.warning("  %s busy (%s)", ep, r.status_code)
                    last = OverpassError(f"{ep} returned {r.status_code}")
                    continue
                r.raise_for_status()
                payload = r.json()
                if "elements" not in payload:
                    raise OverpassError(f"unexpected response shape from {ep}")
                return payload
            except (requests.RequestException, json.JSONDecodeError, OverpassError) as exc:
                last = exc
                log.warning("  %s failed: %s", ep, exc)
        if attempt < retries:
            wait = 10 * (attempt + 1)
            log.info("  all endpoints failed; backing off %ds", wait)
            time.sleep(wait)

    raise OverpassError(f"all Overpass endpoints failed: {last}")


# --------------------------------------------------------------------------
# POIs
# --------------------------------------------------------------------------

def fetch_pois(cfg: Config, *, force: bool = False) -> dict[str, list[tuple[float, float]]]:
    """Fetch POIs by group. Returns {group: [(lon, lat), ...]}. Cached to disk."""
    cache = cfg.raw_dir / "osm" / "pois.json"
    if cache.exists() and not force:
        log.info("cached: %s", cache.name)
        return json.loads(cache.read_text(encoding="utf-8"))

    bbox = _bbox_str(cfg.bbox)
    out: dict[str, list[tuple[float, float]]] = {}

    for group, selectors in POI_GROUPS.items():
        body = "".join(f"{sel}({bbox});" for sel in selectors)
        query = f"[out:json][timeout:120];({body});out center;"
        payload = _run_query(cfg, query)

        pts: list[tuple[float, float]] = []
        for el in payload["elements"]:
            if el.get("type") == "node" and "lat" in el:
                pts.append((el["lon"], el["lat"]))
            elif "center" in el:  # ways/relations returned via `out center`
                pts.append((el["center"]["lon"], el["center"]["lat"]))
        out[group] = pts
        log.info("  %-18s %5d POIs", group, len(pts))
        time.sleep(2)  # be polite to the public endpoint

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Roads
# --------------------------------------------------------------------------

def fetch_roads(cfg: Config, *, force: bool = False) -> dict:
    """Fetch road centrelines as a GeoJSON-like dict of LineStrings by class."""
    cache = cfg.raw_dir / "osm" / "roads.json"
    if cache.exists() and not force:
        log.info("cached: %s", cache.name)
        return json.loads(cache.read_text(encoding="utf-8"))

    bbox = _bbox_str(cfg.bbox)
    classes = "|".join(ROAD_CLASSES)
    query = (
        f'[out:json][timeout:180];'
        f'way["highway"~"^({classes})$"]({bbox});'
        f'out geom;'
    )
    payload = _run_query(cfg, query)

    feats = []
    for el in payload["elements"]:
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        feats.append({
            "highway": el.get("tags", {}).get("highway", "unclassified"),
            "coords": [(p["lon"], p["lat"]) for p in geom],
        })
    log.info("  roads: %d ways", len(feats))

    out = {"features": feats}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Rasterisation onto the analysis frame
# --------------------------------------------------------------------------

def poi_density(
    aoi: AOI, pois: dict[str, list[tuple[float, float]]], frame: AnalysisFrame,
    *, groups: list[str] | None = None,
) -> np.ndarray:
    """Count POIs per analysis cell.

    Points are binned by projected coordinate rather than rasterised via
    geopandas — a plain 2-D histogram is exact here and far faster.
    """
    groups = groups or list(pois.keys())
    xs: list[float] = []
    ys: list[float] = []
    for g in groups:
        for lon, lat in pois.get(g, []):
            x, y = aoi.to_metres(lon, lat)
            xs.append(x)
            ys.append(y)

    counts = np.zeros(frame.shape, dtype="float32")
    if not xs:
        return counts

    cols = ((np.asarray(xs) - frame.minx) / frame.res).astype(int)
    rows = ((frame.maxy - np.asarray(ys)) / frame.res).astype(int)
    inside = (rows >= 0) & (rows < frame.height) & (cols >= 0) & (cols < frame.width)
    np.add.at(counts, (rows[inside], cols[inside]), 1.0)
    return counts


def road_density(
    aoi: AOI, roads: dict, frame: AnalysisFrame, *, weighted: bool = True,
) -> np.ndarray:
    """Metres of road centreline per cell (optionally weighted by class).

    Each segment is sampled at ~half the cell size so a long segment
    crossing several cells contributes to each of them proportionally.
    """
    out = np.zeros(frame.shape, dtype="float32")
    step = frame.res / 2.0

    for feat in roads.get("features", []):
        w = ROAD_WEIGHTS.get(feat["highway"], 0.5) if weighted else 1.0
        pts = [aoi.to_metres(lon, lat) for lon, lat in feat["coords"]]
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            seg = float(np.hypot(x1 - x0, y1 - y0))
            if seg <= 0:
                continue
            n = max(1, int(np.ceil(seg / step)))
            # Midpoint of each sub-segment carries that sub-segment's length.
            ts = (np.arange(n) + 0.5) / n
            sx = x0 + (x1 - x0) * ts
            sy = y0 + (y1 - y0) * ts
            cols = ((sx - frame.minx) / frame.res).astype(int)
            rows = ((frame.maxy - sy) / frame.res).astype(int)
            ok = (rows >= 0) & (rows < frame.height) & (cols >= 0) & (cols < frame.width)
            if ok.any():
                np.add.at(out, (rows[ok], cols[ok]), (seg / n) * w)
    return out
