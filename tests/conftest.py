"""Synthetic fixtures: a small street grid next to one tall building (no network access)."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

CRS = "EPSG:2326"
X0, Y0 = 835000.0, 815000.0  # somewhere in Hong Kong grid coordinates


@pytest.fixture
def tower() -> gpd.GeoDataFrame:
    """A 60 m tower occupying 20x20 m just east of the western street."""
    return gpd.GeoDataFrame(
        {"height": [60.0], "BuildingNameEN": ["Test Tower"]},
        geometry=[box(X0 + 10, Y0 + 40, X0 + 30, Y0 + 60)],
        crs=CRS,
    )


@pytest.fixture
def grid_edges() -> gpd.GeoDataFrame:
    """Two parallel north-south streets 100 m apart, joined at both ends.

    West street (x = X0) runs next to the tower; east street (x = X0 + 100) is open.
    Horizontal links at y = Y0 and y = Y0 + 100 connect them.
    """
    lines = [
        LineString([(X0, Y0), (X0, Y0 + 100)]),  # 0 west street
        LineString([(X0 + 100, Y0), (X0 + 100, Y0 + 100)]),  # 1 east street
        LineString([(X0, Y0), (X0 + 100, Y0)]),  # 2 south link
        LineString([(X0, Y0 + 100), (X0 + 100, Y0 + 100)]),  # 3 north link
    ]
    gdf = gpd.GeoDataFrame(
        {"covered": [False] * 4, "direction": [0] * 4, "kind": ["Footway"] * 4},
        geometry=lines,
        crs=CRS,
    )
    gdf["length"] = gdf.length
    return gdf
