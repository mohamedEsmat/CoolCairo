"""End-to-end stages with an on-disk cache, so notebooks re-run in seconds after the first pass.

Everything runs over the MODEL area (large, for fitting). The DISPLAY district is a subset cut
from the same block grid, so its blocks line up exactly with the ones the model was fitted on.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from coolcairo import enmap, growth, openbuildings, population, separability, stac
from coolcairo.blocks import block_features, height_raster
from coolcairo.buildings import fetch_buildings, footprint_mask
from coolcairo.classify import classify_sentinel2
from coolcairo.config import DATA_DIR, REPO_ROOT, Config, geobox_for, projected_bbox

FINE_RESOLUTION = 10  # Sentinel-2 grid (m).

# OpenStreetMap changes daily, so a fresh download gives slightly different buildings and
# results (8 Oct 2026: 6 more buildings, R² 0.30 instead of 0.25). This committed extract
# (ODbL) is the one behind the published numbers; set `osm_refresh: true` to use live OSM.
OSM_SNAPSHOT = REPO_ROOT / "data" / "osm" / "buildings_osm_2026-09-23.gpkg"


def _cached_array(path: Path, build: callable) -> xr.DataArray | xr.Dataset:
    if path.exists():
        return xr.load_dataset(path, engine="scipy") if path.stem.endswith("_ds") else (
            xr.load_dataarray(path, engine="scipy")
        )
    result = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    result.drop_vars("spatial_ref", errors="ignore").to_netcdf(path, engine="scipy")
    return result


def load_lst(cfg: Config) -> xr.DataArray:
    geobox = geobox_for(cfg, "model_aoi")
    bbox = cfg["model_aoi"]["bbox_wgs84"]
    return _cached_array(DATA_DIR / "lst_30m.nc", lambda: stac.landsat_lst(cfg, geobox, bbox))


def load_sentinel2(cfg: Config) -> xr.Dataset:
    geobox = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    bbox = cfg["model_aoi"]["bbox_wgs84"]
    return _cached_array(
        DATA_DIR / "s2_10m_ds.nc", lambda: stac.sentinel2_composite(cfg, geobox, bbox)
    )


def load_osm_buildings(cfg: Config) -> gpd.GeoDataFrame:
    """OSM footprints with OSM-only heights: the committed snapshot, or live OSM (cached)."""
    if not cfg.raw.get("osm_refresh", False) and OSM_SNAPSHOT.exists():
        return gpd.read_file(OSM_SNAPSHOT)
    path = DATA_DIR / "buildings.gpkg"
    if path.exists():
        return gpd.read_file(path)
    gdf = fetch_buildings(cfg, cfg["model_aoi"]["bbox_wgs84"])
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG")
    return gdf


def load_open_buildings_heights(cfg: Config) -> xr.DataArray:
    return _cached_array(DATA_DIR / "ob_height_m.nc", lambda: openbuildings.height_mosaic(cfg))


def load_presence(cfg: Config, year: int) -> xr.DataArray:
    """Open Buildings building-presence confidence (0-1, 4 m) over the model area for one year.

    Cached as int16 thousandths (-1 = no data) so eight years fit in ~200 MB.
    """
    def build() -> xr.DataArray:
        p = openbuildings.band_mosaic(cfg, openbuildings.PRESENCE_BAND, year)
        coded = (p * 1000).round().fillna(-1).astype("int16")
        coded.attrs = {"year": year}
        return coded.drop_vars("band", errors="ignore")

    coded = _cached_array(DATA_DIR / f"ob_presence_{year}_4m.nc", build)
    presence = coded.where(coded >= 0) / 1000.0
    return presence.rio.write_crs(cfg.crs)


def add_growth(cfg: Config, blocks: pd.DataFrame) -> pd.DataFrame:
    """Blocks plus building cover in the first and last growth year and the growth class."""
    g = cfg["growth"]
    first, last = g["first_year"], g["last_year"]
    presence = {y: load_presence(cfg, y) for y in (first, last)}
    out = growth.attach(blocks, growth.block_built_share(presence, cfg, g["presence_min"]))
    out["built_first"], out["built_last"] = out[f"built_{first}"], out[f"built_{last}"]
    out["growth_class"] = growth.growth_class(
        out, first, last, g["built_block_min"], g["denser_min"])
    return out


def growth_summary(cfg: Config, blocks: pd.DataFrame) -> dict:
    """What the app's Growth view states about the blocks given (the display district)."""
    g = cfg["growth"]
    cell_km2 = cfg.block_size**2 / 1e6
    return {
        "available": 1,
        "firstYear": g["first_year"],
        "lastYear": g["last_year"],
        "builtFirstKm2": float(blocks.built_first.sum() * cell_km2),
        "builtLastKm2": float(blocks.built_last.sum() * cell_km2),
        "newBlocks": int((blocks.growth_class == growth.NEW_CODE).sum()),
        "denserBlocks": int((blocks.growth_class == growth.DENSER_CODE).sum()),
        "denserMin": g["denser_min"],
        "source": "Google Open Buildings 2.5D Temporal (CC BY 4.0)",
    }


