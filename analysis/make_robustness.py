"""Robustness of the heat model: buffered CV, domain shift, random-forest baseline.

Course week 3, session 1 (GeoAI methods), slides 19, 21 and 29-32, on our own data:
1. Buffer: the pipeline's spatial CV (1 km tiles, 5 folds), with training blocks within
   0-500 m of the test tile dropped. Landsat's thermal pixel is ~100 m, so at >= 200 m no
   training block shares a thermal pixel with a test block.
2. Random forest next to our linear models (same folds; 0 and 200 m buffer), for the
   Sentinel-2 PoC features, the app's EnMAP fractions and our features + EnMAP spectra.
3. Domain shift: the Cairo model (Sentinel-2 shares + buildings) applied unchanged to the four
   test cities, against each city's own model and own models trained on few local blocks.

Usage (from /analysis, after run_pipeline.py for Cairo and the four test cities):
    uv run python make_robustness.py
Outputs in docs/robustness/: buffer.csv, random_forest.csv, transfer.csv, coefficients.csv,
summary.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from coolcairo import library as lib
from coolcairo import robustness as rb
from coolcairo import separability as sep
from coolcairo.config import REPO_ROOT, load_config
from coolcairo.model import FEATURES, TARGET, spatial_groups, training_rows
from coolcairo.pipeline import build_blocks, load_enmap

LIB_DIR = REPO_ROOT / "docs" / "spectral_library"
OUT = REPO_ROOT / "docs" / "robustness"
BUFFERS_M = (0, 100, 200, 300, 500)
RF_BUFFERS_M = (0, 200)
TEST_CITIES = ("algiers", "casablanca", "dubai", "riyadh")
LOCAL_BLOCKS = (100, 300, 1000)
LOCAL_REPEATS = 10


def ridge() -> object:
    return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13)))


def feature_sets(cfg: object, train: pd.DataFrame) -> tuple[dict, np.ndarray]:
    """The three feature sets compared in the report, and the mask of blocks valid in all of
    them (all 12,451 in Cairo). Values: (features, model factory, model name)."""
    refl = load_enmap(cfg)
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=lib.PERSON_COLUMN)
    frac, _ = lib.fcls(refl, lib.library_from_sheet(refl, checked))
    names = list(frac.endmember.values)
    fr = sep.block_spectra(frac.rename(endmember="feature"), 3, train)
    enmap_fr = fr[:, [i for i, n in enumerate(names) if n != lib.SAND]]
    ours = train[FEATURES].to_numpy()
    sets = {
        "Sentinel-2 materials + buildings": (ours, LinearRegression, "linear"),
        "EnMAP materials + buildings": (
            np.hstack([enmap_fr, train[["roof_frac", "mean_height_m"]].to_numpy()]),
            LinearRegression, "linear"),
        "Our features + EnMAP spectra": (np.hstack([ours, sep.block_spectra(refl, 3, train)]),
                                         ridge, "ridge"),
    }
    ok = np.isfinite(train[TARGET].to_numpy())
    for x, _, _ in sets.values():
        ok &= np.isfinite(x).all(axis=1)
    return sets, ok


def city_rows(city: str) -> pd.DataFrame:
    """A test city's training rows, built in a subprocess with that city's config and cache."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{city}.csv"
        env = {**os.environ, "COOLCAIRO_CONFIG": f"config/aoi_{city}.yaml",
               "COOLCAIRO_DATA_DIR": f"data/{city}", "COOLCAIRO_EXPORT_DIR": f"../export/{city}"}
        subprocess.run([sys.executable, __file__, "--rows", str(out)], env=env, check=True)
        return pd.read_csv(out)


def write_rows(path: str) -> None:
    cfg = load_config()
    blocks, _, _ = build_blocks(cfg)
    training_rows(blocks, cfg["min_building_coverage"])[["x", "y", *FEATURES, TARGET]].to_csv(
        path, index=False)


