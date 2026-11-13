import numpy as np
import pandas as pd
import pytest

from shadewalk.stats import getis_ord_g, knn_weights, local_moran, morans_i, ols, spatial_lag


@pytest.fixture
def field():
    rng = np.random.default_rng(3)
    xy = rng.uniform(0, 100, size=(400, 2))
    trend = np.sin(xy[:, 0] / 15) + np.cos(xy[:, 1] / 20)
    y = trend + rng.normal(0, 0.3, 400)
    x1 = trend + rng.normal(0, 0.5, 400)
    x2 = rng.normal(size=400)
    return xy, pd.DataFrame({"y": y, "x1": x1, "x2": x2})


def test_moran_detects_autocorrelation_and_randomness(field):
    xy, df = field
    w = knn_weights(xy, 8)
    assert morans_i(df["y"].to_numpy(), w, 199).p_sim < 0.01
    noise = np.random.default_rng(9).normal(size=len(df))
    assert abs(morans_i(noise, w, 199).I) < 0.1


def test_weights_row_standardised(field):
    w = knn_weights(field[0], 5)
    assert np.allclose(np.asarray(w.sum(axis=1)).ravel(), 1.0)
    assert w.diagonal().sum() == 0


def test_against_pysal(field):
    esda = pytest.importorskip("esda")
    libpysal = pytest.importorskip("libpysal")
    xy, df = field
    y = df["y"].to_numpy()
    wl = libpysal.weights.KNN.from_array(xy, k=8)
    wl.transform = "r"
    w = knn_weights(xy, 8)
    assert pytest.approx(esda.Moran(y, wl, permutations=0).I) == morans_i(y, w, 99).I
    ml = esda.Moran_Local(y, wl, permutations=99, seed=1)
    ours = local_moran(y, w, 99)
    assert np.allclose(ours["Ii"], ml.Is)
    assert (ours["quadrant"].to_numpy() == ml.q).all()
    # Gi* is defined for non-negative variables (like sun hours): shift to positive.
    ypos = y - y.min() + 1.0
    wb = libpysal.weights.KNN.from_array(xy, k=8)
    g = esda.G_Local(ypos, wb, star=True, transform="B", permutations=0)
    assert np.allclose(getis_ord_g(ypos, w), g.Zs)


def test_spatial_lag_matches_spreg(field):
    spreg = pytest.importorskip("spreg")
    libpysal = pytest.importorskip("libpysal")
    xy, df = field
    w = knn_weights(xy, 8)
    ours = spatial_lag(df, "y", ["x1", "x2"], w)
    z = (df - df.mean()) / df.std(ddof=0)
    wl = libpysal.weights.KNN.from_array(xy, k=8)
    wl.transform = "r"
    ref = spreg.GM_Lag(z[["y"]].to_numpy(), z[["x1", "x2"]].to_numpy(), w=wl, w_lags=2)
    assert np.allclose(ours.table["coef"].to_numpy(), ref.betas.ravel(), atol=1e-8)
    assert np.allclose(ours.table["se"].to_numpy(), np.sqrt(np.diag(ref.vm)), atol=1e-8)


def test_ols_recovers_coefficients_and_flags_spatial_residuals(field):
    xy, df = field
    w = knn_weights(xy, 8)
    res = ols(df, "y", ["x1", "x2"], w=w, permutations=99)
    assert res.table.loc["x1", "beta_std"] > 0.5
    assert abs(res.table.loc["x2", "beta_std"]) < 0.1
    assert 0 < res.r2 < 1
    assert res.residual_moran is not None and res.residual_moran.I > 0.05
