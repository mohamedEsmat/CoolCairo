"""Refinement checks from the course's advanced-analytics session (week 4, 25 Nov 2026).

1. Threshold sensitivity: heat exposure removed against the share of blocks treated (the plan
   uses the riskiest third; how much does that choice matter, and where does it stop paying?).
2. Monte Carlo: the targeted plan rerun 2,000 times with its uncertain inputs redrawn:
   - heat-model coefficients (street trees): refitted on 1 km tiles resampled with replacement;
   - albedo of pale roof, dusty roof and asphalt: library pixels resampled with replacement;
   - block surface temperature: + noise of a 3-summer composite. Between two summers, stable
     blocks differ by 0.61 °C (SD, after the weather offset; docs/validity), so one summer is
     0.61 / sqrt 2 and the 3-summer composite 0.61 / sqrt 6 = 0.25 °C;
   - scenario B also draws the cool-roof sensitivity from its published range, -4 to -8 K per unit
     albedo (Wang, Huang & Li 2020). The app uses -8, the top of that range.
   Each source is also varied alone, to show which one drives the range.
3. Mask check: what EnMAP's land/water/background layer removes, and the scene's cloud, haze,
   cirrus and snow cover from its metadata (bright ground flagged as cloud or water would bias
   the material shares).
4. Co-registration: FFT phase correlation between EnMAP (simulated Sentinel-2 bands) and the
   Sentinel-2 composite on the 30 m grid, for the whole area and per 128-pixel tile.
5. Two-date check: `refinement.two_date_check` is ready for a second scene (EnMAP 2023 or the
   Planet summer scene); it is tested on a known synthetic shift (tests/test_refinement.py).

Usage (from /analysis, after run_pipeline.py and make_unmixing.py):
    uv run python make_refinement.py
Outputs in docs/refinement/: plan_curve.csv, plan_curve.png, monte_carlo.csv, monte_carlo.png,
coregistration_tiles.csv, summary.json. No imagery is written (EnMAP licence).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from coolcairo import enmap
from coolcairo import library as lib
from coolcairo import separability as sep
from coolcairo.config import REPO_ROOT, load_config
from coolcairo.enmap_materials import broadband_albedo
from coolcairo.model import spatial_groups, training_rows
from coolcairo.pipeline import build_blocks, load_enmap, load_sentinel2
from coolcairo.refinement import (
    phase_correlation,
    plan_curve,
    plan_pct,
    shift_image,
    tiled_shifts,
)

OUT = REPO_ROOT / "docs" / "refinement"
LIB_DIR = REPO_ROOT / "docs" / "spectral_library"
DRAWS = 2000
LST_SIGMA_C = 0.607 / np.sqrt(6)  # docs/validity stable targets, see the module docstring
DTS_RANGE = (-8.0, -4.0)
BUILDING_FEATURES = ["roof_frac", "mean_height_m"]
COREG_TILE = 128


def display_blocks() -> tuple[dict, pd.DataFrame]:
    district = json.loads((REPO_ROOT / "export" / "district.json").read_text(encoding="utf-8"))
    snake = lambda k: re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()  # noqa: E731
    return district, pd.DataFrame({snake(k): v for k, v in district["blocks"].items()})


def heat_features(cfg: object, refl: object, endmembers: pd.DataFrame) -> pd.DataFrame:
    """The EnMAP heat model's training table, as make_unmixing.py builds it."""
    frac, _ = lib.fcls(refl, endmembers)
    names = list(frac.endmember.values)
    blocks, _, _ = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"]).reset_index(drop=True)
    block_frac = pd.DataFrame(sep.block_spectra(frac.rename(endmember="feature"), 3, train),
                              columns=names)
    feats = pd.concat([train, block_frac], axis=1)
    cols = [n for n in names if n != lib.SAND] + BUILDING_FEATURES
    return feats[feats[cols + ["lst_c"]].notna().all(axis=1)].reset_index(drop=True), cols