def main() -> None:
    cfg = load_config()
    folds, tile = cfg["cv_folds"], cfg["cv_tile_size"]
    blocks, _, _ = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"]).reset_index(drop=True)

    sets, ok = feature_sets(cfg, train)
    y = train[TARGET].to_numpy()
    y, xy, groups = y[ok], train[["x", "y"]].to_numpy()[ok], spatial_groups(train[ok], tile)

    buffer_rows, rf_rows = [], []
    for name, (x, make, kind) in sets.items():
        x = x[ok]
        for b in BUFFERS_M:
            pred, n = rb.buffered_cv_predict(x, y, xy, groups, folds, b, make)
            buffer_rows.append({"features": name, "model": kind, "buffer_m": b,
                                "train_blocks_per_fold": round(n), **rb.scores(y, pred)})
            if b in RF_BUFFERS_M:
                rf_rows.append({"features": name, "model": kind, "buffer_m": b,
                                **rb.scores(y, pred)})
        for b in RF_BUFFERS_M:
            pred, _ = rb.buffered_cv_predict(x, y, xy, groups, folds, b, rb.random_forest)
            rf_rows.append({"features": name, "model": "random forest", "buffer_m": b,
                            **rb.scores(y, pred)})
        print(f"{name}: done", flush=True)
    buffer = pd.DataFrame(buffer_rows)
    rf = pd.DataFrame(rf_rows)

    # Domain shift: Cairo's PoC model on the test cities.
    cairo = train[["x", "y", *FEATURES, TARGET]]
    cairo_model = LinearRegression().fit(cairo[FEATURES], cairo[TARGET])
    coefs = {"Cairo": cairo_model.coef_}
    transfer_rows = []
    for city in TEST_CITIES:
        d = city_rows(city)
        x, yc = d[FEATURES].to_numpy(), d[TARGET].to_numpy()
        xyc, gc = d[["x", "y"]].to_numpy(), spatial_groups(d, tile)
        own, _ = rb.buffered_cv_predict(x, yc, xyc, gc, folds, 0, LinearRegression)
        moved = rb.transfer_scores(yc, cairo_model.predict(x))
        row = {"city": city.title(), "blocks": len(d), "lst_mean_c": float(yc.mean()),
               **{f"own_{k}": v for k, v in rb.scores(yc, own).items()},
               **{f"cairo_{k}": v for k, v in moved.items()}}
        for n in LOCAL_BLOCKS:
            row[f"own_r2_{n}_local_blocks"] = float(np.mean([
                rb.scores(yc, rb.buffered_cv_predict(x, yc, xyc, gc, folds, 0, LinearRegression,
                                                     n_train=n, seed=s)[0])["r2"]
                for s in range(LOCAL_REPEATS)]))
        transfer_rows.append(row)
        coefs[city.title()] = LinearRegression().fit(x, yc).coef_
        print(f"{city}: done", flush=True)
    transfer = pd.DataFrame(transfer_rows)
    coefficients = pd.DataFrame(coefs, index=FEATURES)

    OUT.mkdir(parents=True, exist_ok=True)
    buffer.round(4).to_csv(OUT / "buffer.csv", index=False)
    rf.round(4).to_csv(OUT / "random_forest.csv", index=False)
    transfer.round(4).to_csv(OUT / "transfer.csv", index=False)
    coefficients.round(3).to_csv(OUT / "coefficients.csv", index_label="feature")

    def r2(df: pd.DataFrame, features: str, model: str, b: int) -> float:
        row = df[(df.features == features) & (df.model == model) & (df.buffer_m == b)]
        return round(float(row.r2.iloc[0]), 4)

    summary = {
        "blocks": int(len(y)), "folds": folds, "tile_m": tile,
        "buffer_r2": {f: {int(b): r2(buffer, f, k, b) for b in BUFFERS_M}
                      for f, (_, _, k) in sets.items()},
        "max_r2_drop_at_200m": round(max(r2(buffer, f, k, 0) - r2(buffer, f, k, 200)
                                         for f, (_, _, k) in sets.items()), 4),
        "random_forest_r2_200m": {f: r2(rf, f, "random forest", 200) for f in sets},
        "our_model_r2_200m": {f: r2(rf, f, k, 200) for f, (_, _, k) in sets.items()},
        "transfer": transfer.set_index("city")[[
            "own_r2", "cairo_r2", "cairo_bias_c", "cairo_r2_bias_removed", "own_spearman",
            "cairo_spearman", "own_r2_300_local_blocks"]].round(3).to_dict(orient="index"),
        "coefficients": coefficients.round(2).to_dict(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.set_option("display.width", 200)
    print(buffer.pivot(index="features", columns="buffer_m", values="r2").round(3))
    print(rf.pivot_table(index=["features", "model"], columns="buffer_m", values="r2").round(3))
    print(transfer.set_index("city").round(3).T)
    print(coefficients.round(2))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rows":
        write_rows(sys.argv[2])
    else:
        main()
