"""Street-level metrics from the LiDAR surface and Sentinel-2 NDVI.

Pedestrian sample points (every ``step`` metres along each segment, at 1.6 m
above the DTM, or above the deck on footbridges) are evaluated against the DSM:

* ``svf``    - mean sky view factor along the segment
* ``cover``  - share of the segment with *something* overhead (tree, canopy, bridge)
* ``tree``   - share of the segment under **tree canopy** (overhead and NDVI >= 0.3)
* ``ndvi``   - mean summer NDVI (10 m)
* per time slot, the share of the segment in shade from buildings, trees, terrain
  or overhead cover (:func:`slot_shade`)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from shadewalk.data.lidar import Surface
from shadewalk.network import sample_points
from shadewalk.raster import observer_height, overhead_cover, ray_shadow, sky_view_factor

__all__ = [
    "TREE_NDVI",
    "StreetPoints",
    "sample_raster",
    "slot_shade",
    "static_metrics",
    "street_points",
]

#: NDVI above which an overhead obstruction is treated as tree canopy.
TREE_NDVI = 0.3


@dataclass
class StreetPoints:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    owner: np.ndarray
    n_edges: int
    covered: np.ndarray  # officially covered/indoor segment (per point)
    cover: np.ndarray | None = None  # LiDAR overhead cover (per point)

    def per_edge_mean(self, values: np.ndarray) -> np.ndarray:
        v = np.asarray(values, dtype=float)
        ok = np.isfinite(v)
        s = np.bincount(self.owner[ok], weights=v[ok], minlength=self.n_edges)
        c = np.bincount(self.owner[ok], minlength=self.n_edges)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def street_points(edges: gpd.GeoDataFrame, surface: Surface, step: float = 2.0) -> StreetPoints:
    """Sample points with pedestrian eye height for every edge."""
    pts, owner = sample_points(edges, step)
    xy = shapely.get_coordinates(pts)
    elevated = (edges["feature_type"].to_numpy() == 2)[owner] if "feature_type" in edges else None
    z = observer_height(surface, xy[:, 0], xy[:, 1], elevated)
    covered = (
        edges["covered"].to_numpy(dtype=bool)[owner]
        if "covered" in edges
        else np.zeros(len(owner), dtype=bool)
    )
    return StreetPoints(xy[:, 0], xy[:, 1], z, owner, len(edges), covered)


def sample_raster(
    path: str | Path, x: np.ndarray, y: np.ndarray, crs: str = "EPSG:2326"
) -> np.ndarray:
    """Sample a single-band raster at projected points (reprojecting as needed)."""
    import rasterio
    from pyproj import Transformer

    with rasterio.open(path) as src:
        if str(src.crs) != crs:
            tx, ty = Transformer.from_crs(crs, src.crs, always_xy=True).transform(x, y)
        else:
            tx, ty = x, y
        vals = np.array([v[0] for v in src.sample(zip(tx, ty, strict=True))], dtype=float)
        if src.nodata is not None and np.isfinite(src.nodata):
            vals[vals == src.nodata] = np.nan
    return vals


def static_metrics(
    pts: StreetPoints, surface: Surface, ndvi_path: str | Path | None = None, svf_dirs: int = 16
) -> dict[str, np.ndarray]:
    """Time-independent per-edge metrics; also stores ``pts.cover`` for :func:`slot_shade`."""
    cover = overhead_cover(surface, pts.x, pts.y, pts.z)
    pts.cover = cover
    out = {
        "svf": pts.per_edge_mean(sky_view_factor(surface, pts.x, pts.y, pts.z, n_dirs=svf_dirs)),
        "cover": pts.per_edge_mean(cover.astype(float)),
    }
    if ndvi_path is not None:
        nd = sample_raster(ndvi_path, pts.x, pts.y)
        out["ndvi"] = pts.per_edge_mean(nd)
        out["tree"] = pts.per_edge_mean((cover & (nd >= TREE_NDVI)).astype(float))
    return out


def slot_shade(pts: StreetPoints, surface: Surface, altitude: float, azimuth: float) -> np.ndarray:
    """Per-edge share of length shaded at one sun position (LiDAR model)."""
    if altitude <= 0:
        return np.ones(pts.n_edges)
    if pts.cover is None:
        pts.cover = overhead_cover(surface, pts.x, pts.y, pts.z)
    shaded = ray_shadow(surface, pts.x, pts.y, pts.z, altitude, azimuth) | pts.cover | pts.covered
    frac = pts.per_edge_mean(shaded.astype(float))
    return np.where(np.isfinite(frac), frac, 0.0)
