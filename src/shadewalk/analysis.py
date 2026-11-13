"""Daily exposure metrics and street-level spatial analysis of a built area.

``daily_metrics`` integrates the per-slot shade columns over the day:

* ``sun_hours``   - hours of direct sun on the segment (length-averaged), sun up only
* ``shade_share`` - mean shaded share between 09:00 and 17:00

``street_analysis`` joins these with morphology and LiDAR street metrics and runs
global/local spatial autocorrelation and an explanatory OLS model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from shadewalk.morphology import morphology
from shadewalk.stats import (
    GlobalMoran,
    LagResult,
    OLSResult,
    getis_ord_g,
    knn_weights,
    local_moran,
    morans_i,
    ols,
    spatial_lag,
)

__all__ = ["StreetAnalysis", "daily_metrics", "street_analysis"]

QUADRANTS = {1: "High-High", 2: "Low-High", 3: "Low-Low", 4: "High-Low"}


def _minutes(slot: str) -> int:
    t = time.fromisoformat(slot)
    return t.hour * 60 + t.minute


def daily_metrics(edges: pd.DataFrame, meta: dict, prefix: str = "shade") -> pd.DataFrame:
    """Sun hours and mean daytime shade per segment from ``<prefix>_HHMM`` columns."""
    slots = list(meta["slots"])
    mins = np.array([_minutes(s) for s in slots])
    step_h = float(np.median(np.diff(mins))) / 60 if len(mins) > 1 else 1.0
    up = np.array([meta["sun"][s]["altitude"] > 0 for s in slots])
    shade = np.column_stack(
        [edges[f"{prefix}_{s.replace(':', '')}"].to_numpy(float) for s in slots]
    )
    sun_hours = ((1 - shade) * up).sum(axis=1) * step_h
    day = (mins >= 9 * 60) & (mins <= 17 * 60)
    return pd.DataFrame(
        {"sun_hours": sun_hours, "shade_share": shade[:, day].mean(axis=1)}, index=edges.index
    )


@dataclass
class StreetAnalysis:
    data: gpd.GeoDataFrame
    moran: GlobalMoran
    regression: OLSResult
    lag: LagResult | None
    variable: str
    lisa_counts: dict

    def layers(self) -> pd.DataFrame:
        """Per-segment analysis outputs indexed by original segment id."""
        cols = ["sun_hours", "shade_share", "lisa_cluster", "gi_star_z", "hw_ratio", "bcr"]
        return self.data.set_index("eid")[[c for c in cols if c in self.data]]

    def summary(self) -> dict:
        return {
            "variable": self.variable,
            "segments": len(self.data),
            "morans_I": round(self.moran.I, 4),
            "morans_p": self.moran.p_sim,
            "lisa_clusters_p05": self.lisa_counts,
            "ols_r2": round(self.regression.r2, 3),
            "ols_residual_morans_I": round(self.regression.residual_moran.I, 4)
            if self.regression.residual_moran
            else None,
            "coefficients": self.regression.table.round(4)
            .reset_index()
            .rename(columns={"index": "term"})
            .to_dict(orient="records"),
            "spatial_lag": None
            if self.lag is None
            else {
                "rho": round(self.lag.rho, 4),
                "pseudo_r2": round(self.lag.pseudo_r2, 3),
                "coefficients": self.lag.table.round(4)
                .reset_index()
                .rename(columns={"index": "term"})
                .to_dict(orient="records"),
            },
        }


def street_analysis(
    edges: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    meta: dict,
    k: int = 8,
    permutations: int = 999,
    min_length: float = 5.0,
) -> StreetAnalysis:
    """Spatial analysis of daily sun exposure on outdoor, uncovered street segments."""
    e = edges[
        (edges["location"] == "Outdoor") & (~edges["covered"]) & (edges["length"] >= min_length)
    ].copy()
    e = pd.concat([e, daily_metrics(e, meta), morphology(e, buildings)], axis=1)
    theta = np.radians(e["orientation"])
    # Street axis orientation enters as a doubled-angle pair (axial data)
    e["ori_ns"] = np.cos(2 * theta)  # +1 N-S street, -1 E-W street
    e["ori_diag"] = np.sin(2 * theta)  # +1 NE-SW, -1 NW-SE
    e["log_hw"] = np.log1p(e["hw_ratio"].clip(upper=10))
    e["eid"] = e.index  # original segment id in ``edges``
    e = gpd.GeoDataFrame(e.reset_index(drop=True), geometry="geometry", crs=edges.crs)

    mid = shapely.line_interpolate_point(e.geometry.to_numpy(), 0.5, normalized=True)
    w = knn_weights(shapely.get_coordinates(mid), k)
    y = e["sun_hours"].to_numpy()
    g = morans_i(y, w, permutations)
    lisa = local_moran(y, w, permutations)
    e["lisa_I"] = lisa["Ii"].to_numpy()
    e["lisa_p"] = lisa["p_sim"].to_numpy()
    e["lisa_cluster"] = np.where(
        lisa["p_sim"] < 0.05, lisa["quadrant"].map(QUADRANTS), "Not significant"
    )
    e["gi_star_z"] = getis_ord_g(y, w)

    xs = ["log_hw", "ori_ns", "ori_diag", "bcr", "mean_height"]
    for extra in ("svf", "tree"):
        if extra in e and e[extra].notna().mean() > 0.9:
            xs.append(extra)
    reg = ols(e, "sun_hours", xs, w=w, permutations=199)
    complete = e[["sun_hours", *xs]].notna().all(axis=1).to_numpy()
    lag = None
    if complete.all():
        lag = spatial_lag(e, "sun_hours", xs, w)
    counts = e["lisa_cluster"].value_counts().to_dict()
    return StreetAnalysis(e, g, reg, lag, "sun_hours", counts)
