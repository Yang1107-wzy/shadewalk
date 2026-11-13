# Web atlas

The `web/` folder is a **static, serverless** map application, deployed at [`/atlas/`](../atlas/) on this site. It needs no backend: each area is one compact JSON file, and routing runs in the browser.

* **Layers:** shade at any half-hour, daily sun hours, sky view factor, tree-canopy share, and LISA hot/cool-spot clusters.
* **A → B routing:** shortest vs coolest route, with a λ slider and a time slider.
* **Nearest MTR:** click anywhere to get the coolest walk to the nearest MTR station (a reverse multi-source Dijkstra).

## Build the data

```bash
shadewalk build mong_kok --date 2026-07-15 --lidar
shadewalk analyze mong_kok            # adds the LISA layer
shadewalk atlas mong_kok central      # -> web/data/*.json + web/data/index.json
python -m http.server --directory web 8000
```

## Data format

| Key | Content |
|---|---|
| `nodes` | flat `[lon, lat, …]`, 6 decimals |
| `edges.u/v/len/dir/covered/name` | segment endpoints (node indices), length in dm, LandsD direction code, covered flag |
| `coords` | per-segment polylines as micro-degree integer offsets from `base` |
| `shade[slot]` | base64 `uint8`, 0–250 = shade 0–1, 255 = missing |
| `heat` | base64 `uint8`, LST weight \((w-1)\times 250\) |
| `layers` | static layers with their scale (`sun_hours` ×20, `svf` ×250, `tree` ×250, `lisa` codes) |
| `stations` | MTR station names → node indices |

`web/router.js` implements the same cost (`length + λ·length·(1−shade)·heat`) as `shadewalk.routing`. `tests/test_atlas_region.py` runs it under Node and checks that it agrees with Python.
