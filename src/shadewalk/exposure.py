"""Per-segment shade fraction, surface heat weight and sun-exposure cost.

For edge *e* at time *t*::

    shade_e(t)    = fraction of e's length inside building shadows (1 if covered/indoor
                    or the sun is down)
    heat_e        = 1 + beta * clip((LST_e - p10) / (p90 - p10), 0, 1)
    exposure_e(t) = length_e * (1 - shade_e(t)) * heat_e

``exposure`` is in "effective sunlit metres": one metre of unshaded street at the
area's coolest surfaces counts 1, at its hottest surfaces counts ``1 + beta``.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from shadewalk.network import sample_points

__all__ = ["edge_lst", "exposure", "heat_weight", "shade_fraction"]


def shade_fraction(
    edges: gpd.GeoDataFrame,
    shadows: gpd.GeoDataFrame | None,
    step: float = 2.0,
    covered_col: str = "covered",
) -> np.ndarray:
    """Fraction (0-1) of each edge length that lies in shadow.

    ``shadows=None`` means the sun is down: every edge is fully shaded.
    """
    n = len(edges)
    if shadows is None:
        return np.ones(n)
    frac = np.zeros(n)
    if len(shadows):
        pts, owner = sample_points(edges, step)
        tree = shapely.STRtree(shadows.geometry.to_numpy())
        hit_pts, _ = tree.query(pts, predicate="intersects")
        shaded = np.zeros(len(pts), dtype=bool)
        shaded[np.unique(hit_pts)] = True
        counts = np.bincount(owner, minlength=n)
        frac = np.bincount(owner, weights=shaded, minlength=n) / np.maximum(counts, 1)
    if covered_col in edges:
        frac = np.where(edges[covered_col].to_numpy(dtype=bool), 1.0, frac)
    return frac


def edge_lst(edges: gpd.GeoDataFrame, lst_path: str | Path, step: float = 10.0) -> np.ndarray:
    """Mean land surface temperature (deg C) sampled along each edge; NaN if unavailable."""
    import rasterio

    pts, owner = sample_points(edges, step)
    with rasterio.open(lst_path) as src:
        pts_r = gpd.GeoSeries(pts, crs=edges.crs).to_crs(src.crs)
        xy = shapely.get_coordinates(pts_r.to_numpy())
        vals = np.array([v[0] for v in src.sample(xy)], dtype=float)
        if src.nodata is not None and not np.isnan(src.nodata):
            vals[vals == src.nodata] = np.nan
    ok = np.isfinite(vals)
    n = len(edges)
    s = np.bincount(owner[ok], weights=vals[ok], minlength=n)
    c = np.bincount(owner[ok], minlength=n)
    with np.errstate(invalid="ignore"):
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def heat_weight(lst: np.ndarray | None, beta: float = 1.0) -> np.ndarray | float:
    """Map LST to a multiplicative weight in ``[1, 1 + beta]`` using the 10th-90th percentiles.

    Missing values get the median weight. Without LST the weight is 1.
    """
    if lst is None:
        return 1.0
    lst = np.asarray(lst, dtype=float)
    if not np.isfinite(lst).any():
        return np.ones_like(lst)
    lo, hi = np.nanpercentile(lst, [10, 90])
    z = np.clip((lst - lo) / max(hi - lo, 1e-6), 0, 1)
    z = np.where(np.isfinite(z), z, np.nanmedian(z))
    return 1.0 + beta * z


def exposure(length: np.ndarray, shade: np.ndarray, weight: np.ndarray | float = 1.0) -> np.ndarray:
    """Effective sun-exposed metres per edge."""
    return np.asarray(length, dtype=float) * (1.0 - np.asarray(shade, dtype=float)) * weight
