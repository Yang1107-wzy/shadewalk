"""Loaders for Hong Kong Lands Department open data served by the CSDI portal.

* Building (``landsd_rcd_1637211194312_35158``): footprints with ``BaseHeight`` and
  ``TopHeight`` in metres above Hong Kong Principal Datum (mPD).
* 3D Pedestrian Network (``landsd_rcd_1637222018065_52265``): walkable centrelines
  with ``WeatherProof`` (covered), ``Location`` (outdoor/indoor) and ``FeatureType``.

Both are fetched from the portal's OGC WFS 2.0 endpoint with a WGS84 bounding box
and paged with ``startIndex``. Data (c) Lands Department, HKSAR Government, used
under the DATA.GOV.HK terms of use.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from shadewalk.data.cache import cached_get

__all__ = [
    "BUILDING_DATASET",
    "HK_CRS",
    "PEDESTRIAN_DATASET",
    "load_buildings",
    "load_pedestrian_network",
    "load_terminals",
    "wfs_features",
]

HK_CRS = "EPSG:2326"  # Hong Kong 1980 Grid
BUILDING_DATASET = "landsd_rcd_1637211194312_35158"
PEDESTRIAN_DATASET = "landsd_rcd_1637222018065_52265"
_WFS = "https://portal.csdi.gov.hk/server/services/common/{dataset}/MapServer/WFSServer"

# Coded-value domains read from the ArcGIS FeatureServer layer definition.
FEATURE_TYPES = {
    1: "Footway",
    2: "Footbridge",
    4: "Subway",
    5: "Service Lane",
    6: "Traffic Island",
    7: "RunIn",
    8: "Escalator",
    9: "Travelator",
    10: "Lift",
    11: "Ramp",
    12: "Staircase",
    13: "Stairlift",
    14: "Other",
    23: "Park walkway",
    24: "Footpath",
    25: "Village",
    26: "Track",
    30: "Crossing (signalised)",
    31: "Crossing (zebra)",
    32: "Crossing (cautionary)",
    33: "Crossing (other)",
}
LOCATION = {1: "Outdoor", 2: "Indoor", 3: "Paid"}
WEATHERPROOF = {1: "Covered", 2: "NonCovered", 3: "Unclassified"}


def wfs_features(
    dataset: str,
    type_name: str,
    bbox: Sequence[float],
    page_size: int = 2000,
    max_pages: int = 200,
) -> gpd.GeoDataFrame:
    """Fetch all WFS features intersecting ``bbox = (min_lon, min_lat, max_lon, max_lat)``.

    The CSDI WFS expects the WGS84 bbox in latitude/longitude axis order.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    frames: list[gpd.GeoDataFrame] = []
    for page in range(max_pages):
        params = {
            "service": "wfs",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "count": page_size,
            "startIndex": page * page_size,
            "bbox": f"{min_lat},{min_lon},{max_lat},{max_lon},urn:ogc:def:crs:EPSG::4326",
            "outputFormat": "geojson",
        }
        path = cached_get(_WFS.format(dataset=dataset), params, suffix=".geojson")
        payload = json.loads(path.read_bytes())
        features = payload.get("features", [])
        if not features:
            break
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        frames.append(gdf)
        if len(gdf) < page_size:
            break
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    out = pd.concat(frames, ignore_index=True)
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=frames[0].crs or "EPSG:4326")
    key = "OBJECTID" if "OBJECTID" in out.columns else None
    if key:
        out = out.drop_duplicates(subset=key).reset_index(drop=True)
    return out


def load_buildings(bbox: Sequence[float], storey_height: float = 3.0) -> gpd.GeoDataFrame:
    """Building footprints with a ``height`` column (metres above the building base).

    ``height = TopHeight - BaseHeight``; when either is missing, ``Storeys *
    storey_height`` is used and recorded in ``height_source``.
    """
    raw = wfs_features(BUILDING_DATASET, "csdi:Building", bbox)
    if raw.empty:
        return gpd.GeoDataFrame({"height": []}, geometry=[], crs=HK_CRS)
    gdf = raw.to_crs(HK_CRS)
    if "Status" in gdf:
        gdf = gdf[gdf["Status"].fillna("Active") == "Active"]
    top = pd.to_numeric(gdf.get("TopHeight"), errors="coerce")
    base = pd.to_numeric(gdf.get("BaseHeight"), errors="coerce")
    storeys = pd.to_numeric(gdf.get("Storeys"), errors="coerce")
    height = top - base
    source = np.where(height.notna() & (height > 0), "landsd_mpd", "storeys")
    height = height.where(height > 0, storeys * storey_height)
    keep = [
        c
        for c in ("BuildingID", "BuildingNameEN", "BuildingNameTC", "BuildingBlockType")
        if c in gdf.columns
    ]
    out = gpd.GeoDataFrame(gdf[keep].copy(), geometry=gdf.geometry, crs=HK_CRS)
    out["base_mpd"] = base
    out["height"] = height.astype(float)
    out["height_source"] = source
    out = out[out["height"].notna() & (out["height"] > 0)].reset_index(drop=True)
    return out


