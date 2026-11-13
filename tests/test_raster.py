import numpy as np
import pytest
from affine import Affine

from shadewalk.data.lidar import Surface
from shadewalk.raster import (
    observer_height,
    overhead_cover,
    ray_distances,
    ray_shadow,
    sample,
    shade_grid,
    sky_view_factor,
)


def flat_surface(n=200, res=1.0):
    dtm = np.zeros((n, n), dtype="float32")
    return Surface(dtm.copy(), dtm, Affine(res, 0, 0, 0, -res, n * res))


def with_block(height=20.0, x0=100, x1=110, y0=95, y1=105):
    s = flat_surface()
    n = s.dsm.shape[0]
    s.dsm[n - y1 : n - y0, x0:x1] = height  # rows count from the north
    return s


def test_sample_and_bounds():
    s = with_block()
    assert s.bounds == (0, 0, 200, 200)
    assert sample(s, s.dsm, np.array([105.0]), np.array([100.0]))[0] == 20
    assert np.isnan(sample(s, s.dsm, np.array([-5.0]), np.array([10.0]))[0])


def test_ray_distances_grow_geometrically():
    d = ray_distances(1000, 1.0, rel=0.02)
    assert d[0] == 1.0 and d[-1] >= 1000
    assert len(d) < 250  # far fewer than 1000 unit steps


def test_block_casts_shadow_west_in_the_morning():
    s = with_block(height=20)
    x = np.array([95.0, 85.0, 70.0, 125.0])
    y = np.full(4, 100.0)
    z = observer_height(s, x, y)
    # Sun due east at 45 deg: shadow reaches 20 - 1.6 = 18.4 m west of the block (x = 100)
    sh = ray_shadow(s, x, y, z, 45.0, 90.0)
    assert sh.tolist() == [True, True, False, False]


def test_sun_below_horizon_everything_shaded():
    s = flat_surface()
    assert ray_shadow(s, np.array([10.0]), np.array([10.0]), np.array([1.6]), -3, 90).all()


def test_sky_view_factor_open_vs_canyon():
    s = flat_surface()
    open_svf = sky_view_factor(s, np.array([100.0]), np.array([100.0]), np.array([1.6]))
    assert open_svf[0] == pytest.approx(1.0)
    # deep canyon: 40 m walls 10 m apart along the N-S axis
    c = flat_surface()
    c.dsm[:, 90:95] = 40
    c.dsm[:, 105:110] = 40
    svf = sky_view_factor(c, np.array([100.0]), np.array([100.0]), np.array([1.6]))[0]
    assert 0.0 < svf < 0.5


def test_overhead_cover_under_canopy_not_next_to_wall():
    s = flat_surface()
    s.dsm[90:110, 90:110] = 8.0  # canopy/roof over a 20 m square
    z = np.array([1.6, 1.6])
    cov = overhead_cover(s, np.array([100.0, 150.0]), np.array([100.0, 100.0]), z)
    assert cov.tolist() == [True, False]


def test_shade_grid_shapes_and_mask():
    s = with_block()
    grid, bounds = shade_grid(s, 30.0, 90.0, cell=4.0)
    assert grid.shape == (50, 50)
    assert bounds == (0, 0, 200, 200)
    assert np.nanmax(grid) == 1.0 and np.nanmin(grid) == 0.0
