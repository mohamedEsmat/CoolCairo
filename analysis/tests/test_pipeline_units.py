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
    CoolRoofDeltas,
    cool_roof_delta,
    cool_roof_surface_deltas,
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
    assert nw.pale_roof_frac == pytest.approx(0.0)
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
    deltas = CoolRoofDeltas(dark=-result.coefficients["dark_roof_frac"], pale=-3.0)
    assert cool_roof_delta(deltas, 0.1, 0.0) == pytest.approx(-0.5, abs=0.05)
    assert cool_roof_delta(deltas, 0.1, 0.2) == pytest.approx(-1.1, abs=0.05)
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
        **{f: [0.1] * 4 for f in FEATURES},
        "pale_roof_frac": [0.3] * 4, "population": [100.0] * 4, "roof_frac": [0.5] * 4,
    })
    buildings = gpd.GeoDataFrame({"height_m": [9.0]}, geometry=[box(10, 10, 40, 30)])
    result = fit(_synthetic_blocks(), 1000, 5)
    rows, cols = grid_shape(blocks)
    out = write_district(
        tmp_path / "d.json", name="t", crs="EPSG:32636", origin=grid_origin(blocks, 90),
        block_size=90, rows=rows, cols=cols, blocks=blocks, buildings=buildings,
        fit=result, cool_roof=CoolRoofDeltas(-4.64, -3.6), cool_roof_method="literature",
        provenance={},
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
    lit = cool_roof_surface_deltas(cfg, result)
    assert lit.dark == pytest.approx(-8.0 * (0.70 - 0.12))
    assert lit.pale == pytest.approx(-8.0 * (0.70 - 0.25))
    regression = {**cfg["cool_roof"], "method": "regression"}
    reg = cool_roof_surface_deltas(type(cfg)({**cfg.raw, "cool_roof": regression}), result)
    assert reg.dark == pytest.approx(-result.coefficients["dark_roof_frac"])
    assert reg.pale == lit.pale  # Pale roofs are the model's reference: always literature.


def test_open_buildings_fill_only_default_heights():
    from coolcairo.openbuildings import apply_heights, footprint_heights

    # 4 m grid, 10 x 10 pixels, origin (0, 40). Left half 12 m buildings, right half no data.
    h = np.full((10, 10), np.nan)
    h[:, :5] = 12.0
    heights = xr.DataArray(
        h, dims=("y", "x"), coords={"y": 40 - 2 - np.arange(10) * 4.0, "x": 2 + np.arange(10) * 4.0}
    )
    buildings = gpd.GeoDataFrame(
        {"height_m": [16.0, 30.0, 16.0], "height_source": ["default", "osm_height", "default"]},
        geometry=[box(0, 0, 16, 16), box(0, 20, 16, 36), box(24, 0, 40, 16)],
    )
    ob = footprint_heights(buildings, heights, min_pixels=3)
    assert ob.iloc[0] == pytest.approx(12.0) and np.isnan(ob.iloc[2])
    out = apply_heights(buildings, ob, default_height=16.0)
    assert out.height_source.tolist() == ["open_buildings", "osm_height", "default"]
    assert out.height_m.tolist() == [12.0, 30.0, 16.0]  # OSM tag is never overridden.


def test_heat_exposure_counts_only_degrees_above_reference():
    from coolcairo.population import heat_exposure

    lst = np.array([40.0, 45.0, 50.0])
    people = np.array([100.0, 100.0, 10.0])
    assert heat_exposure(lst, people, 44.0).tolist() == [0.0, 100.0, 60.0]


def test_block_population_is_summed_not_averaged():
    coords = _fine_grid(9)
    lst = xr.DataArray(np.full((3, 3), 40.0), dims=("y", "x"),
                       coords={"y": np.arange(3)[::-1] * 30.0 + 15, "x": np.arange(3) * 30.0 + 15})
    df = block_features(
        material=xr.DataArray(
            np.full((9, 9), Material.BRIGHT, dtype=np.uint8), dims=("y", "x"), coords=coords
        ),
        roof=xr.DataArray(np.zeros((9, 9), dtype=np.uint8), dims=("y", "x"), coords=coords),
        heights=np.zeros((9, 9)),
        ndvi=xr.DataArray(np.zeros((9, 9)), dims=("y", "x"), coords=coords),
        lst=lst, fine_factor=9, lst_factor=3,
        population=xr.DataArray(np.full((3, 3), 10.0), dims=("y", "x"), coords=lst.coords),
    )
    assert df.population.iloc[0] == pytest.approx(90.0)


def test_separability_labels_pure_roofs_and_far_open_ground():
    from coolcairo.separability import BUILT, OPEN, labels_30m

    roof = np.zeros((90, 90), dtype=np.uint8)
    roof[:3, :3] = 1          # one fully covered 30 m pixel in the corner
    labels = labels_30m(roof, np.zeros((30, 30)), ndvi_max=0.3)
    assert labels[0, 0] == BUILT
    assert labels[1, 1] == -1          # near the building: neither pure roof nor far ground
    assert labels[29, 29] == OPEN      # > 300 m away, not vegetated


def test_simulated_sentinel2_averages_enmap_bands_in_passband():
    from coolcairo.enmap import simulate_sentinel2

    wl = np.array([460.0, 500.0, 600.0])
    refl = xr.DataArray(np.stack([np.full((2, 2), v) for v in (0.1, 0.3, 0.9)]),
                        dims=("wavelength", "y", "x"), coords={"wavelength": wl})
    s2 = simulate_sentinel2(refl)
    assert float(s2.B02[0, 0]) == pytest.approx(0.2)  # mean of 460 and 500 nm, 600 excluded


def test_heat_r2_ranks_informative_features_higher():
    from coolcairo.separability import heat_r2

    rng = np.random.default_rng(1)
    n = 600
    signal = rng.normal(size=(n, 3))
    lst = 40 + signal @ np.array([2.0, -1.0, 0.5]) + rng.normal(0, 0.3, n)
    groups = np.arange(n) // 20
    r2 = heat_r2({"informative": signal, "noise": rng.normal(size=(n, 3))}, lst, groups, folds=5)
    assert r2["informative"] > 0.9 and r2["noise"] < 0.1


def test_enmap_archive_source_uses_item_url_and_date():
    from coolcairo.enmap import archive_source, attribution

    sid = "ENMAP01-____L2A-DT0000127221_20250422T091720Z_006_V010502_20250424T200249Z"
    src = archive_source(sid)
    assert src["firstDate"] == src["lastDate"] == "2025-04-22"
    assert src["itemUrl"].endswith("/items/" + sid)
    assert attribution(sid).endswith("DLR [2025]")


def test_new_interventions_cool_and_respect_caps():
    from coolcairo.interventions import (
        cool_pavement_surface_delta,
        full_adoption_deltas,
        pocket_park_delta,
    )

    cfg = load_config()
    result = fit(_synthetic_blocks(), 1000, 5)
    assert cool_pavement_surface_delta(cfg) == pytest.approx(-8.0 * (0.40 - 0.12))
    # Synthetic data: veg -8, soil +6 -> greening sand cools by 14 per unit area.
    assert pocket_park_delta(result, 0.1) == pytest.approx(-1.4, abs=0.1)
    blocks = _synthetic_blocks().assign(pale_roof_frac=0.2)
    d = full_adoption_deltas(cfg, result, blocks)
    assert (d <= 0).all().all()
    expected_park = pocket_park_delta(result, 0.5 * blocks.soil_frac)  # 50% cap from config
    assert d.pocket_parks.to_numpy() == pytest.approx(expected_park.to_numpy())
