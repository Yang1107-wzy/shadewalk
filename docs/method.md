# Method

## 1. Data

| Layer | Source | Key fields |
|---|---|---|
| Buildings | LandsD *Building*, CSDI dataset `landsd_rcd_1637211194312_35158` (WFS 2.0) | footprint, `BaseHeight`, `TopHeight` (mPD), `Storeys` |
| Pedestrian network | LandsD *3D Pedestrian Network*, CSDI `landsd_rcd_1637222018065_52265` | `FeatureType`, `Location` (Outdoor/Indoor/Paid), `WeatherProof` (Covered/NonCovered), `Direction` |
| Surface temperature | Landsat 8/9 Collection 2 Level-2 `lwir11` + `qa_pixel`, from Microsoft Planetary Computer | `ST = DN·0.00341802 + 149` K |
| Surface models | CEDD 2020 airborne LiDAR DSM and DTM, CSDI `cedd_rcd_1629267205233_87895` (tile index via WFS, 0.5 m GeoTIFF tiles) | elevation mPD, EPSG:2326 |
| Vegetation | Sentinel-2 L2A `B04`, `B08`, `SCL`, from Microsoft Planetary Computer | NDVI, 10 m |
| Population | 2021 Population Census by Large Subunit Group, CSDI `censtatd_rcd_1635933282224_58228` | `t_pop`, `age_1`…`age_5` |
| Transit terminals | 3D Pedestrian Network relation table (FeatureServer table 1000) | `TerminalID`, `TerminalType` (MST = MTR station) |

The WFS is queried with a WGS84 bbox (latitude/longitude axis order) and paged with `startIndex`. Every response is cached on disk with its URL, parameters and SHA-256 (`~/.cache/shadewalk/manifest.json`). All geometry is reprojected to **EPSG:2326 (Hong Kong 1980 Grid)**.

Building height is \(h = \text{TopHeight} - \text{BaseHeight}\). If that is unavailable, it falls back to \(3\,\text{m} \times \text{Storeys}\), and the choice is recorded in `height_source`. Buildings are fetched with a ~400 m buffer so that towers just outside the study area still cast shadows into it.

## 2. Sun position

The NOAA General Solar Position algorithm (the NOAA Solar Calculator spreadsheet), implemented in vectorised numpy and corrected for refraction. Azimuth runs clockwise from north.

## 3. Shadows

For a prism with footprint \(P\), height \(h\) and sun altitude \(\alpha\) and azimuth \(\phi\), the ground shadow is

$$
S = P \;\cup\; (P + \mathbf{d}) \;\cup\; \bigcup_{e \in \partial P} \mathrm{sweep}(e, \mathbf{d}),
\qquad
\mathbf{d} = -\frac{h}{\tan\alpha}\,(\sin\phi,\ \cos\phi).
$$

This is exact for flat-roofed prisms on flat ground, including concave footprints, and is computed with shapely 2 array operations. When \(\alpha < 2^\circ\) the sun is treated as down and everything counts as shaded.

## 4. Segment shade, heat and exposure

Each segment is sampled every 2 m at sub-segment centres. Its shade fraction \(s_e\) is the share of samples that fall inside any shadow polygon, found with an STRtree query. Segments that are covered, indoor or in a subway get \(s_e = 1\).

Surface heat is the mean LST along the segment (one sample every 10 m), rescaled between the area's 10th and 90th percentiles:

$$
w_e = 1 + \beta \cdot \mathrm{clip}\!\left(\frac{\mathrm{LST}_e - p_{10}}{p_{90} - p_{10}}, 0, 1\right),
\qquad
x_e(t) = \ell_e\,(1 - s_e(t))\,w_e .
$$

\(x_e\) is measured in *effective sunlit metres*. With \(\beta = 1\), a sunlit metre next to the area's hottest surfaces counts twice as much as one next to its coolest.

## 5. Routing

The network becomes a directed multigraph. Endpoints are snapped at 0.5 m, LandsD one-way codes are honoured (escalators), and only the largest connected component is kept. The route minimises

$$
\sum_{e \in \text{route}} \ell_e + \lambda\, x_e(t).
$$

\(\lambda = 0\) gives the shortest path. \(\lambda\) is the number of metres of detour you would accept to avoid one effective sunlit metre. Sweeping \(\lambda\) traces the distance–exposure Pareto set (`AreaModel.compare`).

## 6. LiDAR surface model (v0.2)

DSM and DTM tiles covering the buffered area are mosaicked and aggregated from 0.5 m to 1 m. DSM cells take the **maximum** so that thin occluders survive, and DTM cells take the **mean**. Pedestrian sample points sit at \(z = \text{DTM} + 1.6\) m, or at the deck plus 1.6 m on footbridges.

