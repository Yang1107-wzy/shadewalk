"""District-scale builds by tiling: split a large bbox, build tiles in parallel, merge.

Each tile is a normal :func:`shadewalk.pipeline.build_area` run with a buffered
context (buildings and LiDAR beyond the tile edge still cast shadows into it),
so per-segment results do not depend on the tiling. Segments crossing tile edges
are fetched by both neighbours and de-duplicated on merge. The LST heat weight
is re-normalised over the whole region after merging, so that "hot" means hot
relative to the region rather than to each tile.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from shadewalk.areas import Area
from shadewalk.data.csdi import HK_CRS
from shadewalk.exposure import exposure, heat_weight

__all__ = ["build_region", "merge_tiles", "tile_areas"]


def tile_areas(key: str, bbox: Sequence[float], tile_m: float = 1000.0) -> list[Area]:
    """Split a lon/lat bbox into roughly ``tile_m`` x ``tile_m`` tiles."""
    lat0 = (bbox[1] + bbox[3]) / 2
    dlat = tile_m / 111_320.0
    dlon = tile_m / (111_320.0 * math.cos(math.radians(lat0)))
    nx = max(1, math.ceil((bbox[2] - bbox[0]) / dlon))
    ny = max(1, math.ceil((bbox[3] - bbox[1]) / dlat))
    sx = (bbox[2] - bbox[0]) / nx
    sy = (bbox[3] - bbox[1]) / ny
    tiles = []
    for j in range(ny):
        for i in range(nx):
            b = (bbox[0] + i * sx, bbox[1] + j * sy, bbox[0] + (i + 1) * sx, bbox[1] + (j + 1) * sy)
            tiles.append(Area(f"{key}__t{j:02d}_{i:02d}", f"{key} tile {j},{i}", b))
    return tiles


def _build_tile(tile: Area, day: date, slots: Sequence[str], out: Path, kw: dict) -> Path:
    from shadewalk.pipeline import build_area

    return build_area(tile, day, slots, out, log=lambda *a, **k: None, **kw)


def merge_tiles(
    key: str,
    title: str,
    bbox: Sequence[float],
    tile_dirs: Sequence[Path],
    out_dir: Path,
    beta: float = 1.0,
) -> Path:
    """Merge tile outputs into one area folder; dedupe segments and buildings."""
    edges = pd.concat([gpd.read_parquet(d / "edges.parquet") for d in tile_dirs], ignore_index=True)
    edges["_wkb"] = edges.geometry.to_wkb()
    edges = edges.drop_duplicates(subset=["route_id", "_wkb"]).drop(columns="_wkb")
    bld = pd.concat(
        [gpd.read_parquet(d / "buildings.parquet") for d in tile_dirs], ignore_index=True
    )
    key_cols = ["BuildingID"] if "BuildingID" in bld else None
    bld["_wkb"] = bld.geometry.to_wkb()
    bld = bld.drop_duplicates(subset=key_cols or ["_wkb"]).drop(columns="_wkb")

    metas = [json.loads((d / "meta.json").read_text()) for d in tile_dirs]
    slots = metas[0]["slots"]
    if edges["lst"].notna().any():
        edges["heat"] = heat_weight(edges["lst"].to_numpy(float), beta)
        for s in slots:
            c = s.replace(":", "")
            edges[f"exp_{c}"] = exposure(
                edges["length"].to_numpy(),
                edges[f"shade_{c}"].to_numpy(float),
                edges["heat"].to_numpy(),
            ).astype("float32")
    edges = gpd.GeoDataFrame(edges.reset_index(drop=True), geometry="geometry", crs=HK_CRS)
    bld = gpd.GeoDataFrame(bld.reset_index(drop=True), geometry="geometry", crs=HK_CRS)

    target = out_dir / key
    target.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(target / "edges.parquet")
    bld.to_parquet(target / "buildings.parquet")
    meta = dict(metas[0])
    meta["area"] = {"key": key, "title": title, "bbox": list(bbox)}
    meta["counts"] = {"buildings": len(bld), "edges": len(edges)}
    meta["tiles"] = [str(d) for d in tile_dirs]
    meta["lst_scenes"] = sorted({s for m in metas for s in (m.get("lst_scenes") or [])})
    (target / "meta.json").write_text(json.dumps(meta, indent=2))
    return target


def build_region(
    key: str,
    title: str,
    bbox: Sequence[float],
    day: date,
    slots: Sequence[str],
    out_dir: Path = Path("outputs"),
    tile_m: float = 1000.0,
    workers: int = 2,
    log=print,
    **build_kw,
) -> Path:
    """Tile, build in parallel processes, and merge into ``out_dir/key``."""
    tiles = tile_areas(key, bbox, tile_m)
    tile_root = out_dir / "_tiles"
    log(f"Region {title}: {len(tiles)} tiles, {workers} workers")
    done: list[Path] = []
    ex: Executor
    try:
        ex = ProcessPoolExecutor(max_workers=workers)
    except (OSError, NotImplementedError) as exc:  # e.g. sandboxes without POSIX semaphores
        log(f"  process pool unavailable ({exc}); using threads")
        ex = ThreadPoolExecutor(max_workers=workers)
    with ex:
        futs = {ex.submit(_build_tile, t, day, list(slots), tile_root, build_kw): t for t in tiles}
        for f in as_completed(futs):
            done.append(f.result())
            log(f"  tile {futs[f].key} done ({len(done)}/{len(tiles)})")
    done.sort()
    target = merge_tiles(key, title, bbox, done, out_dir, build_kw.get("beta", 1.0))
    e = gpd.read_parquet(target / "edges.parquet")
    log(f"Merged -> {target}: {len(e):,} segments, {e['length'].sum() / 1000:.1f} km")
    return target
