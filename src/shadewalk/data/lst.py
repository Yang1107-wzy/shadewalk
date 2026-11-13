"""Summer land surface temperature (LST) composite from Landsat 8/9 Collection 2 Level-2.

Scenes are discovered on Microsoft Planetary Computer's STAC API. For every
scene the ``lwir11`` surface-temperature band is converted to degrees Celsius
(``DN * 0.00341802 + 149 - 273.15``), cloud/cloud-shadow/dilated-cloud pixels are
masked with ``qa_pixel``, and the per-pixel median across scenes is written to a
GeoTIFF in the scene's UTM CRS.

LST is the *skin* temperature of surfaces at ~10:30 local overpass time (30 m
product, resampled from 100 m TIRS). ShadeWalk uses it only as a relative weight
for "hot" street segments, not as a pedestrian thermal-comfort index.

Requires the ``lst`` extra: ``pip install "shadewalk[lst]"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from shadewalk.data.cache import cache_dir

__all__ = ["CLOUD_BITS", "qa_clear_mask", "st_to_celsius", "summer_lst"]

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
ST_SCALE, ST_OFFSET = 0.00341802, 149.0
#: QA_PIXEL bits that flag unusable pixels: dilated cloud, cirrus, cloud, cloud shadow.
CLOUD_BITS = (1, 2, 3, 4)


def st_to_celsius(dn: np.ndarray) -> np.ndarray:
    """Convert Collection 2 ST_B10 digital numbers to degrees Celsius (0 -> NaN)."""
    dn = np.asarray(dn, dtype=float)
    out = dn * ST_SCALE + ST_OFFSET - 273.15
    out[dn == 0] = np.nan
    return out


def qa_clear_mask(qa: np.ndarray, bits: Sequence[int] = CLOUD_BITS) -> np.ndarray:
    """True where none of the given QA_PIXEL bits are set."""
    qa = np.asarray(qa, dtype=np.uint16)
    flag = np.zeros(qa.shape, dtype=bool)
    for b in bits:
        flag |= (qa >> b) & 1 == 1
    return ~flag


def summer_lst(
    bbox: Sequence[float],
    years: Sequence[int] = (2023, 2024, 2025),
    months: Sequence[int] = (6, 7, 8, 9),
    max_cloud: float = 40.0,
    max_scenes: int = 12,
    min_clear_fraction: float = 0.5,
    out: Path | None = None,
) -> Path:
    """Build (or reuse) a median summer LST GeoTIFF covering ``bbox`` (lon/lat).

    Returns the path of the GeoTIFF. Scenes with less than ``min_clear_fraction``
    clear pixels inside the bbox are skipped.
    """
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    tag = "_".join(f"{v:.4f}" for v in bbox) + f"_{min(years)}-{max(years)}"
    out = out or cache_dir() / "lst" / f"lst_{tag}.tif"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)

    catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items: list = []
    for year in years:
        dt = f"{year}-{min(months):02d}-01/{year}-{max(months):02d}-30"
        search = catalog.search(
            collections=["landsat-c2-l2"],
            bbox=list(bbox),
            datetime=dt,
            query={
                "eo:cloud_cover": {"lt": max_cloud},
                "platform": {"in": ["landsat-8", "landsat-9"]},
            },
        )
        items.extend(i for i in search.items() if i.datetime and i.datetime.month in months)
    items.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    if not items:
        raise RuntimeError("no Landsat scenes found for bbox/period")

    # Use the CRS/grid of the least cloudy scene as the reference grid.
    ref = items[0]
    with rasterio.open(ref.assets["lwir11"].href) as src:
        crs = src.crs
        b = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
        res = src.res[0]
        left = np.floor(b[0] / res) * res
        top = np.ceil(b[3] / res) * res
        width = int(np.ceil((b[2] - left) / res))
        height = int(np.ceil((top - b[1]) / res))
    transform = rasterio.transform.from_origin(left, top, res, res)

    stack: list[np.ndarray] = []
    used: list[str] = []
    for item in items:
        if len(stack) >= max_scenes:
            break
        with rasterio.open(item.assets["lwir11"].href) as st_src:
            if st_src.crs != crs:
                continue
            win: Window = (
                from_bounds(left, top - height * res, left + width * res, top, st_src.transform)
                .round_offsets()
                .round_lengths()
            )
            st = st_src.read(1, window=win, boundless=True, fill_value=0, out_shape=(height, width))
        with rasterio.open(item.assets["qa_pixel"].href) as qa_src:
            qa = qa_src.read(1, window=win, boundless=True, fill_value=1, out_shape=(height, width))
        celsius = st_to_celsius(st)
        celsius[~qa_clear_mask(qa)] = np.nan
        if np.isfinite(celsius).mean() < min_clear_fraction:
            continue
        stack.append(celsius)
        used.append(item.id)
    if not stack:
        raise RuntimeError("all candidate scenes were too cloudy over the bbox")

    with np.errstate(all="ignore"):
        median = np.nanmedian(np.stack(stack), axis=0).astype("float32")
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
        dst.write(median, 1)
        dst.update_tags(
            description="Median summer Landsat C2 L2 LST (deg C)",
            scenes=",".join(used),
            source="Landsat 8/9 Collection 2 Level-2 via Microsoft Planetary Computer",
        )
    return out
