import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine

from shadewalk.analysis import daily_metrics
from shadewalk.data.lidar import Surface, _mosaic


def _tif(path, arr, x0, y0, res=0.5):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2326",
        nodata=-9999.0,
        transform=Affine(res, 0, x0, 0, -res, y0),
    ) as dst:
        dst.write(arr.astype("float32"), 1)
    return path


def test_mosaic_two_tiles_and_aggregate(tmp_path):
    a = np.zeros((4, 4))
    a[0, 0] = 10.0  # one tall 0.5 m pixel
    b = np.full((4, 4), 2.0)
    b[3, 3] = -9999.0  # nodata
    p1 = _tif(tmp_path / "a.tif", a, 0.0, 2.0)
    p2 = _tif(tmp_path / "b.tif", b, 2.0, 2.0)
    mx, tr = _mosaic([p1, p2], (0, 0, 4, 2), res=1.0, how="max")
    mean, _ = _mosaic([p1, p2], (0, 0, 4, 2), res=1.0, how="mean")
    assert mx.shape == (2, 4) and tr.a == 1.0
    assert mx[0, 0] == 10.0  # max keeps the thin occluder
    assert mean[0, 0] == pytest.approx(2.5)
    assert mean[1, 3] == pytest.approx(2.0)  # NaN ignored inside the block


def test_surface_save_load_roundtrip(tmp_path):
    s = Surface(
        np.ones((3, 3), "float32") * 5, np.zeros((3, 3), "float32"), Affine(1, 0, 100, 0, -1, 200)
    )
    s.save(tmp_path / "surf")
    t = Surface.load(tmp_path / "surf")
    assert np.allclose(t.ndsm, 5) and t.bounds == (100, 197, 103, 200)


def test_daily_metrics():
    meta = {
        "slots": ["08:00", "09:00", "12:00", "17:00", "19:00"],
        "sun": {
            "08:00": {"altitude": 30},
            "09:00": {"altitude": 40},
            "12:00": {"altitude": 85},
            "17:00": {"altitude": 25},
            "19:00": {"altitude": -1},
        },
    }
    e = pd.DataFrame(
        {
            "shade_0800": [0, 1.0],
            "shade_0900": [0, 1.0],
            "shade_1200": [0, 0.5],
            "shade_1700": [0, 1.0],
            "shade_1900": [0, 0.0],
        }
    )
    d = daily_metrics(e, meta)
    # slot length = median gap between slots (gaps 1, 3, 5, 2 h -> 2.5 h)
    step = float(np.median(np.diff([480, 540, 720, 1020, 1140]))) / 60
    assert d.loc[0, "sun_hours"] == pytest.approx(4 * step)  # 19:00 excluded: sun down
    assert d.loc[1, "sun_hours"] == pytest.approx(0.5 * step)
    assert d.loc[1, "shade_share"] == pytest.approx((1 + 0.5 + 1) / 3)
