"""Folium maps of shadows, segment shade and route comparisons."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

import folium
import geopandas as gpd
import numpy as np
from branca.colormap import LinearColormap

from shadewalk.pipeline import AreaModel, _slot_col
from shadewalk.routing import Route, route_geometry
from shadewalk.shadow import MIN_SUN_ALTITUDE_DEG, building_shadows
from shadewalk.sun import solar_position

__all__ = ["ROUTE_STYLES", "route_map", "shadows_at"]

ROUTE_STYLES = {
    "shortest": {"color": "#d1495b", "weight": 6, "opacity": 0.9},
    "coolest": {"color": "#00798c", "weight": 6, "opacity": 0.9},
}
SHADE_CMAP = LinearColormap(
    ["#f6a01a", "#f3e9c6", "#2e4a7d"], vmin=0, vmax=1, caption="Segment shade fraction"
)


def shadows_at(model: AreaModel, slot: str) -> gpd.GeoDataFrame | None:
    """Recompute building shadows for one time slot (None when the sun is down)."""
    b = model.meta["area"]["bbox"]
    lat, lon = (b[1] + b[3]) / 2, (b[0] + b[2]) / 2
    day = datetime.fromisoformat(model.meta["date"]).date()
    when = datetime.combine(day, time.fromisoformat(slot), tzinfo=ZoneInfo("Asia/Hong_Kong"))
    sp = solar_position(when, lat, lon)
    assert not isinstance(sp, list)
    if sp.altitude < MIN_SUN_ALTITUDE_DEG:
        return None
    return building_shadows(model.buildings, sp.altitude, sp.azimuth)


def route_map(
    model: AreaModel,
    slot: str,
    routes: Sequence[Route] = (),
    labels: Sequence[str] = (),
    show_shadows: bool = True,
    show_segments: bool = True,
    tiles: str = "OpenStreetMap",
) -> folium.Map:
    """Interactive map: shadows, per-segment shade and up to a few routes."""
    slot = model.nearest_slot(slot)
    lat, lon = model.meta["area"]["bbox"][1::2], model.meta["area"]["bbox"][0::2]
    m = folium.Map(
        location=[float(np.mean(lat)), float(np.mean(lon))],
        zoom_start=16,
        tiles=tiles,
        control_scale=True,
    )

    if show_shadows:
        sh = shadows_at(model, slot)
        if sh is not None and len(sh):
            sh4326 = gpd.GeoDataFrame(geometry=sh.geometry.simplify(0.5), crs=sh.crs).to_crs(4326)
            folium.GeoJson(
                sh4326.__geo_interface__,
                name=f"Building shadows {slot}",
                style_function=lambda _f: {
                    "fillColor": "#1f2a44",
                    "color": "none",
                    "fillOpacity": 0.25,
                },
            ).add_to(m)

    if show_segments:
        col = _slot_col("shade", slot)
        seg = model.edges[[col, "kind", "covered", "geometry"]].rename(columns={col: "shade"})
        seg = seg.to_crs(4326)
        folium.GeoJson(
            seg.__geo_interface__,
            name="Segment shade",
            style_function=lambda f: {
                "color": SHADE_CMAP(f["properties"]["shade"]),
                "weight": 2.5,
                "opacity": 0.9,
            },
            tooltip=folium.GeoJsonTooltip(["kind", "shade", "covered"]),
        ).add_to(m)
        SHADE_CMAP.add_to(m)

    for i, r in enumerate(routes):
        label = labels[i] if i < len(labels) else f"lambda={r.lam:g}"
        style = ROUTE_STYLES.get(label.split()[0].lower(), {"color": "#6a4c93", "weight": 5})
        line = gpd.GeoSeries([route_geometry(r, model.edges)], crs=model.edges.crs).to_crs(4326)
        tip = (
            f"<b>{label}</b><br>{r.length_m:,.0f} m, {r.shaded_pct:.0f}% shaded, "
            f"{r.sunlit_m:,.0f} m in sun"
        )
        folium.GeoJson(
            line.__geo_interface__,
            name=label,
            style_function=lambda _f, s=style: s,
            tooltip=folium.Tooltip(tip),
        ).add_to(m)
        coords = list(line.iloc[0].coords)
        if i == 0 and coords:
            folium.CircleMarker(
                coords[0][::-1],
                radius=7,
                color="#222",
                fill=True,
                fill_color="#fff",
                tooltip="Start",
            ).add_to(m)
            folium.CircleMarker(
                coords[-1][::-1],
                radius=7,
                color="#222",
                fill=True,
                fill_color="#222",
                tooltip="End",
            ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m
