"""Global fallback layers from the JRC Global Human Settlement Layer (GHSL R2023A, 100 m).

Used only where the better sources are missing:
  * building height: GHS-BUILT-H ANBH 2018 (average net building height per 100 m cell), for
    footprints with no OSM height tag and no Google Open Buildings 2.5D estimate;
  * built-up surface: GHS-BUILT-S 2020 (m2 of building per 100 m cell), the independent check
    of how complete the OpenStreetMap footprints are in each block;
  * residents: GHS-POP 2025, when WorldPop has no file for the country.

Pesaresi & Politis (2023), GHS-BUILT-H R2023A; Pesaresi & Politis (2023), GHS-BUILT-S R2023A;
Schiavina, Freire, Carioli & MacManus (2023), GHS-POP R2023A. European Commission, Joint
Research Centre. Licence: CC BY 4.0.

Tiles are 1000 km squares in World Mollweide (ESRI:54009), public zips on the JRC server (no
account). GDAL reads only the needed window through /vsizip//vsicurl/, nothing is downloaded whole.
"""

from __future__ import annotations

import math

import numpy as np
import rioxarray
import xarray as xr
from odc.geo.geobox import GeoBox
from pyproj import Transformer
from rasterio.enums import Resampling
from rioxarray.merge import merge_arrays

ROOT = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL"
PRODUCTS = {
    "height": ("GHS_BUILT_H_GLOBE_R2023A", "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100"),
    "built": ("GHS_BUILT_S_GLOBE_R2023A", "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100"),
    "population": ("GHS_POP_GLOBE_R2023A", "GHS_POP_E2025_GLOBE_R2023A_54009_100"),
}
CITATION = "GHSL R2023A, European Commission JRC (CC BY 4.0)"
MOLLWEIDE = "ESRI:54009"
CELL_M = 100.0
# Tile grid: 1000 km tiles, column 1 starts at x = -18 041 000 m, row 1 at y = 9 000 000 m.
_X0, _Y0, _TILE = -18_041_000.0, 9_000_000.0, 1_000_000.0


def tile_of(x: float, y: float) -> tuple[int, int]:
    """(row, col) of the tile holding a Mollweide point (1-based, as in the file names)."""
    return math.floor((_Y0 - y) / _TILE) + 1, math.floor((x - _X0) / _TILE) + 1


def mollweide_bbox(bbox_wgs84: list[float], pad_m: float = 0.0) -> tuple[float, float, float, float]:
    """A lon/lat box in Mollweide metres (corners and edge midpoints, padded)."""
    to_moll = Transformer.from_crs("EPSG:4326", MOLLWEIDE, always_xy=True)
    w, s, e, n = bbox_wgs84
    pts = [to_moll.transform(lon, lat) for lon in (w, (w + e) / 2, e) for lat in (s, (s + n) / 2, n)]
    xs, ys = zip(*pts)
    return min(xs) - pad_m, min(ys) - pad_m, max(xs) + pad_m, max(ys) + pad_m


def tiles_for(bbox_moll: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    """Every tile the Mollweide box touches."""
    min_x, min_y, max_x, max_y = bbox_moll
    r0, c0 = tile_of(min_x, max_y)
    r1, c1 = tile_of(max_x, min_y)
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def tile_path(product: str, row: int, col: int) -> str:
    folder, stem = PRODUCTS[product]
    name = f"{stem}_V1_0_R{row}_C{col}"
    return f"/vsizip//vsicurl/{ROOT}/{folder}/{stem}/V1-0/tiles/{name}.zip/{name}.tif"


def read(product: str, bbox_wgs84: list[float], pad_m: float = 1000.0) -> xr.DataArray:
    """One GHSL product over the box, in Mollweide at 100 m; NaN where no data."""
    import rasterio

    box = mollweide_bbox(bbox_wgs84, pad_m)
    parts = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
        for row, col in tiles_for(box):
            da = rioxarray.open_rasterio(tile_path(product, row, col), masked=True).sel(band=1)
            try:
                parts.append(da.rio.clip_box(*box).load())
            except (rioxarray.exceptions.NoDataInBounds, rioxarray.exceptions.OneDimensionalRaster):
                continue
    if not parts:
        raise RuntimeError(f"No GHSL {product} data over {bbox_wgs84}.")
    mosaic = parts[0] if len(parts) == 1 else merge_arrays(parts, nodata=np.nan)
    mosaic = mosaic.where(mosaic >= 0)  # -1 / 65535 style fill values are masked or negative.
    return mosaic.rio.write_crs(MOLLWEIDE)


def sample_points(da: xr.DataArray, xs: np.ndarray, ys: np.ndarray, crs: str) -> np.ndarray:
    """Values of a Mollweide raster at points given in `crs` (nearest cell; NaN outside)."""
    mx, my = Transformer.from_crs(crs, MOLLWEIDE, always_xy=True).transform(xs, ys)
    transform = da.rio.transform()
    cols = np.floor((np.asarray(mx) - transform.c) / transform.a).astype(int)
    rows = np.floor((np.asarray(my) - transform.f) / transform.e).astype(int)
    inside = (rows >= 0) & (rows < da.shape[0]) & (cols >= 0) & (cols < da.shape[1])
    out = np.full(len(cols), np.nan)
    out[inside] = da.values[rows[inside], cols[inside]]
    return out


def share_on_grid(da: xr.DataArray, geobox: GeoBox, per_cell: float) -> xr.DataArray:
    """A per-100 m-cell amount (m2 built, residents) as amount per m2 on `geobox`, area-averaged.

    Mollweide is equal-area, so every source cell is exactly CELL_M x CELL_M.
    """
    density = (da.fillna(0) / per_cell).rio.write_crs(MOLLWEIDE)
    target = xr.DataArray(
        np.zeros(geobox.shape, dtype="float32"), dims=("y", "x"),
        coords={"y": geobox.coordinates["y"].values, "x": geobox.coordinates["x"].values},
    ).rio.write_crs(geobox.crs.to_wkt()).rio.write_transform(geobox.affine)
    out = density.rio.reproject_match(target, resampling=Resampling.average)
    out = out.where(out >= 0).fillna(0).astype("float32")
    return out.assign_coords(x=target.x, y=target.y)
