"""Building heights from Google Open Buildings 2.5D Temporal (v1).

Sirko et al., "High-Resolution Building and Road Detection from Sentinel-2" (2023).
License: CC BY 4.0 and ODbL v1.0. Heights are model estimates from Sentinel-2 at an effective
4 m resolution, so they fill gaps where OSM has no height tag; they do not override OSM tags.

Tiles are public GeoTIFFs on Google Cloud Storage (no account). They are 0.5 m pixel grids with
internal overviews, so only a 4 m overview window over the AOI is read.
Bands: 1 building_fractional_count, 2 building_height (m, 0-100), 3 building_presence.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
import xarray as xr
from rasterio.features import rasterize
from rioxarray.merge import merge_arrays

from coolcairo.config import ANALYSIS_ROOT, Config, projected_bbox

TILE_LIST = ANALYSIS_ROOT / "config" / "open_buildings_tiles.txt"
HEIGHT_BAND = 2
PRESENCE_BAND = 3  # Model confidence (0-1) that a pixel is part of a building.
YEARS = list(range(2016, 2024))  # Annual layers, each dated 30 June.
NODATA = -99.0
# Read at the data's effective resolution; finer overviews only repeat the same information.
TARGET_RESOLUTION_M = 4.0


def overview_level(url: str, target_res: float = TARGET_RESOLUTION_M) -> int | None:
    """Index of the coarsest overview no coarser than target_res (None = full resolution).

    Matched by decimation factor, not position: these files list overviews coarsest-first.
    """
    import rasterio

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open("/vsicurl/" + url) as src:
            factors = src.overviews(HEIGHT_BAND)
            native = abs(src.res[0])
    usable = [(f, i) for i, f in enumerate(factors) if f * native <= target_res]
    return max(usable)[1] if usable else None


def tile_urls(path: Path = TILE_LIST) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def find_tiles(url_list: list[str], bbox_wgs84: list[float]) -> list[str]:
    """Tiles from a country URL list (HDX `urls/EGY_2023.txt`) that intersect the bbox.

    Used once to write config/open_buildings_tiles.txt; reads only each tile's header.
    """
    import rasterio
    from rasterio.warp import transform_bounds

    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    hits = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for url in url_list:
            with rasterio.open("/vsicurl/" + url) as src:
                w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            if w < max_lon and e > min_lon and s < max_lat and n > min_lat:
                hits.append(url)
    return hits


def year_url(url: str, year: int) -> str:
    """Same tile in another year's layer: only the dated folder differs (`<id>_<year>_06_30`)."""
    return re.sub(r"/(\d+)_\d{4}_06_30/", rf"/\g<1>_{year}_06_30/", url)


def height_mosaic(cfg: Config, aoi_key: str = "model_aoi") -> xr.DataArray:
    """Building height (m) over the AOI in the project CRS; NaN where no data."""
    mosaic = band_mosaic(cfg, HEIGHT_BAND, 2023, aoi_key)
    mosaic.name = "ob_height_m"
    return mosaic


def band_mosaic(cfg: Config, band: int, year: int, aoi_key: str = "model_aoi") -> xr.DataArray:
    """One band of one year's layer over the AOI in the project CRS (4 m); NaN where no data."""
    min_x, min_y, max_x, max_y = projected_bbox(cfg[aoi_key]["bbox_wgs84"], cfg.crs, 1)
    parts = []
    for url in (year_url(u, year) for u in tile_urls()):
        da = rioxarray.open_rasterio(
            "/vsicurl/" + url, overview_level=overview_level(url), masked=True
        ).sel(band=band)
        if da.rio.crs.to_string() != cfg.crs:
            da = da.rio.reproject(cfg.crs)
        try:
            parts.append(da.rio.clip_box(min_x, min_y, max_x, max_y).load())
        except (
            rioxarray.exceptions.NoDataInBounds,
            rioxarray.exceptions.OneDimensionalRaster,  # Tile only grazes the AOI edge.
        ):
            continue
    if not parts:
        raise RuntimeError("No Open Buildings tiles cover the AOI; regenerate the tile list.")
    mosaic = merge_arrays(parts, nodata=np.nan)
    return mosaic.where(mosaic != NODATA)


def footprint_heights(
    buildings: gpd.GeoDataFrame, heights: xr.DataArray, min_pixels: int
) -> pd.Series:
    """Median Open Buildings height inside each footprint (NaN if too few built pixels)."""
    ids = rasterize(
        ((geom, i + 1) for i, geom in enumerate(buildings.geometry)),
        out_shape=heights.shape,
        transform=heights.rio.transform(),
        fill=0,
        dtype="int32",
    )
    values = heights.values
    built = (ids > 0) & np.isfinite(values) & (values > 0)
    per_pixel = pd.DataFrame({"id": ids[built] - 1, "h": values[built]})
    stats = per_pixel.groupby("id").h.agg(["median", "size"])
    median = stats["median"].where(stats["size"] >= min_pixels)
    return median.reindex(range(len(buildings))).set_axis(buildings.index)


def validate_against_osm(buildings: gpd.GeoDataFrame, ob_heights: pd.Series) -> dict[str, float]:
    """Compare Open Buildings estimates with OSM-tagged heights (the only ground truth we have)."""
    tagged = buildings.height_source.isin(["osm_height", "osm_levels"])
    pairs = pd.DataFrame({"osm": buildings.height_m[tagged], "ob": ob_heights[tagged]}).dropna()
    err = pairs.ob - pairs.osm
    return {
        "n": len(pairs),
        "bias_m": float(err.mean()),
        "mae_m": float(err.abs().mean()),
        "median_abs_err_m": float(err.abs().median()),
        "correlation": float(pairs.osm.corr(pairs.ob)),
    }


def apply_heights(
    buildings: gpd.GeoDataFrame, ob_heights: pd.Series, default_height: float
) -> gpd.GeoDataFrame:
    """Fill buildings without an OSM height from Open Buildings; the config default stays last."""
    out = buildings.copy()
    fill = (out.height_source == "default") & ob_heights.notna()
    out.loc[fill, "height_m"] = ob_heights[fill]
    out.loc[fill, "height_source"] = "open_buildings"
    still_default = out.height_source == "default"
    out.loc[still_default, "height_m"] = default_height
    return out
