"""Shortest vs. coolest routes and the distance-exposure trade-off."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString

__all__ = ["Route", "find_route", "pareto_routes", "route_geometry"]


@dataclass
class Route:
    """A walking route and its summary statistics."""

    lam: float
    nodes: list
    edge_ids: list
    length_m: float
    sunlit_m: float
    exposure: float
    shaded_pct: float
    mean_lst_c: float | None = None

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("nodes")
        d.pop("edge_ids")
        return d


def _best_edge(g: nx.MultiDiGraph, u, v, weight) -> dict:
    return min(g[u][v].values(), key=lambda d: weight(u, v, {0: d}))


def find_route(
    g: nx.MultiDiGraph,
    edge_table: pd.DataFrame,
    source,
    target,
    lam: float = 0.0,
    exposure_col: str = "exposure",
    shade_col: str = "shade",
) -> Route:
    """Dijkstra route minimising ``length + lam * exposure``.

    ``edge_table`` is indexed by edge id (``eid`` on graph edges) and must hold
    ``length``, ``exposure_col`` and ``shade_col`` (optionally ``lst``).
    ``lam = 0`` gives the shortest path; larger values trade distance for shade.
    """
    expo = edge_table[exposure_col]
    shade = edge_table[shade_col]
    expo_map = expo.to_dict()

    def weight(u, v, data):
        best = np.inf
        for d in data.values():
            w = d["length"] + lam * expo_map[d["eid"]]
            best = min(best, w)
        return best

    nodes = nx.dijkstra_path(g, source, target, weight=weight)
    eids = [_best_edge(g, u, v, weight)["eid"] for u, v in pairwise(nodes)]
    sub = edge_table.loc[eids]
    length = float(sub["length"].sum())
    sunlit = float((sub["length"] * (1 - shade.loc[eids])).sum())
    lst = None
    if "lst" in sub and sub["lst"].notna().any():
        w = sub["length"].where(sub["lst"].notna(), 0)
        lst = float((sub["lst"].fillna(0) * w).sum() / max(w.sum(), 1e-9))
    return Route(
        lam=lam,
        nodes=nodes,
        edge_ids=eids,
        length_m=length,
        sunlit_m=sunlit,
        exposure=float(expo.loc[eids].sum()),
        shaded_pct=100.0 * (1 - sunlit / length) if length > 0 else 100.0,
        mean_lst_c=lst,
    )


def pareto_routes(
    g: nx.MultiDiGraph,
    edge_table: pd.DataFrame,
    source,
    target,
    lams: Sequence[float] = (0, 0.25, 0.5, 1, 2, 4, 8, 16),
    **kw,
) -> list[Route]:
    """Routes for a sweep of ``lam``; duplicates (same edge sequence) are removed."""
    seen: set[tuple] = set()
    out: list[Route] = []
    for lam in lams:
        r = find_route(g, edge_table, source, target, lam, **kw)
        key = tuple(r.edge_ids)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def route_geometry(route: Route, edges: gpd.GeoDataFrame) -> LineString:
    """Merge the route's edges into one LineString oriented from source to target."""
    coords: list[tuple[float, float]] = []
    for (u, _v), eid in zip(
        zip(route.nodes[:-1], route.nodes[1:], strict=True), route.edge_ids, strict=True
    ):
        line = edges.geometry.loc[eid]
        xy = shapely.get_coordinates(line)
        if np.hypot(*(xy[0] - np.asarray(u))) > np.hypot(*(xy[-1] - np.asarray(u))):
            xy = xy[::-1]
        pts = [tuple(p) for p in xy]
        coords.extend(pts if not coords else pts[1:])
    return LineString(coords) if len(coords) >= 2 else LineString()
