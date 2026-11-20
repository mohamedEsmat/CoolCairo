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

    # GHSL fills only what is still at the default; a zero GHSL height (unbuilt cell) does not.
    ghsl = pd.Series([40.0, 40.0, 9.0], index=buildings.index)
    out = apply_heights(buildings, ob, default_height=16.0, ghsl_heights=ghsl)
    assert out.height_source.tolist() == ["open_buildings", "osm_height", "ghsl"]
    assert out.height_m.tolist() == [12.0, 30.0, 9.0]
    out = apply_heights(buildings, ob, 16.0, pd.Series([np.nan, np.nan, 0.0], index=buildings.index))
    assert out.height_source.tolist()[2] == "default"


def test_ghsl_tiles_match_the_jrc_file_names():
    from coolcairo import ghsl

    # Tiles read for the five cities on 20 Nov 2026 (the files exist under these names).
    for lon, lat, tile in [(31.335, 30.06, (6, 21)), (55.305, 25.248, (6, 24)),
                           (46.728, 24.656, (6, 23)), (-7.557, 33.584, (5, 18))]:
        box_m = ghsl.mollweide_bbox([lon, lat, lon, lat])
        assert ghsl.tiles_for(box_m) == [tile]
    assert ghsl.tile_path("height", 6, 21).endswith(
        "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R6_C21.zip/"
        "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R6_C21.tif")


def test_block_confidence_is_the_weakest_check():
    from coolcairo import quality

    # Four 90 m blocks in a row (centres x = 45 .. 315, y = 45).
    blocks = pd.DataFrame({
        "x": [45.0, 135.0, 225.0, 315.0], "y": [45.0] * 4,
        "roof_frac": [0.30, 0.10, 0.30, 0.0],
        "built_last": [0.35, 0.35, 0.35, 0.01],       # Open Buildings: preferred reference
        "ghsl_built_frac": [0.9, 0.9, 0.9, 0.9],        # ignored where Open Buildings exists
    })
    buildings = gpd.GeoDataFrame(
        {"height_source": ["open_buildings", "osm_levels", "ghsl", "default", "default"]},
        geometry=[box(10, 10, 40, 40), box(100, 10, 130, 40), box(190, 10, 230, 40),
                  box(240, 10, 250, 20), box(140, 50, 150, 60)],
    )
    q = quality.block_quality(blocks, buildings, 90.0, "worldpop")
    # Block 0: mapped 86 %, heights measured -> high. Block 1: 29 % mapped -> low (footprints).
    # Block 2: mapped, heights mostly GHSL -> medium (heights). Block 3: nothing built, no
    # buildings -> high.
    assert q.confidence.tolist() == [2, 0, 1, 2]
    assert q.confidence_reason.tolist() == [-1, 0, 1, -1]
    assert q.footprint_completeness.round(2).tolist()[:3] == [0.86, 0.29, 0.86]
    assert np.isnan(q.footprint_completeness[3])
    assert q.height_ghsl_share.round(2)[2] == round(1200 / 1300, 2)
    # Block 1 holds one measured building and one default one of a quarter its area.
    assert q.height_measured_share.round(2)[1] == 0.9
    # GHS-POP residents cap every block at medium.
    assert quality.block_quality(blocks, buildings, 90.0, "ghs_pop").confidence.tolist() == [1, 0, 1, 1]
    # Without Open Buildings the GHSL share is the reference.
    no_ob = blocks.drop(columns="built_last")
    assert quality.built_reference_name(no_ob).startswith("GHSL")
    assert quality.block_quality(no_ob, buildings, 90.0, "worldpop").confidence.tolist()[0] == 0


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


def test_enmap_band_choices_report_counts_each_bad_window(tmp_path):
    import json

    from coolcairo.enmap import band_choices, write_report

    wl = np.array([410.0, 500.0, 1400.0, 1450.0, 1600.0, 1900.0, 2200.0, 2450.0])
    rep = band_choices(wl)
    assert rep["bands_total"] == 8 and rep["bands_kept"] == 3
    assert rep["kept_range_nm"] == [500.0, 2200.0]
    dropped = [w["bands_dropped"] for w in rep["bad_windows"]]
    assert dropped == [1, 2, 1, 1]  # <420, water vapour 1330-1480, 1780-1990, >2400 nm

    write_report({"bands": rep}, tmp_path / "out" / "enmap.json")
    assert json.loads((tmp_path / "out" / "enmap.json").read_text(encoding="utf-8"))["bands"] == rep


def test_shadow_mask_falls_away_from_the_sun_with_the_right_length():
    from coolcairo.library import shadow_mask

    h = np.zeros((41, 41), dtype="float32")
    h[20, 20] = 40.0  # One 40 m tower on a 4 m grid; sun due south, 45 degrees high.
    grid = xr.DataArray(h, dims=("y", "x"),
                        coords={"y": np.arange(41)[::-1] * 4.0, "x": np.arange(41) * 4.0})
    sh = shadow_mask(grid, sun_elevation=45.0, sun_azimuth=180.0)
    assert sh[19, 20] and sh[11, 20]          # North of the tower, up to ~40 m away.
    assert not sh[21, 20] and not sh[8, 20]   # Not south of it, not beyond 40 m.
    assert not sh[20, 20]                     # The roof itself is lit.


