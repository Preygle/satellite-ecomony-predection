from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage

from ..analysis import growth_model as GM
from ..aoi import AOI, AnalysisFrame

# Roads that carry traffic between places rather than within a block. Growth
# follows these; a service road behind a house predicts nothing.
MAJOR_CLASSES = {"motorway", "trunk", "primary", "secondary",
                 "motorway_link", "trunk_link", "primary_link"}


def _smooth(arr: np.ndarray, radius_m: float, frame: AnalysisFrame) -> np.ndarray:
    """Mean of `arr` over a circle of `radius_m`."""
    r = max(1, int(round(radius_m / frame.res)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = ((xx**2 + yy**2) <= r**2).astype("float32")
    k /= k.sum()
    return ndimage.convolve(arr.astype("float32"), k, mode="nearest")


def _distance_km(mask: np.ndarray, frame: AnalysisFrame, *, cap: float = 30.0) -> np.ndarray:
    """Distance in kilometres from every cell to the nearest True cell."""
    if not mask.any():
        return np.full(frame.shape, cap, dtype="float32")
    d = ndimage.distance_transform_edt(~mask) * frame.res / 1000.0
    return np.clip(d, 0, cap).astype("float32")


def junctions(aoi: AOI, roads: dict, frame: AnalysisFrame, *,
              snap_m: float = 15.0) -> np.ndarray:
    """Count of road junctions per cell.

    A junction is a point where centrelines from two or more different ways
    meet. It is not the same thing as road density: a long bypass raises
    density without creating anywhere to turn off, while a grid of small
    streets is dense in junctions and is where plots actually get built. The
    two together separate "a road goes past here" from "this place is
    connected".

    Vertices are snapped to a `snap_m` grid before matching, because two ways
    that meet at a junction rarely carry bit-identical coordinates.
    """
    seen: dict[tuple[int, int], set[int]] = {}
    for i, feat in enumerate(roads.get("features", [])):
        for lon, lat in feat["coords"]:
            x, y = aoi.to_metres(lon, lat)
            key = (int(round(x / snap_m)), int(round(y / snap_m)))
            seen.setdefault(key, set()).add(i)

    out = np.zeros(frame.shape, dtype="float32")
    for (kx, ky), ways in seen.items():
        if len(ways) < 2:
            continue
        col = int((kx * snap_m - frame.minx) / frame.res)
        row = int((frame.maxy - ky * snap_m) / frame.res)
        if 0 <= row < frame.height and 0 <= col < frame.width:
            out[row, col] += 1.0
    return out


def major_road_mask(aoi: AOI, roads: dict, frame: AnalysisFrame) -> np.ndarray:
    """Cells crossed by a road that carries traffic between places."""
    out = np.zeros(frame.shape, dtype=bool)
    step = frame.res / 2.0
    for feat in roads.get("features", []):
        if feat["highway"] not in MAJOR_CLASSES:
            continue
        pts = [aoi.to_metres(lon, lat) for lon, lat in feat["coords"]]
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            seg = float(np.hypot(x1 - x0, y1 - y0))
            n = max(1, int(np.ceil(seg / step)))
            ts = (np.arange(n) + 0.5) / n
            cols = ((x0 + (x1 - x0) * ts - frame.minx) / frame.res).astype(int)
            rows = ((frame.maxy - (y0 + (y1 - y0) * ts)) / frame.res).astype(int)
            ok = ((rows >= 0) & (rows < frame.height)
                  & (cols >= 0) & (cols < frame.width))
            out[rows[ok], cols[ok]] = True
    return out


def extended_drivers(
    builtup: dict[int, np.ndarray],
    frame: AnalysisFrame,
    *,
    year: int,
    aoi: AOI,
    distance_km: np.ndarray,
    road_density: np.ndarray | None = None,
    population: dict[int, np.ndarray] | None = None,
    slope: np.ndarray | None = None,
    roads: dict | None = None,
    water: np.ndarray | None = None,
    nightlights: np.ndarray | None = None,
    poi_density: np.ndarray | None = None,
    poi_detail: dict | None = None,
    urban_threshold: float = 0.20,
    momentum: bool = True,
) -> tuple[np.ndarray, list[str]]:
    """The eight published drivers plus everything else the data supports.

    Every layer here is measurable at or before `year`, so nothing leaks from
    the period being predicted. Two exceptions are flagged rather than hidden:
    OpenStreetMap roads and points of interest are a present-day snapshot, as
    they already are in the published model, and the water mask is taken from
    a recent year because a river does not move.

    Returns the design matrix over all cells, and the column names.
    """
    X, names = GM.build_drivers(
        builtup[year], frame, distance_km=distance_km, road_density=road_density,
        population=(population or {}).get(year), slope=slope,
        urban_threshold=urban_threshold,
    )
    extra: dict[str, np.ndarray] = {}
    built = builtup[year]
    urban = built >= urban_threshold

    # A third, wider neighbourhood. Growth responds to the district as well as
    # to the street, and 500 m and 1,500 m both sit inside a single suburb.
    extra["neighbourhood_built_3000m"] = _smooth(urban.astype("float32"), 3000.0, frame)

    if roads is not None:
        j = junctions(aoi, roads, frame)
        extra["junction_density_500m"] = _smooth(j, 500.0, frame)
        extra["distance_to_major_road_km"] = _distance_km(
            major_road_mask(aoi, roads, frame), frame)

    if water is not None:
        extra["distance_to_water_km"] = _distance_km(water > 0.5, frame)

    if nightlights is not None:
        lit = np.nan_to_num(nightlights, nan=0.0)
        extra["nightlights"] = lit.astype("float32")
        extra["nightlights_500m"] = _smooth(lit, 500.0, frame)

    if poi_density is not None:
        extra["poi_density_500m"] = _smooth(np.nan_to_num(poi_density, nan=0.0),
                                            500.0, frame)
    if poi_detail is not None:
        extra.update(poi_layers(aoi, poi_detail, frame))

    # What happened here over the previous five years. A cell beside land that
    # just converted is a far better bet than one beside land that has been
    # static for twenty years, and none of the other drivers carry that.
    prev = year - 5
    if momentum and prev in builtup:
        change = np.clip(built - builtup[prev], 0, None).astype("float32")
        extra["builtup_growth_previous"] = change
        extra["builtup_growth_previous_1500m"] = _smooth(change, 1500.0, frame)
        if population and prev in population and year in population:
            extra["population_growth_previous"] = np.nan_to_num(
                population[year] - population[prev], nan=0.0).astype("float32")

    if not extra:
        return X, names
    cols = [np.nan_to_num(v, nan=0.0).reshape(-1, 1) for v in extra.values()]
    return np.hstack([X, np.hstack(cols).astype(X.dtype)]), names + list(extra)


# Relative footfall weights. These are a documented PROXY for how many people
# a place draws in a day, not measured visits: a railway station or a mall
# pulls a whole district, a kiosk pulls the street. The ordering is what the
# model uses, and it is the ordering a planner would agree with. Anything not
# listed falls back to 2.
FOOTFALL: dict[str, float] = {
    "mall": 20.0, "department_store": 14.0, "marketplace": 15.0,
    "supermarket": 10.0, "convenience": 5.0, "kiosk": 2.0, "clothes": 4.0,
    "bakery": 4.0, "hardware": 3.0, "furniture": 3.0, "car": 3.0,
    "station": 20.0, "halt": 10.0, "bus_station": 15.0, "fuel": 7.0,
    "taxi": 5.0, "hospital": 12.0, "clinic": 5.0, "doctors": 4.0,
    "pharmacy": 6.0, "university": 10.0, "college": 8.0, "school": 8.0,
    "educational_institution": 8.0, "restaurant": 6.0, "fast_food": 6.0,
    "cafe": 5.0, "bar": 4.0, "food_court": 8.0, "hotel": 4.0,
    "guest_house": 3.0, "hostel": 3.0, "bank": 5.0, "atm": 3.0,
    "bureau_de_change": 3.0, "industrial": 2.0, "works": 2.0,
}
POI_GROUP_NAMES = ["retail", "food_hospitality", "finance_office",
                   "health_education", "industrial", "transport"]


def poi_kind(tags: dict) -> str:
    """The most specific label OpenStreetMap gives a place."""
    for key in ("shop", "amenity", "railway", "public_transport", "office",
                "tourism", "landuse", "industrial", "man_made"):
        v = tags.get(key)
        if v and v != "yes":
            return str(v)
    return "other"


def _accessibility(weights: np.ndarray, frame: AnalysisFrame, *,
                   reach_km: float = 3.0) -> np.ndarray:
    """Sum of nearby weight discounted by distance, as 1 / (1 + d^2).

    A gravity measure rather than a count in a circle: a hospital 400 m away
    counts for much more than one 2.5 km away, and a plain density inside a
    radius treats them identically.
    """
    r = max(1, int(round(reach_km * 1000.0 / frame.res)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d_km = np.hypot(xx, yy) * frame.res / 1000.0
    kernel = np.where(d_km <= reach_km, 1.0 / (1.0 + d_km**2), 0.0).astype("float32")
    return ndimage.convolve(weights.astype("float32"), kernel, mode="constant")


def poi_layers(aoi: AOI, detailed: dict, frame: AnalysisFrame) -> dict[str, np.ndarray]:
    """Everything the points of interest can say, not just how many there are.

    Type matters as much as count. A district with a station, a hospital and a
    market is a different proposition from one with the same number of kiosks,
    and a mix of kinds is what marks a place that has become a centre rather
    than a dormitory. These layers separate those cases: weighted footfall,
    one density per kind of activity, how varied the mix is, and how far the
    nearest of each kind actually is.

    All of it comes from a present-day OpenStreetMap snapshot, so for a
    back-test over 2015-2020 it carries information from after the outcome.
    See `run_feature_model.py --no-poi` for the comparison that shows how much.
    """
    feats = detailed.get("features", [])
    weight = np.zeros(frame.shape, dtype="float32")
    counts = {g: np.zeros(frame.shape, dtype="float32") for g in POI_GROUP_NAMES}
    kinds_here: dict[tuple[int, int], set[str]] = {}

    for f in feats:
        x, y = aoi.to_metres(f["lon"], f["lat"])
        col = int((x - frame.minx) / frame.res)
        row = int((frame.maxy - y) / frame.res)
        if not (0 <= row < frame.height and 0 <= col < frame.width):
            continue
        kind = poi_kind(f.get("tags", {}))
        weight[row, col] += FOOTFALL.get(kind, 2.0)
        g = f.get("group")
        if g in counts:
            counts[g][row, col] += 1.0
        kinds_here.setdefault((row, col), set()).add(kind)

    out: dict[str, np.ndarray] = {}
    out["poi_footfall_500m"] = _smooth(weight, 500.0, frame)
    out["poi_footfall_1500m"] = _smooth(weight, 1500.0, frame)
    out["poi_accessibility"] = _accessibility(weight, frame)

    present = []
    for g in POI_GROUP_NAMES:
        layer = _smooth(counts[g], 1500.0, frame)
        out[f"poi_{g}_1500m"] = layer
        present.append(layer)

    # How mixed the activity is. Six shops of one kind and six of six kinds
    # give the same density; only the second is a centre.
    stack = np.stack(present)
    total = stack.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(total > 0, stack / np.maximum(total, 1e-6), 0.0)
        ent = -(share * np.log(np.maximum(share, 1e-12))).sum(axis=0)
    out["poi_mix_entropy_1500m"] = np.where(total > 0, ent, 0.0).astype("float32")

    variety = np.zeros(frame.shape, dtype="float32")
    for (row, col), ks in kinds_here.items():
        variety[row, col] = float(len(ks))
    out["poi_variety_1500m"] = _smooth(variety, 1500.0, frame)

    for g in ("retail", "health_education", "transport", "industrial"):
        out[f"distance_to_{g}_km"] = _distance_km(counts[g] > 0, frame)
    return out
