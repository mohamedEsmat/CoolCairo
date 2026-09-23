"""End-to-end stages with an on-disk cache, so notebooks re-run in seconds after the first pass.

Everything runs over the MODEL area (large, for fitting). The DISPLAY district is a subset cut
from the same block grid, so its blocks line up exactly with the ones the model was fitted on.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import xarray as xr

from coolcairo import stac
from coolcairo.blocks import block_features, height_raster
from coolcairo.buildings import fetch_buildings, footprint_mask
from coolcairo.classify import classify_sentinel2
from coolcairo.config import DATA_DIR, Config, geobox_for, projected_bbox

FINE_RESOLUTION = 10  # Sentinel-2 grid (m).


def _cached_array(path: Path, build: callable) -> xr.DataArray | xr.Dataset:
    if path.exists():
        return xr.load_dataset(path, engine="scipy") if path.stem.endswith("_ds") else (
            xr.load_dataarray(path, engine="scipy")
        )
    result = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    result.drop_vars("spatial_ref", errors="ignore").to_netcdf(path, engine="scipy")
    return result


def load_lst(cfg: Config) -> xr.DataArray:
    geobox = geobox_for(cfg, "model_aoi")
    bbox = cfg["model_aoi"]["bbox_wgs84"]
    return _cached_array(DATA_DIR / "lst_30m.nc", lambda: stac.landsat_lst(cfg, geobox, bbox))


def load_sentinel2(cfg: Config) -> xr.Dataset:
    geobox = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    bbox = cfg["model_aoi"]["bbox_wgs84"]
    return _cached_array(
        DATA_DIR / "s2_10m_ds.nc", lambda: stac.sentinel2_composite(cfg, geobox, bbox)
    )


def load_buildings(cfg: Config) -> gpd.GeoDataFrame:
    path = DATA_DIR / "buildings.gpkg"
    if path.exists():
        return gpd.read_file(path)
    gdf = fetch_buildings(cfg, cfg["model_aoi"]["bbox_wgs84"])
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG")
    return gdf


def build_blocks(cfg: Config) -> tuple[pd.DataFrame, xr.DataArray, gpd.GeoDataFrame]:
    """Block feature table for the model area, plus the material raster and buildings."""
    fine_box = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    s2 = load_sentinel2(cfg)
    lst = load_lst(cfg)
    buildings = load_buildings(cfg)

    material = classify_sentinel2(cfg, s2)
    roof = footprint_mask(buildings, fine_box)
    heights = height_raster(buildings, fine_box)
    blocks = block_features(
        material=material,
        roof=roof.assign_coords(x=material.x, y=material.y),
        heights=heights,
        ndvi=stac.ndvi(s2),
        lst=lst,
        fine_factor=cfg.block_size // FINE_RESOLUTION,
        lst_factor=cfg.block_factor,
    )
    return blocks, material, buildings


def display_subset(
    cfg: Config, blocks: pd.DataFrame, buildings: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Blocks and buildings of the display district, with rows/cols renumbered from zero."""
    min_x, min_y, max_x, max_y = projected_bbox(
        cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size
    )
    inside = blocks.x.between(min_x, max_x) & blocks.y.between(min_y, max_y)
    sub = blocks[inside].copy()
    sub["row"] -= sub.row.min()
    sub["col"] -= sub.col.min()

    centroids = buildings.geometry.centroid
    in_display = centroids.x.between(min_x, max_x) & centroids.y.between(min_y, max_y)
    return sub.reset_index(drop=True), buildings[in_display].reset_index(drop=True)