def coefficient_draws(feats: pd.DataFrame, cols: list[str], rng: np.random.Generator,
                      n: int) -> pd.DataFrame:
    """Coefficients refitted on 1 km tiles resampled with replacement (spatial bootstrap)."""
    groups = spatial_groups(feats, 1000)
    tiles = np.unique(groups)
    rows_of = {t: np.flatnonzero(groups == t) for t in tiles}
    x, y = feats[cols].to_numpy(), feats.lst_c.to_numpy()
    out = []
    for _ in range(n):
        idx = np.concatenate([rows_of[t] for t in rng.choice(tiles, len(tiles))])
        out.append(LinearRegression().fit(x[idx], y[idx]).coef_)
    return pd.DataFrame(out, columns=cols)


def albedo_draws(refl: object, used: pd.DataFrame, rng: np.random.Generator,
                 n: int) -> pd.DataFrame:
    """Broadband albedo of each class from library pixels resampled with replacement."""
    wl = refl.wavelength.values
    v = refl.values
    out = {}
    for cls in (lib.PALE_ROOF, lib.DUSTY_ROOF, lib.ASPHALT):
        g = used[used["class"] == cls]
        spectra = v[:, g.row.values, g.col.values]  # (band, pixel)
        out[cls] = [broadband_albedo(pd.Series(
            np.nanmean(spectra[:, rng.integers(0, len(g), len(g))], axis=1), index=wl))
            for _ in range(n)]
    return pd.DataFrame(out)


def info_for(base: dict, cfg: object, dts: float, alb: dict, veg: float, asphalt: float) -> dict:
    """The plan's per-measure deltas with one draw of the inputs (as app_materials)."""
    info = dict(base)
    roof_after, pave_after = cfg["cool_roof"]["albedo_after"], cfg["cool_pavement"]["albedo_after"]
    info["coolRoofPaleDeltaC"] = dts * (roof_after - alb[lib.PALE_ROOF])
    info["coolRoofDustyDeltaC"] = dts * (roof_after - alb[lib.DUSTY_ROOF])
    info["coolPavementDeltaC"] = dts * (pave_after - alb[lib.ASPHALT])
    info["treesDeltaC"] = veg - asphalt
    return info


