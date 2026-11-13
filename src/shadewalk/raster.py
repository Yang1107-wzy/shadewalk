"""Raster (DSM-based) shade, sky view factor and overhead cover.

Unlike :mod:`shadewalk.shadow`, which casts exact shadows from LoD1 building
prisms, this module works on a digital surface model and therefore captures
**trees, terrain, flyovers and podium roofs** as well as buildings.

All functions evaluate *points* (e.g. pedestrian sample points at head height)
by marching rays through the DSM, which is far cheaper than computing whole
shadow rasters when only street-level answers are needed:

* :func:`ray_shadow` - is the sun blocked between the point and the sun?
* :func:`sky_view_factor` - share of the sky hemisphere visible (Zaksek et al. 2011).
* :func:`overhead_cover` - is something (canopy, roof, bridge) directly overhead?

Ray steps grow geometrically with distance (``step = max(res, rel * d)``), so a
1 km ray costs ~ 150 lookups instead of 1000 while keeping metre-level accuracy
near the observer, where it matters most.
"""

from __future__ import annotations

import numpy as np

from shadewalk.data.lidar import Surface

__all__ = [
    "PEDESTRIAN_HEIGHT",
    "observer_height",
    "overhead_cover",
    "rasterize_buildings",
    "ray_distances",
    "ray_shadow",
    "sample",
    "shade_grid",
    "sky_view_factor",
]

#: Eye/head height used for street-level visibility tests (m).
PEDESTRIAN_HEIGHT = 1.6


