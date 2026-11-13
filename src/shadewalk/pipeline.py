"""End-to-end build of an area model and loading it back for routing.

``build_area`` writes to ``<out>/<area>/``:

* ``buildings.parquet`` - footprints with heights (EPSG:2326)
* ``edges.parquet``     - pedestrian segments with static attributes, ``lst``,
  ``heat`` and per time slot ``shade_HHMM`` / ``exp_HHMM`` columns
* ``lst.tif``           - summer LST composite clipped to the area (optional)
* ``meta.json``         - provenance, parameters, time slots and solar angles
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd

from shadewalk import __version__
from shadewalk.areas import Area
from shadewalk.data.csdi import HK_CRS, load_buildings, load_pedestrian_network
from shadewalk.exposure import edge_lst, exposure, heat_weight, shade_fraction
from shadewalk.network import build_graph, nearest_node
from shadewalk.routing import Route, find_route, pareto_routes
from shadewalk.shadow import MIN_SUN_ALTITUDE_DEG, building_shadows
from shadewalk.sun import solar_position

__all__ = ["AreaModel", "build_area", "load_area", "time_slots"]

HK_TZ = ZoneInfo("Asia/Hong_Kong")


def time_slots(start: str = "07:00", end: str = "19:00", step_min: int = 30) -> list[str]:
    """``["07:00", "07:30", ...]`` inclusive of ``end``."""
    t0 = datetime.combine(date.today(), time.fromisoformat(start))
    t1 = datetime.combine(date.today(), time.fromisoformat(end))
    out = []
    while t0 <= t1:
        out.append(t0.strftime("%H:%M"))
        t0 += timedelta(minutes=step_min)
    return out


def _slot_col(prefix: str, slot: str) -> str:
    return f"{prefix}_{slot.replace(':', '')}"


def build_area(
    area: Area,
    day: date,
    slots: Sequence[str] | None = None,
    out_dir: Path = Path("outputs"),
    with_lst: bool = True,
    beta: float = 1.0,
    step: float = 2.0,
    buffer_deg: float = 0.004,
    lidar: bool = False,
    lidar_res: float = 1.0,
    with_ndvi: bool = True,
    log=print,
) -> Path:
    """Download data for ``area`` and precompute shade/exposure for each time slot.

    With ``lidar=True`` the CEDD 2020 LiDAR DSM/DTM is used to add trees, terrain and
    overhead structures to the shade model (columns ``shade_*``), while the exact
    building-only vector model is kept as ``bshade_*`` for comparison. Static
    street metrics ``svf``, ``cover``, ``tree`` and ``ndvi`` are added as well.
    """
    slots = list(slots or time_slots())
    target = out_dir / area.key
    target.mkdir(parents=True, exist_ok=True)

    # Buildings outside the area can shade streets inside it: fetch a buffered bbox.
    b = area.bbox
    bbox_buf = (b[0] - buffer_deg, b[1] - buffer_deg, b[2] + buffer_deg, b[3] + buffer_deg)
    log(f"[1/4] LandsD buildings for {area.title} ...")
    buildings = load_buildings(bbox_buf)
    log(f"      {len(buildings):,} buildings, median height {buildings['height'].median():.1f} m")
    log("[2/4] LandsD 3D pedestrian network ...")
    edges = load_pedestrian_network(area.bbox)
    log(
        f"      {len(edges):,} segments, {edges['length'].sum() / 1000:.1f} km, "
        f"{edges['covered'].mean() * 100:.0f}% covered/indoor"
    )

    lst_vals = None
    lst_scenes = None
    if with_lst:
        log("[3/4] Landsat summer LST composite ...")
        try:
            from shadewalk.data.lst import summer_lst

            src = summer_lst(bbox_buf)
            shutil.copyfile(src, target / "lst.tif")
            lst_vals = edge_lst(edges, target / "lst.tif")
            import rasterio

            with rasterio.open(target / "lst.tif") as ds:
                lst_scenes = ds.tags().get("scenes", "").split(",")
            log(
                f"      {len(lst_scenes)} scenes, street LST p10-p90 "
                f"{np.nanpercentile(lst_vals, 10):.1f}-{np.nanpercentile(lst_vals, 90):.1f} C"
            )
        except Exception as exc:  # pragma: no cover - network dependent
            log(f"      LST skipped: {exc}")
    else:
        log("[3/4] LST disabled")
    edges["lst"] = lst_vals if lst_vals is not None else np.nan
    edges["heat"] = heat_weight(lst_vals, beta) if lst_vals is not None else 1.0

    pts = surface = None
    ndvi_scenes = None
    if lidar:
        from shadewalk.data.lidar import load_surface
        from shadewalk.streetscape import static_metrics, street_points

        log(f"[3b] CEDD LiDAR surface at {lidar_res:g} m ...")
        surface = load_surface(bbox_buf, res=lidar_res, log=log)
        surface.save(target / "surface")
        ndvi_path = None
        if with_ndvi:
            try:
                from shadewalk.data.sentinel import summer_ndvi

                ndvi_path = target / "ndvi.tif"
                shutil.copyfile(summer_ndvi(bbox_buf), ndvi_path)
                import rasterio

                with rasterio.open(ndvi_path) as ds:
                    ndvi_scenes = ds.tags().get("scenes", "").split(",")
            except Exception as exc:  # pragma: no cover - network dependent
                log(f"      NDVI skipped: {exc}")
                ndvi_path = None
        pts = street_points(edges, surface, step)
        for k, v in static_metrics(pts, surface, ndvi_path).items():
            edges[k] = v.astype("float32")
        log(
            f"      street SVF median {np.nanmedian(edges['svf']):.2f}, overhead cover "
            f"{np.average(edges['cover'].fillna(0), weights=edges['length']) * 100:.0f}%"
        )

    log(f"[4/4] Shadows for {len(slots)} time slots on {day.isoformat()} ...")
    lat, lon = area.center
    sun_meta = {}
    new_cols: dict[str, np.ndarray] = {}
    for slot in slots:
        when = datetime.combine(day, time.fromisoformat(slot), tzinfo=HK_TZ)
        sp = solar_position(when, lat, lon)
        assert not isinstance(sp, list)
        if sp.altitude < MIN_SUN_ALTITUDE_DEG:
            bshade = shade_fraction(edges, None)
        else:
            shadows = building_shadows(buildings, sp.altitude, sp.azimuth)
            bshade = shade_fraction(edges, shadows, step=step)
        if pts is not None and surface is not None:
            from shadewalk.streetscape import slot_shade

            alt = sp.altitude if sp.altitude >= MIN_SUN_ALTITUDE_DEG else 0.0
            shade = slot_shade(pts, surface, alt, sp.azimuth)
            new_cols[_slot_col("bshade", slot)] = bshade.astype("float32")
        else:
            shade = bshade
        new_cols[_slot_col("shade", slot)] = shade.astype("float32")
        new_cols[_slot_col("exp", slot)] = exposure(
            edges["length"].to_numpy(), shade, edges["heat"].to_numpy()
        ).astype("float32")
        sun_meta[slot] = {"altitude": round(sp.altitude, 3), "azimuth": round(sp.azimuth, 3)}
    edges = pd.concat([edges, pd.DataFrame(new_cols, index=edges.index)], axis=1)
    edges = gpd.GeoDataFrame(edges, geometry="geometry", crs=HK_CRS)

    buildings.to_parquet(target / "buildings.parquet")
    edges.to_parquet(target / "edges.parquet")
    meta = {
        "shadewalk_version": __version__,
        "area": {"key": area.key, "title": area.title, "bbox": list(area.bbox)},
        "date": day.isoformat(),
        "timezone": "Asia/Hong_Kong",
        "slots": slots,
        "sun": sun_meta,
        "params": {
            "beta": beta,
            "sample_step_m": step,
            "building_buffer_deg": buffer_deg,
            "shade_model": "lidar" if lidar else "vector",
            "lidar_res_m": lidar_res,
        },
        "counts": {"buildings": len(buildings), "edges": len(edges)},
        "lst_scenes": lst_scenes,
        "ndvi_scenes": ndvi_scenes,
        "built_at": datetime.now(HK_TZ).isoformat(timespec="seconds"),
        "sources": {
            "buildings": "LandsD Building (CSDI landsd_rcd_1637211194312_35158)",
            "network": "LandsD 3D Pedestrian Network (CSDI landsd_rcd_1637222018065_52265)",
            "lst": "Landsat 8/9 C2 L2 ST via Microsoft Planetary Computer" if lst_scenes else None,
            "surface": "CEDD 2020 LiDAR DSM/DTM (CSDI cedd_rcd_1629267205233_87895)"
            if lidar
            else None,
            "ndvi": "Sentinel-2 L2A via Microsoft Planetary Computer" if ndvi_scenes else None,
        },
    }
    (target / "meta.json").write_text(json.dumps(meta, indent=2))
    log(f"Done -> {target}")
    return target


@dataclass
class AreaModel:
    """A built area ready for routing."""

    path: Path
    meta: dict
    edges: gpd.GeoDataFrame
    buildings: gpd.GeoDataFrame
    graph: nx.MultiDiGraph = field(repr=False)

    @property
    def slots(self) -> list[str]:
        return list(self.meta["slots"])

    def nearest_slot(self, hhmm: str) -> str:
        t = time.fromisoformat(hhmm)
        mins = t.hour * 60 + t.minute

        def dist(s: str) -> int:
            st = time.fromisoformat(s)
            return abs(st.hour * 60 + st.minute - mins)

        return min(self.slots, key=dist)

    def edge_table(self, slot: str) -> pd.DataFrame:
        slot = self.nearest_slot(slot)
        t = self.edges[["length", "lst", "covered"]].copy()
        t["shade"] = self.edges[_slot_col("shade", slot)].astype(float)
        t["exposure"] = self.edges[_slot_col("exp", slot)].astype(float)
        return t

    def study_polygon(self):
        """The area's bbox as a polygon in EPSG:2326 (for clipping analyses)."""
        from shapely.geometry import box

        b = self.meta["area"]["bbox"]
        return gpd.GeoSeries([box(*b)], crs="EPSG:4326").to_crs(HK_CRS).iloc[0]

    def node_at(self, lon: float, lat: float):
        p = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs="EPSG:4326").to_crs(HK_CRS)
        return nearest_node(self.graph, float(p.x.iloc[0]), float(p.y.iloc[0]))

    def find_place(self, query: str) -> tuple[float, float]:
        """Resolve ``"lon,lat"`` or a (partial, case-insensitive) LandsD building name."""
        try:
            lon, lat = (float(v) for v in query.split(","))
            return lon, lat
        except ValueError:
            pass
        names = self.buildings["BuildingNameEN"].fillna("")
        hits = self.buildings[names.str.contains(query, case=False, regex=False)]
        if hits.empty:
            raise ValueError(f"no building named like {query!r} in {self.meta['area']['key']}")
        c = hits.geometry.iloc[0].representative_point()
        p = gpd.GeoSeries([c], crs=HK_CRS).to_crs("EPSG:4326").iloc[0]
        return float(p.x), float(p.y)

    def route(
        self, origin: tuple[float, float], dest: tuple[float, float], slot: str, lam: float = 0.0
    ) -> Route:
        return find_route(
            self.graph, self.edge_table(slot), self.node_at(*origin), self.node_at(*dest), lam
        )

    def compare(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        slot: str,
        lams: Sequence[float] = (0, 0.25, 0.5, 1, 2, 4, 8, 16),
    ) -> list[Route]:
        return pareto_routes(
            self.graph, self.edge_table(slot), self.node_at(*origin), self.node_at(*dest), lams
        )


def load_area(path: Path | str) -> AreaModel:
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    edges = gpd.read_parquet(path / "edges.parquet")
    buildings = gpd.read_parquet(path / "buildings.parquet")
    graph = build_graph(edges)
    return AreaModel(path, meta, edges, buildings, graph)
