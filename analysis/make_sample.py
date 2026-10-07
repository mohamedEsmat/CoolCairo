"""Write the example input in data/sample_input/ from the pipeline's cached data.

Usage (from /analysis, after run_pipeline.py has cached the rasters in analysis/data/):
    uv run python make_sample.py

It writes:
  blocks_east_cairo.csv          every 90 m block of the east-Cairo model area: material shares,
                                 building height, summer surface temperature, residents,
                                 building cover 2016/2023. Input of the model, risk and growth.
  nasr_city/lst_summer_30m.tif   Landsat summer surface temperature, display district
  nasr_city/sentinel2_summer_10m.tif   Sentinel-2 summer composite (6 bands), display district
  nasr_city/buildings.gpkg       building footprints with heights, display district

run_example.py turns the block table into the results in results/, offline. No EnMAP data is
included: its licence does not allow redistribution.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from coolcairo.config import REPO_ROOT, load_config, projected_bbox
from coolcairo.pipeline import add_growth, build_blocks, load_lst, load_sentinel2

SAMPLE_DIR = REPO_ROOT / "data" / "sample_input"

COLUMNS = [
    "row", "col", "x", "y", "in_display",
    "veg_frac", "dark_frac", "bright_frac", "roof_frac", "dark_roof_frac", "pale_roof_frac",
    "dark_ground_frac", "soil_frac", "mean_height_m", "ndvi_mean",
    "lst_c", "population", "built_2016", "built_2023", "growth_class",
]


def main() -> None:
    cfg = load_config()
    blocks, _, buildings = build_blocks(cfg)
    blocks = add_growth(cfg, blocks)

    min_x, min_y, max_x, max_y = projected_bbox(
        cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size)
    blocks["in_display"] = (blocks.x.between(min_x, max_x)
                            & blocks.y.between(min_y, max_y)).astype(int)

    district = SAMPLE_DIR / "nasr_city"
    district.mkdir(parents=True, exist_ok=True)
    table = blocks[COLUMNS].copy()
    floats = table.select_dtypes("number").columns.difference(
        ["row", "col", "in_display", "growth_class"])
    table[floats] = table[floats].astype(float).round(5)
    table.to_csv(SAMPLE_DIR / "blocks_east_cairo.csv", index=False)

    def crop(da: xr.DataArray | xr.Dataset) -> xr.DataArray | xr.Dataset:  # y runs N to S
        return da.sel(x=slice(min_x, max_x), y=slice(max_y, min_y)).rio.write_crs(cfg.crs)

    lst = crop(load_lst(cfg)).astype(np.float32)
    lst.attrs = {"units": "degC", "description": "Landsat 8/9 C2 L2 ST_B10, summer median 2023-25"}
    lst.rio.to_raster(district / "lst_summer_30m.tif", compress="deflate")

    s2 = crop(load_sentinel2(cfg)).astype(np.float32)
    s2.attrs = {"description": "Sentinel-2 L2A summer median composite 2023-25, reflectance 0-1"}
    s2.rio.to_raster(district / "sentinel2_summer_10m.tif", compress="deflate")

    c = buildings.geometry.centroid
    inside = c.x.between(min_x, max_x) & c.y.between(min_y, max_y)
    buildings[inside].to_file(district / "buildings.gpkg", driver="GPKG")

    print(f"{len(table):,} blocks ({table.in_display.sum()} in the display district), "
          f"{int(inside.sum()):,} buildings, rasters {lst.shape} and {s2.rio.shape} "
          f"-> {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
