"""Cross-check ShadeWalk building shadows against pybdshadow (independent implementation).

Usage (pybdshadow is NOT a ShadeWalk dependency; install it in a separate env):

    pip install pybdshadow shadewalk
    python scripts/validate_pybdshadow.py outputs/kennedy_town --date 2026-07-15

Reports, for each time slot, the shadow-union area from both tools and their
intersection-over-union (IoU). Results are written to ``<area>/validation.json``.
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import pandas as pd
import shapely

from shadewalk.shadow import building_shadows
from shadewalk.sun import solar_position

warnings.filterwarnings("ignore")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("area_dir", type=Path)
    ap.add_argument("--date", default="2026-07-15")
    ap.add_argument("--times", default="08:00,10:00,12:00,14:00,16:00,18:00")
    args = ap.parse_args()

    import pybdshadow

    meta = json.loads((args.area_dir / "meta.json").read_text())
    b = meta["area"]["bbox"]
    lat, lon = (b[1] + b[3]) / 2, (b[0] + b[2]) / 2
    bld = gpd.read_parquet(args.area_dir / "buildings.parquet")
    bld = bld[bld.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    bld = bld.explode(index_parts=False).reset_index(drop=True)
    bld = bld[bld.geometry.geom_type == "Polygon"]
    bld4326 = bld.to_crs(4326)
    bld4326 = pybdshadow.bd_preprocess(bld4326[["height", "geometry"]].copy())

    rows = []
    day = datetime.fromisoformat(args.date).date()
    for hhmm in args.times.split(","):
        local = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=ZoneInfo("Asia/Hong_Kong"))
        sp = solar_position(local, lat, lon)
        ours = building_shadows(bld, sp.altitude, sp.azimuth)
        ours_u = shapely.union_all(ours.geometry.to_numpy())
        utc = pd.Timestamp(local).tz_convert("UTC").tz_localize(None)
        theirs = pybdshadow.bdshadow_sunlight(bld4326, utc)
        theirs = gpd.GeoDataFrame(theirs, geometry="geometry", crs=4326).to_crs(bld.crs)
        theirs_u = shapely.union_all(shapely.make_valid(theirs.geometry.to_numpy()))
        inter = shapely.intersection(ours_u, theirs_u).area
        union = shapely.union(ours_u, theirs_u).area
        rows.append(
            {
                "time": hhmm,
                "sun_altitude": round(sp.altitude, 2),
                "sun_azimuth": round(sp.azimuth, 2),
                "shadewalk_m2": round(ours_u.area),
                "pybdshadow_m2": round(theirs_u.area),
                "iou": round(inter / union, 4) if union else 1.0,
            }
        )
        print(rows[-1])
    out = {"pybdshadow_version": pybdshadow.__version__, "date": args.date, "slots": rows}
    (args.area_dir / "validation.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
