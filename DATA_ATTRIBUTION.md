# Data attribution

ShadeWalk downloads data from the public sources below. The software itself is MIT-licensed, but these data remain subject to their providers' terms. The files in `demo_data/` are derived from these sources.

| Data | Provider | Access | Terms |
|---|---|---|---|
| Building (footprints, heights) | Lands Department, HKSAR Government | CSDI Portal, dataset `landsd_rcd_1637211194312_35158` (WFS) | [DATA.GOV.HK Terms and Conditions](https://data.gov.hk/en/terms-and-conditions) / [CSDI Portal terms](https://portal.csdi.gov.hk) |
| 3D Pedestrian Network | Lands Department, HKSAR Government | CSDI Portal, dataset `landsd_rcd_1637222018065_52265` (WFS) | as above |
| 2020 airborne LiDAR DSM / DTM (0.5 m) | Civil Engineering and Development Department, HKSAR Government | CSDI Portal, dataset `cedd_rcd_1629267205233_87895` (tile index WFS + `bulkdata.csdi.gov.hk`) | DATA.GOV.HK / CSDI terms |
| 2021 Population Census, Large Subunit Groups | Census and Statistics Department, HKSAR Government | CSDI Portal, dataset `censtatd_rcd_1635933282224_58228` (WFS) | DATA.GOV.HK / CSDI terms |
| Transport terminals (pedestrian-network relation table) | Lands Department, HKSAR Government | CSDI FeatureServer, `landsd_rcd_1637222018065_52265` table 1000 | DATA.GOV.HK / CSDI terms |
| Sentinel-2 Level-2A surface reflectance | European Space Agency (Copernicus) | Microsoft Planetary Computer STAC (`sentinel-2-l2a`) | Copernicus Sentinel data terms (free, attribution) |
| Landsat 8/9 Collection 2 Level-2 surface temperature | U.S. Geological Survey | Microsoft Planetary Computer STAC (`landsat-c2-l2`) | Public domain (USGS); Planetary Computer terms of use |
| Current weather (`rhrread`) | Hong Kong Observatory | data.weather.gov.hk Open Data API | [HKO disclaimer and open data terms](https://www.hko.gov.hk/en/appweb/applink.htm) |

Suggested acknowledgement: *"Contains data from the Lands Department, the Civil Engineering and Development Department and the Census and Statistics Department, HKSAR Government (CSDI Portal); modified Copernicus Sentinel data; Landsat imagery courtesy of the U.S. Geological Survey."*

The web atlas basemap uses OpenFreeMap tiles built from OpenStreetMap data (© OpenStreetMap contributors, ODbL).

The Landsat scene IDs used for each bundled area are listed in `demo_data/<area>/meta.json` (`lst_scenes`).
