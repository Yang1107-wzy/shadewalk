"""Spatial statistics for segment-level metrics (numpy/scipy, PySAL-compatible).

* :func:`knn_weights`   - row-standardised k-nearest-neighbour weights (sparse)
* :func:`morans_i`      - global Moran's I with permutation inference
* :func:`local_moran`   - LISA (Anselin 1995) with conditional permutation p-values
* :func:`getis_ord_g`   - Getis-Ord Gi* z-scores (hot/cold spots)
* :func:`ols`           - OLS with standardised coefficients, robust (HC1) SEs and
  Moran's I of residuals, a standard check for remaining spatial dependence

Results agree with ``esda`` (PySAL) to numerical precision; see ``tests/test_stats.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.spatial import cKDTree

__all__ = [
    "GlobalMoran",
    "LagResult",
    "OLSResult",
    "getis_ord_g",
    "knn_weights",
    "local_moran",
    "morans_i",
    "ols",
    "spatial_lag",
]


def knn_weights(xy: np.ndarray, k: int = 8) -> sparse.csr_matrix:
    """Row-standardised kNN spatial weights (self excluded)."""
    xy = np.asarray(xy, dtype=float)
    n = len(xy)
    k = min(k, n - 1)
    _, idx = cKDTree(xy).query(xy, k=k + 1)
    rows = np.repeat(np.arange(n), k)
    cols = idx[:, 1:].ravel()
    w = sparse.csr_matrix((np.full(n * k, 1.0 / k), (rows, cols)), shape=(n, n))
    return w


@dataclass
class GlobalMoran:
    I: float  # noqa: E741 - conventional symbol
    expected: float
    z_sim: float
    p_sim: float
    permutations: int


def morans_i(
    y: np.ndarray, w: sparse.csr_matrix, permutations: int = 999, seed: int | None = 0
) -> GlobalMoran:
    """Global Moran's I (row-standardised W) with a one-sided pseudo p-value."""
    y = np.asarray(y, dtype=float)
    z = y - y.mean()
    n = len(y)
    s0 = w.sum()
    denom = (z * z).sum()

    def stat(v: np.ndarray) -> float:
        return float(n / s0 * (v @ (w @ v)) / denom)

    obs = stat(z)
    rng = np.random.default_rng(seed)
    sims = np.array([stat(rng.permutation(z)) for _ in range(permutations)])
    larger = int((sims >= obs).sum())
    if permutations - larger < larger:
        larger = permutations - larger
    p = (larger + 1.0) / (permutations + 1.0)
    z_sim = (obs - sims.mean()) / sims.std()
    return GlobalMoran(obs, -1.0 / (n - 1), float(z_sim), float(p), permutations)


def local_moran(
    y: np.ndarray, w: sparse.csr_matrix, permutations: int = 999, seed: int | None = 0
) -> pd.DataFrame:
    """Local Moran's I_i, quadrant (1 HH, 2 LH, 3 LL, 4 HL) and conditional-permutation p.

    Implements the same conditional randomisation as ``esda.Moran_Local``: for
    each observation, its neighbours' values are drawn at random from all *other*
    observations.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    z = (y - y.mean()) / y.std()
    lag = w @ z
    m2 = (z * z).sum() / (n - 1)  # (n - 1) normalisation, as in esda.Moran_Local
    Ii = z * lag / m2
    q = np.where(z > 0, np.where(lag > 0, 1, 4), np.where(lag > 0, 2, 3))

    rng = np.random.default_rng(seed)
    w = w.tocsr()
    card = np.diff(w.indptr)
    kmax = int(card.max())
    # Pre-draw neighbour index sets from 0..n-2, shifted to skip self.
    draws = rng.integers(0, n - 1, size=(permutations, kmax))
    larger = np.zeros(n)
    for i in range(n):
        k = card[i]
        if k == 0:
            continue
        wi = w.data[w.indptr[i] : w.indptr[i + 1]]
        cand = draws[:, :k]
        cand = cand + (cand >= i)  # skip self
        sim_lag = (z[cand] * wi).sum(axis=1)
        sim_I = z[i] * sim_lag / m2
        ge = (sim_I >= Ii[i]).sum()
        larger[i] = min(ge, permutations - ge)
    p = (larger + 1.0) / (permutations + 1.0)
    return pd.DataFrame({"Ii": Ii, "quadrant": q, "p_sim": p})


def getis_ord_g(y: np.ndarray, w_binary: sparse.csr_matrix) -> np.ndarray:
    """Getis-Ord Gi* z-scores using binary weights *including* each focal unit.

    Like the G statistic itself, this assumes a non-negative variable (e.g. hours).
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    w = (w_binary != 0).astype(float).tolil()
    w.setdiag(1.0)
    w = w.tocsr()
    xbar = y.mean()
    s = np.sqrt((y**2).mean() - xbar**2)
    wsum = np.asarray(w.sum(axis=1)).ravel()
    w2sum = np.asarray(w.multiply(w).sum(axis=1)).ravel()
    num = w @ y - xbar * wsum
    den = s * np.sqrt((n * w2sum - wsum**2) / (n - 1))
    return num / den


