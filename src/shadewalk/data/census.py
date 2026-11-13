"""2021 Population Census statistics by Large Subunit Group (LSUG), via CSDI WFS.

Each LSUG polygon carries counts such as ``t_pop`` (total population) and
``age_1`` ... ``age_5`` (five age bands that sum to ``t_pop``). ShadeWalk uses
``age_5`` as the population aged 65 and over. This reading of the band was
checked against the territory-wide share in :func:`check_age_bands` (see docs).

Data (c) Census and Statistics Department, HKSAR Government.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import pandas as pd

from shadewalk.data.csdi import HK_CRS, wfs_features

__all__ = ["CENSUS_DATASET", "check_age_bands", "load_lsug"]

CENSUS_DATASET = "censtatd_rcd_1635933282224_58228"
AGE_COLS = ["age_1", "age_2", "age_3", "age_4", "age_5"]


def _num(s: pd.Series) -> pd.Series:
    """Census tables use '-' for zero / suppressed small counts."""
    return pd.to_numeric(s.replace("-", 0), errors="coerce").fillna(0.0)


def load_lsug(bbox: Sequence[float]) -> gpd.GeoDataFrame:
    """LSUG polygons intersecting ``bbox`` with ``pop`` and ``pop65`` columns (EPSG:2326)."""
    raw = wfs_features(CENSUS_DATASET, "csdi:LSUG_21C", bbox)
    if raw.empty:
        return gpd.GeoDataFrame({"lsug": [], "pop": [], "pop65": []}, geometry=[], crs=HK_CRS)
    g = raw.to_crs(HK_CRS)
    out = gpd.GeoDataFrame(
        {
            "lsug": g.get("lsbg", g.get("LSUG")),
            "pop": _num(g["t_pop"]),
            "pop65": _num(g["age_5"]),
            **{c: _num(g[c]) for c in AGE_COLS if c in g},
        },
        geometry=g.geometry,
        crs=HK_CRS,
    )
    return out.drop_duplicates("lsug").reset_index(drop=True)


def check_age_bands(lsug: gpd.GeoDataFrame) -> dict[str, float]:
    """Share of each age band in total population (sanity check of band meanings)."""
    tot = float(lsug["pop"].sum())
    return {c: float(lsug[c].sum()) / tot for c in AGE_COLS if c in lsug}
