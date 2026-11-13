import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from shadewalk.morphology import canyon_geometry, morphology, neighbourhood_form, orientation


@pytest.fixture
def canyon():
    # N-S street at x = 0 between two 30 m buildings with faces at x = -10 and x = +10
    edges = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (0, 100)]), LineString([(0, 0), (100, 0)])], crs=2326
    )
    b = gpd.GeoDataFrame(
        {"height": [30.0, 30.0]}, geometry=[box(-40, 20, -10, 80), box(10, 20, 40, 80)], crs=2326
    )
    return edges, b


def test_orientation(canyon):
    edges, _ = canyon
    assert orientation(edges).tolist() == pytest.approx([0.0, 90.0])


def test_canyon_width_height_ratio(canyon):
    edges, b = canyon
    c = canyon_geometry(edges, b, max_reach=60)
    assert c.loc[0, "canyon_w"] == pytest.approx(20.0)
    assert c.loc[0, "canyon_h"] == pytest.approx(30.0)
    assert c.loc[0, "hw_ratio"] == pytest.approx(1.5)
    assert c.loc[1, "canyon_h"] == 0.0  # E-W street at y=0 has no buildings beside it


def test_coverage_dissolves_overlaps():
    e = gpd.GeoDataFrame(geometry=[LineString([(-1, 0), (1, 0)])], crs=2326)
    # two identical, fully overlapping footprints covering the whole 50 m disk
    b = gpd.GeoDataFrame({"height": [10.0, 30.0]}, geometry=[box(-60, -60, 60, 60)] * 2, crs=2326)
    f = neighbourhood_form(e, b, radius=50)
    assert f.loc[0, "bcr"] == pytest.approx(1.0, abs=0.01)
    assert f.loc[0, "mean_height"] == pytest.approx(20.0)


def test_morphology_columns(canyon):
    edges, b = canyon
    m = morphology(edges, b)
    assert {"orientation", "canyon_w", "hw_ratio", "bcr", "mean_height", "frontal_area"} <= set(
        m.columns
    )
    assert np.isfinite(m.to_numpy()).all()
