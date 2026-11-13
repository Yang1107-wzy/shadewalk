# Architecture

```mermaid
flowchart LR
  subgraph Sources["Open data (fetched, cached with SHA-256 provenance)"]
    B["LandsD Building\n(WFS)"]
    N["LandsD 3D Pedestrian\nNetwork (WFS)"]
    T["Terminal table\n(FeatureServer)"]
    L["CEDD 2020 LiDAR\nDSM / DTM tiles"]
    S2["Sentinel-2 L2A\n(STAC)"]
    LS["Landsat 8/9 ST\n(STAC)"]
    C["2021 Census LSUG\n(WFS)"]
  end
  subgraph Core["shadewalk (EPSG:2326)"]
    SUN["sun: NOAA solar position"]
    VS["shadow: exact LoD1 vector shadows"]
    RS["raster: ray-marched shade,\nSVF, overhead cover"]
    SS["streetscape: street points,\nNDVI tree canopy"]
    EX["exposure: shade x heat"]
    G["network: directed graph"]
    R["routing: Dijkstra, λ sweep"]
    M["morphology: H/W, orientation,\ncoverage, frontal area"]
    ST["stats: Moran, LISA, Gi*,\nOLS, spatial lag (S2SLS)"]
    A["access: dasymetric population,\nmulti-source Dijkstra"]
  end
  subgraph Out["Interfaces"]
    CLI["CLI"]
    API["Python API"]
    GP["GeoParquet / GeoPackage"]
    APP["Streamlit app"]
    WEB["Static MapLibre atlas\n(in-browser routing)"]
  end
  B --> VS & M & A
  N --> G
  T --> A
  L --> RS
  S2 --> SS
  LS --> EX
  C --> A
  SUN --> VS & RS
  RS --> SS --> EX
  VS --> EX --> R
  G --> R & A
  M --> ST
  EX --> ST
  R --> CLI & API & APP & WEB
  ST --> GP & WEB
  A --> GP & WEB
```

| Module | Responsibility |
|---|---|
| `shadewalk.data.*` | Loaders: CSDI WFS/FeatureServer paging, LiDAR tile index and mosaics, Planetary Computer STAC composites (Landsat LST, Sentinel-2 NDVI), census, HKO weather, and the provenance cache |
| `shadewalk.sun`, `shadow` | Solar geometry and exact vector building shadows |
| `shadewalk.raster`, `streetscape` | DSM ray marching, sky view factor, overhead cover, tree canopy at street level |
| `shadewalk.exposure`, `network`, `routing` | Segment shade fraction, heat weight and exposure; graph building; shortest/coolest routes |
| `shadewalk.morphology`, `stats`, `analysis` | Street-canyon descriptors, spatial statistics, daily metrics and the per-area analysis |
| `shadewalk.access` | Dasymetric population and population-weighted MTR accessibility |
| `shadewalk.pipeline`, `region` | Area build/load, tiled parallel district builds and merging |
| `shadewalk.atlas`, `viz`, `cli` | Web-atlas export, folium maps, command line |
| `web/` | Static MapLibre front-end with a JS router that mirrors `routing.py` |
