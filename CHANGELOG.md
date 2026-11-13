# Changelog

## 0.2.0 - 2026-11-13

From routing tool to street-level urban-climate GIS toolkit.

* **LiDAR surface model** (`shadewalk.data.lidar`, `shadewalk.raster`): CEDD 2020 DSM/DTM tile discovery, mosaicking and max/mean aggregation. Ray-marched street-level shade covering trees, terrain and structures. Sky view factor and overhead-cover detection. `build --lidar` keeps the building-only vector shade as `bshade_*`.
* **Sentinel-2 NDVI** composite (SCL cloud masking) fused with the LiDAR nDSM to separate tree canopy from other cover.
* **Urban morphology** (`shadewalk.morphology`): street orientation, canyon H/W from perpendicular ray casting, building coverage on dissolved footprints, mean height, frontal-area index.
* **Spatial statistics** (`shadewalk.stats`): kNN weights, global Moran's I, LISA, Getis-Ord Gi*, OLS with HC1 errors and residual Moran's I, spatial lag S2SLS. Cross-validated against PySAL (`esda`, `spreg`).
* **Accessibility** (`shadewalk.access`): dasymetric allocation of 2021 census population (all ages and 65+) to buildings, MTR station access points from the network's terminal table, multi-source Dijkstra for shortest and shade-aware access.
* **District scale** (`shadewalk.region`): tiled builds in parallel (process pool with a thread fallback), deterministic merge with de-duplication and regional LST normalisation. Yau Tsim Mong demo (22k segments, 279 km).
* **Static web atlas** (`web/`, `shadewalk atlas`): MapLibre front-end with in-browser Dijkstra (shortest vs coolest, nearest MTR), layers for shade by time, sun hours, SVF, tree cover and LISA clusters. Node-based parity test against Python.
* CLI: `region`, `analyze`, `access`, `export` (GeoPackage), `atlas`. Thread-safe cache with atomic writes.
* Validation: vector-vs-raster shadow agreement, overhead cover vs `WeatherProof`, and a decomposition of shade by source.

## 0.1.0 - 2026-11-13

First public release.

* LandsD Building and 3D Pedestrian Network loaders (CSDI WFS, paged, cached with SHA-256 provenance).
* NOAA solar position, exact LoD1 building shadows, segment shade fractions.
* Landsat 8/9 C2 L2 summer LST composite (Planetary Computer STAC, QA cloud masking).
* Exposure-weighted Dijkstra routing with a λ sweep (Pareto set).
* `shadewalk` CLI (`areas`, `build`, `route`, `map`, `sun`, `weather`), folium maps, Streamlit demo.
* Demo data for Kennedy Town–HKU, Central–Sheung Wan, Mong Kok and Sha Tin (15 July 2026).
* Case study (400 random trips × 3 times) and a cross-validation of shadows against pybdshadow.
