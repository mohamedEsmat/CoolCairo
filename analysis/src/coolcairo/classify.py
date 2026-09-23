"""Surface material classification.

Interim: three coarse classes from Sentinel-2 (the fallback in CLAUDE.md), so the rest of the
pipeline and the Unity app can be built before EnMAP access arrives. The EnMAP classifier must
return the same kind of integer raster; everything downstream only sees class codes.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np
import xarray as xr

from coolcairo.config import Config


class Material(IntEnum):
    NODATA = 0
    VEGETATION = 1
    DARK = 2  # Asphalt, dark roofs, dark aggregate.
    BRIGHT = 3  # Light concrete, pale roofs, bare soil, cool-coated roofs.


def classify_sentinel2(cfg: Config, s2: xr.Dataset) -> xr.DataArray:
    """Rule-based three-class map. Thresholds live in config so they are tunable and traceable."""
    rules = cfg["s2_classification"]
    ndvi = (s2.B08 - s2.B04) / (s2.B08 + s2.B04)
    brightness = (s2.B02 + s2.B03 + s2.B04) / 3.0

    classes = xr.full_like(brightness, Material.BRIGHT, dtype=np.uint8)
    classes = classes.where(brightness > rules["brightness_dark_max"], Material.DARK)
    classes = classes.where(ndvi <= rules["ndvi_vegetation"], Material.VEGETATION)
    classes = classes.where(brightness.notnull(), Material.NODATA)
    classes.name = "material"
    return classes.astype(np.uint8)
