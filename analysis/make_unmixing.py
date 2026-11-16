"""Unmix EnMAP into material fractions and test them in the heat model.

Usage (from /analysis, after make_library_candidates.py):
    uv run python make_unmixing.py               # library = pixels confirmed by a person
    uv run python make_unmixing.py --provisional # library = AI pre-check, NOT confirmed

Each 30 m pixel is solved as a mix of the library spectra plus a near-zero shade spectrum
(fully constrained least squares: fractions >= 0, summing to 1). Then:

1. Pixel checks on labels independent of the library: pure OSM roofs should get mostly roof,
   open ground (far from OSM and Open Buildings) mostly sand, and the shade fraction should
   rise where the building-height model predicts shadow.
2. Heat model: the PoC's linear model and spatial folds (1 km tiles, 5 folds), with the
   Sentinel-2 material shares (veg, dark roof, dark ground, soil) replaced by the EnMAP
   fractions averaged over each 90 m block. Roof cover and height stay. Sand is left out as
   the reference fraction, so each coefficient reads "this material instead of sand".

Writes docs/spectral_library/unmixing[_provisional]/:
  fractions.png     one map per endmember, plus the residual
  heat_model.csv    spatial-CV R2 and MAE per feature set and held-out tile size
  coefficients.csv  linear-model coefficients (degC per unit fraction), all blocks
  summary.json      everything above plus the pixel checks
"""

from __future__ import annotations

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

from coolcairo import enmap
from coolcairo import library as lib
from coolcairo import separability as sep
from coolcairo.config import load_config
from coolcairo.model import FEATURES, spatial_groups, training_rows
from coolcairo.pipeline import build_blocks, load_enmap
from make_sam_map import LIB_DIR, SHADE_HIGH, SHADE_LOW, independent_labels

ROOFS = [lib.PALE_ROOF, lib.DUSTY_ROOF]
REFERENCE = lib.SAND
BUILDING_FEATURES = ["roof_frac", "mean_height_m"]  # From footprints, not from spectra.


def ols_cv(x: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int) -> tuple[float, float]:
    """The PoC's evaluation: linear regression, predictions on held-out spatial tiles."""
    pred = np.empty_like(y)
    for train, test in GroupKFold(n_splits=folds).split(x, y, groups):
        pred[test] = LinearRegression().fit(x[train], y[train]).predict(x[test])
    return float(r2_score(y, pred)), float(mean_absolute_error(y, pred))


