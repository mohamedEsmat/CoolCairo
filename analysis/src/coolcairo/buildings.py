"""Building footprints and heights from OpenStreetMap, with machine-learned outlines filling its gaps."""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import shapely
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


# Machine-learned outlines in Overture that may fill OSM gaps (Overture dataset names).
ML_DATASETS = {"Google Open Buildings": "google", "Microsoft ML Buildings": "microsoft"}


def read_overture(path: Path, crs: str) -> gpd.GeoDataFrame:
    """Machine-learned outlines from a fetch_footprints.py snapshot, in the project CRS.

    Overture already keeps one outline per building across its sources; OSM ones are skipped
    here because the pipeline's own OSM extract is used instead.
    """
    df = pd.read_csv(path)
    source = df.datasets.str.strip("[]").map(ML_DATASETS)
    df = df[source.notna()]
    geoms = shapely.from_wkb(df.wkb_hex.map(bytes.fromhex).to_numpy())
    gdf = gpd.GeoDataFrame({"footprint_source": source[source.notna()].to_numpy()},
                           geometry=geoms, crs="EPSG:4326").to_crs(crs)
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].explode(index_parts=False)
    return gdf[gdf.geometry.area > 10].reset_index(drop=True)  # Same sliver rule as OSM.


def fill_footprints(
    osm: gpd.GeoDataFrame, extra: gpd.GeoDataFrame, max_overlap: float = 0.1
) -> gpd.GeoDataFrame:
    """OSM footprints plus the extra outlines that OSM does not already cover.

    An extra outline is dropped when more than `max_overlap` of its area lies inside OSM
    footprints, so OSM always wins where both exist. Added outlines get height_source
    "default", so the height chain (Open Buildings 2.5D, GHSL, default) fills them as usual.
    """
    out_osm = osm.assign(footprint_source="osm")
    if len(extra) == 0:
        return out_osm
    pairs = gpd.sjoin(extra[["geometry"]], osm[["geometry"]], predicate="intersects", how="inner")
    covered = pd.Series(0.0, index=extra.index)
    if len(pairs):
        inter = shapely.intersection(
            extra.geometry.loc[pairs.index].to_numpy(),
            osm.geometry.loc[pairs.index_right].to_numpy(),
        )
        covered = (pd.Series(shapely.area(inter), index=pairs.index).groupby(level=0).sum()
                   .reindex(extra.index, fill_value=0.0))
    keep = covered / extra.geometry.area <= max_overlap
    added = extra[keep].assign(height_m=np.nan, height_source="default")
    cols = ["geometry", "height_m", "height_source", "footprint_source"]
    return gpd.GeoDataFrame(pd.concat([out_osm[cols], added[cols]], ignore_index=True),
                            geometry="geometry", crs=osm.crs)


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
