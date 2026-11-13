"""Building shadow geometry from footprints, heights and sun position.

A prism with footprint ``P`` and height ``h`` lit by a sun at altitude ``alt`` and
azimuth ``az`` casts a ground shadow equal to the union of

* the footprint itself,
* the footprint translated by the shadow vector ``d = h / tan(alt)`` pointing away
  from the sun, and
* for every footprint edge, the quadrilateral swept by that edge along ``d``.

This is exact for flat-roofed prisms on flat ground (LoD1), which matches the
LandsD building layer (footprint + ``TopHeight - BaseHeight``).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

__all__ = ["building_shadows", "shadow_vector"]

#: Sun altitudes below this are treated as "no direct sun" (everything shaded).
MIN_SUN_ALTITUDE_DEG = 2.0


def shadow_vector(height: np.ndarray | float, altitude: float, azimuth: float) -> tuple:
    """Return ``(dx, dy)`` ground offset of the shadow tip for objects of ``height`` metres.

    Coordinates are in a projected CRS where +x is east and +y is north.
    """
    if altitude <= 0:
        raise ValueError("sun is below the horizon; no finite shadow vector")
    length = np.asarray(height, dtype=float) / np.tan(np.radians(altitude))
    az = np.radians(azimuth)
    # The sun lies in direction (sin az, cos az); the shadow points the opposite way.
    return -length * np.sin(az), -length * np.cos(az)


def _exterior_rings(geoms: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Explode (multi)polygons into exterior rings with their source index."""
    parts, part_idx = shapely.get_parts(geoms, return_index=True)
    rings = shapely.get_exterior_ring(parts)
    return rings, part_idx


def building_shadows(
    buildings: gpd.GeoDataFrame,
    altitude: float,
    azimuth: float,
    height_col: str = "height",
) -> gpd.GeoDataFrame:
    """Cast one shadow polygon per building.

    Parameters
    ----------
    buildings:
        GeoDataFrame in a *projected* metric CRS with a numeric ``height_col``.
    altitude, azimuth:
        Sun position in degrees (see :func:`shadewalk.sun.solar_position`).

    Returns
    -------
    GeoDataFrame with the same index as ``buildings`` and a ``geometry`` column of
    shadow polygons (footprint included). Returns an empty frame when the sun is
    below :data:`MIN_SUN_ALTITUDE_DEG` - callers should then treat every outdoor
    segment as shaded.
    """
    if buildings.crs is None or not buildings.crs.is_projected:
        raise ValueError("buildings must use a projected CRS in metres")
    if altitude < MIN_SUN_ALTITUDE_DEG or len(buildings) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=buildings.crs)

    b = buildings[buildings[height_col].fillna(0) > 0]
    geoms = shapely.make_valid(b.geometry.to_numpy())
    heights = b[height_col].to_numpy(dtype=float)

    rings, part_idx = _exterior_rings(geoms)
    coords, coord_ring = shapely.get_coordinates(rings, return_index=True)
    dx, dy = shadow_vector(heights[part_idx][coord_ring], altitude, azimuth)

    # Edges: consecutive coordinates within the same ring (rings are closed).
    same_ring = coord_ring[:-1] == coord_ring[1:]
    a = coords[:-1][same_ring]
    c = coords[1:][same_ring]
    da = np.column_stack([dx[:-1][same_ring], dy[:-1][same_ring]])
    quads = np.stack([a, c, c + da, a + da, a], axis=1)  # (n_edges, 5, 2)
    quad_polys = shapely.make_valid(shapely.polygons(quads))
    quad_owner = part_idx[coord_ring[:-1][same_ring]]

    # Footprints translated by their own shadow vector (roof outline on the ground).
    all_xy, all_owner = shapely.get_coordinates(geoms, return_index=True)
    sx, sy = shadow_vector(heights[all_owner], altitude, azimuth)
    shifted = shapely.set_coordinates(
        shapely.from_wkb(shapely.to_wkb(geoms)), all_xy + np.column_stack([sx, sy])
    )

    all_geoms = np.concatenate([geoms, shifted, quad_polys])
    owners = np.concatenate([np.arange(len(geoms)), np.arange(len(geoms)), quad_owner])
    order = np.argsort(owners, kind="stable")
    owners_sorted = owners[order]
    geoms_sorted = all_geoms[order]
    bounds = np.flatnonzero(np.diff(owners_sorted)) + 1
    groups = np.split(geoms_sorted, bounds)
    unioned = [shapely.union_all(g) for g in groups]

    out = gpd.GeoDataFrame({"height": heights}, geometry=unioned, crs=buildings.crs, index=b.index)
    return out
