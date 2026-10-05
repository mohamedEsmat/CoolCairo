"""Urban growth 2016-2023 from Google Open Buildings 2.5D Temporal (annual layers, 30 June).

The same dataset already supplies building heights. Its `building_presence` band is a model
confidence (0-1, effective 4 m) that a pixel is part of a building; a pixel counts as built
when it is at least `growth.presence_min`. Per 90 m block that gives a built share per year,
on the same block grid as the heat model, so growth can be compared with summer surface
temperature block by block.

Caveat: each year is an independent Sentinel-2-based prediction, so small year-to-year changes
are partly noise; the report uses the 2016 -> 2023 change and checks threshold sensitivity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr
from rasterio.enums import Resampling

from coolcairo.blocks import block_mean
from coolcairo.config import Config, geobox_for

FINE_RESOLUTION = 10  # Same 10 m grid as the material map, so blocks line up exactly.

# Block transition classes between the first and last year.
BUILT_BEFORE, NEWLY_BUILT, OPEN = "Built before 2016", "Built 2016-2023", "Still open"


def built_share_fine(presence: xr.DataArray, cfg: Config, presence_min: float) -> xr.DataArray:
    """Share of each 10 m cell covered by built 4 m pixels (0-1), on the model-area grid."""
    geobox = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    target = xr.DataArray(
        np.zeros(geobox.shape, dtype="float32"),
        dims=("y", "x"),
        coords={"y": geobox.coordinates["y"].values, "x": geobox.coordinates["x"].values},
    ).rio.write_crs(geobox.crs.to_wkt()).rio.write_transform(geobox.affine)
    built = (presence >= presence_min).astype("float32").where(presence.notnull())
    share = built.rio.write_nodata(np.nan).rio.reproject_match(target, resampling=Resampling.average)
    return share.assign_coords(x=target.x, y=target.y)


def block_built_share(
    presence_by_year: dict[int, xr.DataArray], cfg: Config, presence_min: float
) -> pd.DataFrame:
    """One row per block (x, y centre) and one `built_<year>` column per year."""
    factor = cfg.block_size // FINE_RESOLUTION
    cols = {
        f"built_{year}": block_mean(built_share_fine(p, cfg, presence_min), factor)
        for year, p in sorted(presence_by_year.items())
    }
    return xr.Dataset(cols).to_dataframe().reset_index()[["x", "y", *cols]]


def transitions(shares: pd.DataFrame, first: int, last: int, built_min: float) -> pd.Series:
    """Block class from the first to the last year, using the same urban cut-off as the model."""
    before = shares[f"built_{first}"] >= built_min
    after = shares[f"built_{last}"] >= built_min
    out = pd.Series(OPEN, index=shares.index)
    out[before] = BUILT_BEFORE
    out[~before & after] = NEWLY_BUILT
    return out


# Codes exported to the app (district.json `blocks.growthClass`), drawn in the Growth view.
OPEN_CODE, STABLE_CODE, DENSER_CODE, NEW_CODE = 0, 1, 2, 3


def growth_class(
    shares: pd.DataFrame, first: int, last: int, built_min: float, denser_min: float
) -> pd.Series:
    """Per block: 3 newly built, 2 built before and denser (cover up by >= denser_min),
    1 built before with little change, 0 still open; -1 where cover is unknown."""
    t = transitions(shares, first, last, built_min)
    gain = shares[f"built_{last}"] - shares[f"built_{first}"]
    out = pd.Series(OPEN_CODE, index=shares.index)
    out[t == BUILT_BEFORE] = STABLE_CODE
    out[(t == BUILT_BEFORE) & (gain >= denser_min)] = DENSER_CODE
    out[t == NEWLY_BUILT] = NEW_CODE
    out[shares[f"built_{first}"].isna() | shares[f"built_{last}"].isna()] = -1
    return out


def attach(blocks: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """Blocks with the yearly `built_<year>` columns joined on their centre coordinates."""
    key = ["x", "y"]
    left = blocks.assign(_x=blocks.x.round(), _y=blocks.y.round())
    right = shares.assign(_x=shares.x.round(), _y=shares.y.round()).drop(columns=key)
    return left.merge(right, on=["_x", "_y"], how="left").drop(columns=["_x", "_y"])


def built_area_km2(shares: pd.DataFrame, block_size: int) -> pd.Series:
    """Building footprint area (km2) per year, summed over the blocks given."""
    cell_km2 = block_size**2 / 1e6
    cols = [c for c in shares.columns if c.startswith("built_")]
    return pd.Series({int(c.split("_")[1]): shares[c].sum() * cell_km2 for c in cols})


def heat_by_transition(blocks: pd.DataFrame) -> pd.DataFrame:
    """Summer LST of blocks by transition class (blocks need `lst_c` and `transition`)."""
    g = blocks.dropna(subset=["lst_c"]).groupby("transition").lst_c
    return g.agg(blocks="size", mean_lst_c="mean", median_lst_c="median").reindex(
        [BUILT_BEFORE, NEWLY_BUILT, OPEN]
    )
