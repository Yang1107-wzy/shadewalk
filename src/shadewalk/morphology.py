"""Urban morphology descriptors for street segments.

* ``orientation``  - street axis bearing in [0, 180) degrees (0 = N-S, 90 = E-W)
* ``canyon_w``     - street canyon width: distance between the first building
  faces hit by rays cast perpendicular to the segment on both sides (capped)
* ``canyon_h``     - mean height of those two buildings (0 when open)
* ``hw_ratio``     - canyon aspect ratio H/W, the classic urban-climate descriptor
* ``bcr``          - building coverage ratio within ``radius`` metres
* ``mean_height``  - footprint-area-weighted building height within ``radius``
* ``frontal_area`` - frontal area index facing south-west (afternoon sun), within ``radius``
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

__all__ = ["canyon_geometry", "morphology", "neighbourhood_form", "orientation"]


def orientation(edges: gpd.GeoDataFrame) -> np.ndarray:
    """Axis bearing of each segment (start->end chord), folded into [0, 180)."""
    g = edges.geometry.to_numpy()
    a = shapely.get_coordinates(shapely.get_point(g, 0))
    b = shapely.get_coordinates(shapely.get_point(g, -1))
    dx, dy = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
    return np.mod(np.degrees(np.arctan2(dx, dy)), 180.0)


def canyon_geometry(
    edges: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, max_reach: float = 60.0
) -> pd.DataFrame:
    """Canyon width/height from perpendicular rays at each segment midpoint."""
    g = edges.geometry.to_numpy()
    mid = shapely.line_interpolate_point(g, 0.5, normalized=True)
    mxy = shapely.get_coordinates(mid)
    bearing = np.radians(orientation(edges))
    # unit normal to the street axis
    nx_, ny_ = np.cos(bearing), -np.sin(bearing)
    tree = shapely.STRtree(buildings.geometry.to_numpy())
    heights = buildings["height"].to_numpy(dtype=float)
    dist = np.full((len(g), 2), max_reach)
    hgt = np.zeros((len(g), 2))
    for side, sgn in enumerate((1.0, -1.0)):
        ends = mxy + sgn * max_reach * np.column_stack([nx_, ny_])
        rays = shapely.linestrings(np.stack([mxy, ends], axis=1))
        ray_idx, bld_idx = tree.query(rays, predicate="intersects")
        if len(ray_idx) == 0:
            continue
        inter = shapely.intersection(rays[ray_idx], buildings.geometry.to_numpy()[bld_idx])
        d = shapely.distance(mid[ray_idx], inter)
        df = pd.DataFrame({"ray": ray_idx, "d": d, "h": heights[bld_idx]})
        df = df[df["d"] > 0.05]  # midpoint inside a footprint -> ignore that building
        first = df.sort_values("d").groupby("ray", sort=False).first()
        dist[first.index.to_numpy(), side] = first["d"].to_numpy()
        hgt[first.index.to_numpy(), side] = first["h"].to_numpy()
    width = np.maximum(dist.sum(axis=1), 3.0)  # at least a footway's width
    h_mean = hgt.mean(axis=1)
    return pd.DataFrame(
        {"canyon_w": width, "canyon_h": h_mean, "hw_ratio": h_mean / width},
        index=edges.index,
    )


def neighbourhood_form(
    edges: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, radius: float = 50.0
) -> pd.DataFrame:
    """Building coverage, mean height and SW frontal-area index around each midpoint."""
    mid = shapely.line_interpolate_point(edges.geometry.to_numpy(), 0.5, normalized=True)
    disks = shapely.buffer(mid, radius, quad_segs=8)
    area = np.pi * radius**2
    bgeom = buildings.geometry.to_numpy()
    heights = buildings["height"].to_numpy(dtype=float)
    tree = shapely.STRtree(bgeom)
    di, bi = tree.query(disks, predicate="intersects")
    inter_area = shapely.area(shapely.intersection(disks[di], bgeom[bi]))
    # Coverage uses dissolved footprints: LandsD towers often sit on podiums whose
    # footprints overlap, which would otherwise double-count ground coverage.
    parts = shapely.get_parts(shapely.union_all(shapely.make_valid(bgeom)))
    ptree = shapely.STRtree(parts)
    dj, pj = ptree.query(disks, predicate="intersects")
    cover_area = shapely.area(shapely.intersection(disks[dj], parts[pj]))
    # Frontal area towards the SW (azimuth 225 deg): projected width x height
    minx, miny, maxx, maxy = shapely.bounds(bgeom[bi]).T
    proj_width = ((maxx - minx) + (maxy - miny)) / np.sqrt(2)
    frac_in = inter_area / np.maximum(shapely.area(bgeom[bi]), 1e-9)
    frontal = proj_width * heights[bi] * frac_in
    n = len(edges)
    cov = np.bincount(di, weights=inter_area, minlength=n)
    ground = np.bincount(dj, weights=cover_area, minlength=n)
    hsum = np.bincount(di, weights=inter_area * heights[bi], minlength=n)
    fai = np.bincount(di, weights=frontal, minlength=n) / area
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_h = np.where(cov > 0, hsum / cov, 0.0)
    return pd.DataFrame(
        {"bcr": ground / area, "mean_height": mean_h, "frontal_area": fai}, index=edges.index
    )


def morphology(
    edges: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, radius: float = 50.0
) -> pd.DataFrame:
    """All morphology descriptors as a DataFrame aligned with ``edges``."""
    out = pd.concat(
        [canyon_geometry(edges, buildings), neighbourhood_form(edges, buildings, radius)], axis=1
    )
    out.insert(0, "orientation", orientation(edges))
    return out