def load_population(cfg: Config) -> xr.DataArray:
    """Residents per 30 m pixel over the model area (WorldPop)."""
    return _cached_array(
        DATA_DIR / "population_30m.nc",
        lambda: population.population_on_grid(cfg, geobox_for(cfg, "model_aoi")),
    )


def load_enmap(cfg: Config) -> xr.DataArray:
    """EnMAP reflectance (wavelength, y, x) on the 30 m model grid (primary scene)."""
    return _cached_array(
        DATA_DIR / "enmap_30m.nc",
        lambda: enmap.reflectance_on_grid(geobox_for(cfg, "model_aoi")),
    )


def load_buildings(cfg: Config) -> gpd.GeoDataFrame:
    """Footprints with heights: OSM tags, then Open Buildings 2.5D, then the config default."""
    osm = load_osm_buildings(cfg)
    ob = openbuildings.footprint_heights(
        osm, load_open_buildings_heights(cfg), cfg["open_buildings_min_pixels"]
    )
    default = cfg["default_levels"] * cfg["storey_height_m"]
    return openbuildings.apply_heights(osm, ob, default)


def build_blocks(cfg: Config) -> tuple[pd.DataFrame, xr.DataArray, gpd.GeoDataFrame]:
    """Block feature table for the model area, plus the material raster and buildings."""
    fine_box = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    s2 = load_sentinel2(cfg)
    lst = load_lst(cfg)
    buildings = load_buildings(cfg)

    material = classify_sentinel2(cfg, s2)
    roof = footprint_mask(buildings, fine_box)
    heights = height_raster(buildings, fine_box)
    blocks = block_features(
        material=material,
        roof=roof.assign_coords(x=material.x, y=material.y),
        heights=heights,
        ndvi=stac.ndvi(s2),
        lst=lst,
        fine_factor=cfg.block_size // FINE_RESOLUTION,
        lst_factor=cfg.block_factor,
        population=load_population(cfg).assign_coords(x=lst.x, y=lst.y),
    )
    return blocks, material, buildings


def display_subset(
    cfg: Config, blocks: pd.DataFrame, buildings: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Blocks and buildings of the display district, with rows/cols renumbered from zero."""
    min_x, min_y, max_x, max_y = projected_bbox(
        cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size
    )
    inside = blocks.x.between(min_x, max_x) & blocks.y.between(min_y, max_y)
    sub = blocks[inside].copy()
    sub["row"] -= sub.row.min()
    sub["col"] -= sub.col.min()

    centroids = buildings.geometry.centroid
    in_display = centroids.x.between(min_x, max_x) & centroids.y.between(min_y, max_y)
    return sub.reset_index(drop=True), buildings[in_display].reset_index(drop=True)


def hyperspectral_summary(cfg: Config, blocks: pd.DataFrame) -> dict | None:
    """How much better EnMAP explains block heat than Sentinel-2 (our features + spectra,
    spatial CV); None when the EnMAP files are not downloaded (they need a DLR login)."""
    from coolcairo.model import FEATURES, spatial_groups, training_rows

    try:
        refl = load_enmap(cfg)
    except FileNotFoundError as err:
        print(f"EnMAP not available, skipping hyperspectral summary: {err}")
        return None
    urban = training_rows(blocks, cfg["min_building_coverage"])
    s2 = load_sentinel2(cfg)[list(enmap.S2_PASSBANDS_NM)].to_array("feature")
    ours = urban[FEATURES].to_numpy()
    r2 = separability.heat_r2(
        {
            "multispectral": np.hstack([ours, separability.block_spectra(s2, 9, urban)]),
            "hyperspectral": np.hstack([ours, separability.block_spectra(refl, 3, urban)]),
        },
        urban.lst_c.to_numpy(),
        spatial_groups(urban, cfg["cv_tile_size"]),
        cfg["cv_folds"],
    )
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    return {
        "available": 1,
        "sceneId": scene,
        "acquired": enmap.acquisition_date(scene),
        "r2Multispectral": float(r2["multispectral"]),
        "r2Hyperspectral": float(r2["hyperspectral"]),
        "attribution": enmap.attribution(scene),
    }
