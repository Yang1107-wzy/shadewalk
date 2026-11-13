import geopandas as gpd
import numpy as np
import pytest

from shadewalk.exposure import exposure, heat_weight, shade_fraction
from shadewalk.network import build_graph, nearest_node, sample_points
from shadewalk.routing import find_route, pareto_routes, route_geometry
from shadewalk.shadow import building_shadows

from .conftest import X0, Y0


def test_sample_points_are_evenly_spaced(grid_edges):
    pts, owner = sample_points(grid_edges.iloc[[0]], step=10)
    assert len(pts) == 10
    ys = sorted(p.y - Y0 for p in pts)
    assert ys[0] == pytest.approx(5) and ys[-1] == pytest.approx(95)
    assert set(owner) == {0}


def test_morning_sun_shades_west_street_only(tower, grid_edges):
    # Sun in the east at 30 deg: the 60 m tower casts a ~104 m shadow westwards.
    sh = building_shadows(tower, 30.0, 90.0)
    frac = shade_fraction(grid_edges, sh, step=1)
    assert frac[0] == pytest.approx(0.2, abs=0.02)  # tower spans y 40..60 of a 100 m street
    assert frac[1] == 0.0


def test_covered_and_night(grid_edges, tower):
    edges = grid_edges.copy()
    edges.loc[1, "covered"] = True
    sh = building_shadows(tower, 30.0, 90.0)
    assert shade_fraction(edges, sh)[1] == 1.0
    assert np.all(shade_fraction(edges, None) == 1.0)


def test_heat_weight_range_and_missing():
    w = heat_weight(np.array([30.0, 35.0, 40.0, np.nan]), beta=1.0)
    assert w.min() >= 1.0 and w.max() <= 2.0
    assert np.isfinite(w).all()
    assert heat_weight(None) == 1.0


def test_exposure_formula():
    assert exposure(np.array([100.0]), np.array([0.25]), 2.0)[0] == pytest.approx(150.0)


def _table(edges, shade):
    t = edges[["length"]].copy()
    t["shade"] = shade
    t["exposure"] = exposure(edges["length"].to_numpy(), shade)
    t["lst"] = np.nan
    return t


def test_router_prefers_shaded_street_when_lambda_large(grid_edges):
    # West street fully shaded, everything else sunny. Going SW -> NE, both options
    # have equal length (200 m); with lambda > 0 the router must take the west street.
    g = build_graph(grid_edges)
    shade = np.array([1.0, 0.0, 0.0, 0.0])
    t = _table(grid_edges, shade)
    src = nearest_node(g, X0, Y0)
    dst = nearest_node(g, X0 + 100, Y0 + 100)
    r = find_route(g, t, src, dst, lam=5)
    assert 0 in r.edge_ids and 1 not in r.edge_ids
    assert r.length_m == pytest.approx(200)
    assert r.shaded_pct == pytest.approx(50)


def test_lambda_zero_is_shortest_and_detour_tradeoff(grid_edges):
    # From SW corner to SE corner: shortest is the 100 m sunny south link; the shaded
    # alternative (west street + north link + east street) is 300 m.
    edges = grid_edges.copy()
    g = build_graph(edges)
    shade = np.array([1.0, 1.0, 0.0, 1.0])
    t = _table(edges, shade)
    src, dst = nearest_node(g, X0, Y0), nearest_node(g, X0 + 100, Y0)
    assert find_route(g, t, src, dst, lam=0).edge_ids == [2]
    assert find_route(g, t, src, dst, lam=1.5).edge_ids == [2]  # 100+150 < 300
    assert sorted(find_route(g, t, src, dst, lam=3).edge_ids) == [0, 1, 3]  # 400 > 300
    routes = pareto_routes(g, t, src, dst, lams=(0, 1, 3, 10))
    assert len(routes) == 2
    geom = route_geometry(routes[1], edges)
    assert geom.length == pytest.approx(300)
    assert geom.coords[0] == pytest.approx((X0, Y0))


def test_one_way_edges_respected(grid_edges):
    edges = grid_edges.copy()
    edges.loc[2, "direction"] = -1  # south link only walkable east -> west
    g = build_graph(edges)
    src, dst = nearest_node(g, X0, Y0), nearest_node(g, X0 + 100, Y0)
    t = _table(edges, np.zeros(4))
    assert sorted(find_route(g, t, src, dst).edge_ids) == [0, 1, 3]


def test_graph_requires_projected_crs(grid_edges):
    with pytest.raises(ValueError):
        build_graph(grid_edges.to_crs(4326))


def test_snapping_merges_nearby_endpoints(grid_edges):
    edges = grid_edges.copy()
    edges = gpd.GeoDataFrame(
        edges,
        geometry=edges.geometry.translate(0.1, 0.1).where(edges.index != 1, edges.geometry),
        crs=edges.crs,
    )
    g = build_graph(edges, snap=0.5)
    assert g.number_of_nodes() == 4
