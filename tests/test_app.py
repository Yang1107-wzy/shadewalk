"""Headless smoke test of the Streamlit demo against a tiny synthetic area."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("streamlit_folium")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


@pytest.fixture
def built_area(tmp_path, tower, grid_edges, monkeypatch):
    area = tmp_path / "toy"
    area.mkdir()
    edges = grid_edges.copy()
    edges["lst"] = np.nan
    edges["shade_1500"] = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
    edges["exp_1500"] = (edges["length"] * (1 - edges["shade_1500"])).astype("float32")
    edges.to_parquet(area / "edges.parquet")
    tower.to_parquet(area / "buildings.parquet")
    meta = {
        "area": {"key": "toy", "title": "Toy", "bbox": [114.17, 22.28, 114.18, 22.29]},
        "date": "2026-07-15",
        "slots": ["15:00"],
        "sun": {"15:00": {"altitude": 55.0, "azimuth": 276.0}},
    }
    (area / "meta.json").write_text(json.dumps(meta))
    monkeypatch.setenv("SHADEWALK_OUTPUTS", str(tmp_path))
    return area


def test_app_renders_without_points(built_area):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "ShadeWalk HK"
    assert any("0/2 points" in i.value for i in at.info)


def test_app_compares_routes_for_two_points(built_area):
    import geopandas as gpd
    from shapely.geometry import Point

    from .conftest import X0, Y0

    pts = gpd.GeoSeries([Point(X0, Y0), Point(X0 + 100, Y0 + 100)], crs="EPSG:2326").to_crs(4326)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["pts_toy"] = [(p.x, p.y) for p in pts]
    at.run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels[:3] == ["Shortest", "Coolest", "Sunlit walking saved"]
    assert at.metric[0].value == "200 m"
