"""CEDD 2020 airborne LiDAR digital surface / terrain models (0.5 m, EPSG:2326).

The CSDI dataset ``cedd_rcd_1629267205233_87895`` exposes tile indexes as WFS
layers (``DSM_2020``, ``DTM_2020``). Each 750 m x 600 m tile links to a zipped
GeoTIFF on ``bulkdata.csdi.gov.hk``. This module discovers the tiles that cover a
bbox, downloads them through the provenance cache, mosaics and crops them, and
optionally aggregates them to a coarser grid:

* DSM is aggregated with **max** so that thin occluders (poles, canopy edges) survive;
* DTM is aggregated with **mean**.

Data (c) Civil Engineering and Development Department, HKSAR Government.
"""

from __future__ import annotations

import os
import threading
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine

from shadewalk.data.cache import cache_dir, cached_get
from shadewalk.data.csdi import HK_CRS, wfs_features

__all__ = ["LIDAR_DATASET", "Surface", "lidar_tiles", "load_surface"]

LIDAR_DATASET = "cedd_rcd_1629267205233_87895"
NODATA = -9999.0


@dataclass
class Surface:
    """Co-registered DSM and DTM grids in EPSG:2326 (row 0 = north)."""

    dsm: np.ndarray
    dtm: np.ndarray
    transform: Affine
    crs: str = HK_CRS

    @property
    def res(self) -> float:
        return float(self.transform.a)

    @property
    def ndsm(self) -> np.ndarray:
        """Height above ground (m); NaN where either model is missing."""
        return self.dsm - self.dtm

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        h, w = self.dsm.shape
        x0, y1 = self.transform.c, self.transform.f
        return (x0, y1 - h * self.res, x0 + w * self.res, y1)

    def save(self, folder: Path) -> None:
        import rasterio

        folder.mkdir(parents=True, exist_ok=True)
        for name, arr in (("dsm", self.dsm), ("dtm", self.dtm)):
            profile = {
                "driver": "GTiff",
                "height": arr.shape[0],
                "width": arr.shape[1],
                "count": 1,
                "dtype": "float32",
                "crs": self.crs,
                "transform": self.transform,
                "nodata": np.nan,
                "compress": "deflate",
                "predictor": 3,
                "tiled": True,
            }
            with rasterio.open(folder / f"{name}.tif", "w", **profile) as dst:
                dst.write(arr.astype("float32"), 1)

    @classmethod
    def load(cls, folder: Path) -> Surface:
        import rasterio

        with rasterio.open(folder / "dsm.tif") as a, rasterio.open(folder / "dtm.tif") as b:
            return cls(a.read(1), b.read(1), a.transform, str(a.crs))


def lidar_tiles(bbox: Sequence[float], kind: str = "DSM", year: int = 2020) -> list[dict]:
    """Tile records (``TILE_NAME``, ``URL``) intersecting a WGS84 bbox."""
    gdf = wfs_features(LIDAR_DATASET, f"csdi:{kind}_{year}", bbox)
    if gdf.empty:
        return []
    return gdf[["TILE_NAME", "URL"]].drop_duplicates("TILE_NAME").to_dict("records")


def _tile_tif(url: str) -> Path:
    """Download a zipped tile (cached) and return the extracted GeoTIFF path."""
    zpath = cached_get(url, suffix=".zip", timeout=600)
    out_dir = cache_dir() / "lidar" / zpath.stem
    tifs = sorted(out_dir.glob("*.tif"))
    if not tifs:
        out_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".tif"):
                    target = out_dir / Path(name).name
                    tmp = out_dir / f".{target.name}.{os.getpid()}.{threading.get_ident()}"
                    tmp.write_bytes(zf.read(name))
                    tmp.replace(target)  # atomic: concurrent tiles never see partial files
        tifs = sorted(out_dir.glob("*.tif"))
    if not tifs:
        raise RuntimeError(f"no GeoTIFF inside {url}")
    return tifs[0]


def _mosaic(paths: list[Path], bounds_xy: Sequence[float], res: float, how: str) -> tuple:
    import warnings

    import rasterio
    from rasterio.merge import merge

    srcs = [rasterio.open(p) for p in paths]
    try:
        arr, transform = merge(srcs, bounds=tuple(bounds_xy), nodata=NODATA, res=srcs[0].res)
    finally:
        for s in srcs:
            s.close()
    a = arr[0].astype("float32")
    a[a <= NODATA + 1] = np.nan
    native = float(transform.a)
    f = round(res / native)
    if f > 1:
        h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
        blocks = a[:h, :w].reshape(h // f, f, w // f, f)
        with warnings.catch_warnings():  # all-NaN blocks are expected at the sea edge
            warnings.simplefilter("ignore", RuntimeWarning)
            a = np.nanmax(blocks, axis=(1, 3)) if how == "max" else np.nanmean(blocks, axis=(1, 3))
        transform = transform * Affine.scale(f)
    return a, transform


def load_surface(bbox: Sequence[float], res: float = 1.0, log=None) -> Surface:
    """Mosaic DSM/DTM tiles covering ``bbox`` (lon/lat) at ``res`` metres (multiple of 0.5)."""
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", HK_CRS, always_xy=True)
    xs, ys = tr.transform(
        [bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]]
    )
    x0 = np.floor(min(xs) / res) * res
    y0 = np.floor(min(ys) / res) * res
    x1 = np.ceil(max(xs) / res) * res
    y1 = np.ceil(max(ys) / res) * res

    layers = {}
    for kind, how in (("DSM", "max"), ("DTM", "mean")):
        tiles = lidar_tiles(bbox, kind)
        if not tiles:
            raise RuntimeError(f"no LiDAR {kind} tiles found for bbox {bbox}")
        if log:
            log(f"      LiDAR {kind}: {len(tiles)} tiles")
        paths = [_tile_tif(t["URL"]) for t in tiles]
        layers[kind], transform = _mosaic(paths, (x0, y0, x1, y1), res, how)
    dsm, dtm = layers["DSM"], layers["DTM"]
    h = min(dsm.shape[0], dtm.shape[0])
    w = min(dsm.shape[1], dtm.shape[1])
    return Surface(dsm[:h, :w], dtm[:h, :w], transform)
