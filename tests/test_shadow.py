import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box

from shadewalk.shadow import building_shadows, shadow_vector


def test_shadow_vector_length_and_direction():
    dx, dy = shadow_vector(10.0, 45.0, 180.0)  # sun due south -> shadow due north
    assert dx == pytest.approx(0, abs=1e-9)
    assert dy == pytest.approx(10.0)
    dx, dy = shadow_vector(10.0, 45.0, 90.0)  # sun in the east -> shadow to the west
    assert dx == pytest.approx(-10.0)
    assert dy == pytest.approx(0, abs=1e-9)


def test_shadow_vector_rejects_sun_below_horizon():
    with pytest.raises(ValueError):
        shadow_vector(10.0, -1.0, 90.0)


def test_box_shadow_area_matches_analytic():
    b = gpd.GeoDataFrame({"height": [10.0]}, geometry=[box(0, 0, 10, 10)], crs=2326)
    s = building_shadows(b, 45.0, 180.0).geometry.iloc[0]
    assert s.area == pytest.approx(200.0)  # footprint + 10 m shadow strip
    assert s.bounds == pytest.approx((0, 0, 10, 20))


def test_low_sun_long_shadow_scales_with_cot():
    b = gpd.GeoDataFrame({"height": [30.0]}, geometry=[box(0, 0, 10, 10)], crs=2326)
    s = building_shadows(b, 20.0, 270.0).geometry.iloc[0]  # sun west -> shadow east
    expected = 30.0 / np.tan(np.radians(20.0))
    assert s.bounds[2] == pytest.approx(10 + expected, rel=1e-6)


def test_concave_footprint_shadow_covers_notch():
    # U-shaped building opening north; sun from the north casts shadow south.
    u = Polygon([(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)])
    b = gpd.GeoDataFrame({"height": [5.0]}, geometry=[u], crs=2326)
    s = building_shadows(b, 45.0, 0.0).geometry.iloc[0]
    assert s.contains(Point(15, -2))  # south of the building
    assert not s.contains(Point(15, 28))  # inside the notch, near its open end, still lit


def test_sun_below_threshold_returns_empty(tower):
    assert building_shadows(tower, 1.0, 90.0).empty


def test_requires_projected_crs():
    b = gpd.GeoDataFrame({"height": [10.0]}, geometry=[box(0, 0, 1, 1)], crs=4326)
    with pytest.raises(ValueError):
        building_shadows(b, 45.0, 180.0)


def test_zero_height_buildings_ignored():
    b = gpd.GeoDataFrame(
        {"height": [0.0, 10.0]}, geometry=[box(0, 0, 1, 1), box(5, 5, 6, 6)], crs=2326
    )
    out = building_shadows(b, 45.0, 180.0)
    assert list(out.index) == [1]
