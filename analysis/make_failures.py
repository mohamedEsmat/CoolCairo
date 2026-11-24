"""Failure cases with their spectra (course week 3, session 3: "three failure cases").

The three blocks the heat model gets most wrong on held-out 1 km tiles (EnMAP spectra + our
features, the report's best model): the worst under-prediction, the worst over-prediction and
the next-worst block at least `MIN_SEP_M` from both. Plus one point where the Sentinel-2
material rule disagreed with the M2 spot check. For each: a Sentinel-2 true-colour chip, its
EnMAP spectrum against the checked library's class means, and the numbers behind it.

Usage (from /analysis, after run_pipeline.py):
    uv run python make_failures.py
Outputs in docs/validity/: failures.png, failures.json.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from openpyxl import load_workbook
from pyproj import Transformer

from coolcairo import library as lib
from coolcairo import robustness as rb
from coolcairo.config import REPO_ROOT, load_config
from coolcairo.growth import DENSER_CODE, NEW_CODE, OPEN_CODE, STABLE_CODE
from coolcairo.model import TARGET, spatial_groups, training_rows
from coolcairo.pipeline import add_growth, build_blocks, load_enmap, load_sentinel2
from make_robustness import LIB_DIR, feature_sets

OUT = REPO_ROOT / "docs" / "validity"
HEAD = "Our features + EnMAP spectra"
MIN_SEP_M = 1500
CHIP_M = 600          # side of the true-colour chip
M2_POINT = 3          # spot-check point shown (Sentinel-2 rule said sand; seen: dusty asphalt)
GROWTH = {OPEN_CODE: "open", STABLE_CODE: "built before 2016, little change",
          DENSER_CODE: "built before 2016, denser by 2023", NEW_CODE: "newly built 2016-2023",
          -1: "unknown"}
COLOURS = {lib.SAND: "#C9A227", lib.PALE_ROOF: "#8E8E8E", lib.DUSTY_ROOF: "#A0522D",
           lib.ASPHALT: "#222222", lib.VEGETATION: "#2E8B57"}


def pick_blocks(res: np.ndarray, xy: np.ndarray) -> list[int]:
    """Worst under-prediction, worst over-prediction, then the next worst far from both."""
    picks = [int(np.argmin(res)), int(np.argmax(res))]
    for i in np.argsort(-np.abs(res)):
        if all(np.hypot(*(xy[i] - xy[j])) >= MIN_SEP_M for j in picks):
            picks.append(int(i))
            break
    return picks


def window(da: object, x: float, y: float, half: float) -> object:
    return da.sel(x=slice(x - half, x + half), y=slice(y + half, y - half))


def rgb_chip(s2: object, x: float, y: float) -> np.ndarray:
    w = window(s2, x, y, CHIP_M / 2)
    img = np.dstack([w[b].values for b in ("B04", "B03", "B02")]).astype(float)
    lo, hi = np.nanpercentile(img, 2), np.nanpercentile(img, 98)
    return np.clip((img - lo) / (hi - lo), 0, 1)


def enmap_spectrum(refl: object, x: float, y: float, half: float) -> np.ndarray:
    return window(refl, x, y, half).mean(["x", "y"]).values


def sam_deg(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    c = np.dot(a[ok], b[ok]) / (np.linalg.norm(a[ok]) * np.linalg.norm(b[ok]))
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def main() -> None:
    cfg = load_config()
    blocks, _, _ = build_blocks(cfg)
    blocks = add_growth(cfg, blocks)
    train = training_rows(blocks, cfg["min_building_coverage"]).reset_index(drop=True)
    sets, ok = feature_sets(cfg, train)
    sub = train[ok].reset_index(drop=True)
    y, xy = sub[TARGET].to_numpy(), sub[["x", "y"]].to_numpy()
    x, make, _ = sets[HEAD]
    pred, _ = rb.buffered_cv_predict(x[ok], y, xy, spatial_groups(sub, cfg["cv_tile_size"]),
                                     cfg["cv_folds"], 0, make)
    res = pred - y

    refl = load_enmap(cfg)
    s2 = load_sentinel2(cfg)
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=lib.PERSON_COLUMN)
    used = checked[checked.accepted].reset_index(drop=True)
    means = lib.class_spectra(refl, used)
    frac, _ = lib.fcls(refl, lib.library_from_sheet(refl, checked))
    wl = means.index.to_numpy(float)
    to_ll = Transformer.from_crs(cfg.crs, "EPSG:4326", always_xy=True)
    half_block = cfg.block_size / 2

    cases = []
    for i in pick_blocks(res, xy):
        b = sub.iloc[i]
        spec = enmap_spectrum(refl, b.x, b.y, half_block)
        fr = window(frac, b.x, b.y, half_block).mean(["x", "y"])
        lon, lat = to_ll.transform(b.x, b.y)
        cases.append({
            "kind": "block", "x": float(b.x), "y": float(b.y), "lat": lat, "lon": lon,
            "measured_c": float(y[i]), "predicted_c": float(pred[i]), "residual_c": float(res[i]),
            "residual_rank_pct": float((np.abs(res) < abs(res[i])).mean() * 100),
            "veg_frac": float(b.veg_frac), "roof_frac": float(b.roof_frac),
            "soil_frac": float(b.soil_frac), "dark_ground_frac": float(b.dark_ground_frac),
            "mean_height_m": float(b.mean_height_m), "growth": GROWTH[int(b.growth_class)]
            if pd.notna(b.growth_class) else "unknown",
            "enmap_fractions": {str(k): round(float(v), 3) for k, v in
                                zip(fr.endmember.values, fr.values, strict=True)},
            "sam_deg": {c: round(sam_deg(spec, means[c].to_numpy()), 2) for c in means.columns},
            "spectrum": spec,
        })

    ws = load_workbook(REPO_ROOT / "docs" / "m2_spot_check.xlsx")["Spot check"]
    row = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == M2_POINT)
    lat, lon = ws.cell(row, 2).value, ws.cell(row, 3).value
    px, py = Transformer.from_crs("EPSG:4326", cfg.crs, always_xy=True).transform(lon, lat)
    spec = refl.sel(x=px, y=py, method="nearest").values
    cases.append({
        "kind": "point", "x": px, "y": py, "lat": lat, "lon": lon, "point": M2_POINT,
        "predicted_class": ws.cell(row, 5).value, "observed_class": ws.cell(row, 6).value,
        "note": str(ws.cell(row, 8).value).split(" [")[0],
        "sam_deg": {c: round(sam_deg(spec, means[c].to_numpy()), 2) for c in means.columns},
        "spectrum": spec,
    })

    # Figure: chips on top, spectra below.
    fig, axes = plt.subplots(2, len(cases), figsize=(3.2 * len(cases), 6.0), dpi=200,
                             gridspec_kw={"height_ratios": [1, 0.9]})
    letters = "ABCD"
    for k, c in enumerate(cases):
        ax = axes[0, k]
        ax.imshow(rgb_chip(s2, c["x"], c["y"]), extent=[-CHIP_M / 2, CHIP_M / 2] * 2)
        size = cfg.block_size if c["kind"] == "block" else cfg.pixel_size
        ax.add_patch(Rectangle((-size / 2, -size / 2), size, size, fill=False, ec="#FF3B30",
                               lw=2))
        ax.set_xticks([]), ax.set_yticks([])
        if c["kind"] == "block":
            title = (f"{letters[k]}  {c['measured_c']:.1f} °C measured\n"
                     f"{c['predicted_c']:.1f} °C modelled ({c['residual_c']:+.1f})")
        else:
            title = (f"{letters[k]}  spot-check point {c['point']}\n"
                     f"rule: {c['predicted_class'].split(' /')[-1].strip().lower()}; "
                     f"seen: {c['observed_class'].lower()}")
        ax.set_title(title, fontsize=10)
        ax = axes[1, k]
        for cls in means.columns:
            ax.plot(wl, means[cls], color=COLOURS.get(cls, "#999999"), lw=1.0, alpha=0.75,
                    label=cls)
        ax.plot(wl, c["spectrum"], color="#FF3B30", lw=2.0,
                label="this block" if c["kind"] == "block" else "this pixel")
        ax.set_xlabel("wavelength (nm)", fontsize=9)
        ax.set_ylim(0, 0.72)
        ax.tick_params(labelsize=8)
        if k == 0:
            ax.set_ylabel("reflectance", fontsize=9)
            ax.legend(fontsize=7, frameon=False, loc="upper left", ncol=2, handlelength=1.0,
                      columnspacing=0.8)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "failures.png")

    for c in cases:
        c.pop("spectrum")
    summary = {"model": HEAD, "tile_m": cfg["cv_tile_size"], "blocks": int(len(y)),
               "residual_sd_c": float(res.std()), "cases": cases}
    text = json.dumps(summary, indent=2, ensure_ascii=False, default=lambda o: o.item())
    (OUT / "failures.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