def load_pedestrian_network(bbox: Sequence[float], include_paid: bool = False) -> gpd.GeoDataFrame:
    """Pedestrian route centrelines exploded to LineStrings in EPSG:2326.

    Adds boolean ``covered`` (weather-proof, indoor, paid area or subway) and a
    readable ``kind``. Disabled segments are dropped, and so are segments inside
    fare-paid areas (e.g. MTR concourses) unless ``include_paid`` is true, because
    walking through them requires a ticket.
    """
    raw = wfs_features(PEDESTRIAN_DATASET, "csdi:PedestrianRoute", bbox)
    if raw.empty:
        return gpd.GeoDataFrame(geometry=[], crs=HK_CRS)
    gdf = raw.to_crs(HK_CRS)
    if "Enabled" in gdf:
        gdf = gdf[pd.to_numeric(gdf["Enabled"], errors="coerce").fillna(1) == 1]
    if not include_paid and "Location" in gdf:
        gdf = gdf[pd.to_numeric(gdf["Location"], errors="coerce").fillna(1) != 3]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    ftype = pd.to_numeric(gdf.get("FeatureType"), errors="coerce").fillna(14).astype(int)
    loc = pd.to_numeric(gdf.get("Location"), errors="coerce").fillna(1).astype(int)
    wp = pd.to_numeric(gdf.get("WeatherProof"), errors="coerce").fillna(3).astype(int)
    direction = pd.to_numeric(gdf.get("Direction"), errors="coerce").fillna(0).astype(int)
    name = gdf.get("StreetNameEN", pd.Series(index=gdf.index, dtype=object))
    alias = gdf.get("AliasNameEN", pd.Series(index=gdf.index, dtype=object))
    out = gpd.GeoDataFrame(
        {
            "route_id": gdf.get("PedestrianRouteID", gdf.get("OBJECTID")),
            "feature_type": ftype,
            "kind": ftype.map(FEATURE_TYPES).fillna("Other"),
            "location": loc.map(LOCATION).fillna("Outdoor"),
            "weatherproof": wp.map(WEATHERPROOF).fillna("Unclassified"),
            "direction": direction,
            "name": name.fillna(alias),
            "terminal_id": pd.to_numeric(gdf.get("TerminalID"), errors="coerce").astype("Int64"),
        },
        geometry=gdf.geometry.force_2d(),
        crs=HK_CRS,
    )
    out["covered"] = (wp == 1) | (loc != 1) | (ftype == 4)
    out["length"] = out.geometry.length
    return out[out["length"] > 0.01].reset_index(drop=True)


TERMINAL_TYPES = {
    "MST": "MTR station",
    "LRS": "Light Rail stop",
    "BTE": "Bus terminus",
    "MBT": "Minibus terminus",
    "TTE": "Taxi stand",
    "TST": "Tram stop",
    "FTE": "Ferry pier",
    "ATE": "Airport",
    "CCS": "Cross-boundary checkpoint",
    "PTS": "Peak Tram station",
}


def load_terminals(page_size: int = 1000) -> pd.DataFrame:
    """Transport terminals linked from the pedestrian network (``TerminalID``).

    Read from the ArcGIS FeatureServer relation table of the 3D Pedestrian Network.
    ``TerminalType`` codes are expanded in ``type_name`` (e.g. MST = MTR station).
    """
    url = (
        "https://portal.csdi.gov.hk/server/rest/services/common/"
        f"{PEDESTRIAN_DATASET}/FeatureServer/1000/query"
    )
    rows: list[dict] = []
    for offset in range(0, 100 * page_size, page_size):
        params = {
            "where": "1=1",
            "outFields": "TerminalID,EnglishName,ChineseName,TerminalType",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "json",
        }
        feats = json.loads(cached_get(url, params, suffix=".json").read_bytes()).get("features", [])
        rows.extend(f["attributes"] for f in feats)
        if len(feats) < page_size:
            break
    df = pd.DataFrame(rows)
    if not df.empty:
        df["TerminalID"] = df["TerminalID"].astype("int64")
        df["type_name"] = df["TerminalType"].map(TERMINAL_TYPES).fillna(df["TerminalType"])
    return df
