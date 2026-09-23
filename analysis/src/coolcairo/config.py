"""Load the project configuration and derive the common analysis grid."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from odc.geo.geobox import GeoBox
from pyproj import Transformer

ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ANALYSIS_ROOT.parent
CONFIG_PATH = ANALYSIS_ROOT / "config" / "aoi.yaml"
DATA_DIR = ANALYSIS_ROOT / "data"  # Git-ignored cache for downloaded rasters.
EXPORT_DIR = REPO_ROOT / "export"


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]

    @property
    def crs(self) -> str:
        return self.raw["crs"]

    @property
    def pixel_size(self) -> int:
        return int(self.raw["pixel_size"])

    @property
    def block_size(self) -> int:
        return int(self.raw["block_size"])

    @property
    def block_factor(self) -> int:
        """Number of analysis pixels along one block edge."""
        factor, rem = divmod(self.block_size, self.pixel_size)
        if rem:
            raise ValueError("block_size must be a multiple of pixel_size")
        return factor

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]


def load_config(path: Path = CONFIG_PATH) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config(yaml.safe_load(f))


def projected_bbox(
    bbox_wgs84: list[float], crs: str, snap: float
) -> tuple[float, float, float, float]:
    """Project a lon/lat bbox and expand it outward to multiples of `snap` metres."""
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    xs, ys = t.transform(
        [min_lon, min_lon, max_lon, max_lon], [min_lat, max_lat, min_lat, max_lat]
    )
    return (
        math.floor(min(xs) / snap) * snap,
        math.floor(min(ys) / snap) * snap,
        math.ceil(max(xs) / snap) * snap,
        math.ceil(max(ys) / snap) * snap,
    )


def geobox_for(cfg: Config, aoi_key: str, resolution: float | None = None) -> GeoBox:
    """Grid for an AOI, snapped to block edges so pixels aggregate cleanly into blocks.

    Every source (Landsat, Sentinel-2, EnMAP) is loaded onto this grid, which is what makes
    the scenes "reprojected to a common grid" (milestone M1).
    """
    bbox = projected_bbox(cfg[aoi_key]["bbox_wgs84"], cfg.crs, cfg.block_size)
    return GeoBox.from_bbox(bbox, crs=cfg.crs, resolution=resolution or cfg.pixel_size)
