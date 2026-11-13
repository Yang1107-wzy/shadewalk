import json
import shutil
import subprocess

import geopandas as gpd
import numpy as np
import pytest

from shadewalk.atlas import export_atlas, pack_u8, unpack_u8
from shadewalk.network import build_graph
from shadewalk.pipeline import AreaModel
from shadewalk.region import merge_tiles, tile_areas
from shadewalk.routing import find_route

from .conftest import X0, Y0


def test_pack_roundtrip():
    v = np.array([0.0, 0.5, 1.0, np.nan])
    out = unpack_u8(pack_u8(v, 250), 250)
    assert np.allclose(out[:3], v[:3], atol=0.005) and np.isnan(out[3])


@pytest.fixture
def model(tmp_path, grid_edges, tower):
    e = grid_edges.copy()
    e["shade_1500"] = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
    e["exp_1500"] = (e["length"] * (1 - e["shade_1500"])).astype("float32")
    e["heat"] = 1.0
    e["lst"] = np.nan
    e["name"] = "x"
    meta = {
        "area": {"key": "toy", "title": "Toy", "bbox": [114.1, 22.2, 114.2, 22.3]},
        "date": "2026-07-15",
        "slots": ["15:00"],
        "sun": {"15:00": {"altitude": 55.0, "azimuth": 276.0}},
    }
    return AreaModel(tmp_path, meta, e, tower, build_graph(e))


def test_export_atlas_structure(model, tmp_path):
    p = export_atlas(model, tmp_path / "toy.json")
    d = json.loads(p.read_text())
    assert len(d["nodes"]) == 2 * model.graph.number_of_nodes()
    assert len(d["edges"]["u"]) == 4 == len(d["coords"]["lines"])
    shade = unpack_u8(d["shade"]["15:00"], 250)
    assert shade.tolist() == pytest.approx([1.0, 0.0, 0.0, 0.0])


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_router_matches_python(model, tmp_path):
    p = export_atlas(model, tmp_path / "toy.json")
    nodes = list(model.graph.nodes)
    s = nodes.index(min(nodes, key=lambda n: (n[0] - X0) ** 2 + (n[1] - Y0) ** 2))
    t = nodes.index(min(nodes, key=lambda n: (n[0] - X0 - 100) ** 2 + (n[1] - Y0 - 100) ** 2))
    for lam in (0, 5):
        py = find_route(model.graph, model.edge_table("15:00"), nodes[s], nodes[t], lam)
        out = subprocess.run(
            ["node", "web/tools/route_cli.mjs", str(p), "15:00", str(lam), str(s), str(t)],
            capture_output=True,
            text=True,
            check=True,
        )
        js = json.loads(out.stdout)
        assert js["length"] == pytest.approx(py.length_m, abs=0.2)
        assert js["sunlit"] == pytest.approx(py.sunlit_m, abs=0.5)


def test_tiles_cover_bbox():
    b = (114.16, 22.30, 114.18, 22.32)
    tiles = tile_areas("r", b, tile_m=1000)
    assert len(tiles) == 9
    xs = [t.bbox[0] for t in tiles] + [t.bbox[2] for t in tiles]
    ys = [t.bbox[1] for t in tiles] + [t.bbox[3] for t in tiles]
    assert min(xs) == b[0] and max(xs) == pytest.approx(b[2])
    assert min(ys) == b[1] and max(ys) == pytest.approx(b[3])


def test_merge_tiles_dedupes(tmp_path, grid_edges, tower):
    dirs = []
    for k, rows in enumerate(([0, 1, 2], [2, 3])):
        d = tmp_path / f"t{k}"
        d.mkdir()
        e = grid_edges.iloc[rows].copy()
        e["route_id"] = e.index
        e["lst"] = [30.0 + i for i in rows]
        e["heat"] = 1.0
        e["shade_1500"] = 0.5
        e["exp_1500"] = 0.0
        e.to_parquet(d / "edges.parquet")
        tower.assign(BuildingID=[1]).to_parquet(d / "buildings.parquet")
        (d / "meta.json").write_text(json.dumps({"slots": ["15:00"], "sun": {}, "date": "x"}))
        dirs.append(d)
    out = merge_tiles("m", "Merged", (0, 0, 1, 1), dirs, tmp_path / "out")
    e = gpd.read_parquet(out / "edges.parquet")
    assert len(e) == 4
    assert len(gpd.read_parquet(out / "buildings.parquet")) == 1
    assert e["heat"].between(1, 2).all() and e["exp_1500"].gt(0).all()
