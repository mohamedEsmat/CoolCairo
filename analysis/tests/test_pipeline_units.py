import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from coolcairo.blocks import block_features
from coolcairo.classify import Material, classify_sentinel2
from coolcairo.config import geobox_for, load_config
from coolcairo.export import grid_origin, grid_shape, write_district
from coolcairo.interventions import (
    cool_roof_delta,
    cool_roof_surface_delta,
    plausibility_warnings,
    tree_delta,
)
from coolcairo.model import FEATURES, fit, spatial_groups


def test_grid_is_snapped_to_blocks():
    cfg = load_config()
    gb = geobox_for(cfg, "display_aoi")
    x0, y0 = gb.affine.c, gb.affine.f
    assert x0 % cfg.block_size == 0 and y0 % cfg.block_size == 0
    assert gb.shape[0] % cfg.block_factor == 0 and gb.shape[1] % cfg.block_factor == 0


def _fine_grid(n: int) -> dict:
    return {"y": np.arange(n)[::-1] * 10.0 + 5, "x": np.arange(n) * 10.0 + 5}


def test_block_fractions():
    coords = _fine_grid(18)  # 2 x 2 blocks of 9 x 9 pixels.
    material = np.full((18, 18), Material.BRIGHT, dtype=np.uint8)
    material[:9, :9] = Material.DARK  # North-west block all dark.
    roof = np.zeros((18, 18), dtype=np.uint8)
    roof[:9, :9] = 1
    lst = xr.DataArray(np.full((6, 6), 40.0), dims=("y", "x"),
                       coords={"y": np.arange(6)[::-1] * 30.0 + 15, "x": np.arange(6) * 30.0 + 15})
    df = block_features(
        material=xr.DataArray(material, dims=("y", "x"), coords=coords),
        roof=xr.DataArray(roof, dims=("y", "x"), coords=coords),
        heights=roof * 12.0,
        ndvi=xr.DataArray(np.zeros((18, 18)), dims=("y", "x"), coords=coords),
        lst=lst,
        fine_factor=9,
        lst_factor=3,
    )
    nw = df[(df.row == 0) & (df.col == 0)].iloc[0]
    assert nw.dark_roof_frac == pytest.approx(1.0)
    assert nw.mean_height_m == pytest.approx(12.0)
    assert nw.lst_c == pytest.approx(40.0)
    assert df.dark_frac.sum() == pytest.approx(1.0)


def _synthetic_blocks(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "veg_frac": rng.uniform(0, 0.3, n),
        "dark_roof_frac": rng.uniform(0, 0.3, n),
        "dark_ground_frac": rng.uniform(0, 0.3, n),
        "soil_frac": rng.uniform(0, 0.2, n),
        "roof_frac": rng.uniform(0.3, 0.6, n),
        "mean_height_m": rng.uniform(6, 30, n),
        "x": rng.uniform(0, 10_000, n),
        "y": rng.uniform(0, 10_000, n),
    })
    df["lst_c"] = (45 - 8 * df.veg_frac + 5 * df.dark_roof_frac + 3 * df.dark_ground_frac
                   + 6 * df.soil_frac
                   - 0.05 * df.mean_height_m + rng.normal(0, 0.2, n))
    return df


def test_fit_recovers_coefficients_and_intervention_signs():
    result = fit(_synthetic_blocks(), cv_tile_size=1000, cv_folds=5)
    assert result.coefficients["dark_roof_frac"] == pytest.approx(5, abs=0.3)
    assert result.r2_spatial_cv > 0.8
    fitted_roof = -result.coefficients["dark_roof_frac"]
    assert cool_roof_delta(fitted_roof, 0.1) == pytest.approx(-0.5, abs=0.05)
    assert tree_delta(result, 0.1) == pytest.approx(-1.1, abs=0.1)
    assert plausibility_warnings(load_config(), result) == []


def test_spatial_groups_share_tiles():
    df = pd.DataFrame({"x": [10, 990, 1010], "y": [10, 10, 10]})
    g = spatial_groups(df, 1000)
    assert g[0] == g[1] != g[2]


def test_export_roundtrip(tmp_path):
    blocks = pd.DataFrame({
        "row": [0, 0, 1, 1], "col": [0, 1, 0, 1],
        "x": [45.0, 135.0, 45.0, 135.0], "y": [135.0, 135.0, 45.0, 45.0],
        "lst_c": [40.0, np.nan, 42.0, 43.0],
        **{f: [0.1] * 4 for f in FEATURES}, "roof_frac": [0.5] * 4,
    })
    buildings = gpd.GeoDataFrame({"height_m": [9.0]}, geometry=[box(10, 10, 40, 30)])
    result = fit(_synthetic_blocks(), 1000, 5)
    rows, cols = grid_shape(blocks)
    out = write_district(
        tmp_path / "d.json", name="t", crs="EPSG:32636", origin=grid_origin(blocks, 90),
        block_size=90, rows=rows, cols=cols, blocks=blocks, buildings=buildings,
        fit=result, cool_roof_delta_c=-4.64, cool_roof_method="literature", provenance={},
    )
    data = json.loads((tmp_path / "d.json").read_text())
    assert data["blocks"]["valid"] == [1, 1, 1, 0]  # Row 0 is south after the flip.
    assert out["buildings"]["blockIndex"] == [0]
    assert out["buildings"]["vertexCount"] == [4]


def test_bright_soil_is_separated_from_bright_concrete():
    cfg = load_config()
    def px(b02, b03, b04, b08, b11):
        return {"B02": b02, "B03": b03, "B04": b04, "B08": b08, "B11": b11}
    samples = {
        "concrete": px(0.22, 0.23, 0.24, 0.27, 0.30),  # BSI ~ 0.05
        "soil": px(0.18, 0.22, 0.27, 0.30, 0.42),      # BSI ~ 0.18
        "asphalt": px(0.08, 0.09, 0.10, 0.12, 0.15),
        "grass": px(0.04, 0.08, 0.05, 0.40, 0.20),
    }
    s2 = xr.Dataset({b: ("x", [s[b] for s in samples.values()]) for b in samples["soil"]})
    got = [Material(int(v)) for v in classify_sentinel2(cfg, s2).values]
    assert got == [Material.BRIGHT, Material.SOIL, Material.DARK, Material.VEGETATION]


def test_literature_cool_roof_is_cooling_and_switchable():
    cfg = load_config()
    result = fit(_synthetic_blocks(), 1000, 5)
    assert cfg["cool_roof"]["method"] == "literature"
    assert cool_roof_surface_delta(cfg, result) == pytest.approx(-8.0 * (0.70 - 0.12))
    regression = {**cfg["cool_roof"], "method": "regression"}
    regression_cfg = type(cfg)({**cfg.raw, "cool_roof": regression})
    assert cool_roof_surface_delta(regression_cfg, result) == pytest.approx(
        -result.coefficients["dark_roof_frac"])