@dataclass
class OLSResult:
    table: pd.DataFrame
    r2: float
    adj_r2: float
    n: int
    residual_moran: GlobalMoran | None

    def __str__(self) -> str:
        head = f"OLS n={self.n} R2={self.r2:.3f} adjR2={self.adj_r2:.3f}"
        if self.residual_moran:
            rm = self.residual_moran
            head += f" | residual Moran's I={rm.I:.3f} (p={rm.p_sim:.3f})"
        return head + "\n" + self.table.round(4).to_string()


def ols(
    df: pd.DataFrame,
    y: str,
    xs: Sequence[str],
    w: sparse.csr_matrix | None = None,
    permutations: int = 199,
) -> OLSResult:
    """OLS on standardised variables, HC1 robust standard errors, residual Moran's I."""
    d = df[[y, *xs]].dropna()
    keep = d.index
    Z = (d - d.mean()) / d.std(ddof=0)
    X = np.column_stack([np.ones(len(Z)), Z[list(xs)].to_numpy()])
    Y = Z[y].to_numpy()
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    n, p = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    meat = X.T @ (X * (resid**2)[:, None])
    cov = xtx_inv @ meat @ xtx_inv * n / (n - p)
    se = np.sqrt(np.diag(cov))
    from scipy import stats as st

    t = beta / se
    pv = 2 * st.t.sf(np.abs(t), n - p)
    r2 = 1 - (resid**2).sum() / ((Y - Y.mean()) ** 2).sum()
    table = pd.DataFrame({"beta_std": beta, "se_hc1": se, "t": t, "p": pv}, index=["const", *xs])
    rm = None
    if w is not None:
        pos = df.index.get_indexer(keep)
        wk = w[pos][:, pos]
        rs = np.asarray(wk.sum(axis=1)).ravel()
        wk = sparse.diags(1.0 / np.where(rs > 0, rs, 1.0)) @ wk
        rm = morans_i(resid, wk.tocsr(), permutations)
    return OLSResult(table, float(r2), float(1 - (1 - r2) * (n - 1) / (n - p)), n, rm)


@dataclass
class LagResult:
    rho: float
    table: pd.DataFrame
    pseudo_r2: float
    n: int

    def __str__(self) -> str:
        return (
            f"Spatial lag (S2SLS) n={self.n} rho={self.rho:.3f} pseudo-R2={self.pseudo_r2:.3f}\n"
            + self.table.round(4).to_string()
        )


def spatial_lag(
    df: pd.DataFrame, y: str, xs: Sequence[str], w: sparse.csr_matrix, w_lags: int = 2
) -> LagResult:
    """Spatial lag model y = rho*Wy + X*beta + e by spatial two-stage least squares.

    Instruments are ``[X, WX, W^2X]`` (Kelejian & Prucha 1998), i.e. the estimator
    implemented by ``spreg.GM_Lag``. Variables are standardised as in :func:`ols`;
    ``w`` must be row-standardised and aligned with ``df`` rows.
    """
    d = df[[y, *xs]]
    if d.isna().any().any():
        raise ValueError("spatial_lag needs complete cases aligned with w")
    Z = (d - d.mean()) / d.std(ddof=0)
    n = len(Z)
    X = np.column_stack([np.ones(n), Z[list(xs)].to_numpy()])
    Y = Z[y].to_numpy()
    wy = w @ Y
    inst = [X]
    lagged = X[:, 1:]
    for _ in range(w_lags):
        lagged = w @ lagged
        inst.append(lagged)
    H = np.column_stack(inst)
    Zr = np.column_stack([X, wy])
    # first stage: project regressors on instruments
    P = H @ np.linalg.lstsq(H, Zr, rcond=None)[0]
    coef = np.linalg.lstsq(P, Y, rcond=None)[0]
    resid = Y - Zr @ coef
    sig2 = (resid @ resid) / n
    cov = sig2 * np.linalg.inv(P.T @ P)
    se = np.sqrt(np.diag(cov))
    from scipy import stats as st

    zval = coef / se
    pv = 2 * st.norm.sf(np.abs(zval))
    table = pd.DataFrame(
        {"coef": coef, "se": se, "z": zval, "p": pv}, index=["const", *xs, "rho (W_y)"]
    )
    yhat = Zr @ coef
    pr2 = float(np.corrcoef(Y, yhat)[0, 1] ** 2)
    return LagResult(float(coef[-1]), table, pr2, n)
