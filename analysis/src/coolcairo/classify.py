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
    BRIGHT = 3  # Light concrete, pale roofs, cool-coated roofs.
    SOIL = 4  # Bare desert soil and sand. As bright as pale concrete, but spectrally distinct.


def bare_soil_index(s2: xr.Dataset) -> xr.DataArray:
    """BSI = ((SWIR1 + red) - (NIR + blue)) / ((SWIR1 + red) + (NIR + blue))."""
    a = s2.B11 + s2.B04
    b = s2.B08 + s2.B02
    return (a - b) / (a + b)


def soil_threshold(
    s2: xr.Dataset, roof: np.ndarray, open_ground: np.ndarray, ndvi_max: float
) -> tuple[float, float]:
    """Best single BSI threshold separating roof pixels from open-ground pixels.

    Returns (threshold, balanced accuracy). This is how `bsi_soil_min` in config was chosen;
    notebook 02 re-runs it so the number is traceable.
    """
    bsi = bare_soil_index(s2).values
    ndvi = ((s2.B08 - s2.B04) / (s2.B08 + s2.B04)).values
    usable = np.isfinite(bsi) & (ndvi < ndvi_max)
    roofs, ground = bsi[usable & roof], bsi[usable & open_ground]
    candidates = np.percentile(np.concatenate([roofs, ground]), np.linspace(2, 98, 97))
    scores = [((ground > t).mean() + (roofs <= t).mean()) / 2 for t in candidates]
    best = int(np.argmax(scores))
    return float(candidates[best]), float(scores[best])


def classify_sentinel2(cfg: Config, s2: xr.Dataset) -> xr.DataArray:
    """Rule-based four-class map. Thresholds live in config so they are tunable and traceable.

    Brightness alone cannot separate pale roofs from desert soil in Cairo (identical medians),
    so bright pixels with a high Bare Soil Index become SOIL.
    """
    rules = cfg["s2_classification"]
    ndvi = (s2.B08 - s2.B04) / (s2.B08 + s2.B04)
    brightness = (s2.B02 + s2.B03 + s2.B04) / 3.0

    classes = xr.full_like(brightness, Material.BRIGHT, dtype=np.uint8)
    classes = classes.where(bare_soil_index(s2) <= rules["bsi_soil_min"], Material.SOIL)
    classes = classes.where(brightness > rules["brightness_dark_max"], Material.DARK)
    classes = classes.where(ndvi <= rules["ndvi_vegetation"], Material.VEGETATION)
    classes = classes.where(brightness.notnull(), Material.NODATA)
    classes.name = "material"
    return classes.astype(np.uint8)
