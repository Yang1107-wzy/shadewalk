# Validation

## 1. Vector shadows vs. pybdshadow

[pybdshadow](https://github.com/ni1o1/pybdshadow) is an independent open-source building-shadow implementation with its own sun-position code (suncalc). We cast shadows for the 2,080 LandsD buildings in the Kennedy Town area on 2026-07-15 with both tools and compare the union of all shadow polygons in EPSG:2326.

| Local time | Sun altitude | Sun azimuth | ShadeWalk (m²) | pybdshadow 0.3.5 (m²) | IoU |
|---|---:|---:|---:|---:|---:|
| 08:00 | 28.1° | 76.6° | 1,299,370 | 1,299,704 | 0.9970 |
| 10:00 | 55.4° | 84.0° | 986,737 | 985,631 | 0.9964 |
| 12:00 | 83.1° | 95.0° | 708,647 | 708,412 | 0.9975 |
| 14:00 | 69.0° | 272.2° | 848,795 | 847,470 | 0.9968 |
| 16:00 | 41.4° | 279.6° | 1,144,318 | 1,142,341 | 0.9963 |
| 18:00 | 14.5° | 287.6° | 1,752,041 | 1,752,391 | 0.9967 |

```bash
pip install pybdshadow
python scripts/validate_pybdshadow.py demo_data/kennedy_town --date 2026-07-15
```

## 2. LiDAR ray marching vs. exact vector shadows, and shade by source

`scripts/validate_lidar.py` evaluates every outdoor street sample point (2 m spacing) in four ways:

* *Vector:* exact LandsD prism shadows.
* *Buildings on terrain:* LandsD roofs rasterised onto the LiDAR DTM, ray-marched.
* *Full DSM:* adds trees, bridges and small structures.
* *+ cover:* adds overhead canopy and verandahs.

The first column checks the implementation: the same buildings on flat ground, vector vs raster.

| Area | Time | Vector = raster (buildings, flat) | Buildings only (vector) | Buildings on terrain | Full DSM | Full DSM + cover |
|---|---|---:|---:|---:|---:|---:|
| Central–Sheung Wan | 09:00 | 97.2% | 67.4% | 64.6% | 84.4% | 84.6% |
| Central–Sheung Wan | 12:00 | 96.3% | 20.6% | 17.9% | 31.7% | 46.4% |
| Central–Sheung Wan | 15:00 | 97.1% | 55.3% | 54.9% | 78.5% | 78.8% |
| Kennedy Town–HKU | 09:00 | 95.3% | 48.5% | 47.9% | 82.3% | 82.4% |
| Kennedy Town–HKU | 12:00 | 95.7% | 13.9% | 10.3% | 33.2% | 47.6% |
| Kennedy Town–HKU | 15:00 | 95.1% | 40.8% | 37.4% | 72.9% | 73.5% |
| Mong Kok | 09:00 | 95.3% | 57.6% | 59.8% | 85.8% | 86.0% |
| Mong Kok | 12:00 | 95.3% | 21.5% | 18.5% | 35.2% | 50.2% |
| Mong Kok | 15:00 | 95.8% | 54.7% | 53.6% | 78.1% | 78.9% |
| Sha Tin | 09:00 | 96.5% | 32.7% | 30.4% | 69.2% | 69.7% |
| Sha Tin | 12:00 | 98.6% | 6.0% | 4.7% | 17.8% | 36.9% |
| Sha Tin | 15:00 | 96.6% | 23.0% | 20.8% | 60.2% | 61.3% |

* **The ray marcher reproduces exact vector shadows at 95–99% of points.** The disagreement is confined to 1 m pixel edges along facades.
* **Terrain matters little at these times** in these areas. Adding the full DSM raises street shade by roughly 20–35 percentage points. That increase is the shade from trees, footbridges, canopies and other structures that building footprints do not capture.

**Overhead-cover detection vs. LandsD `WeatherProof` coding.** This is the share of street points where LiDAR finds something overhead:

| Area | Segments coded *Covered* | Segments coded *NonCovered* |
|---|---:|---:|
| Central–Sheung Wan | 78.8% | 27.3% |
| Kennedy Town–HKU | 59.4% | 35.3% |
| Mong Kok | 82.2% | 28.3% |
| Sha Tin | 86.6% | 26.8% |

Most officially covered walkways are detected. About a quarter to a third of "non-covered" footway points also have something overhead (street trees, shop canopies, signboards, flyovers): that is shade for a pedestrian, but it is not recorded as a covered walkway. Some of it is facade spill-over at 1 m resolution. ShadeWalk therefore reports the LiDAR model (`shade_*`) as an **upper bound** and the vector building model (`bshade_*`) as a **lower bound**.

## 3. Spatial statistics vs. PySAL

`tests/test_stats.py` checks `shadewalk.stats` against `esda` and `spreg` on synthetic autocorrelated data:

* global Moran's I and the local Moran's \(I_i\) are identical, and the LISA quadrants all agree;
* Getis–Ord \(G_i^*\) z-scores are identical;
* the S2SLS spatial-lag coefficients and standard errors match `spreg.GM_Lag` to \(10^{-8}\).

## 4. Browser router vs. Python

`tests/test_atlas_region.py` exports an atlas JSON, runs `web/router.js` under Node, and checks route length and sunlit metres against `shadewalk.routing`.

## 5. Unit tests

`pytest` (61 tests, offline, synthetic fixtures) covers:

* solar geometry (solstices, equinox, timezones);
* analytic shadow lengths and concave footprints;
* ray-marched shadows, sky view factor and overhead cover on synthetic DSMs, plus LiDAR mosaicking with max/mean aggregation;
* canyon H/W and dissolved coverage;
* routing (λ switch point, one-way edges);
* multi-source access against networkx, and dasymetric totals;
* tiling and merging, caching with SHA-256 provenance, and the CLI and Streamlit app.
