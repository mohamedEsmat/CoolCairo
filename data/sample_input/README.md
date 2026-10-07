# Example input

Real data for running CoolCairo's analysis offline, without downloading satellite archives.
`analysis/run_example.py` turns it into the files in [`results/`](../../results/summary.md) in a few seconds.
`analysis/make_sample.py` recreates these files from the full pipeline's cache.

| File | What | Size |
| --- | --- | --- |
| `blocks_east_cairo.csv` | Every 90 m block of the east-Cairo model area (23,103 blocks; `in_display = 1` for the 576 Nasr City blocks shown in the app) | 2.7 MB |
| `nasr_city/lst_summer_30m.tif` | Landsat 8/9 summer surface temperature, °C, median of the 2023–25 scenes, 30 m, EPSG:32636 | 72 × 72 px |
| `nasr_city/sentinel2_summer_10m.tif` | Sentinel-2 L2A summer median composite, reflectance 0–1, bands B02 B03 B04 B08 B11 B12, 10 m, EPSG:32636 | 216 × 216 px |
| `nasr_city/buildings.gpkg` | 1,901 building footprints with height (m) and where the height comes from (OSM, Open Buildings, default) | |

## Columns of `blocks_east_cairo.csv`

Shares are fractions of the block's area (0–1). Coordinates are block centres in EPSG:32636 (UTM 36N), metres.

| Column | Meaning |
| --- | --- |
| `row`, `col`, `x`, `y` | Block position in the grid and its centre |
| `in_display` | 1 inside the Nasr City display district |
| `veg_frac`, `dark_frac`, `bright_frac` | Vegetation, dark and bright surfaces (Sentinel-2 rules) |
| `roof_frac`, `dark_roof_frac`, `pale_roof_frac` | Building cover, and dark / pale roofs (OSM footprints × material) |
| `dark_ground_frac`, `soil_frac` | Dark ground (asphalt, dark paving) and bare sand outside buildings |
| `mean_height_m` | Mean roof height (OSM tags, Google Open Buildings 2.5D) |
| `ndvi_mean` | Mean Sentinel-2 NDVI |
| `lst_c` | Summer land surface temperature, °C (Landsat; empty where masked) |
| `population` | Residents (WorldPop 2024) |
| `built_2016`, `built_2023` | Building cover share in 2016 and 2023 (Google Open Buildings Temporal) |
| `growth_class` | 0 still open, 1 built before 2016, 2 denser since 2016, 3 newly built |

## Licences and credits

- Landsat 8/9: USGS, public domain.
- Contains modified Copernicus Sentinel data [2023–2025].
- WorldPop Global2 R2025A, 2024 (CC BY 4.0).
- Building footprints © OpenStreetMap contributors, ODbL; heights and growth: Google Open Buildings 2.5D Temporal (CC BY 4.0).
- No EnMAP data is included: its licence does not allow redistribution (the hyperspectral results need a free DLR account, see the main README).
