"""Report figures, drawn from the results in compute.py. No EnMAP pixels are drawn (licence):
only statistics derived from them."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, TwoSlopeNorm  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from coolcairo.config import projected_bbox  # noqa: E402
from coolcairo.pipeline import load_sentinel2  # noqa: E402
from coolcairo.population import heat_exposure  # noqa: E402

# Report palette: categorical order blue, orange, aqua, yellow; text in ink tokens.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, MUTED, GRID = "#1f2328", "#5f6670", "#d9dbde"
# Diverging around the heat reference: cool blue, neutral grey midpoint, hot orange.
LST_CMAP = LinearSegmentedColormap.from_list(
    "lst", ["#174a8b", BLUE, "#f0efec", ORANGE, "#9c3a14"])
# Sequential, single hue (orange), for heat exposure.
EXPOSURE_CMAP = LinearSegmentedColormap.from_list("exposure", ["#f6f4f1", "#f6c2a8", ORANGE, "#7a2e12"])
FIT_CMAP = LinearSegmentedColormap.from_list("fit", ["#e6eef8", BLUE, "#123d70"])
# Semantic material colours (same as notebook 02 and the app).
MATERIALS = [("Vegetation", "#4f8a3c"), ("Dark surface", "#38383d"),
             ("Pale surface", "#dbd4c2"), ("Bare sand / soil", "#d6b37d")]

plt.rcParams.update({
    "font.family": "Arial", "font.size": 8.5, "text.color": INK, "axes.labelcolor": INK,
    "axes.edgecolor": GRID, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "savefig.dpi": 220, "savefig.bbox": "tight",
})


def _grid(blocks: pd.DataFrame, values: pd.Series) -> np.ndarray:
    out = np.full((blocks.row.max() + 1, blocks.col.max() + 1), np.nan)
    out[blocks.row.to_numpy(), blocks.col.to_numpy()] = values.to_numpy()
    return out


def _extent(blocks: pd.DataFrame, half: float) -> list[float]:
    return [blocks.x.min() - half, blocks.x.max() + half, blocks.y.min() - half, blocks.y.max() + half]


def _map_axes(ax: plt.Axes, title: str) -> None:
    ax.set_title(title)
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _scale_bar(ax: plt.Axes, metres: float, label: str) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x, y = x0 + 0.05 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    ax.add_patch(Rectangle((x, y), metres, (y1 - y0) * 0.012, color=INK, lw=0))
    ax.text(x + metres / 2, y + (y1 - y0) * 0.03, label, ha="center", va="bottom", fontsize=7.5,
            color=INK, bbox={"fc": "white", "ec": "none", "alpha": 0.7, "pad": 1})


def _true_colour(s2, box: list[float] | None = None) -> tuple[np.ndarray, list[float]]:
    if box is not None:
        s2 = s2.sel(x=slice(box[0], box[2]), y=slice(box[3], box[1]))
    rgb = np.dstack([s2[b].values for b in ("B04", "B03", "B02")])
    lo, hi = np.nanpercentile(rgb, [2, 98])
    rgb = np.clip((rgb - lo) / (hi - lo), 0, 1) ** 0.8
    half = 5.0
    ext = [float(s2.x.min()) - half, float(s2.x.max()) + half,
           float(s2.y.min()) - half, float(s2.y.max()) + half]
    return np.nan_to_num(rgb, nan=1.0), ext


def study_area(r, out: Path) -> Path:
    cfg = r.cfg
    s2 = load_sentinel2(cfg)
    rgb, ext = _true_colour(s2)
    disp = projected_bbox(cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.7))
    axes[0].imshow(rgb, extent=ext)
    _map_axes(axes[0], "a  Model area, Sentinel-2 true colour")

    lst = _grid(r.blocks, r.blocks.lst_c)
    norm = TwoSlopeNorm(vcenter=r.reference_c, vmin=r.reference_c - 5, vmax=r.reference_c + 5)
    im = axes[1].imshow(lst, cmap=LST_CMAP, norm=norm, extent=_extent(r.blocks, cfg.block_size / 2),
                        interpolation="nearest")
    _map_axes(axes[1], "b  Summer surface temperature, 90 m blocks")
    cb = fig.colorbar(im, ax=axes[1], fraction=0.046, pad=0.02, extend="both")
    cb.set_label("°C (centre = urban median %.1f °C)" % r.reference_c, color=MUTED)
    cb.outline.set_visible(False)
    for ax in axes:
        ax.add_patch(Rectangle((disp[0], disp[1]), disp[2] - disp[0], disp[3] - disp[1],
                               fill=False, ec=INK, lw=1.4))
        ax.text(disp[0], disp[3] + 150, "Nasr City (app)", fontsize=7.5, color=INK,
                bbox={"fc": "white", "ec": "none", "alpha": 0.75, "pad": 1})
        _scale_bar(ax, 2000, "2 km")
    return _save(fig, out / "fig1_study_area.png")


def district(r, out: Path) -> Path:
    cfg = r.cfg
    box = projected_bbox(cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size)
    rgb, ext = _true_colour(load_sentinel2(cfg), box)
    mat = r.material.sel(x=slice(box[0], box[2]), y=slice(box[3], box[1]))
    d = r.display
    exposure = heat_exposure(d.lst_c, d.population.clip(lower=0), r.reference_c)
    exposure[d.lst_c.isna()] = np.nan

    fig, axes = plt.subplots(2, 2, figsize=(6.6, 6.6), gridspec_kw={"hspace": 0.32})
    axes = axes.ravel()
    axes[0].imshow(rgb, extent=ext)
    _map_axes(axes[0], "a  Sentinel-2 true colour")
    axes[1].imshow(mat.values, cmap=ListedColormap(["#ffffff", *[c for _, c in MATERIALS]]),
                   vmin=-0.5, vmax=4.5, extent=ext, interpolation="nearest")
    _map_axes(axes[1], "b  Surface materials, 10 m")
    axes[1].legend(handles=[Patch(color=c, label=n) for n, c in MATERIALS], loc="upper center",
                   bbox_to_anchor=(0.5, -0.01), ncol=2, fontsize=7, handlelength=1)
    block_ext = _extent(d, cfg.block_size / 2)
    norm = TwoSlopeNorm(vcenter=r.reference_c, vmin=r.reference_c - 5, vmax=r.reference_c + 5)
    im = axes[2].imshow(_grid(d, d.lst_c), cmap=LST_CMAP, norm=norm, extent=block_ext,
                        interpolation="nearest")
    _map_axes(axes[2], "c  Summer surface temperature")
    cb = fig.colorbar(im, ax=axes[2], fraction=0.046, pad=0.02, extend="both")
    cb.set_label("°C (centre = reference)", color=MUTED)
    cb.outline.set_visible(False)
    im = axes[3].imshow(_grid(d, exposure), cmap=EXPOSURE_CMAP, extent=block_ext,
                        interpolation="nearest")
    _map_axes(axes[3], "d  Heat risk (exposure) per block")
    cb = fig.colorbar(im, ax=axes[3], fraction=0.046, pad=0.02)
    cb.set_label("residents × °C above reference", color=MUTED)
    cb.outline.set_visible(False)
    for ax in axes:
        ax.set_xlim(ext[0], ext[1]), ax.set_ylim(ext[2], ext[3])
        _scale_bar(ax, 500, "500 m")
    return _save(fig, out / "fig2_district.png")


def model_fit(r, out: Path) -> Path:
    y = r.train.lst_c.to_numpy()
    fig, ax = plt.subplots(figsize=(3.6, 3.4))
    hb = ax.hexbin(y, r.cv_pred, gridsize=38, cmap=FIT_CMAP, mincnt=1, linewidths=0.2,
                   edgecolors="white")
    lo, hi = np.floor(y.min()), np.ceil(y.max())
    ax.plot([lo, hi], [lo, hi], color=INK, lw=1, ls="--")
    ax.text(hi - 1.4, hi - 0.6, "1:1", ha="right", color=MUTED, fontsize=7.5)
    ax.set_xlim(lo, hi), ax.set_ylim(lo, hi)
    ax.set_xlabel("Observed block surface temperature (°C)")
    ax.set_ylabel("Predicted, held-out 1 km tiles (°C)")
    ax.set_title(f"Spatial CV R² {r.fit.r2_spatial_cv:.2f}, MAE {r.fit.mae_spatial_cv:.1f} °C, "
                 f"n = {r.fit.n_blocks:,}", fontsize=8.5)
    ax.grid(color=GRID, lw=0.5), ax.set_axisbelow(True)
    cb = fig.colorbar(hb, ax=ax, fraction=0.046, pad=0.02)
    cb.set_label("blocks per cell", color=MUTED)
    cb.outline.set_visible(False)
    return _save(fig, out / "fig3_model_fit.png")


def hyperspectral(r, out: Path) -> Path:
    t = r.heat_r2.iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.6, 3.0))
    h = 0.26
    pos = np.arange(len(t))
    for k, (tile, colour) in enumerate(zip(t.columns, (BLUE, ORANGE, AQUA), strict=True)):
        ys = pos + (1 - k) * h
        ax.barh(ys, t[tile], height=h - 0.04, color=colour, label=f"{tile // 1000} km held-out tiles")
        if k == 0:
            for yy, v in zip(ys, t[tile], strict=True):
                ax.text(v + 0.006, yy, f"{v:.2f}", va="center", fontsize=7, color=INK)
    ax.set_yticks(pos, t.index)
    ax.set_xlabel("Spatial cross-validated R² of block surface temperature")
    ax.set_xlim(0, 0.65)
    ax.grid(axis="x", color=GRID, lw=0.5), ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=3, fontsize=7.5)
    return _save(fig, out / "fig4_hyperspectral.png")


def interventions(r, out: Path) -> Path:
    e = r.exposure
    rows = [("Cool roofs (all roofs coated)", e.cool_roofs_pct, BLUE),
            ("Street trees (≤25% of dark ground)", e.street_trees_pct, BLUE),
            ("Cool pavements (all dark ground)", e.cool_pavements_pct, BLUE),
            ("Pocket parks (≤50% of bare sand)", e.pocket_parks_pct, BLUE),
            ("Targeted plan: roofs + parks on\nthe riskiest third of blocks",
             r.targeted["exposure_change_pct"], ORANGE)][::-1]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for i, (name, v, colour) in enumerate(rows):
        ax.barh(i, -v, height=0.6, color=colour)
        ax.text(-v + 1, i, f"−{-v:.0f}%", va="center", fontsize=7.5, color=INK)
    ax.set_yticks(range(len(rows)), [n for n, _, _ in rows])
    ax.set_xlabel("Reduction in heat exposure (%), Nasr City display district, full adoption")
    ax.set_xlim(0, 85)
    ax.grid(axis="x", color=GRID, lw=0.5), ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _save(fig, out / "fig5_interventions.png")


# Same four classes and colours as the app's Growth view (DistrictView.cs).
GROWTH = [("Still open land", "#a08f6c"), ("Built up before 2016, little change", "#737a8a"),
          ("Denser since 2016", "#f2c14e"), ("New built-up since 2016", "#eb6834")]


def urban_growth(r, out: Path) -> Path:
    from coolcairo.growth import NEWLY_BUILT, BUILT_BEFORE, OPEN, growth_class

    cfg, gr = r.cfg, r.growth
    b = gr["blocks"]
    g = cfg["growth"]
    codes = growth_class(b, gr["first"], gr["last"], g["built_block_min"], g["denser_min"])
    disp = projected_bbox(cfg["display_aoi"]["bbox_wgs84"], cfg.crs, cfg.block_size)

    fig = plt.figure(figsize=(7.2, 3.9))
    grid = fig.add_gridspec(2, 2, width_ratios=[1.15, 1], hspace=0.55, wspace=0.28)
    ax = fig.add_subplot(grid[:, 0])
    ax.imshow(np.ma.masked_less(_grid(b, codes.astype(float)), 0),
              cmap=ListedColormap([c for _, c in GROWTH]), vmin=-0.5, vmax=3.5,
              extent=_extent(b, cfg.block_size / 2), interpolation="nearest")
    _map_axes(ax, f"a  Building growth {gr['first']}–{gr['last']}, 90 m blocks")
    ax.add_patch(Rectangle((disp[0], disp[1]), disp[2] - disp[0], disp[3] - disp[1],
                           fill=False, ec=INK, lw=1.2))
    _scale_bar(ax, 2000, "2 km")
    ax.legend(handles=[Patch(color=c, label=n) for n, c in GROWTH[::-1]], loc="upper center",
              bbox_to_anchor=(0.5, -0.01), ncol=2, fontsize=6.8, handlelength=1)

    area = gr["area_model"]
    ax = fig.add_subplot(grid[0, 1])
    ax.plot(area.index, area.values, color=BLUE, lw=2, marker="o", ms=4)
    ax.set_title("b  Building footprint area, model area", fontsize=8.5)
    ax.set_ylabel("km²")
    ax.set_xticks(area.index[::2])
    ax.set_xlim(area.index[0] - 1.2, area.index[-1] + 1.2)
    pad = (area.max() - area.min()) * 0.15
    ax.set_ylim(area.min() - pad, area.max() + pad)
    ax.grid(color=GRID, lw=0.5), ax.set_axisbelow(True)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    ax.annotate(f"{area.iloc[-1]:.1f}", (area.index[-1], area.iloc[-1]), xytext=(4, 0),
                textcoords="offset points", va="center", fontsize=7.5)
    ax.annotate(f"{area.iloc[0]:.1f}", (area.index[0], area.iloc[0]), xytext=(-4, 0),
                textcoords="offset points", va="center", ha="right", fontsize=7.5)

    heat = gr["heat"]
    ax = fig.add_subplot(grid[1, 1])
    colours = {BUILT_BEFORE: "#737a8a", NEWLY_BUILT: "#eb6834", OPEN: "#a08f6c"}
    names = {BUILT_BEFORE: "Built before 2016", NEWLY_BUILT: "Built 2016–23", OPEN: "Still open"}
    ys = np.arange(len(heat))[::-1]
    ax.barh(ys, heat.mean_lst_c - 40, left=40, height=0.6,
            color=[colours[k] for k in heat.index])
    for y_, (k, row) in zip(ys, heat.iterrows(), strict=True):
        ax.text(row.mean_lst_c + 0.1, y_, f"{row.mean_lst_c:.1f} °C  (n = {int(row.blocks):,})",
                va="center", fontsize=7)
    ax.axvline(r.reference_c, color=INK, lw=0.8, ls="--")
    ax.set_yticks(ys, [names[k] for k in heat.index])
    ax.set_xlim(40, 52)
    ax.set_title("c  Mean summer surface temperature", fontsize=8.5)
    ax.set_xlabel("°C (dashed: urban median)")
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    for s_ in ("top", "right", "left"):
        ax.spines[s_].set_visible(False)
    return _save(fig, out / "fig6_growth.png")


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def all_figures(r, out: Path) -> dict[str, Path]:
    return {f.__name__: f(r, out) for f in (study_area, district, model_fit, hyperspectral,
                                             interventions, urban_growth)}