**Ray-marched shadow.** A point is shadowed when some distance \(d\) towards the sun satisfies

$$
\text{DSM}(\mathbf{p} + d\,\mathbf{u}_{sun}) > z + d \tan\alpha + 0.5\,\text{m}.
$$

Steps grow as \(\max(\text{res}, 0.02\,d)\), so a 1 km ray needs about 200 lookups. This captures trees, terrain, flyovers and podiums that the vector building model misses.

**Overhead cover.** A point is covered when the *minimum* DSM within 1 m exceeds head height plus 1 m (canopy, verandah, footbridge). Taking the minimum keeps footways that run along a facade from being read as "under the building".

**Sky view factor.** \(\text{SVF} = 1 - \frac{1}{n}\sum_{i=1}^{n} \sin\gamma_i\) over \(n = 16\) azimuths, where \(\gamma_i\) is the horizon elevation angle within 100 m (Zakšek et al. 2011).

**Tree canopy.** A covered point counts as under tree canopy when its summer median Sentinel-2 NDVI is at least 0.3. This fuses the LiDAR structure with the multispectral greenness.

Both models are stored: `shade_*` uses the full LiDAR model, and `bshade_*` uses exact building-only vector shadows. Treat them as upper and lower bounds (see [Validation](validation.md)).

## 7. Urban morphology

For every segment ShadeWalk computes:

* **Street axis orientation** \(\theta \in [0, 180)\). It enters models as \(\cos 2\theta\) (N–S vs E–W) and \(\sin 2\theta\) (diagonals), the standard treatment for axial data.
* **Canyon width and height** from rays cast perpendicular to the segment midpoint up to 60 m on each side, giving the **aspect ratio** \(H/W\).
* **Building coverage ratio** within 50 m, computed on *dissolved* footprints because LandsD towers overlap their podiums.
* **Mean building height** within 50 m, area-weighted.
* **South-west frontal area index**.

## 8. Spatial statistics

Spatial weights are \(k\)-nearest neighbours (\(k = 8\)) on segment midpoints, row-standardised.

* **Global Moran's I** with permutation inference.
* **Local Moran's I** (LISA) with conditional permutation (999 draws), giving High-High (hot) and Low-Low (cool) street clusters.
* **Getis–Ord \(G_i^*\)** z-scores.
* **OLS** on standardised variables with HC1 robust standard errors, plus Moran's I of the residuals.
* **Spatial lag model** \(y = \rho W y + X\beta + \varepsilon\), estimated by spatial two-stage least squares with instruments \([X, WX, W^2X]\) (Kelejian & Prucha 1998).

All of these are implemented in numpy/scipy and tested against PySAL (`esda`, `spreg`). Moran's I, \(G_i^*\), the LISA statistics and the S2SLS coefficients and standard errors agree to numerical precision.

## 9. Dasymetric population and MTR accessibility

Census LSUG counts (total and aged 65+) are redistributed to the buildings inside each LSUG in proportion to **floor area** (footprint × storeys). Open-sided and temporary structures are excluded.

Destinations are the network nodes of segments linked to MTR stations (`TerminalType = MST`). A **multi-source Dijkstra** on the reversed graph gives every node its walking length and sunlit metres to the nearest station, once for the shortest route and once for the shade-aware cost. The results are population-weighted, for example the share of residents aged 65+ who face more than 200 m of direct sun on the way to the MTR.

## 10. Scaling and delivery

`shadewalk region` splits a large bbox into ~1 km tiles and builds them in parallel, using processes or falling back to threads. Each tile keeps a buffered context so that results do not depend on where the tile edges fall. Duplicate edge segments are removed on merge, and the LST weight is re-normalised over the whole region.

`shadewalk atlas` exports compact JSON (quantised uint8 layers, ~1 MB per km²) for a static MapLibre site that routes in the browser with the same algorithm. A test checks that the browser router and the Python router agree.

## Assumptions and limitations

* The vector model counts building shadows only. The LiDAR model adds trees, terrain and structures, but at 1 m it can also pick up facade edges and signage next to footways, so its shade is an upper bound. LiDAR is a 2020 snapshot.
* LST is a relative surface-heat weight measured at ~10:30 local time. It does not measure air temperature or pedestrian thermal comfort.
* The network is snapped in 2D, and fare-paid areas are excluded by default.
* Dasymetric allocation assumes residents are spread in proportion to floor area, including commercial floor area within an LSUG.
* The meaning of the census age bands (`age_5` = 65+) was inferred from the territory-wide totals: 19.6% of 7.41 M. It is not taken from an official field dictionary.
