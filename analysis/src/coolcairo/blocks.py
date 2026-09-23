"""Aggregate pixel rasters into block-level features.

Blocks are the only unit the project reports. A block's numbers are statements like
"this block is 60% dark surface", never per-roof temperatures.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.features import rasterize

from coolcairo.classify import Material


def block_mean(da: xr.DataArray, factor: int) -> xr.DataArray:
    """Mean over non-overlapping factor x factor windows (grids are snapped, so no trimming)."""
    return da.coarsen(x=factor, y=factor, boundary="trim").mean(skipna=True)


def height_raster(buildings: gpd.GeoDataFrame, geobox: GeoBox) -> np.ndarray:
    """Building height (m) per pixel, 0 outside footprints. Taller footprints win overlaps."""
    ordered = buildings.sort_values("height_m")
    return rasterize(
        zip(ordered.geometry, ordered.height_m, strict=True),
        out_shape=geobox.shape,
        transform=geobox.affine,
        fill=0,
        dtype="float32",
    )


def block_features(
    material: xr.DataArray,
    roof: xr.DataArray,
    heights: np.ndarray,
    ndvi: xr.DataArray,
    lst: xr.DataArray,
    fine_factor: int,
    lst_factor: int,
) -> pd.DataFrame:
    """One row per block.

    `material`, `roof`, `heights` and `ndvi` share the fine (10 m) grid; `lst` is on the 30 m
    grid. `fine_factor` and `lst_factor` are how many pixels of each span one block edge.
    """
    is_roof = roof.astype(bool)
    valid = material != Material.NODATA

    def frac(mask: xr.DataArray) -> xr.DataArray:
        return block_mean(mask.where(valid).astype(float), fine_factor)

    height_da = xr.DataArray(heights, dims=roof.dims, coords=roof.coords)
    roof_heights = height_da.where(is_roof)

    layers = {
        "veg_frac": frac(material == Material.VEGETATION),
        "dark_frac": frac(material == Material.DARK),
        "bright_frac": frac(material == Material.BRIGHT),
        "roof_frac": frac(is_roof),
        "dark_roof_frac": frac(is_roof & (material == Material.DARK)),
        "dark_ground_frac": frac(~is_roof & (material == Material.DARK)),
        "mean_height_m": block_mean(roof_heights, fine_factor).fillna(0.0),
        "ndvi_mean": block_mean(ndvi, fine_factor),
    }
    ds = xr.Dataset(layers)
    lst_blocks = block_mean(lst, lst_factor)
    ds["lst_c"] = lst_blocks.assign_coords(x=ds.x, y=ds.y)

    df = ds.to_dataframe().reset_index()
    # Derive grid indices from coordinates, not row order (to_dataframe does not promise one).
    # Row 0 = northernmost block.
    step = abs(float(ds.x[1] - ds.x[0])) if ds.sizes["x"] > 1 else 1.0
    df["row"] = np.rint((df.y.max() - df.y) / step).astype(int)
    df["col"] = np.rint((df.x - df.x.min()) / step).astype(int)
    return df.sort_values(["row", "col"]).reset_index(drop=True)
