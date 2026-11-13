# Demo data

Pre-built areas for 15 July 2026, 07:00–19:00 in 30-minute slots, using the **LiDAR shade model** (`shade_*`). The building-only vector shade is kept as `bshade_*`. Built with:

```bash
shadewalk build <area> --date 2026-07-15 --step 30 --lidar
shadewalk region yau_tsim_mong 114.163,22.293,114.180,22.326 --lidar --tile-m 1200 --workers 3
python scripts/district_report.py --outputs <outputs>   # analysis.json, analysis_layers.parquet
```

Each folder holds:

* `edges.parquet`: segments with per-slot shade and exposure, plus `svf`, `cover`, `tree`, `ndvi`, `lst`.
* `buildings.parquet`.
* `meta.json`: provenance, sun angles and scene IDs.
* The LST and NDVI composites (single areas only).
* The street-analysis outputs.

The 1 m LiDAR surface rasters (~25 MB per area) are not bundled. Rebuild with `--lidar` to obtain them.

Source data © Lands Department, Civil Engineering and Development Department and Census and Statistics Department, HKSAR Government (CSDI); modified Copernicus Sentinel data; Landsat courtesy of USGS. See `../DATA_ATTRIBUTION.md`.
