"""Validation checks from the course's accuracy-assessment session (week 3, session 3).

1. Random vs spatial split: the same models scored with random 5-fold CV and with held-out
   tiles of 0.5-3 km; the gap is the optimism a random split would report.
2. Continuous agreement: bias, MAE, RMSE, R² about the 1:1 line, Pearson r² and Bland-Altman
   limits for the heat model's out-of-fold predictions (1 km tiles) and for building heights
   (Open Buildings against OSM tags). Figure: Bland-Altman plots of both.
3. Stable targets: block temperature in one summer against another, on blocks that were already
   built-up in 2016 and barely changed by 2023. After removing the summer-wide offset (weather),
   what is left is the noise a real cooling must exceed before Landsat can show it.

Usage (from /analysis, after run_pipeline.py; downloads per-summer Landsat once, then cached):
    uv run python make_validity.py
Outputs in docs/validity/: split_comparison.csv, continuous.csv, stable_targets.csv,
bland_altman.png, summary.json.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from coolcairo import openbuildings
from coolcairo import robustness as rb
from coolcairo.agreement import agreement, stable_target_noise
from coolcairo.blocks import block_mean
from coolcairo.config import REPO_ROOT, load_config
from coolcairo.growth import STABLE_CODE
from coolcairo.model import TARGET, spatial_groups, training_rows
from coolcairo.pipeline import (
    add_growth,
    build_blocks,
    load_lst,
    load_lst_by_year,
    load_open_buildings_heights,
    load_osm_buildings,
)
from make_robustness import feature_sets

OUT = REPO_ROOT / "docs" / "validity"
TILES_M = (500, 1000, 2000, 3000)
HOT_SHARE = 0.10  # "hottest blocks" = the top 10 % by measured temperature


def random_cv_predict(x: np.ndarray, y: np.ndarray, folds: int, make: object) -> np.ndarray:
    pred = np.empty_like(y, dtype=float)
    for tr, te in KFold(n_splits=folds, shuffle=True, random_state=0).split(x):
        pred[te] = make().fit(x[tr], y[tr]).predict(x[te])
    return pred


def yearly_block_lst(cfg: object, blocks: pd.DataFrame) -> pd.DataFrame:
    """Per-summer block temperature joined to the blocks on their centres; checked against the
    blocks' own (all-summers) temperature so the join cannot silently misalign."""
    f = cfg.block_factor
    comp = block_mean(load_lst(cfg), f)
    yearly = block_mean(load_lst_by_year(cfg), f)
    df = yearly.to_dataset(dim="year").assign(composite=comp).to_dataframe().reset_index()
    df = df.rename(columns={y: f"lst_{y}" for y in yearly.year.values})
    key = blocks.assign(_x=blocks.x.round(), _y=blocks.y.round())
    df = df.assign(_x=df.x.round(), _y=df.y.round()).drop(columns=["x", "y"])
    out = key.merge(df, on=["_x", "_y"], how="left").drop(columns=["_x", "_y"])
    both = out[["lst_c", "composite"]].dropna()
    assert len(both) > 0.9 * out.lst_c.notna().sum(), "yearly LST did not join to the blocks"
    assert np.allclose(both.lst_c, both.composite, atol=1e-3), "yearly LST grid misaligned"
    return out


def ba_panel(ax: plt.Axes, ref: np.ndarray, est: np.ndarray, a: dict, unit: str, title: str,
             gridsize: int = 60) -> None:
    """Bland-Altman plot: hexagon density for many points, dots for few."""
    mean, diff = (ref + est) / 2, est - ref
    if len(mean) >= 1000:
        ax.hexbin(mean, diff, gridsize=gridsize, cmap="Greys", mincnt=1, bins="log", linewidths=0)
    else:
        ax.scatter(mean, diff, s=9, color="#555555", alpha=0.6, linewidths=0)
    x = np.linspace(np.percentile(mean, 0.5), np.percentile(mean, 99.5), 50)
    ax.axhline(0, color="#999999", lw=0.8)
    bias = round(a["bias"], 2) + 0.0  # no "-0.00"
    ax.axhline(a["bias"], color="#1f5fa8", lw=1.6, label=f"bias {bias:+.2f} {unit}")
    for v in (a["loa_low"], a["loa_high"]):
        ax.axhline(v, color="#1f5fa8", lw=1.2, ls="--")
    k, c = np.polyfit(mean, diff, 1)
    ax.plot(x, k * x + c, color="#c0392b", lw=1.6, label=f"trend, slope {round(k, 2) + 0.0:+.2f}")
    ax.text(0.02, 0.04, f"95 % limits {a['loa_low']:+.1f} to {a['loa_high']:+.1f} {unit}",
            transform=ax.transAxes, fontsize=8, color="#1f5fa8")
    ax.set_xlim(x[0], x[-1])
    lim = np.percentile(np.abs(diff), 99.5)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel(f"mean of estimate and reference ({unit})")
    ax.set_ylabel(f"estimate − reference ({unit})")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8, loc="upper right", frameon=False)