def sample(surface: Surface, arr: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Nearest-neighbour lookup of ``arr`` (same grid as ``surface``); NaN outside."""
    t = surface.transform
    col = np.floor((np.asarray(x) - t.c) / t.a).astype(np.int64)
    row = np.floor((np.asarray(y) - t.f) / t.e).astype(np.int64)
    h, w = arr.shape
    ok = (row >= 0) & (row < h) & (col >= 0) & (col < w)
    out = np.full(np.shape(x), np.nan, dtype=float)
    out[ok] = arr[row[ok], col[ok]]
    return out


def ray_distances(max_dist: float, res: float, rel: float = 0.02) -> np.ndarray:
    """Distances along a ray: steps of ``res`` near the origin growing to ``rel * d``."""
    d = [res]
    while d[-1] < max_dist:
        d.append(d[-1] + max(res, rel * d[-1]))
    return np.asarray(d, dtype=float)


def observer_height(
    surface: Surface, x: np.ndarray, y: np.ndarray, elevated: np.ndarray | None = None
) -> np.ndarray:
    """Pedestrian eye elevation (mPD): DTM + 1.6 m, or DSM + 1.6 m on elevated walkways."""
    z = sample(surface, surface.dtm, x, y)
    if elevated is not None and np.any(elevated):
        zs = sample(surface, surface.dsm, x, y)
        z = np.where(elevated, np.fmax(zs, z), z)
    return z + PEDESTRIAN_HEIGHT


def ray_shadow(
    surface: Surface,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    altitude: float,
    azimuth: float,
    max_dist: float | None = None,
    min_clearance: float = 0.5,
) -> np.ndarray:
    """Boolean array: True where the direct sun is blocked for observers at ``(x, y, z)``.

    A point is shadowed when, for some distance ``d`` towards the sun,
    ``DSM(p + d*u) > z + d*tan(alt) + min_clearance``. ``min_clearance`` suppresses
    false hits from DSM noise right next to the observer.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    if altitude <= 0:
        return np.ones(x.shape, dtype=bool)
    tan_a = np.tan(np.radians(altitude))
    if max_dist is None:
        relief = float(np.nanmax(surface.dsm) - np.nanmin(z)) if z.size else 0.0
        max_dist = min(max(relief, 0.0) / tan_a, 2000.0)
    ux, uy = np.sin(np.radians(azimuth)), np.cos(np.radians(azimuth))
    blocked = np.zeros(x.shape, dtype=bool)
    active = np.isfinite(z)
    for d in ray_distances(max_dist, surface.res):
        idx = np.flatnonzero(active & ~blocked)
        if idx.size == 0:
            break
        h = sample(surface, surface.dsm, x[idx] + d * ux, y[idx] + d * uy)
        hit = h > z[idx] + d * tan_a + min_clearance
        blocked[idx[hit]] = True
    return blocked


def sky_view_factor(
    surface: Surface,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    n_dirs: int = 16,
    max_dist: float = 100.0,
) -> np.ndarray:
    """Sky view factor in [0, 1] at observer points (``1 - mean(sin horizon angle)``).

    Follows the Zaksek et al. (2011) definition used in relief visualisation and
    urban climatology; horizon angles below 0 count as 0.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    dists = ray_distances(max_dist, surface.res, rel=0.05)
    acc = np.zeros(x.shape, dtype=float)
    for k in range(n_dirs):
        az = 2 * np.pi * k / n_dirs
        ux, uy = np.sin(az), np.cos(az)
        best = np.zeros(x.shape, dtype=float)  # max tan(horizon angle)
        for d in dists:
            h = sample(surface, surface.dsm, x + d * ux, y + d * uy)
            with np.errstate(invalid="ignore"):
                best = np.fmax(best, (h - z) / d)
        acc += np.sin(np.arctan(np.clip(best, 0, None)))
    svf = 1.0 - acc / n_dirs
    svf[~np.isfinite(z)] = np.nan
    return svf


def overhead_cover(
    surface: Surface,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    min_gap: float = 1.0,
    radius: float = 1.0,
) -> np.ndarray:
    """True where the surface directly above the observer is higher than its head.

    Uses the *minimum* DSM within ``radius`` so that a footway running along a
    facade is not mistaken for being under the building.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lo = np.full(x.shape, np.inf)
    r = max(radius, surface.res)
    for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
        lo = np.fmin(lo, sample(surface, surface.dsm, x + dx, y + dy))
    with np.errstate(invalid="ignore"):
        return lo > np.asarray(z) + min_gap


def shade_grid(
    surface: Surface,
    altitude: float,
    azimuth: float,
    cell: float = 4.0,
    building_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Street-level shade raster (1 = shaded, 0 = sunlit) at ``cell`` metres, for maps.

    Each cell is evaluated at DTM + 1.6 m. Cells under canopy or other cover count
    as shaded. ``building_mask`` (same shape as the output, True inside building
    footprints, see :func:`rasterize_buildings`) marks cells to blank out (NaN).
    """
    x0, y0, x1, y1 = surface.bounds
    xs = np.arange(x0 + cell / 2, x1, cell)
    ys = np.arange(y1 - cell / 2, y0, -cell)
    gx, gy = np.meshgrid(xs, ys)
    fx, fy = gx.ravel(), gy.ravel()
    z = observer_height(surface, fx, fy)
    shade = ray_shadow(surface, fx, fy, z, altitude, azimuth) | overhead_cover(surface, fx, fy, z)
    out = shade.astype("float32").reshape(gx.shape)
    out[~np.isfinite(z.reshape(gx.shape))] = np.nan
    if building_mask is not None:
        out[building_mask] = np.nan
    return out, (x0, y1 - len(ys) * cell, x0 + len(xs) * cell, y1)


def rasterize_buildings(
    buildings, bounds: tuple[float, float, float, float], cell: float
) -> np.ndarray:
    """Boolean footprint mask on the ``shade_grid`` lattice for ``bounds``."""
    from affine import Affine
    from rasterio.features import rasterize

    x0, _, x1, y1 = bounds
    w = int(np.ceil((x1 - x0) / cell - 1e-9))
    h = int(np.ceil((y1 - bounds[1]) / cell - 1e-9))
    if len(buildings) == 0:
        return np.zeros((h, w), dtype=bool)
    tr = Affine(cell, 0, x0, 0, -cell, y1)
    return rasterize(
        ((g, 1) for g in buildings.geometry), out_shape=(h, w), transform=tr, fill=0, dtype="uint8"
    ).astype(bool)
