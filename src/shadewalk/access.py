"""Shade-aware accessibility: how far, and how much in the sun, do residents walk to transit?

Pipeline
--------
1. **Destinations** - station access nodes: end points of pedestrian segments linked
   (``terminal_id``) to MTR stations in the LandsD terminal table.
2. **Dasymetric population** - 2021 census LSUG counts are redistributed to the
   buildings inside each LSUG in proportion to floor area (footprint x storeys),
   giving building-level population and 65+ population.
3. **Multi-source Dijkstra** on the reversed graph, run once for the shortest
   (``lam = 0``) and once for the shade-aware cost, accumulating walking length
   and sunlit metres to the *nearest* station for every node.
4. **Population-weighted summaries**, e.g. the share of older residents whose walk
   to the MTR exceeds 200 m in direct sun at 15:00.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

__all__ = [
    "access_summary",
    "dasymetric_population",
    "nearest_access",
    "station_nodes",
]


def station_nodes(
    graph: nx.MultiDiGraph,
    edges: gpd.GeoDataFrame,
    terminals: pd.DataFrame,
    types: Iterable[str] = ("MST",),
) -> dict:
    """Graph nodes touching segments linked to terminals of ``types`` -> terminal name."""
    t = terminals[terminals["TerminalType"].isin(list(types))]
    names = dict(zip(t["TerminalID"].astype("int64"), t["EnglishName"], strict=True))
    if "terminal_id" not in edges:
        return {}
    tid = edges["terminal_id"]
    linked = set(edges.index[tid.notna() & tid.astype("Int64").isin(list(names))])
    out = {}
    for u, v, d in graph.edges(data=True):
        if d["eid"] in linked:
            name = names[int(tid.loc[d["eid"]])]
            out[u] = name
            out[v] = name
    return out


def dasymetric_population(
    buildings: gpd.GeoDataFrame, lsug: gpd.GeoDataFrame, storey_height: float = 3.0
) -> gpd.GeoDataFrame:
    """Allocate LSUG population to buildings by floor area (building points, EPSG:2326).

    Open-sided and temporary structures receive no residents. Floor area is the
    footprint area times ``Storeys`` (or height / ``storey_height``). LSUG people
    with no eligible building inside are dropped and reported in ``attrs``.
    """
    b = buildings.copy()
    if "BuildingBlockType" in b:
        b = b[~b["BuildingBlockType"].isin(["Open-sided Structure", "Temporary Structure"])]
    storeys = b["Storeys"] if "Storeys" in b else pd.Series(np.nan, index=b.index)
    floors = pd.to_numeric(storeys, errors="coerce").fillna(b["height"] / storey_height)
    b["floor_area"] = b.geometry.area * floors.clip(lower=1)
    pts = gpd.GeoDataFrame(b[["floor_area"]], geometry=b.geometry.representative_point(), crs=b.crs)
    j = gpd.sjoin(pts, lsug[["lsug", "pop", "pop65", "geometry"]], predicate="within", how="inner")
    share = j["floor_area"] / j.groupby("lsug")["floor_area"].transform("sum")
    j["pop"] = j["pop"] * share
    j["pop65"] = j["pop65"] * share
    out = gpd.GeoDataFrame(
        j[["lsug", "floor_area", "pop", "pop65"]], geometry=j.geometry, crs=b.crs
    )
    covered = set(j["lsug"])
    out.attrs["unallocated_pop"] = float(lsug.loc[~lsug["lsug"].isin(covered), "pop"].sum())
    return out


def _multi_source(
    graph: nx.MultiDiGraph, sources: Iterable, length: dict, sun: dict, expo: dict, lam: float
) -> dict:
    """Dijkstra from all sources over *reversed* edges; returns node -> (cost, len, sun, src)."""
    best: dict = {}
    heap: list = []
    counter = 0
    for s in sources:
        heap.append((0.0, counter, s, 0.0, 0.0, s))
        counter += 1
    heapq.heapify(heap)
    pred = graph.pred
    while heap:
        cost, _, node, ln, sn, src = heapq.heappop(heap)
        if node in best:
            continue
        best[node] = (cost, ln, sn, src)
        # walking node -> station: relax edges (u -> node) backwards
        for u, keyed in pred[node].items():
            if u in best:
                continue
            for d in keyed.values():
                e = d["eid"]
                c = cost + length[e] + lam * expo[e]
                counter += 1
                heapq.heappush(heap, (c, counter, u, ln + length[e], sn + sun[e], src))
    return best


def nearest_access(
    graph: nx.MultiDiGraph, edge_table: pd.DataFrame, sources: dict, lam: float
) -> pd.DataFrame:
    """Per node: walking length and sunlit metres to the nearest source under ``lam``."""
    length = edge_table["length"].to_dict()
    sun = (edge_table["length"] * (1 - edge_table["shade"])).to_dict()
    expo = edge_table["exposure"].to_dict()
    res = _multi_source(graph, sources.keys(), length, sun, expo, lam)
    df = pd.DataFrame.from_dict(res, orient="index", columns=["cost", "length", "sunlit", "src"])
    df["station"] = df["src"].map(sources)
    return df.drop(columns="src")


def access_summary(
    graph: nx.MultiDiGraph,
    edge_table: pd.DataFrame,
    sources: dict,
    people: gpd.GeoDataFrame,
    lam: float = 2.0,
    max_snap: float = 80.0,
    sun_threshold: float = 200.0,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Attach shortest/coolest access metrics to building points and summarise.

    Returns ``(people_with_metrics, summary)``. Buildings farther than ``max_snap``
    metres from the network are excluded (reported in the summary).
    """
    nodes = list(graph.nodes)
    xy = np.asarray(nodes, dtype=float)
    pxy = shapely.get_coordinates(people.geometry.to_numpy())
    dist, idx = cKDTree(xy).query(pxy)
    p = people.copy()
    p["snap_m"] = dist
    p["node"] = [nodes[i] for i in idx]
    p = p[p["snap_m"] <= max_snap]

    short = nearest_access(graph, edge_table, sources, 0.0)
    cool = nearest_access(graph, edge_table, sources, lam)
    p["walk_m"] = p["node"].map(short["length"]) + p["snap_m"]
    p["sun_m"] = p["node"].map(short["sunlit"])
    p["cool_walk_m"] = p["node"].map(cool["length"]) + p["snap_m"]
    p["cool_sun_m"] = p["node"].map(cool["sunlit"])
    p["station"] = p["node"].map(short["station"])
    p = p.dropna(subset=["walk_m"])

    def wshare(mask: pd.Series, col: str) -> float:
        tot = p[col].sum()
        return float(p.loc[mask, col].sum() / tot) if tot > 0 else float("nan")

    def wmedian(v: pd.Series, w: pd.Series) -> float:
        o = np.argsort(v.to_numpy())
        cw = np.cumsum(w.to_numpy()[o])
        return float(v.to_numpy()[o][np.searchsorted(cw, cw[-1] / 2)]) if len(cw) else np.nan

    summary = {
        "residents": float(p["pop"].sum()),
        "residents_65plus": float(p["pop65"].sum()),
        "excluded_far_from_network": float(people["pop"].sum() - p["pop"].sum()),
        "median_walk_m": wmedian(p["walk_m"], p["pop"]),
        "share_within_500m": wshare(p["walk_m"] <= 500, "pop"),
        "median_sun_m_shortest": wmedian(p["sun_m"], p["pop"]),
        "median_sun_m_coolest": wmedian(p["cool_sun_m"], p["pop"]),
        "median_extra_walk_m": wmedian(p["cool_walk_m"] - p["walk_m"], p["pop"]),
        f"share_65plus_sun_over_{int(sun_threshold)}m_shortest": wshare(
            p["sun_m"] > sun_threshold, "pop65"
        ),
        f"share_65plus_sun_over_{int(sun_threshold)}m_coolest": wshare(
            p["cool_sun_m"] > sun_threshold, "pop65"
        ),
        "lam": lam,
    }
    return gpd.GeoDataFrame(p.drop(columns="node"), geometry="geometry", crs=people.crs), summary
