"""Validate the LiDAR ray-marching shade model and decompose shade by source.

    python scripts/validate_lidar.py outputs_lidar/mong_kok [--times 09:00,12:00,15:00]

1. **Implementation check.** Rasterise LandsD buildings (roof elevation =
   base mPD + height) onto the DTM, run :func:`shadewalk.raster.ray_shadow` on
   street sample points, and compare point-by-point with the exact vector
   shadows from :func:`shadewalk.shadow.building_shadows`. Disagreement should be
   confined to pixel-edge effects.
2. **Overhead-cover agreement.** LiDAR overhead detection versus the LandsD
   ``WeatherProof`` coding on outdoor segments (covered vs non-covered).
3. **Decomposition.** Street-level shade share with progressively richer
   occluders: buildings only (vector) -> + terrain (buildings on DTM) -> full DSM
   (adds trees, bridges, small structures) -> + overhead cover.

Writes ``docs/validation/lidar_<area>.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from rasterio.features import rasterize

from shadewalk.data.lidar import Surface
from shadewalk.network import sample_points
from shadewalk.raster import observer_height, overhead_cover, ray_shadow
from shadewalk.shadow import building_shadows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("area_dir", type=Path)
    ap.add_argument("--times", default="09:00,12:00,15:00")
    ap.add_argument("--out", type=Path, default=Path("docs/validation"))
    args = ap.parse_args()

    meta = json.loads((args.area_dir / "meta.json").read_text())
    surface = Surface.load(args.area_dir / "surface")
    edges = gpd.read_parquet(args.area_dir / "edges.parquet")
    bld = gpd.read_parquet(args.area_dir / "buildings.parquet")
    outdoor = edges[(edges["location"] == "Outdoor")].reset_index(drop=True)
    pts, owner = sample_points(outdoor, 2.0)
    xy = shapely.get_coordinates(pts)
    x, y = xy[:, 0], xy[:, 1]
    z = observer_height(surface, x, y)
    ok = np.isfinite(z)

    # Buildings-on-terrain DSM: roof mPD where a footprint covers the cell, else DTM.
    roof = (bld["base_mpd"].fillna(0) + bld["height"]).to_numpy()
    h, w = surface.dsm.shape
    order = np.argsort(roof)  # draw tallest last so overlaps keep the max
    braster = rasterize(
        ((bld.geometry.iloc[i], roof[i]) for i in order),
        out_shape=(h, w),
        transform=surface.transform,
        fill=np.nan,
        dtype="float32",
    )
    dsm_b = np.fmax(surface.dtm, braster)
    surf_b = Surface(dsm_b, surface.dtm, surface.transform)
    # Terrain-free version: buildings on a flat datum at the local street level.
    flat = np.full_like(surface.dtm, np.nanmedian(surface.dtm))
    surf_flat = Surface(
        np.fmax(
            flat,
            np.where(np.isfinite(braster), flat + (braster - np.nan_to_num(surface.dtm)), flat),
        ),
        flat,
        surface.transform,
    )
    z_flat = np.full_like(z, np.nanmedian(surface.dtm) + 1.6)

    cover = overhead_cover(surface, x, y, z)
    wp = outdoor["weatherproof"].to_numpy()[owner]
    agree = {
        "points_covered_label": int((wp == "Covered").sum()),
        "points_noncovered_label": int((wp == "NonCovered").sum()),
        "detected_on_covered": float(cover[(wp == "Covered") & ok].mean()),
        "detected_on_noncovered": float(cover[(wp == "NonCovered") & ok].mean()),
    }

    rows = []
    for slot in args.times.split(","):
        sun = meta["sun"][slot]
        alt, az = sun["altitude"], sun["azimuth"]
        vec = building_shadows(bld, alt, az)
        tree = shapely.STRtree(vec.geometry.to_numpy())
        hit, _ = tree.query(pts, predicate="intersects")
        v = np.zeros(len(pts), dtype=bool)
        v[np.unique(hit)] = True
        r_flat = ray_shadow(surf_flat, x, y, z_flat, alt, az)
        r_b = ray_shadow(surf_b, x, y, z, alt, az)
        r_full = ray_shadow(surface, x, y, z, alt, az)
        m = ok
        rows.append(
            {
                "time": slot,
                "sun_altitude": alt,
                "sun_azimuth": az,
                "points": int(m.sum()),
                "vector_vs_raster_buildings_agreement": float((v[m] == r_flat[m]).mean()),
                "shade_buildings_vector": float(v[m].mean()),
                "shade_buildings_on_terrain": float(r_b[m].mean()),
                "shade_full_dsm": float(r_full[m].mean()),
                "shade_full_dsm_plus_cover": float((r_full | cover)[m].mean()),
            }
        )
        print(rows[-1])
    out = {
        "area": meta["area"]["key"],
        "date": meta["date"],
        "lidar_res_m": surface.res,
        "overhead_cover_vs_weatherproof": agree,
        "slots": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"lidar_{meta['area']['key']}.json"
    path.write_text(json.dumps(out, indent=2))
    print(agree)
    print("written", path)


if __name__ == "__main__":
    main()
