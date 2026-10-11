from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
import yaml

from ..config import DEFAULT_CONFIG, REPO_ROOT

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "urbanintel/1.0 (academic urban growth research; VIT capstone)"

CITIES_ROOT = REPO_ROOT / "data" / "cities"

# Curated list of large Indian urban areas; each name is resolved against OpenStreetMap at run time
CITIES: dict[str, str] = {
    "Delhi": "Delhi, India",
    "Mumbai": "Mumbai, Maharashtra, India",
    "Bengaluru": "Bengaluru, Karnataka, India",
    "Hyderabad": "Hyderabad, Telangana, India",
    "Chennai": "Chennai, Tamil Nadu, India",
    "Kolkata": "Kolkata, West Bengal, India",
    "Pune": "Pune, Maharashtra, India",
    "Ahmedabad": "Ahmedabad, Gujarat, India",
    "Surat": "Surat, Gujarat, India",
    "Jaipur": "Jaipur, Rajasthan, India",
    "Lucknow": "Lucknow, Uttar Pradesh, India",
    "Kanpur": "Kanpur, Uttar Pradesh, India",
    "Nagpur": "Nagpur, Maharashtra, India",
    "Indore": "Indore, Madhya Pradesh, India",
    "Bhopal": "Bhopal, Madhya Pradesh, India",
    "Patna": "Patna, Bihar, India",
    "Varanasi": "Varanasi, Uttar Pradesh, India",
    "Chandigarh": "Chandigarh, India",
    "Kochi": "Kochi, Kerala, India",
    "Coimbatore": "Coimbatore, Tamil Nadu, India",
    "Visakhapatnam": "Visakhapatnam, Andhra Pradesh, India",
    "Bhubaneswar": "Bhubaneswar, Odisha, India",
    "Guwahati": "Guwahati, Assam, India",
    "Noida": "Noida, Uttar Pradesh, India",
    "Gurugram": "Gurugram, Haryana, India",
}

# Mirrors that answered in testing; two others only returned 500 or held a request for minutes
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://z.overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://lz4.overpass-api.de/api/interpreter"]
URBAN_TYPES = {"city", "town", "municipality", "state", "state_district", "county",
               "city_district", "district"}
MIN_AREA_KM2 = 20.0
MAX_SIDE_KM = 80.0


class CityError(RuntimeError):
    pass


@dataclass(frozen=True)
class City:
    name: str
    display: str
    lon: float
    lat: float
    boundary: tuple[float, float, float, float]
    osm: str
    kind: str

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")

    @property
    def utm_epsg(self) -> int:
        zone = int(math.floor((self.lon + 180.0) / 6.0)) + 1
        return (32600 if self.lat >= 0 else 32700) + zone

    def side_km(self) -> tuple[float, float]:
        lon0, lat0, lon1, lat1 = self.boundary
        return (_km_lon(lon1 - lon0, self.lat), (lat1 - lat0) * 111.32)

    def buffer_km(self) -> float:
        return float(min(8.0, max(3.0, 0.15 * max(self.side_km()))))

    def aoi_bbox(self) -> tuple[float, float, float, float]:
        lon0, lat0, lon1, lat1 = self.boundary
        b = self.buffer_km()
        dlat, dlon = b / 111.32, b / (111.32 * math.cos(math.radians(self.lat)))
        lon0, lat0, lon1, lat1 = lon0 - dlon, lat0 - dlat, lon1 + dlon, lat1 + dlat
        # A very large administrative unit is cropped to a box of MAX_SIDE_KM centred on the city centre
        half_lat = MAX_SIDE_KM / 2 / 111.32
        half_lon = MAX_SIDE_KM / 2 / (111.32 * math.cos(math.radians(self.lat)))
        lon0, lon1 = max(lon0, self.lon - half_lon), min(lon1, self.lon + half_lon)
        lat0, lat1 = max(lat0, self.lat - half_lat), min(lat1, self.lat + half_lat)
        return (round(lon0, 5), round(lat0, 5), round(lon1, 5), round(lat1, 5))

    def aoi_km(self) -> tuple[float, float]:
        lon0, lat0, lon1, lat1 = self.aoi_bbox()
        return (_km_lon(lon1 - lon0, (lat0 + lat1) / 2), (lat1 - lat0) * 111.32)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(slug=self.slug, utm_epsg=self.utm_epsg, buffer_km=round(self.buffer_km(), 2),
                 aoi_bbox=self.aoi_bbox(), aoi_km=[round(v, 1) for v in self.aoi_km()])
        return d