def plot(frac: object, rmse: np.ndarray, path: object, scene: str, title: str) -> None:
    names = list(frac.endmember.values)
    fig, axes = plt.subplots(2, 4, figsize=(14, 7.5), dpi=130)
    for ax, name in zip(axes.flat, [*names, "Residual RMSE"], strict=False):
        data = rmse if name == "Residual RMSE" else frac.sel(endmember=name).values
        vmax = np.nanpercentile(rmse, 99) if name == "Residual RMSE" else 1
        im = ax.imshow(data, cmap="magma" if name == "Residual RMSE" else "viridis",
                       vmin=0, vmax=vmax, interpolation="nearest")
        ax.set_title(name, fontsize=9)
        ax.set_axis_off()
        fig.colorbar(im, ax=ax, fraction=0.04)
    for ax in axes.flat[len(names) + 1:]:
        ax.set_axis_off()
    fig.suptitle(title, fontsize=10)
    fig.text(0.01, 0.01, enmap.attribution(scene) + " · Google Open Buildings 2.5D (CC BY 4.0)"
             " · © OpenStreetMap contributors (ODbL)", fontsize=6, color="#555")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provisional", action="store_true",
                    help="use the AI pre-check (column I) instead of the person's answers")
    args = ap.parse_args()
    column = lib.AI_PRECHECK_COLUMN if args.provisional else lib.PERSON_COLUMN
    out = LIB_DIR / ("unmixing_provisional" if args.provisional else "unmixing")
    kind = ("provisional library (AI pre-check, not confirmed)" if args.provisional
            else "confirmed library")

    cfg = load_config()
    refl = load_enmap(cfg)
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=column)
    used = checked[checked.accepted].reset_index(drop=True)
    if used.empty:
        raise SystemExit(f"No accepted rows in column {column}: confirm the candidates first.")
    endmembers = lib.library_from_sheet(refl, checked)
    frac, rmse = lib.fcls(refl, endmembers)
    names = list(frac.endmember.values)

    # 1. Pixel checks.
    truth, shade, near_library = independent_labels(cfg, refl, scene, used)
    ok = np.isfinite(rmse) & ~near_library
    roof_px, ground_px = ok & (truth == sep.BUILT), ok & (truth == sep.OPEN)
    f = {n: frac.sel(endmember=n).values for n in names}
    roof_share = sum(f[n] for n in ROOFS)
    shade_bins = {f"model shadow < {SHADE_LOW:.0%}": ok & (shade < SHADE_LOW),
                  f"model shadow {SHADE_LOW:.0%}-{SHADE_HIGH:.0%}":
                      ok & (shade >= SHADE_LOW) & (shade <= SHADE_HIGH),
                  f"model shadow > {SHADE_HIGH:.0%}": ok & (shade > SHADE_HIGH)}
    pixel_checks = {
        "osm_roof_pixels": int(roof_px.sum()),
        "osm_roof_mean_fractions": {n: round(float(f[n][roof_px].mean()), 3) for n in names},
        "osm_roof_roof_fraction_over_half": round(float((roof_share[roof_px] > 0.5).mean()), 3),
        "open_ground_pixels": int(ground_px.sum()),
        "open_ground_mean_fractions": {n: round(float(f[n][ground_px].mean()), 3) for n in names},
        "open_ground_sand_over_half": round(float((f[REFERENCE][ground_px] > 0.5).mean()), 3),
        "shade_fraction_by_modelled_shadow": {
            k: {"pixels": int(m.sum()),
                "mean_shade_fraction": round(float(f["Shade"][m].mean()), 3)}
            for k, m in shade_bins.items()},
        "shade_vs_modelled_shadow_spearman": round(float(
            pd.Series(f["Shade"][ok]).corr(pd.Series(shade[ok]), method="spearman")), 3),
        "residual_rmse_median": round(float(np.nanmedian(rmse)), 4),
        "residual_rmse_p95": round(float(np.nanpercentile(rmse, 95)), 4),
    }

    # 2. Heat model, PoC blocks and folds.
    blocks, _, _ = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"]).reset_index(drop=True)
    block_frac = pd.DataFrame(sep.block_spectra(frac.rename(endmember="feature"), 3, train),
                              columns=names)
    enmap_cols = [n for n in names if n != REFERENCE]
    feats = pd.concat([train, block_frac.add_prefix("enmap: ")], axis=1)
    sets = {
        "PoC (Sentinel-2 shares + buildings)": FEATURES,
        "EnMAP fractions + buildings": [f"enmap: {n}" for n in enmap_cols] + BUILDING_FEATURES,
        "EnMAP fractions only": [f"enmap: {n}" for n in enmap_cols],
        "PoC + EnMAP fractions": FEATURES + [f"enmap: {n}" for n in enmap_cols],
    }
    usable = feats[[c for cols in sets.values() for c in cols] + ["lst_c"]].notna().all(axis=1)
    feats = feats[usable].reset_index(drop=True)
    y = feats.lst_c.to_numpy()
    rows = []
    for name, cols in sets.items():
        for tile in (1000, 2000, 3000):
            r2, mae = ols_cv(feats[cols].to_numpy(), y, spatial_groups(feats, tile),
                             cfg["cv_folds"])
            rows.append({"features": name, "tile_m": tile, "r2_spatial_cv": r2, "mae_c": mae})
    heat = pd.DataFrame(rows)
    cols = sets["EnMAP fractions + buildings"]
    model = LinearRegression().fit(feats[cols].to_numpy(), y)
    coef = pd.Series(model.coef_, index=[c.removeprefix("enmap: ") for c in cols],
                     name="degC_per_unit_fraction_vs_sand")

    out.mkdir(parents=True, exist_ok=True)
    heat.round(4).to_csv(out / "heat_model.csv", index=False)
    coef.round(3).to_csv(out / "coefficients.csv")
    summary = {
        "library": kind, "scene": scene,
        "endmembers": names, "library_pixels": used["class"].value_counts().to_dict(),
        "pixel_checks": pixel_checks,
        "heat_model_blocks": int(len(feats)),
        "heat_model": heat.round(4).to_dict(orient="records"),
        "coefficients_vs_sand": coef.round(3).to_dict(),
        "attribution": enmap.attribution(scene) + " · Google Open Buildings 2.5D (CC BY 4.0)"
                       " · © OpenStreetMap contributors (ODbL)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    plot(frac, rmse, out / "fractions.png", scene,
         f"FCLS material fractions, east Cairo, EnMAP 22 Apr 2025: {kind}")

    print(json.dumps(pixel_checks, indent=1))
    print(heat.pivot(index="features", columns="tile_m", values="r2_spatial_cv").round(3))
    print(heat[heat.tile_m == 1000].set_index("features").mae_c.round(3))
    print(coef.round(2).to_string())
    print(f"blocks {len(feats)} -> {out}")


if __name__ == "__main__":
    main()