def monte_carlo(cfg: object, district: dict, blocks: pd.DataFrame, coefs: pd.DataFrame,
                albedos: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Plan % change for each draw, per scenario (all sources, each source alone, + roof range)."""
    info0, ref = district["enmap"], district["model"]["heatReferenceC"]
    dts0 = cfg["cool_roof"]["dts_per_albedo"]
    alb0 = {lib.PALE_ROOF: info0["albedoPaleRoof"], lib.DUSTY_ROOF: info0["albedoDustyRoof"],
            lib.ASPHALT: info0["albedoAsphalt"]}
    veg0, asph0 = info0["coefVegetation"], info0["coefAsphalt"]
    d = blocks.dropna(subset=["lst_c"])
    rows = []
    for i in range(DRAWS):
        noise = pd.Series(rng.normal(0, LST_SIGMA_C, len(d)), index=d.index)
        alb_i = albedos.iloc[i].to_dict()
        veg_i, asph_i = coefs[lib.VEGETATION].iloc[i], coefs[lib.ASPHALT].iloc[i]
        dts_i = rng.uniform(*DTS_RANGE)
        scenarios = {
            "all data sources": (dts0, alb_i, veg_i, asph_i, d.lst_c + noise),
            "heat model only": (dts0, alb0, veg_i, asph_i, d.lst_c),
            "albedo only": (dts0, alb_i, veg0, asph0, d.lst_c),
            "temperature only": (dts0, alb0, veg0, asph0, d.lst_c + noise),
            "all + cool-roof range": (dts_i, alb_i, veg_i, asph_i, d.lst_c + noise),
        }
        for name, (dts, alb, veg, asph, lst) in scenarios.items():
            pct = plan_pct(cfg, blocks, info_for(info0, cfg, dts, alb, veg, asph), ref, lst=lst)
            rows.append({"draw": i, "scenario": name, **pct})
    return pd.DataFrame(rows)


def mask_check(refl: object) -> dict:
    report = json.loads((REPO_ROOT / "analysis" / "data" / "enmap_30m.json")
                        .read_text(encoding="utf-8"))
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    meta = enmap._file(scene, "METADATA").read_text(encoding="utf-8")
    cover = {tag: float(m.group(1)) for tag in
             ("cloudCover", "cloudShadow", "hazeCover", "cirrusCover", "snowCover")
             if (m := re.search(fr"<{tag}>([\d.]+)<", meta))}
    px = report["pixels"]
    return {
        "scene_cover_pct_from_metadata": cover,
        "pixels_on_grid": px["total"],
        "removed_as_water": px["water"],
        "removed_as_background": px["background"],
        "removed_no_data": px["land_without_data"],
        "removed_pct": round(100 * (px["total"] - px["kept"]) / px["total"], 3),
        "reflectance_above_1": report["reflectance"]["above_one_values"],
        "masks_used": "QL_QUALITY_CLASSES only (land / water / background); no cloud, haze or "
                      "snow mask is applied, because the scene metadata report 0 % of each",
    }


def coregistration(cfg: object, refl: object) -> tuple[dict, pd.DataFrame]:
    """EnMAP (as Sentinel-2 bands) against the Sentinel-2 composite, both on the 30 m grid."""
    sim = enmap.simulate_sentinel2(refl)
    s2 = load_sentinel2(cfg).coarsen(x=3, y=3, boundary="trim").mean()
    assert np.allclose(s2.x.values, refl.x.values) and np.allclose(s2.y.values, refl.y.values)
    whole, tiles = {}, []
    for band in ("B04", "B08", "B11"):
        a, b = s2[band].values.astype(float), sim[band].values.astype(float)
        dy, dx, peak = phase_correlation(a, b)
        whole[band] = {"dy_px": round(dy, 3), "dx_px": round(dx, 3), "peak": round(peak, 3)}
        t = tiled_shifts(a, b, COREG_TILE)
        t.insert(0, "band", band)
        tiles.append(t)
    tiles = pd.concat(tiles, ignore_index=True)
    res = abs(float(refl.x[1] - refl.x[0]))
    shift_m = np.hypot(tiles.dy, tiles.dx) * res
    summary = {
        "reference": "Sentinel-2 L2A summer composite (median 2023-25), 10 m averaged to 30 m",
        "moving": "EnMAP 22 Apr 2025 averaged into Sentinel-2 passbands",
        "sign": "the shift that moves EnMAP onto Sentinel-2 (rows down, columns right)",
        "whole_area": whole,
        "tiles": int(len(tiles) / 3),
        "tile_px": COREG_TILE,
        "tile_shift_m_median": round(float(np.median(shift_m)), 1),
        "tile_shift_m_max": round(float(np.max(shift_m)), 1),
        "tile_peak_median": round(float(tiles.peak.median()), 3),
    }
    return summary, tiles


def shift_test(cfg: object, refl: object, checked: pd.DataFrame, dy: float, dx: float) -> dict:
    """Does moving EnMAP onto Sentinel-2 improve the heat model? Same library rows/columns
    (the ground a person checked), same blocks and folds.

    A fractional shift interpolates, which also smooths, and smoothing alone can raise a
    block-level R². So the measured shift is scored next to controls: the opposite shift (same
    smoothing, worse alignment), the same smoothing with no net shift, and whole-pixel shifts
    (exact moves, no smoothing), which is what nearest-neighbour preprocessing can apply.
    """
    from make_unmixing import ols_cv

    v = refl.values
    blur = 0.5 * (shift_image(v, dy, dx) + shift_image(v, -dy, -dx))
    variants = {
        "as delivered": v,
        "measured shift (interpolated)": shift_image(v, dy, dx),
        "opposite shift (same smoothing)": shift_image(v, -dy, -dx),
        "smoothing only (no net shift)": blur,
        "smoothing, then measured shift": shift_image(blur, dy, dx),
        f"whole pixel: {round(dx):.0f} east": shift_image(v, 0.0, float(round(dx))),
        f"whole pixel: {round(dy):.0f} south": shift_image(v, float(round(dy)), 0.0),
        f"whole pixel: {round(dy):.0f} south, {round(dx):.0f} east":
            shift_image(v, float(round(dy)), float(round(dx))),
    }
    out = {}
    for name, data in variants.items():
        cube = refl if data is v else refl.copy(data=data)
        feats, cols = heat_features(cfg, cube, lib.library_from_sheet(cube, checked))
        r2, mae = ols_cv(feats[cols].to_numpy(), feats.lst_c.to_numpy(),
                         spatial_groups(feats, 1000), cfg["cv_folds"])
        coef = LinearRegression().fit(feats[cols].to_numpy(), feats.lst_c.to_numpy()).coef_
        out[name] = {"blocks": len(feats), "r2_spatial_cv": round(r2, 4), "mae_c": round(mae, 4),
                     "coefficients": dict(zip(cols, np.round(coef, 3).tolist(), strict=True))}
        print(name, out[name])
    return out


def plot_curve(curve: pd.DataFrame, third: float, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=130)
    ax.plot(curve.hectares, -curve.targeted_pct, "o-", color="#FF8A3D", ms=4,
            label="roofs + trees + pavements")
    ax.plot(curve.hectares, -curve.no_water_pct, "s--", color="#22C3E6", ms=3,
            label="no-water: roofs + pavements")
    ax.axvline(third, color="#5B6B80", lw=1, ls=":")
    ax.text(third, 5, "  riskiest third\n  (the plan)", color="#5B6B80", fontsize=8)
    for _, r in curve[curve.share.isin([0.1, 0.2, 0.5, 1.0])].iterrows():
        ax.annotate(f"{r.share:.0%} of blocks", (r.hectares, -r.targeted_pct),
                    textcoords="offset points", xytext=(4, -12), fontsize=7, color="#555")
    ax.set_xlabel("roof and asphalt treated, ha (riskiest blocks first)")
    ax.set_ylabel("heat exposure removed, %")
    ax.set_ylim(0, 102)
    ax.set_title("Nasr City: how much the 'riskiest third' choice matters", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_mc(mc: pd.DataFrame, published: float, path: Path) -> None:
    order = ["all data sources", "heat model only", "albedo only", "temperature only",
             "all + cool-roof range"]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=130)
    data = [-mc[mc.scenario == s].targeted for s in order]
    ax.boxplot(data, vert=False, tick_labels=order, whis=(5, 95), showfliers=False,
               medianprops={"color": "#FF8A3D"})
    ax.axvline(-published, color="#5B6B80", lw=1, ls=":")
    ax.text(-published, 5.45, f" published {-published:.1f} %", color="#5B6B80", fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("heat exposure removed by the targeted plan, % (box 25-75 %, whiskers 5-95 %)")
    ax.set_title(f"Targeted plan, {DRAWS:,} Monte Carlo draws per row", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def pct_range(values: pd.Series) -> dict:
    v = -values  # report as "% removed"
    return {"median": round(float(v.median()), 1), "p5": round(float(v.quantile(0.05)), 1),
            "p95": round(float(v.quantile(0.95)), 1)}


def main() -> None:
    cfg = load_config()
    rng = np.random.default_rng(20261125)
    OUT.mkdir(parents=True, exist_ok=True)
    district, blocks = display_blocks()
    info0, ref = district["enmap"], district["model"]["heatReferenceC"]

    # 1. Threshold sensitivity.
    curve = plan_curve(cfg, blocks, info0, ref, district["blockSize"])
    curve.round(3).to_csv(OUT / "plan_curve.csv", index=False)
    d = blocks.dropna(subset=["lst_c"])
    third = plan_curve(cfg, blocks, info0, ref, district["blockSize"],
                       shares=np.array([(len(d) // 3) / len(d)])).iloc[0]
    plot_curve(curve, third.hectares, OUT / "plan_curve.png")
    print(curve.round(1).to_string(index=False))

    # 3. Mask check (cheap, before loading the cube for the rest).
    refl = load_enmap(cfg)
    masks = mask_check(refl)
    print(json.dumps(masks, indent=1))

    # 4. Co-registration.
    coreg, tiles = coregistration(cfg, refl)
    tiles.round(3).to_csv(OUT / "coregistration_tiles.csv", index=False)
    print(json.dumps(coreg, indent=1))
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=lib.PERSON_COLUMN)
    w = coreg["whole_area"]
    dy = float(np.mean([w["B04"]["dy_px"], w["B08"]["dy_px"]]))
    dx = float(np.mean([w["B04"]["dx_px"], w["B08"]["dx_px"]]))
    coreg["heat_model_shift_test"] = {"shift_px": [round(dy, 3), round(dx, 3)],
                                      **shift_test(cfg, refl, checked, dy, dx)}

    # 2. Monte Carlo.
    used = checked[checked.accepted].reset_index(drop=True)
    endmembers = lib.library_from_sheet(refl, checked)
    feats, cols = heat_features(cfg, refl, endmembers)
    full = LinearRegression().fit(feats[cols].to_numpy(), feats.lst_c.to_numpy())
    published = pd.read_csv(LIB_DIR / "unmixing" / "coefficients.csv", index_col=0).iloc[:, 0]
    refit = pd.Series(full.coef_, index=cols)
    assert np.allclose(refit[published.index], published, atol=0.002), "heat model differs"
    coefs = coefficient_draws(feats, cols, rng, DRAWS)
    albedos = albedo_draws(refl, used, rng, DRAWS)
    for cls, key in ((lib.PALE_ROOF, "albedoPaleRoof"), (lib.DUSTY_ROOF, "albedoDustyRoof"),
                     (lib.ASPHALT, "albedoAsphalt")):
        assert abs(albedos[cls].median() - info0[key]) < 0.02, cls
    mc = monte_carlo(cfg, district, blocks, coefs, albedos, rng)
    mc.round(3).to_csv(OUT / "monte_carlo.csv", index=False)
    plot_mc(mc, info0["targetedPct"], OUT / "monte_carlo.png")
    ranges = {s: {"targeted": pct_range(g.targeted), "no_water": pct_range(g.no_water)}
              for s, g in mc.groupby("scenario", sort=False)}
    print(json.dumps(ranges, indent=1))

    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    summary = {
        "session": "Course 3 week 4, advanced hyperspectral analytics (25 Nov 2026)",
        "threshold_sensitivity": {
            "plan_share": round(float(third.share), 4), "plan_blocks": int(third.blocks),
            "plan_hectares": round(float(third.hectares), 1),
            "plan_targeted_pct": round(float(third.targeted_pct), 2),
            "blocks_hotter_than_reference": int((d.lst_c > ref).sum()),
            "reference_c": round(float(ref), 2),
            "note": "heat exposure counts only degrees above the reference, so it all sits in "
                    "the blocks hotter than it; treating more blocks cools them but removes no "
                    "more exposure as defined",
            "curve": curve.round(2).to_dict(orient="records"),
        },
        "monte_carlo": {
            "draws": DRAWS,
            "published_targeted_pct": info0["targetedPct"],
            "sources": {
                "heat model": "coefficients refitted on 1 km tiles resampled with replacement "
                              f"({len(np.unique(spatial_groups(feats, 1000)))} tiles, "
                              f"{len(feats):,} blocks)",
                "albedo": "library pixels resampled with replacement "
                          f"(pale roof {int((used['class'] == lib.PALE_ROOF).sum())}, dusty roof "
                          f"{int((used['class'] == lib.DUSTY_ROOF).sum())}, asphalt "
                          f"{int((used['class'] == lib.ASPHALT).sum())})",
                "temperature": f"block noise SD {LST_SIGMA_C:.2f} °C (3-summer composite)",
                "cool-roof range": f"dTs per unit albedo uniform {DTS_RANGE[1]} to {DTS_RANGE[0]}"
                                   " K (published range; the app uses -8)",
            },
            "coefficient_sd": coefs[[lib.VEGETATION, lib.ASPHALT]].std().round(3).to_dict(),
            "trees_delta_p5_p95": [round(float((coefs[lib.VEGETATION] - coefs[lib.ASPHALT])
                                               .quantile(q)), 2) for q in (0.05, 0.95)],
            "albedo_p5_p95": {c: [round(float(albedos[c].quantile(q)), 3) for q in (0.05, 0.95)]
                              for c in albedos},
            "pct_removed": ranges,
            "not_included": "block material fractions (held fixed) and the population grid",
        },
        "masks": masks,
        "coregistration": coreg,
        "two_date_check": "refinement.two_date_check (shift by phase correlation, then the mean "
                          "spectrum offset on unchanged control pixels) is ready for a second "
                          "scene; tested on a known synthetic shift and offset",
        "attribution": enmap.attribution(scene) + " · Contains modified Copernicus Sentinel data"
                       " [2023-2025] · Landsat 8/9 (USGS) · WorldPop (CC BY 4.0)",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
