"""Area-of-interest geometry, the analysis grid, and the common raster frame.

Everything downstream snaps to the frame defined here, so that built-up,
nightlight, vegetation and thermal layers are pixel-aligned and can be
combined arithmetically without resampling surprises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from .config import Config


@dataclass(frozen=True)
class AnalysisFrame:
    """A north-up, metric raster frame covering the AOI.

    Attributes
    ----------
    crs : str
        Projected CRS (UTM for the city).
    res : float
        Pixel size in metres.
    minx, miny, maxx, maxy : float
        Bounds in `crs`, snapped outward to whole multiples of `res`.
    width, height : int
        Raster dimensions in pixels.
    """

    crs: str
    res: float
    minx: float
    miny: float
    maxx: float
    maxy: float
    width: int
    height: int

    @property
    def transform(self):
        """Affine transform (origin at top-left, north-up)."""
        from affine import Affine

        return Affine(self.res, 0.0, self.minx, 0.0, -self.res, self.maxy)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.minx, self.miny, self.maxx, self.maxy)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    def profile(self, dtype: str = "float32", nodata: float | None = np.nan, count: int = 1) -> dict:
        """A rasterio creation profile for this frame."""
        return {
            "driver": "GTiff",
            "dtype": dtype,
            "nodata": nodata,
            "width": self.width,
            "height": self.height,
            "count": count,
            "crs": CRS.from_user_input(self.crs),
            "transform": self.transform,
            "compress": "deflate",
            "predictor": 2 if dtype.startswith("float") else 1,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }

    def xy_centres(self) -> tuple[np.ndarray, np.ndarray]:
        """1-D arrays of pixel-centre coordinates (x eastings, y northings)."""
        xs = self.minx + (np.arange(self.width) + 0.5) * self.res
        ys = self.maxy - (np.arange(self.height) + 0.5) * self.res
        return xs, ys


class AOI:
    """The study area for one city."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.name = cfg.city
        self.slug = cfg.city_slug
        self.bbox_ll = cfg.bbox  # (min_lon, min_lat, max_lon, max_lat)
        self.crs_ll = cfg.crs_geographic
        self.crs_m = cfg.crs_projected
        self._to_m = Transformer.from_crs(self.crs_ll, self.crs_m, always_xy=True)
        self._to_ll = Transformer.from_crs(self.crs_m, self.crs_ll, always_xy=True)

    # ------------------------------------------------------------ geometry
    @property
    def geom_ll(self) -> BaseGeometry:
        """AOI polygon in geographic coordinates."""
        return box(*self.bbox_ll)

    @property
    def geom_m(self) -> BaseGeometry:
        """AOI polygon in the projected CRS."""
        return box(*self.bounds_m)

    @property
    def bounds_m(self) -> tuple[float, float, float, float]:
        """AOI bounds in the projected CRS.

        The four corners are transformed and the envelope taken, which is
        marginally larger than transforming just SW/NE — correct for a
        projected frame that must fully contain the geographic box.
        """
        lon0, lat0, lon1, lat1 = self.bbox_ll
        corners = [(lon0, lat0), (lon0, lat1), (lon1, lat0), (lon1, lat1)]
        xs, ys = zip(*(self._to_m.transform(lon, lat) for lon, lat in corners))
        return (min(xs), min(ys), max(xs), max(ys))

    def to_metres(self, lon: float, lat: float) -> tuple[float, float]:
        return self._to_m.transform(lon, lat)

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self._to_ll.transform(x, y)

    @property
    def centre_m(self) -> tuple[float, float]:
        lon, lat = self.cfg.centre
        return self.to_metres(lon, lat)

    def geojson(self) -> dict:
        """AOI as a GeoJSON Feature (EPSG:4326) — for GEE and web maps."""
        return {
            "type": "Feature",
            "properties": {"name": self.name, "role": "aoi"},
            "geometry": mapping(self.geom_ll),
        }

    def area_km2(self) -> float:
        return self.geom_m.area / 1e6

    # --------------------------------------------------------------- frame
    def frame(self, res_m: float | None = None) -> AnalysisFrame:
        """Build the common raster frame at `res_m` (default: grid cell size).

        Bounds are snapped outward to whole multiples of `res_m` so that
        frames at 100 m / 500 m nest exactly.
        """
        res = float(res_m if res_m is not None else self.cfg.cell_size_m)
        minx, miny, maxx, maxy = self.bounds_m
        minx = math.floor(minx / res) * res
        miny = math.floor(miny / res) * res
        maxx = math.ceil(maxx / res) * res
        maxy = math.ceil(maxy / res) * res
        width = int(round((maxx - minx) / res))
        height = int(round((maxy - miny) / res))
        return AnalysisFrame(
            crs=self.crs_m, res=res,
            minx=minx, miny=miny, maxx=maxx, maxy=maxy,
            width=width, height=height,
        )

    def frame_pair(self, fine_res: float, coarse_res: float) -> tuple[AnalysisFrame, AnalysisFrame]:
        """Build a fine and a coarse frame that tile each other *exactly*.

        Calling `frame()` twice does not achieve this: each call snaps its
        bounds outward to its own resolution, so a 500 m frame reaches
        further out than a 100 m one and `fine.width / factor` does not equal
        `coarse.width`. Aggregation would then silently misalign.

        The coarse frame is built first and the fine frame is derived from
        it, sharing an origin and extent, with exactly `factor x factor`
        fine cells per coarse cell.
        """
        ratio = coarse_res / fine_res
        factor = int(round(ratio))
        if abs(ratio - factor) > 1e-9 or factor < 1:
            raise ValueError(
                f"coarse resolution ({coarse_res}) must be a positive integer "
                f"multiple of fine ({fine_res})"
            )
        coarse = self.frame(coarse_res)
        fine = AnalysisFrame(
            crs=self.crs_m, res=float(fine_res),
            minx=coarse.minx, miny=coarse.miny,
            maxx=coarse.maxx, maxy=coarse.maxy,
            width=coarse.width * factor, height=coarse.height * factor,
        )
        return fine, coarse

    # ---------------------------------------------------------------- grid
    def grid_cells(self, res_m: float | None = None) -> Iterator[dict]:
        """Yield analysis-grid cells as GeoJSON-ready dicts.

        Each cell carries its row/col and both projected and geographic
        centroids, so zonal results can be joined back to rasters by index
        without a spatial join.
        """
        fr = self.frame(res_m)
        for row in range(fr.height):
            for col in range(fr.width):
                x0 = fr.minx + col * fr.res
                y1 = fr.maxy - row * fr.res
                x1, y0 = x0 + fr.res, y1 - fr.res
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                lon, lat = self.to_lonlat(cx, cy)
                yield {
                    "cell_id": row * fr.width + col,
                    "row": row,
                    "col": col,
                    "x": cx,
                    "y": cy,
                    "lon": lon,
                    "lat": lat,
                    "geometry": box(x0, y0, x1, y1),
                }

    def grid_gdf(self, res_m: float | None = None):
        """The analysis grid as a GeoDataFrame in the projected CRS."""
        import geopandas as gpd

        cells = list(self.grid_cells(res_m))
        geoms = [c.pop("geometry") for c in cells]
        return gpd.GeoDataFrame(cells, geometry=geoms, crs=self.crs_m)

    def __repr__(self) -> str:
        fr = self.frame()
        return (
            f"<AOI {self.name} bbox={self.bbox_ll} "
            f"area={self.area_km2():.0f} km2 grid={fr.width}x{fr.height}@{fr.res:.0f}m>"
        )


def distance_to_centre(aoi: AOI, frame: AnalysisFrame) -> np.ndarray:
    """Euclidean distance (km) from each pixel centre to the city centre.

    Used as a driver in the growth analysis and as the radial axis for
    the urban-gradient profile.
    """
    cx, cy = aoi.centre_m
    xs, ys = frame.xy_centres()
    dx = xs[None, :] - cx
    dy = ys[:, None] - cy
    return np.sqrt(dx**2 + dy**2).astype("float32") / 1000.0