def test_library_candidates_are_spread_out_and_ranked_by_homogeneity():
    from coolcairo.library import CLASSES, candidates

    rng = np.random.default_rng(0)
    wl = np.linspace(450, 2400, 20)
    base = np.linspace(0.1, 0.4, 20)[:, None, None]
    cube = base + rng.normal(0, 0.002, (20, 30, 30))
    refl = xr.DataArray(cube, dims=("wavelength", "y", "x"),
                        coords={"wavelength": wl, "y": 3_330_000 - np.arange(30) * 30.0,
                                "x": 330_000 + np.arange(30) * 30.0})
    masks = {c: np.zeros((30, 30), bool) for c in CLASSES}
    masks[CLASSES[0]][:] = True
    picks = candidates(refl, masks, "EPSG:32636", per_class=5)
    assert len(picks) == 5
    d = np.hypot(picks.x.values[:, None] - picks.x.values, picks.y.values[:, None] - picks.y.values)
    assert d[np.triu_indices(5, 1)].min() >= 300
    assert picks.homogeneity_deg.is_monotonic_increasing


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


def test_open_buildings_year_url_swaps_only_the_dated_folder():
    from coolcairo.openbuildings import year_url

    url = "https://x/v1/geotiffs/14584_2023_06_30/tile_2023ab.tif"
    assert year_url(url, 2016) == "https://x/v1/geotiffs/14584_2016_06_30/tile_2023ab.tif"


def test_growth_transitions_and_built_area():
    from coolcairo.growth import BUILT_BEFORE, NEWLY_BUILT, OPEN, built_area_km2, transitions

    shares = pd.DataFrame({"built_2016": [0.30, 0.02, 0.01], "built_2023": [0.35, 0.25, 0.05]})
    assert transitions(shares, 2016, 2023, 0.10).tolist() == [BUILT_BEFORE, NEWLY_BUILT, OPEN]
    area = built_area_km2(shares, 90)  # 0.0081 km2 per block.
    assert area[2016] == pytest.approx(0.33 * 0.0081)
    assert area[2023] == pytest.approx(0.65 * 0.0081)


def test_growth_built_share_counts_confident_pixels_per_10m_cell():
    from coolcairo.growth import built_share_fine

    cfg = load_config()
    gb = geobox_for(cfg, "model_aoi", 10)
    x0, y0 = gb.affine.c, gb.affine.f  # North-west corner.
    # 5 m pixels over the first two 10 m cells of the top row: left cell 3 of 4 built, right 0.
    p = np.array([[0.9, 0.8, 0.1, 0.2], [0.7, 0.3, 0.0, 0.4]], dtype="float32")
    da = xr.DataArray(p, dims=("y", "x"),
                      coords={"y": [y0 - 2.5, y0 - 7.5], "x": x0 + 2.5 + 5.0 * np.arange(4)})
    da = da.rio.write_crs(cfg.crs)
    share = built_share_fine(da, cfg, 0.5)
    assert float(share.isel(y=0, x=0)) == pytest.approx(0.75)
    assert float(share.isel(y=0, x=1)) == pytest.approx(0.0)


def test_growth_class_codes():
    from coolcairo.growth import growth_class

    shares = pd.DataFrame({"built_2016": [0.30, 0.30, 0.02, 0.01, np.nan],
                           "built_2023": [0.32, 0.40, 0.25, 0.05, 0.2]})
    assert growth_class(shares, 2016, 2023, 0.10, 0.05).tolist() == [1, 2, 3, 0, -1]


def test_osm_buildings_come_from_the_committed_snapshot():
    """Live OSM changes daily; the published numbers use the 23 Sep 2026 extract in data/osm."""
    from coolcairo.pipeline import OSM_SNAPSHOT, load_osm_buildings

    if not OSM_SNAPSHOT.exists():
        pytest.skip("snapshot not in this checkout")
    cfg = load_config()
    assert cfg["osm_refresh"] is False
    assert len(load_osm_buildings(cfg)) == 15129


def test_sam_ignores_brightness_and_leaves_far_or_missing_pixels_unclassified():
    from coolcairo.library import UNCLASSIFIED, sam_angles, sam_classify

    a, b = np.array([0.2, 0.3, 0.4]), np.array([0.4, 0.3, 0.2])
    spectra = pd.DataFrame({"A": a, "B": b})
    pixels = np.stack([a * 0.3, b * 2.0, np.array([0.3, 0.3, 0.3]), [np.nan, 0.3, 0.3]], axis=1)
    refl = xr.DataArray(pixels[:, None, :], dims=("wavelength", "y", "x"))
    angles = sam_angles(refl, spectra)
    assert angles[0, 0, 0] == pytest.approx(0, abs=1e-4)  # A, three times darker
    assert sam_classify(angles, max_angle=30)[0].tolist() == [0, 1, 0, UNCLASSIFIED]
    assert sam_classify(angles, max_angle=5)[0].tolist() == [0, 1, UNCLASSIFIED, UNCLASSIFIED]


