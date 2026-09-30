"""Residents per block from WorldPop, and block heat exposure (the "risk" in heat risk).

WorldPop Global2 R2025A, 100 m, constrained (people placed only in built-up areas), 2024.
WorldPop, University of Southampton (www.worldpop.org). Licence: CC BY 4.0.

Heat exposure = residents x degrees C above a reference surface temperature (person-degrees).
It is a hazard x exposure screening indicator, not a health outcome: vulnerability (age,
housing, cooling access) is not included.
"""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import pandas as pd
import rioxarray
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.enums import Resampling

from coolcairo.config import DATA_DIR, Config


def worldpop_path(cfg: Config) -> Path:
    """Local copy of the national WorldPop raster (downloaded once, ~32 MB for Egypt)."""
    url = cfg["worldpop"]["url"]
    path = DATA_DIR / url.rsplit("/", 1)[-1]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(url, path)
    return path


def population_on_grid(cfg: Config, geobox: GeoBox) -> xr.DataArray:
    """Residents per pixel of `geobox`, preserving totals.

    WorldPop pixels are ~3 arc-seconds (about 92 x 80 m here), not aligned to our grid, so
    counts are converted to density (people per m2), resampled by area-weighted average, and
    multiplied back by our pixel area.
    """
    src = rioxarray.open_rasterio(worldpop_path(cfg), masked=True).sel(band=1)
    bounds = geobox.boundingbox.to_crs("EPSG:4326")
    pad = 0.01  # Degrees; avoids edge losses when clipping before reprojection.
    src = src.rio.clip_box(
        bounds.left - pad, bounds.bottom - pad, bounds.right + pad, bounds.top + pad
    )
    src = src.fillna(0)

    # Pixel area in m2 varies with latitude for a lon/lat grid.
    res_x, res_y = (abs(v) for v in src.rio.resolution())
    lat = np.deg2rad(src.y.values)
    m_per_deg = 111_320.0
    area = (res_x * m_per_deg * np.cos(lat))[:, None] * (res_y * m_per_deg)
    density = (src / area).rio.write_crs("EPSG:4326")

    target = xr.DataArray(
        np.zeros(geobox.shape, dtype="float32"),
        dims=("y", "x"),
        coords={"y": geobox.coordinates["y"].values, "x": geobox.coordinates["x"].values},
    ).rio.write_crs(geobox.crs.to_wkt()).rio.write_transform(geobox.affine)
    on_grid = density.rio.reproject_match(target, resampling=Resampling.average)
    pixel_area = abs(geobox.resolution.x * geobox.resolution.y)
    people = (on_grid.where(on_grid >= 0).fillna(0) * pixel_area).astype("float32")
    people.name = "population"
    return people.assign_coords(x=target.x, y=target.y)


def heat_exposure(
    lst_c: pd.Series | np.ndarray, population: pd.Series | np.ndarray, reference_c: float
) -> pd.Series | np.ndarray:
    """Person-degrees above the reference surface temperature (0 where cooler than it)."""
    return population * np.clip(lst_c - reference_c, 0, None)
