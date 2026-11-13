"""Pedestrian graph construction and segment sampling."""

from __future__ import annotations

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely

__all__ = ["build_graph", "nearest_node", "sample_points"]


def _node_keys(xy: np.ndarray, snap: float) -> list[tuple[float, float]]:
    q = np.round(xy / snap) * snap
    return [(float(x), float(y)) for x, y in q]


def build_graph(
    edges: gpd.GeoDataFrame, snap: float = 0.5, largest_component: bool = True
) -> nx.MultiDiGraph:
    """Build a directed multigraph from LineString ``edges`` (projected CRS).

    End points within ``snap`` metres are merged into one node. Each edge keeps
    the row index of ``edges`` in ``eid`` so per-time attributes can be joined.
    ``direction`` (1 forward, -1 backward, 0 both, LandsD coding) is respected,
    which matters for escalators such as the Central-Mid-Levels system.
    """
    if edges.crs is None or not edges.crs.is_projected:
        raise ValueError("edges must use a projected CRS in metres")
    geoms = edges.geometry.to_numpy()
    starts = shapely.get_coordinates(shapely.get_point(geoms, 0))
    ends = shapely.get_coordinates(shapely.get_point(geoms, -1))
    u_keys = _node_keys(starts, snap)
    v_keys = _node_keys(ends, snap)
    lengths = edges["length"].to_numpy() if "length" in edges else shapely.length(geoms)
    directions = edges["direction"].to_numpy() if "direction" in edges else np.zeros(len(edges))

    g = nx.MultiDiGraph(crs=str(edges.crs))
    for eid, u, v, length, d in zip(edges.index, u_keys, v_keys, lengths, directions, strict=True):
        if u == v:
            continue
        for key in (u, v):
            if key not in g:
                g.add_node(key, x=key[0], y=key[1])
        if d in (0, 1):
            g.add_edge(u, v, eid=eid, length=float(length), forward=True)
        if d in (0, -1):
            g.add_edge(v, u, eid=eid, length=float(length), forward=False)

    if largest_component and g.number_of_nodes():
        comp = max(nx.weakly_connected_components(g), key=len)
        g = g.subgraph(comp).copy()
    return g


def nearest_node(g: nx.MultiDiGraph, x: float, y: float) -> tuple[float, float]:
    """Graph node closest to projected coordinate ``(x, y)``."""
    nodes = list(g.nodes)
    xy = np.asarray(nodes, dtype=float)
    i = int(np.argmin(((xy - [x, y]) ** 2).sum(axis=1)))
    return nodes[i]


def sample_points(edges: gpd.GeoDataFrame, step: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Evenly spaced sample points along each edge.

    Every edge gets ``max(1, ceil(length / step))`` points at the centres of equal
    sub-segments, so the fraction of points that fall in shadow is an unbiased
    estimate of the fraction of the edge length in shadow.

    Returns ``(points, owner)``, where ``owner[i]`` is the positional index of the edge.
    """
    geoms = edges.geometry.to_numpy()
    lengths = shapely.length(geoms)
    n = np.maximum(1, np.ceil(lengths / step).astype(int))
    owner = np.repeat(np.arange(len(geoms)), n)
    # Position of each sample within its edge: (k + 0.5) / n
    offsets = np.concatenate([(np.arange(k) + 0.5) / k for k in n]) if len(n) else np.array([])
    pts = shapely.line_interpolate_point(geoms[owner], offsets, normalized=True)
    return pts, owner