def test_band_depth_and_brightness_separate_classes_the_angle_cannot():
    from coolcairo.library import band_depth, fused_classify, material_features, sam_angles

    grid = np.arange(2200, 2401, 10.0)  # EnMAP-like 10 nm spacing; depths average 3 bands.
    dip = np.where(np.abs(grid - 2310) <= 10, 0.8, 1.0)
    one = xr.DataArray(dip[:, None, None] * 0.4, dims=("wavelength", "y", "x"),
                       coords={"wavelength": grid})
    assert band_depth(one, 2310, 2230, 2390)[0, 0] == pytest.approx(0.2)

    wl = np.array([450, 700, 900, 2230, 2310, 2340, 2390], float)
    flat = np.ones(7)

    # Two bright and two dark flat pixels (slightly different shapes): one shape, two classes.
    tilt = np.linspace(-0.01, 0.01, 7)
    px = [0.40 * (flat + tilt), 0.42 * (flat - tilt), 0.10 * (flat + tilt), 0.11 * (flat - tilt)]
    refl = xr.DataArray(np.stack(px, axis=1)[:, None, :], dims=("wavelength", "y", "x"),
                        coords={"wavelength": wl})
    picks = pd.DataFrame({"class": ["bright", "bright", "dark", "dark"],
                          "row": [0, 0, 0, 0], "col": [0, 1, 2, 3]})
    spectra = pd.DataFrame({"bright": 0.4 * flat, "dark": 0.1 * flat})
    assert np.ptp(sam_angles(refl, spectra)[:, 0, 0]) < 1e-6  # The angle cannot tell them apart.
    out = fused_classify(refl, material_features(refl, depths=False), picks, max_dist=1e9)
    assert out[0].tolist() == [0, 0, 1, 1]


def test_fcls_recovers_known_fractions_that_sum_to_one():
    from coolcairo.library import fcls

    wl = np.arange(400, 2401, 100.0)
    rng = np.random.default_rng(0)
    em = pd.DataFrame({"a": rng.uniform(0.1, 0.5, wl.size), "b": rng.uniform(0.1, 0.5, wl.size),
                       "Shade": np.full(wl.size, 0.01)})
    truth = np.array([[0.6, 0.3, 0.1], [0.0, 0.8, 0.2]]).T  # (endmember, pixel)
    pix = em.to_numpy() @ truth
    pix = np.column_stack([pix, np.full(wl.size, np.nan)])  # a pixel with missing data
    refl = xr.DataArray(pix[:, None, :], dims=("wavelength", "y", "x"),
                        coords={"wavelength": wl, "y": [0.0], "x": [0.0, 1.0, 2.0]})
    frac, rmse = fcls(refl, em)
    assert frac.values[:, 0, :2] == pytest.approx(truth, abs=1e-3)
    assert frac.values[:, 0, :2].sum(axis=0) == pytest.approx([1, 1], abs=1e-3)
    assert (frac.values[:, 0, :2] >= 0).all() and np.isnan(frac.values[:, 0, 2]).all()
    assert rmse[0, :2] == pytest.approx([0, 0], abs=1e-4)


def test_broadband_albedo_weights_visible_light_most():
    from coolcairo.enmap_materials import broadband_albedo

    wl = np.arange(420, 2450, 10.0)
    flat = pd.Series(0.3, index=wl)
    assert broadband_albedo(flat) == pytest.approx(0.3)
    # Bright in the visible, dark in the SWIR: the sun's weight pulls the albedo up.
    vis_bright = pd.Series(np.where(wl < 700, 0.6, 0.1), index=wl)
    assert broadband_albedo(vis_bright) > vis_bright.mean()


def test_enmap_treatable_areas_put_roofs_on_footprints_and_cap_ground():
    from coolcairo.enmap_materials import treatable_areas

    blocks = pd.DataFrame({
        "roof_frac": [0.4, 0.0, 0.5],
        "enmap_pale_roof": [0.3, 0.5, 0.0],
        "enmap_dusty_roof": [0.1, 0.0, 0.0],
        "enmap_asphalt": [0.7, 0.2, 0.3],
        "enmap_sand": [0.1, 0.6, 0.2],
    })
    area = treatable_areas(blocks)
    # Footprint share split in EnMAP's pale : dusty proportions (3:1); half and half if neither.
    assert area.roof_pale.tolist() == pytest.approx([0.3, 0.0, 0.25])
    assert area.roof_dusty.tolist() == pytest.approx([0.1, 0.0, 0.25])
    # No footprint, no roof to coat, even where EnMAP sees pale-roof-like paving.
    assert area.roof_pale[1] + area.roof_dusty[1] == 0
    # Asphalt and sand never exceed the ground share.
    assert area.asphalt.tolist() == pytest.approx([0.6, 0.2, 0.3])
    assert area.sand.tolist() == pytest.approx([0.1, 0.6, 0.2])
