import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from shadewalk.access import access_summary, dasymetric_population, nearest_access, station_nodes
from shadewalk.network import build_graph, nearest_node

from .conftest import X0, Y0


def _table(edges, shade):
    t = edges[["length"]].copy()
    t["shade"] = shade
    t["exposure"] = edges["length"] * (1 - t["shade"])
    return t


def test_nearest_access_matches_networkx(grid_edges):
    g = build_graph(grid_edges)
    src = {nearest_node(g, X0 + 100, Y0 + 100): "Station"}
    t = _table(grid_edges, np.array([1.0, 0.0, 0.0, 0.0]))
    res = nearest_access(g, t, src, lam=0)
    ref = nx.multi_source_dijkstra_path_length(g.reverse(), set(src), weight="length")
    for n, d in ref.items():
        assert res.loc[[n], "length"].iloc[0] == pytest.approx(d)
    # from SW corner, shortest (lam=0) is a 200 m route; with lam the shaded west street wins
    sw = nearest_node(g, X0, Y0)
    cool = nearest_access(g, t, src, lam=5)
    assert cool.loc[[sw], "sunlit"].iloc[0] == pytest.approx(100.0)
    assert res.loc[[sw], "length"].iloc[0] == pytest.approx(200.0)


def test_station_nodes_from_terminal_ids(grid_edges):
    e = grid_edges.copy()
    e["terminal_id"] = pd.array([pd.NA, 77, pd.NA, pd.NA], dtype="Int64")
    g = build_graph(e)
    term = pd.DataFrame(
        {
            "TerminalID": [77, 88],
            "EnglishName": ["Toy Station", "Bus"],
            "TerminalType": ["MST", "BTE"],
        }
    )
    nodes = station_nodes(g, e, term)
    assert set(nodes.values()) == {"Toy Station"}
    assert len(nodes) == 2


def test_dasymetric_allocation_preserves_totals():
    lsug = gpd.GeoDataFrame(
        {"lsug": ["A"], "pop": [300.0], "pop65": [60.0]}, geometry=[box(0, 0, 100, 100)], crs=2326
    )
    b = gpd.GeoDataFrame(
        {
            "height": [30.0, 10.0, 5.0],
            "Storeys": [10, 2, 1],
            "BuildingBlockType": ["Tower", "Tower", "Open-sided Structure"],
        },
        geometry=[box(10, 10, 20, 20), box(50, 50, 60, 60), box(70, 70, 80, 80)],
        crs=2326,
    )
    p = dasymetric_population(b, lsug)
    assert len(p) == 2
    assert p["pop"].sum() == pytest.approx(300.0)
    assert p["pop"].iloc[0] / p["pop"].iloc[1] == pytest.approx(5.0)  # 10 vs 2 storeys


def test_access_summary(grid_edges):
    # Station at the SE corner. From the SW corner the shortest walk is the sunny
    # 100 m south link; the shaded detour (west, north, east streets) is 300 m.
    g = build_graph(grid_edges)
    src = {nearest_node(g, X0 + 100, Y0): "Station"}
    t = _table(grid_edges, np.array([1.0, 1.0, 0.0, 1.0]))
    people = gpd.GeoDataFrame(
        {"pop": [100.0, 50.0], "pop65": [10.0, 5.0]},
        geometry=[Point(X0 - 5, Y0), Point(X0 + 500, Y0)],
        crs=2326,
    )
    _pts, s = access_summary(g, t, src, people, lam=5, max_snap=80)
    assert s["residents"] == pytest.approx(100.0)
    assert s["excluded_far_from_network"] == pytest.approx(50.0)
    assert s["median_walk_m"] == pytest.approx(105.0)
    assert s["median_sun_m_shortest"] == pytest.approx(100.0)
    assert s["median_sun_m_coolest"] == pytest.approx(0.0)
    assert s["median_extra_walk_m"] == pytest.approx(200.0)
