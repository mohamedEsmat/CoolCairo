"""Where each block's input data come from, and how far the app's numbers for it can be trusted.

Every block gets a confidence label from three checks; the label is the weakest of the three:

  footprints  OSM footprint area / built-up area seen from space: Google Open Buildings 2023
              building presence (4 m) where the city has it, else GHSL built-up surface 2020
              (100 m, global; it reads ~40 % higher than Open Buildings in Nasr City, so it is
              only the fallback). Under 40 % mapped = low, under 70 % = medium. Blocks seen as
              almost unbuilt (< 5 % of the block) have nothing to miss and pass. Footprints
              filled from machine-learned outlines (Google / Microsoft, via Overture) count as
              mapped, but a block where they are most of the footprint area is at best medium:
              they are detections, not surveyed outlines.
  heights     share of the block's footprint area with a measured height (OSM tag or storeys,
              Google Open Buildings 2.5D at 4 m). At least 70 % = high; at least 70 % once the
              coarse GHSL 100 m height is added = medium; otherwise mostly the default = low.
  residents   WorldPop (built-up-constrained, 100 m) = high; the GHS-POP fallback = medium.

The label is about inputs, not about the heat model, whose own error (spatial CV) the app
reports separately.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

HIGH, MEDIUM, LOW = 2, 1, 0
LABELS = {HIGH: "high", MEDIUM: "medium", LOW: "low"}

MEASURED_HEIGHTS = ("osm_height", "osm_levels", "open_buildings")
# Height source codes per building in the export (index = code).
HEIGHT_CODES = ("osm_height", "osm_levels", "open_buildings", "ghsl", "default")

FOOTPRINT_HIGH, FOOTPRINT_MEDIUM = 0.7, 0.4
FILLED_MAX_HIGH = 0.5  # Above this share of machine-learned footprint area: at best medium.
BUILT_MIN = 0.05
HEIGHT_SHARE = 0.7
POPULATION_SCORE = {"worldpop": HIGH, "ghs_pop": MEDIUM}


def footprint_completeness(roof_frac: pd.Series, ghsl_built_frac: pd.Series) -> pd.Series:
    """Mapped share of the built-up area GHSL sees (NaN where GHSL sees almost nothing built)."""
    built = ghsl_built_frac.where(ghsl_built_frac >= BUILT_MIN)
    return (roof_frac / built).clip(upper=1.0)


def built_reference(blocks: pd.DataFrame) -> pd.Series:
    """Built-up share per block to check the footprints against: Open Buildings 2023 presence
    (`built_last`, from the growth layers) where present, else GHSL; NaN if neither was read."""
    none = pd.Series(np.nan, index=blocks.index)
    ob = blocks.get("built_last", none)
    ob = ob.where(ob >= 0)  # The export writes missing as negative; keep NaN here.
    return ob.fillna(blocks.get("ghsl_built_frac", none))


def built_reference_name(blocks: pd.DataFrame) -> str:
    ob = blocks.get("built_last")
    if ob is not None and (ob >= 0).any():
        return "Google Open Buildings 2.5D Temporal 2023 (4 m)"
    if "ghsl_built_frac" in blocks:
        return "GHSL built-up surface 2020 (100 m)"
    return ""


def footprint_score(completeness: pd.Series, filled: pd.Series | None = None) -> pd.Series:
    filled = pd.Series(0.0, index=completeness.index) if filled is None else filled.fillna(0.0)
    score = np.select(
        [completeness.isna(), completeness >= FOOTPRINT_MEDIUM],
        [HIGH, np.where((completeness >= FOOTPRINT_HIGH) & (filled <= FILLED_MAX_HIGH), HIGH, MEDIUM)],
        LOW,
    )
    return pd.Series(score, index=completeness.index, dtype=int)


def height_shares(
    blocks: pd.DataFrame, buildings: gpd.GeoDataFrame, block_size: float
) -> pd.DataFrame:
    """Per block: footprint-area shares with a measured height, with a GHSL height, and
    filled from machine-learned outlines.

    Buildings belong to the block holding their centroid; `blocks` has centre x/y columns.
    Blocks without buildings get NaN (nothing to be wrong about).
    """
    min_x = blocks.x.min() - block_size / 2
    max_y = blocks.y.max() + block_size / 2
    c = buildings.geometry.centroid
    col = np.floor((c.x - min_x) / block_size).astype(int)
    row = np.floor((max_y - c.y) / block_size).astype(int)
    table = pd.DataFrame({
        "key": list(zip(row, col)),
        "area": buildings.geometry.area.to_numpy(),
        "measured": buildings.height_source.isin(MEASURED_HEIGHTS).to_numpy(),
        "ghsl": (buildings.height_source == "ghsl").to_numpy(),
        "filled": (buildings.get("footprint_source", pd.Series("osm", index=buildings.index))
                   != "osm").to_numpy(),
    })
    table["measured_area"] = table.area * table.measured
    table["ghsl_area"] = table.area * table.ghsl
    table["filled_area"] = table.area * table.filled
    sums = table.groupby("key")[["area", "measured_area", "ghsl_area", "filled_area"]].sum()
    keys = list(zip(
        np.rint((max_y - block_size / 2 - blocks.y) / block_size).astype(int),
        np.rint((blocks.x - min_x - block_size / 2) / block_size).astype(int),
    ))
    sums = sums.reindex(keys)
    return pd.DataFrame({
        "height_measured_share": (sums.measured_area / sums.area).to_numpy(),
        "height_ghsl_share": (sums.ghsl_area / sums.area).to_numpy(),
        "footprint_filled_share": (sums.filled_area / sums.area).to_numpy(),
    }, index=blocks.index)


def height_score(measured: pd.Series, ghsl: pd.Series) -> pd.Series:
    score = np.select(
        [measured.isna(), measured >= HEIGHT_SHARE, measured + ghsl.fillna(0) >= HEIGHT_SHARE],
        [HIGH, HIGH, MEDIUM], LOW,
    )
    return pd.Series(score, index=measured.index, dtype=int)


def block_quality(
    blocks: pd.DataFrame, buildings: gpd.GeoDataFrame, block_size: float, population_source: str
) -> pd.DataFrame:
    """Completeness, height shares and the confidence label (0 low, 1 medium, 2 high) per block.

    `blocks` needs x, y, roof_frac and ghsl_built_frac (NaN when GHSL was not read: then the
    footprint check is skipped, never guessed).
    """
    shares = height_shares(blocks, buildings, block_size)
    completeness = footprint_completeness(blocks.roof_frac, built_reference(blocks))
    scores = pd.DataFrame({
        "footprint": footprint_score(completeness, shares.footprint_filled_share),
        "height": height_score(shares.height_measured_share, shares.height_ghsl_share),
        "population": POPULATION_SCORE[population_source],
    })
    return pd.DataFrame({
        "footprint_completeness": completeness,
        **shares,
        "confidence": scores.min(axis=1).astype(int),
        # Which check set the label (0 footprints, 1 heights, 2 residents; -1 when all are high).
        "confidence_reason": np.where(
            scores.min(axis=1) == HIGH, -1, scores.to_numpy().argmin(axis=1)
        ).astype(int),
    }, index=blocks.index)


def summary(quality: pd.DataFrame, valid: pd.Series) -> dict:
    """Shares of the district's measured blocks per label, for the app's data panel."""
    labels = quality.confidence[valid]
    n = max(len(labels), 1)
    return {
        "high": round(float((labels == HIGH).sum() / n), 4),
        "medium": round(float((labels == MEDIUM).sum() / n), 4),
        "low": round(float((labels == LOW).sum() / n), 4),
        "footprintHigh": FOOTPRINT_HIGH,
        "filledMaxHigh": FILLED_MAX_HIGH,
        "footprintMedium": FOOTPRINT_MEDIUM,
        "heightShare": HEIGHT_SHARE,
    }
