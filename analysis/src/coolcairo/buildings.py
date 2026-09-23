"""Building footprints and heights from OpenStreetMap."""

from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.features import rasterize

from coolcairo.config import Config

_NUMBER = re.compile(r"[-+]?\d*\.?\d+")


def _to_float(value: object) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    match = _NUMBER.search(str(value))
    return float(match.group()) if match else np.nan


def fetch_buildings(cfg: Config, bbox_wgs84: list[float]) -> gpd.GeoDataFrame:
    """Footprints in the project CRS with a `height_m` column and its provenance.

    Height order here: OSM `height` -> OSM `building:levels` x storey height -> config default.
    Most Cairo buildings have no height tag; pipeline.load_buildings then replaces "default"
    heights with Google Open Buildings 2.5D estimates where available.
    """
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    raw = ox.features_from_bbox((min_lon, min_lat, max_lon, max_lat), tags={"building": True})
    gdf = raw[raw.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].explode(index_parts=False)
    gdf = gdf.reset_index()[["geometry", *[c for c in ("height", "building:levels") if c in gdf]]]
    gdf = gdf.to_crs(cfg.crs)

    tagged = gdf.get("height", pd.Series(np.nan, index=gdf.index)).map(_to_float)
    levels = gdf.get("building:levels", pd.Series(np.nan, index=gdf.index)).map(_to_float)
    from_levels = levels * cfg["storey_height_m"]
    default = cfg["default_levels"] * cfg["storey_height_m"]

    gdf["height_m"] = tagged.fillna(from_levels).fillna(default)
    gdf["height_source"] = np.select(
        [tagged.notna(), from_levels.notna()], ["osm_height", "osm_levels"], "default"
    )
    gdf = gdf[gdf.geometry.area > 10].reset_index(drop=True)  # Drop slivers / mapping errors.
    return gdf[["geometry", "height_m", "height_source"]]


def footprint_mask(buildings: gpd.GeoDataFrame, geobox: GeoBox) -> xr.DataArray:
    """1 where a pixel centre falls inside a footprint, else 0, on the given grid."""
    mask = rasterize(
        ((geom, 1) for geom in buildings.geometry),
        out_shape=geobox.shape,
        transform=geobox.affine,
        fill=0,
        dtype="uint8",
    )
    coords = geobox.coordinates
    return xr.DataArray(
        mask, dims=("y", "x"), coords={"y": coords["y"].values, "x": coords["x"].values}
    )