def _km_lon(dlon: float, lat: float) -> float:
    return dlon * 111.32 * math.cos(math.radians(lat))


def _cache_path() -> Path:
    CITIES_ROOT.mkdir(parents=True, exist_ok=True)
    return CITIES_ROOT / "_geocode_cache.json"


def _load_cache() -> dict:
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _cache_path().write_text(json.dumps(cache, indent=1), encoding="utf-8")


def nominatim_search(query: str, *, limit: int = 10) -> list[dict]:
    r = requests.get(f"{NOMINATIM}/search",
                     params={"q": query, "format": "jsonv2", "limit": limit, "countrycodes": "in"},
                     headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    time.sleep(1.1)
    return r.json()


def _area_km2(h: dict) -> float:
    s, n, w, e = (float(v) for v in h["boundingbox"])
    return _km_lon(e - w, (s + n) / 2) * (n - s) * 111.32


def _pick(results: list[dict]) -> dict | None:
    # Administrative boundary relations first: a place node only carries a synthetic box around a point
    ok = [h for h in results if h.get("addresstype") in URBAN_TYPES and _area_km2(h) >= MIN_AREA_KM2]
    rel = [h for h in ok if h.get("osm_type") == "relation" and h.get("category", h.get("class")) == "boundary"]
    if rel:
        return max(rel, key=lambda h: int(h.get("place_rank", 0)))
    return None


def resolve(name: str) -> City:
    key = name.strip()
    if not key:
        raise CityError("no city name given")
    query = CITIES.get(key, key if "india" in key.lower() else f"{key}, India")
    cache = _load_cache()
    hit = cache.get(f"v2:{query}")
    if hit is None:
        hit = _pick(nominatim_search(query))
        if hit is None:
            raise CityError(f"'{key}' did not resolve to an Indian city or town of at least "
                            f"{MIN_AREA_KM2:.0f} km2 on OpenStreetMap")
        cache[f"v2:{query}"] = hit
        _save_cache(cache)
    s, n, w, e = (float(v) for v in hit["boundingbox"])
    label = key if key in CITIES else hit.get("name") or key
    return City(name=label, display=hit["display_name"], lon=float(hit["lon"]),
                lat=float(hit["lat"]), boundary=(w, s, e, n),
                osm=f"{hit['osm_type']}/{hit['osm_id']}", kind=hit.get("addresstype", ""))


def city_dir(city: City) -> Path:
    d = CITIES_ROOT / city.slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_config(city: City, *, nightlights_end: int | None = None) -> Path:
    raw = yaml.safe_load(Path(DEFAULT_CONFIG).read_text(encoding="utf-8"))
    lon0, lat0, lon1, lat1 = city.aoi_bbox()
    raw["city"] = {"name": city.name, "state": city.display.split(",")[-2].strip()
                   if city.display.count(",") >= 2 else "", "country": "India",
                   "country_iso3": "IND", "centre": {"lat": city.lat, "lon": city.lon},
                   "osm": city.osm}
    raw["aoi"] = {"bbox": {"min_lon": lon0, "min_lat": lat0, "max_lon": lon1, "max_lat": lat1},
                  "boundary_bbox": list(city.boundary), "buffer_km": round(city.buffer_km(), 2)}
    raw["crs"]["projected"] = f"EPSG:{city.utm_epsg}"
    raw["sources"]["osm"]["user_agent"] = USER_AGENT
    raw["sources"]["osm"]["overpass_endpoints"] = OVERPASS
    if nightlights_end:
        raw["timeseries"]["nightlights_end"] = int(nightlights_end)
    rel = Path("data") / "cities" / city.slug
    raw["paths"] = {"data_raw": str(rel / "raw"), "data_interim": str(rel / "interim"),
                    "data_processed": str(rel / "processed"), "outputs": str(rel / "outputs")}
    out = city_dir(city) / "config.yaml"
    out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out
