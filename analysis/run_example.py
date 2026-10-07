"""Run the analysis on the example input only: no downloads, no account, a few seconds.

Usage (from /analysis):  uv run python run_example.py
Reads   data/sample_input/blocks_east_cairo.csv   (written by make_sample.py)
Writes  results/                                  (model fit, cooling effects, heat risk,
                                                   urban growth, three maps, summary.md)

The steps are the same functions run_pipeline.py and the notebooks use, starting from the
block table instead of the satellite rasters, so the numbers match the report and the app.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

from coolcairo import growth
from coolcairo.config import REPO_ROOT, load_config
from coolcairo.interventions import (
    exposure_reduction_summary,
    full_adoption_deltas,
    heat_reference_c,
    targeted_plan,
)
from coolcairo.model import fit, training_rows
from coolcairo.population import heat_exposure

SAMPLE = REPO_ROOT / "data" / "sample_input" / "blocks_east_cairo.csv"
RESULTS = REPO_ROOT / "results"

# Same diverging colours as the report and the app's "Report" scheme: blue cooler, grey typical,
# orange hotter than the typical urban block.
HEAT = LinearSegmentedColormap.from_list(
    "heat", ["#174A8B", "#2A78D6", "#F0EFEC", "#EB6834", "#9C3A14"])
RISK = LinearSegmentedColormap.from_list("risk", ["#F0EFEC", "#F4B183", "#EB6834", "#5B1A5E"])


def run() -> dict:
    """All results as one dict (also written to results/); the unit test checks it."""
    cfg = load_config()
    blocks = pd.read_csv(SAMPLE)
    RESULTS.mkdir(exist_ok=True)

    # 1. Heat model on the urban blocks of the model area, tested on hidden 1 km tiles.
    train = training_rows(blocks, cfg["min_building_coverage"])
    result = fit(train, cfg["cv_tile_size"], cfg["cv_folds"])
    (RESULTS / "model_fit.json").write_text(json.dumps(result.to_dict(), indent=2))

    # 2. Cooling per block at full adoption of each measure (within its cap).
    effects = full_adoption_deltas(cfg, result, train).describe().T
    effects.round(3).to_csv(RESULTS / "cooling_effects_per_block_degC.csv")

    # 3. Heat risk in the Nasr City display district, today and after each measure / a plan.
    reference = heat_reference_c(cfg, train)
    display = blocks[blocks.in_display == 1].copy()
    measured = display.dropna(subset=["lst_c"])
    exposure = exposure_reduction_summary(cfg, result, measured, reference)
    plan = targeted_plan(cfg, result, display, reference)
    risk = {k: float(v) for k, v in exposure.items()} | {"targeted_plan": plan}
    (RESULTS / "heat_risk_nasr_city.json").write_text(json.dumps(risk, indent=2))

    # 4. Urban growth 2016-2023 and the heat of newly built blocks (model area).
    g = cfg["growth"]
    first, last = g["first_year"], g["last_year"]
    blocks["transition"] = growth.transitions(blocks, first, last, g["built_block_min"])
    area = growth.built_area_km2(blocks, cfg.block_size)
    by_class = growth.heat_by_transition(blocks)
    by_class.round(2).to_csv(RESULTS / "urban_growth_heat_by_class.csv")
    new = blocks[blocks.transition == growth.NEWLY_BUILT]
    grown = {
        "built_area_km2_first": float(area[first]),
        "built_area_km2_last": float(area[last]),
        "growth_pct": float(100 * (area[last] / area[first] - 1)),
        "newly_built_blocks": int(len(new)),
        "residents_in_newly_built_blocks": float(new.population.clip(lower=0).sum()),
        "mean_lst_c": by_class.mean_lst_c.round(2).to_dict(),
    }

    maps(cfg, result, display, reference)
    out = {"model": result.to_dict(), "reference_c": reference, "heat_risk": risk, "growth": grown}
    write_summary(out, effects)
    return out


def grid(display: pd.DataFrame, values: pd.Series) -> np.ndarray:
    """Block values on the display grid, north up."""
    rows = display.row - display.row.min()
    cols = display.col - display.col.min()
    out = np.full((rows.max() + 1, cols.max() + 1), np.nan)
    out[rows, cols] = values
    return out[::-1] if display.y.iloc[0] < display.y.iloc[-1] else out


def maps(cfg: object, result: object, display: pd.DataFrame, reference: float) -> None:
    from coolcairo.interventions import (
        cool_roof_delta,
        cool_roof_surface_deltas,
        pocket_park_delta,
    )

    d = display.copy()
    base = heat_exposure(d.lst_c, d.population.clip(lower=0), reference)
    chosen = base.sort_values(ascending=False).index[: d.lst_c.notna().sum() // 3]
    delta = pd.Series(0.0, index=d.index)
    roofs = cool_roof_delta(cool_roof_surface_deltas(cfg, result), d.dark_roof_frac,
                            d.pale_roof_frac)
    parks = pocket_park_delta(result, cfg["interventions"]["park_max_share_of_sand"] * d.soil_frac)
    delta[chosen] = (roofs + parks)[chosen]
    after = heat_exposure(d.lst_c + delta, d.population.clip(lower=0), reference)

    top = float(np.nanpercentile(base[base > 0], 95))
    panels = [
        ("nasr_city_surface_temperature.png", grid(d, d.lst_c), HEAT,
         TwoSlopeNorm(reference, d.lst_c.min(), d.lst_c.max()),
         f"Summer surface temperature (°C), grey = typical block {reference:.1f} °C"),
        ("nasr_city_heat_exposure.png", grid(d, base.where(d.lst_c.notna())), RISK,
         plt.Normalize(0, top), f"Heat exposure today: {base.sum():,.0f} person·°C"),
        ("nasr_city_after_targeted_plan.png", grid(d, after.where(d.lst_c.notna())), RISK,
         plt.Normalize(0, top), f"After cool roofs + pocket parks on the riskiest third: "
                                f"{after.sum():,.0f} person·°C"),
    ]
    for name, values, cmap, norm, title in panels:
        fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=120)
        im = ax.imshow(values, cmap=cmap, norm=norm)
        ax.set_title(title, fontsize=9)
        ax.set_axis_off()
        fig.colorbar(im, ax=ax, shrink=0.8)
        fig.text(0.01, 0.01, "Nasr City, 90 m blocks · Landsat (USGS), Sentinel-2 (Copernicus), "
                 "WorldPop 2024, OSM, Google Open Buildings", fontsize=6, color="#555")
        fig.savefig(RESULTS / name, bbox_inches="tight")
        plt.close(fig)


def write_summary(out: dict, effects: pd.DataFrame) -> None:
    m, r, g = out["model"], out["heat_risk"], out["growth"]
    t = r["targeted_plan"]
    lines = [
        "# Example results",
        "",
        "Written by `analysis/run_example.py` from `data/sample_input/blocks_east_cairo.csv` "
        "(offline). Surface temperature, not air temperature.",
        "",
        "## Heat model (east-Cairo urban blocks)",
        f"- Spatial cross-validated R² **{m['r2_spatial_cv']:.2f}**, mean error "
        f"±{m['mae_spatial_cv']:.1f} °C, {m['n_blocks']:,} blocks, {m['cv_folds']} folds of "
        f"{m['cv_tile_size_m'] // 1000} km tiles. Coefficients: `model_fit.json`.",
        "",
        "## Cooling per block at full adoption (mean °C, model area)",
        *[f"- {k.replace('_', ' ')}: {v:+.2f} °C" for k, v in effects["mean"].items()],
        "",
        "## Heat risk, Nasr City display district",
        f"- {r['residents']:,.0f} residents, typical block {out['reference_c']:.1f} °C, "
        f"heat exposure **{r['exposure_person_degC']:,.0f} person·°C** today.",
        "- One measure in every block: " + ", ".join(
            f"{k.removesuffix('_pct').replace('_', ' ')} {v:+.0f}%"
            for k, v in r.items() if k.endswith("_pct")) + ".",
        f"- Targeted plan (cool roofs + pocket parks on the riskiest third, {t['blocks']} blocks): "
        f"{t['exposure_before']:,.0f} → {t['exposure_after']:,.0f} person·°C "
        f"(**{t['exposure_change_pct']:+.0f}%**), {t['residents_cooled']:,.0f} residents cooled.",
        "",
        "## Urban growth 2016–2023 (model area)",
        f"- Building footprint {g['built_area_km2_first']:.1f} → {g['built_area_km2_last']:.1f} "
        f"km² ({g['growth_pct']:+.1f}%); {g['newly_built_blocks']:,} newly built blocks, "
        f"~{g['residents_in_newly_built_blocks']:,.0f} residents.",
        "- Mean summer surface temperature: " + ", ".join(
            f"{k} {v:.1f} °C" for k, v in g["mean_lst_c"].items()) + ".",
        "",
        "## Files",
        "| File | What |",
        "| --- | --- |",
        "| `model_fit.json` | Heat model coefficients and validation |",
        "| `cooling_effects_per_block_degC.csv` | Per-block cooling of each measure, statistics |",
        "| `heat_risk_nasr_city.json` | Exposure today, per measure and for the targeted plan |",
        "| `urban_growth_heat_by_class.csv` | Blocks and surface temperature by growth class |",
        "| `nasr_city_*.png` | Maps: surface temperature, heat exposure, after the plan |",
    ]
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print((lambda o: json.dumps(o, indent=2, default=float))(run()))
