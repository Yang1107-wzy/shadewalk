"""Export built areas to compact JSON for the static web atlas (``web/``).

The format is designed for a serverless MapLibre front-end that does its own
routing in the browser:

* ``nodes``   - flat ``[lon, lat, ...]`` (1e-6 deg ~ 0.1 m)
* ``edges``   - parallel arrays ``u``, ``v``, ``len`` (dm), ``dir``, ``covered``
* ``coords``  - per-edge polylines as flat micro-degree integer offsets
* ``shade``   - one base64 ``uint8`` string per time slot (0-250 = shade 0-1)
* ``heat``    - base64 ``uint8`` LST weight ((w - 1) * 250)
* ``layers``  - optional static per-edge layers (``sun_hours``, ``svf``, ``tree``,
  ``lisa``) as base64 ``uint8`` with a declared scale
* ``stations``- MTR access nodes ``[{name, nodes:[...]}]``

A Mong Kok-sized area (~10k segments, 25 slots) exports to roughly 1.5 MB.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from shadewalk.pipeline import AreaModel

__all__ = ["LISA_CODES", "export_atlas", "pack_u8", "unpack_u8"]

LISA_CODES = {"Not significant": 0, "High-High": 1, "Low-High": 2, "Low-Low": 3, "High-Low": 4}


def pack_u8(values: np.ndarray, scale: float, offset: float = 0.0) -> str:
    """Quantise ``(values - offset) * scale`` to uint8 (NaN -> 255) and base64-encode."""
    v = (np.asarray(values, dtype=float) - offset) * scale
    q = np.where(np.isfinite(v), np.clip(np.round(v), 0, 254), 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode("ascii")


def unpack_u8(s: str, scale: float, offset: float = 0.0) -> np.ndarray:
    q = np.frombuffer(base64.b64decode(s), dtype=np.uint8).astype(float)
    out = q / scale + offset
    out[q == 255] = np.nan
    return out


def export_atlas(
    model: AreaModel, out: Path, layers: pd.DataFrame | None = None, stations: dict | None = None
) -> Path:
    """Write ``out`` (JSON) for ``model``; ``layers`` is indexed like ``model.edges``."""
    e = model.edges.to_crs(4326)
    nodes = list(model.graph.nodes)
    node_index = {n: i for i, n in enumerate(nodes)}
    node_ll = _nodes_lonlat(nodes, str(model.edges.crs))

    # One record per *segment* (not per direction), oriented as digitised.
    seg: dict[int, tuple[int, int]] = {}
    for u, v, d in model.graph.edges(data=True):
        eid = d["eid"]
        if eid not in seg:
            a, b = (u, v) if d.get("forward", True) else (v, u)
            seg[eid] = (node_index[a], node_index[b])
    eids = sorted(seg)
    direction = (
        model.edges.loc[eids, "direction"].to_numpy()
        if "direction" in model.edges
        else np.zeros(len(eids))
    )

    geoms = e.geometry.loc[eids].to_numpy()
    coords, owner = shapely.get_coordinates(geoms, return_index=True)
    q = np.round(coords * 1e6).astype(np.int64)
    base = q.min(axis=0)
    rel = q - base
    starts = np.searchsorted(owner, np.arange(len(eids)))
    ends = np.append(starts[1:], len(owner))
    polylines = [rel[s:t].ravel().tolist() for s, t in zip(starts, ends, strict=True)]

    slots = model.slots
    payload = {
        "version": 1,
        "meta": {
            "key": model.meta["area"]["key"],
            "title": model.meta["area"]["title"],
            "date": model.meta["date"],
            "slots": slots,
            "sun": model.meta["sun"],
            "bbox": model.meta["area"]["bbox"],
            "shade_model": model.meta.get("params", {}).get("shade_model", "vector"),
        },
        "nodes": np.round(np.asarray(node_ll), 6).ravel().tolist(),
        "edges": {
            "u": [seg[i][0] for i in eids],
            "v": [seg[i][1] for i in eids],
            "len": np.round(model.edges.loc[eids, "length"].to_numpy() * 10).astype(int).tolist(),
            "dir": [int(direction[k]) for k in range(len(eids))],
            "covered": model.edges.loc[eids, "covered"].astype(int).tolist(),
            "name": model.edges.loc[eids, "name"].fillna("").astype(str).tolist()
            if "name" in model.edges
            else [""] * len(eids),
        },
        "coords": {"base": base.tolist(), "lines": polylines},
        "shade": {
            s: pack_u8(model.edges.loc[eids, f"shade_{s.replace(':', '')}"], 250) for s in slots
        },
        "heat": pack_u8(
            model.edges.loc[eids, "heat"].fillna(1.0)
            if "heat" in model.edges
            else np.ones(len(eids)),
            250,
            1.0,
        ),
        "layers": {},
        "stations": [],
    }
    if layers is not None:
        specs = {"sun_hours": 20.0, "svf": 250.0, "tree": 250.0, "lisa": 1.0}
        for col, scale in specs.items():
            if col in layers:
                vals = layers[col].reindex(eids)
                if col == "lisa":
                    vals = vals.map(LISA_CODES)
                payload["layers"][col] = {"scale": scale, "data": pack_u8(vals, scale)}
    if stations:
        by_name: dict[str, list[int]] = {}
        for n, name in stations.items():
            if n in node_index:
                by_name.setdefault(name, []).append(node_index[n])
        payload["stations"] = [{"name": k, "nodes": v} for k, v in sorted(by_name.items())]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")))
    return out


def _nodes_lonlat(nodes: list, crs: str) -> np.ndarray:
    from pyproj import Transformer

    xy = np.asarray(nodes, dtype=float)
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(xy[:, 0], xy[:, 1])
    return np.column_stack([lon, lat])
