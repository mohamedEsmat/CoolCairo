"""Write the analysis -> Unity handoff file (export/district.json).

Unity reads this with JsonUtility, so the layout is flat arrays and named fields only
(no dictionaries, no nested arrays, no NaN).

Coordinates: Unity world origin (0, 0, 0) = south-west corner of the display grid.
Unity +X = east (metres), +Z = north (metres). Block arrays are row-major, row 0 = SOUTH.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from coolcairo.interventions import CoolRoofDeltas
from coolcairo.model import FitResult

SCHEMA_VERSION = 1
MISSING = -999.0


def _block_arrays(blocks: pd.DataFrame, rows: int, cols: int) -> dict[str, list]:
    # Analysis rows run north -> south; flip so row 0 is south, matching Unity +Z.
    south_first = blocks.assign(row=rows - 1 - blocks.row).sort_values(["row", "col"])
    if len(south_first) != rows * cols:
        raise ValueError("Block table does not cover the full grid.")
    valid = south_first.lst_c.notna().to_numpy()

    def column(name: str) -> list[float]:
        return [round(float(v), 4) for v in south_first[name].fillna(MISSING)]

    return {
        "valid": valid.astype(int).tolist(),
        "lstC": column("lst_c"),
        "vegFrac": column("veg_frac"),
        "darkRoofFrac": column("dark_roof_frac"),
        "paleRoofFrac": column("pale_roof_frac"),
        "darkGroundFrac": column("dark_ground_frac"),
        "soilFrac": column("soil_frac"),
        "roofFrac": column("roof_frac"),
        "meanHeightM": column("mean_height_m"),
    }


def _building_arrays(
    buildings: gpd.GeoDataFrame, origin: tuple[float, float], block_size: float,
    rows: int, cols: int,
) -> dict[str, list]:
    ox, oy = origin
    xz: list[float] = []
    starts, counts, heights, block_index = [], [], [], []
    for geom, height in zip(buildings.geometry, buildings.height_m, strict=True):
        if not isinstance(geom, Polygon):
            continue
        ring = orient(geom.simplify(0.5), sign=1.0).exterior.coords[:-1]  # CCW, open ring.
        if len(ring) < 3:
            continue
        c = geom.centroid
        col = int((c.x - ox) // block_size)
        row = int((c.y - oy) // block_size)
        if not (0 <= col < cols and 0 <= row < rows):
            continue
        starts.append(len(xz) // 2)
        counts.append(len(ring))
        heights.append(round(float(height), 2))
        block_index.append(row * cols + col)
        for x, y in ring:
            xz.extend((round(x - ox, 2), round(y - oy, 2)))
    return {
        "count": len(counts),
        "vertexStart": starts,
        "vertexCount": counts,
        "heightM": heights,
        "blockIndex": block_index,
        "xz": xz,
    }


def write_district(
    path: Path,
    *,
    name: str,
    crs: str,
    origin: tuple[float, float],
    block_size: float,
    rows: int,
    cols: int,
    blocks: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
    fit: FitResult,
    cool_roof: CoolRoofDeltas,
    cool_roof_method: str,
    provenance: dict[str, str],
) -> dict:
    c = fit.coefficients
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "name": name,
        "crs": crs,
        "originX": origin[0],
        "originY": origin[1],
        "blockSize": block_size,
        "rows": rows,
        "cols": cols,
        "blocks": _block_arrays(blocks, rows, cols),
        "buildings": _building_arrays(buildings, origin, block_size, rows, cols),
        "model": {
            "intercept": fit.intercept,
            "vegFrac": c["veg_frac"],
            "darkRoofFrac": c["dark_roof_frac"],
            "darkGroundFrac": c["dark_ground_frac"],
            "soilFrac": c["soil_frac"],
            "roofFrac": c["roof_frac"],
            "meanHeightM": c["mean_height_m"],
            "r2SpatialCv": fit.r2_spatial_cv,
            "maeSpatialCv": fit.mae_spatial_cv,
            "nBlocks": fit.n_blocks,
            # Surface temperature change per unit block area coated, by starting roof type.
            "coolRoofDarkDeltaC": cool_roof.dark,
            "coolRoofPaleDeltaC": cool_roof.pale,
            "coolRoofMethod": cool_roof_method,
        },
        "provenance": provenance,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def grid_shape(blocks: pd.DataFrame) -> tuple[int, int]:
    return int(blocks.row.max()) + 1, int(blocks.col.max()) + 1


def grid_origin(blocks: pd.DataFrame, block_size: float) -> tuple[float, float]:
    """South-west corner of the block grid in CRS metres (block x/y are centres)."""
    return float(np.min(blocks.x) - block_size / 2), float(np.min(blocks.y) - block_size / 2)