def main() -> None:
    cfg = load_config()
    folds = cfg["cv_folds"]
    blocks, _, _ = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"]).reset_index(drop=True)
    sets, ok = feature_sets(cfg, train)
    sub = train[ok].reset_index(drop=True)
    y, xy = sub[TARGET].to_numpy(), sub[["x", "y"]].to_numpy()
    hot = y >= np.quantile(y, 1 - HOT_SHARE)

    # 1 + 2: random vs spatial split, and agreement of the 1 km out-of-fold predictions.
    split_rows, cont_rows, oof = [], [], {}
    for name, (x, make, kind) in sets.items():
        x = x[ok]
        pred = random_cv_predict(x, y, folds, make)
        split_rows.append({"features": name, "model": kind, "split": "random 5-fold",
                           "tile_m": 0, **rb.scores(y, pred)})
        for t in TILES_M:
            pred, _ = rb.buffered_cv_predict(x, y, xy, spatial_groups(sub, t), folds, 0, make)
            split_rows.append({"features": name, "model": kind, "split": f"{t / 1000:g} km tiles",
                               "tile_m": t, **rb.scores(y, pred)})
            if t == cfg["cv_tile_size"]:
                oof[name] = pred
                a = agreement(y, pred)
                cont_rows.append({"product": f"Heat model: {name}", "unit": "°C", **a,
                                  "hot_bias": float(np.mean(pred[hot] - y[hot])),
                                  "hot_threshold": float(np.quantile(y, 1 - HOT_SHARE))})
        print(f"{name}: done", flush=True)
    split = pd.DataFrame(split_rows)

    osm = load_osm_buildings(cfg)
    ob = openbuildings.footprint_heights(osm, load_open_buildings_heights(cfg),
                                         cfg["open_buildings_min_pixels"])
    hp = openbuildings.height_pairs(osm, ob)
    ha = agreement(hp.osm.to_numpy(), hp.ob.to_numpy())
    cont_rows.append({"product": "Building heights: Open Buildings vs OSM tags", "unit": "m", **ha})
    cont = pd.DataFrame(cont_rows)

    # 3: stable targets.
    g = add_growth(cfg, blocks)
    urban = training_rows(g, cfg["min_building_coverage"])
    stable = urban[urban.growth_class == STABLE_CODE]
    yearly = yearly_block_lst(cfg, stable)
    years = sorted(int(c[4:]) for c in yearly.columns if c.startswith("lst_2"))
    per_year = load_lst_by_year(cfg).attrs["scenes_per_year"]
    scenes = {y: int(n) for y, n in zip(years, per_year, strict=True)}
    st_rows = []
    for i, y0 in enumerate(years):
        for y1 in years[i + 1:]:
            s = stable_target_noise(yearly[f"lst_{y0}"].to_numpy(),
                                    yearly[f"lst_{y1}"].to_numpy())
            st_rows.append({"from": y0, "to": y1, **s})
    st = pd.DataFrame(st_rows)

    # Figure: Bland-Altman, headline heat model and building heights.
    head = "Our features + EnMAP spectra"
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=200)
    ba_panel(axes[0], y, oof[head], agreement(y, oof[head]), "°C",
             f"Heat model (EnMAP spectra), held-out 1 km tiles, n = {len(y):,}")
    ba_panel(axes[1], hp.osm.to_numpy(), hp.ob.to_numpy(), ha, "m",
             f"Building heights, Open Buildings vs OSM, n = {len(hp):,}")
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "bland_altman.png")

    split.round(4).to_csv(OUT / "split_comparison.csv", index=False)
    cont.round(4).to_csv(OUT / "continuous.csv", index=False)
    st.round(4).to_csv(OUT / "stable_targets.csv", index=False)

    def r2(features: str, split_name: str) -> float:
        row = split[(split.features == features) & (split.split == split_name)]
        return round(float(row.r2.iloc[0]), 4)

    tile_name = f"{cfg['cv_tile_size'] / 1000:g} km tiles"
    summary = {
        "blocks": int(len(y)), "folds": folds, "tile_m": cfg["cv_tile_size"],
        "split_r2": {f: {s: r2(f, s) for s in split.split.unique()} for f in sets},
        "optimism_r2": {f: round(r2(f, "random 5-fold") - r2(f, tile_name), 4) for f in sets},
        "continuous": {k: {f: v for f, v in row.items() if not pd.isna(v)}
                       for k, row in cont.set_index("product").round(4).iterrows()},
        "hot_share": HOT_SHARE,
        "stable": {
            "blocks": int(yearly[[f"lst_{y}" for y in years]].notna().all(axis=1).sum()),
            "years": years, "scenes_per_year": scenes,
            "pairs": st.round(3).to_dict(orient="records"),
            "threshold_95_mean": round(float(st.threshold_95.mean()), 3),
            "resid_sd_mean": round(float(st.resid_sd.mean()), 3),
        },
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False, default=lambda o: o.item())
    (OUT / "summary.json").write_text(text, encoding="utf-8")
    pd.set_option("display.width", 200)
    print(split.pivot(index="features", columns="split", values="r2").round(3))
    print(cont.set_index("product")[["bias", "mae", "rmse", "r2_1to1", "pearson_r2", "loa_low",
                                     "loa_high", "ba_slope"]].round(3))
    print(st.round(3))


if __name__ == "__main__":
    main()
