# Tutorial

## Install

```bash
git clone https://github.com/Yang1107-wzy/shadewalk && cd shadewalk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[lst,app,dev]"
```

`lst` adds rasterio and the STAC client for Landsat, and `app` adds Streamlit. Without `lst`, run `shadewalk build ... --no-lst`; segments then get a uniform heat weight.

## Build an area

```bash
shadewalk areas
shadewalk build kennedy_town --date 2026-07-15 --start 07:00 --end 19:00 --step 30
# custom bbox (min_lon,min_lat,max_lon,max_lat):
shadewalk build 114.205,22.278,114.218,22.288 --date 2026-08-01
```

This writes `outputs/<area>/` containing `edges.parquet` (columns `shade_HHMM` and `exp_HHMM` for each slot), `buildings.parquet`, `lst.tif` and `meta.json` (provenance, sun angles and Landsat scene IDs).

## LiDAR, analysis and accessibility (v0.2)

```bash
# Street-level model with trees, terrain and overhead cover (downloads ~20 LiDAR tiles)
shadewalk build mong_kok --date 2026-07-15 --lidar

# Spatial statistics of daily sun hours: Moran's I, LISA, Gi*, OLS, spatial lag
shadewalk analyze mong_kok

# Population-weighted walking access to MTR stations (2021 census, 65+)
shadewalk access mong_kok --time 15:00 --lambda 2

# District scale: 1 km tiles built in parallel, then merged
shadewalk region yau_tsim_mong 114.163,22.293,114.180,22.326 --lidar --workers 3

# GIS hand-off and the web atlas
shadewalk export mong_kok -o mong_kok.gpkg     # layers: segments, buildings, street_analysis
shadewalk atlas mong_kok yau_tsim_mong          # -> web/data/*.json
```

In Python:

```python
from shadewalk.pipeline import load_area
from shadewalk.analysis import street_analysis

m = load_area("outputs/mong_kok")
res = street_analysis(m.edges, m.buildings, m.meta)
print(res.moran.I, res.lisa_counts)
print(res.regression)  # OLS + residual Moran's I
print(res.lag)  # spatial lag (S2SLS)
```

## Route

```bash
shadewalk route kennedy_town --from "Kennedy Town Centre" --to "Haking Wong" --time 15:00 --lambda 4 --html kt.html
shadewalk route central --from 114.1545,22.2810 --to 114.1590,22.2850 --time 12:00 --json
```

Places can be given as `lon,lat` or as part of a LandsD building name.

## Python

```python
from shadewalk.pipeline import load_area
from shadewalk.viz import route_map

m = load_area("demo_data/mong_kok")
o, d = m.find_place("Langham Place"), m.find_place("Sino Centre")
routes = m.compare(o, d, "15:00", lams=(0, 1, 2, 4, 8))
for r in routes:
    print(f"λ={r.lam:<4} {r.length_m:6.0f} m  {r.shaded_pct:5.1f}% shaded")
route_map(m, "15:00", [routes[0], routes[-1]], ["Shortest", "Coolest"]).save("mk.html")
```

Lower-level pieces can be used on their own:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from shadewalk import solar_position, building_shadows

sun = solar_position(datetime(2026, 7, 15, 15, tzinfo=ZoneInfo("Asia/Hong_Kong")), 22.32, 114.17)
shadows = building_shadows(m.buildings, sun.altitude, sun.azimuth)
```

## Interactive demo

```bash
streamlit run app/streamlit_app.py
```

Click the map once for the start and once for the end, then move the time slider and the λ slider.

## Reproduce the figures and case study

```bash
python scripts/case_study.py --outputs demo_data --pairs 100
python scripts/make_figures.py --outputs demo_data
python scripts/validate_pybdshadow.py demo_data/kennedy_town   # needs `pip install pybdshadow`
python scripts/validate_lidar.py outputs/mong_kok               # needs a --lidar build
python scripts/district_report.py --outputs outputs             # street analysis + MTR access
```
