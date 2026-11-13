"""Summer NDVI composite from Sentinel-2 L2A (10 m) via Microsoft Planetary Computer.

NDVI = (B08 - B04) / (B08 + B04) on surface reflectance, with the scene
classification layer (SCL) masking clouds (8, 9, 10), cloud shadow (3),
water (6) and no-data (0). The per-pixel median across scenes is written to a
GeoTIFF in the scenes' UTM CRS.

ShadeWalk combines NDVI with the LiDAR nDSM to tell **tree canopy** (tall and
green) apart from other overhead structures such as canopies, signs and
footbridges.

Requires the ``lst`` extra (rasterio, pystac-client, planetary-computer).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from shadewalk.data.cache import cache_dir

__all__ = ["SCL_INVALID", "ndvi", "summer_ndvi"]

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SCL_INVALID = (0, 1, 3, 6, 8, 9, 10)


def ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDVI from reflectance (or DN with a common offset already removed)."""
    red = np.asarray(red, dtype=float)
    nir = np.asarray(nir, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (nir - red) / (nir + red)
    out[(nir + red) <= 0] = np.nan
    return out


def summer_ndvi(
    bbox: Sequence[float],
    years: Sequence[int] = (2024, 2025),
    months: Sequence[int] = (6, 7, 8, 9, 10),
    max_cloud: float = 30.0,
    max_scenes: int = 8,
    min_clear_fraction: float = 0.4,
    out: Path | None = None,
) -> Path:
    """Build (or reuse) a median NDVI GeoTIFF covering ``bbox`` (lon/lat)."""
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    tag = "_".join(f"{v:.4f}" for v in bbox) + f"_{min(years)}-{max(years)}"
    out = out or cache_dir() / "ndvi" / f"ndvi_{tag}.tif"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)

    catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items: list = []
    for year in years:
        search = catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=list(bbox),
            datetime=f"{year}-{min(months):02d}-01/{year}-{max(months):02d}-30",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        )
        items.extend(i for i in search.items() if i.datetime and i.datetime.month in months)
    items.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    if not items:
        raise RuntimeError("no Sentinel-2 scenes found for bbox/period")

    with rasterio.open(items[0].assets["B04"].href) as src:
        crs = src.crs
        b = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
        res = src.res[0]
    left, top = np.floor(b[0] / res) * res, np.ceil(b[3] / res) * res
    width = int(np.ceil((b[2] - left) / res))
    height = int(np.ceil((top - b[1]) / res))
    transform = rasterio.transform.from_origin(left, top, res, res)

    def read(href: str, scale: int = 1) -> np.ndarray:
        with rasterio.open(href) as s:
            if s.crs != crs:
                raise ValueError("CRS mismatch")
            win = from_bounds(left, top - height * res, left + width * res, top, s.transform)
            return s.read(1, window=win, boundless=True, fill_value=0, out_shape=(height, width))

    stack: list[np.ndarray] = []
    used: list[str] = []
    for item in items:
        if len(stack) >= max_scenes:
            break
        try:
            red, nir = read(item.assets["B04"].href), read(item.assets["B08"].href)
            scl = read(item.assets["SCL"].href)
        except ValueError:
            continue
        offset = (
            1000.0 if float(item.properties.get("s2:processing_baseline", "0") or 0) >= 4 else 0
        )
        v = ndvi(red - offset, nir - offset)
        v[np.isin(scl, SCL_INVALID)] = np.nan
        if np.isfinite(v).mean() < min_clear_fraction:
            continue
        stack.append(v)
        used.append(item.id)
    if not stack:
        raise RuntimeError("all Sentinel-2 scenes too cloudy over bbox")
    with warnings.catch_warnings():  # all-NaN pixels (water, persistent cloud) stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(np.stack(stack), axis=0).astype("float32")
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(med, 1)
        dst.update_tags(description="Median summer Sentinel-2 L2A NDVI", scenes=",".join(used))
    return out
