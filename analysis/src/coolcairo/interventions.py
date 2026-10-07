"""Translate interventions into feature changes and predicted surface-temperature change.

Unity implements the same arithmetic in C# (InterventionModel.cs); this module is the reference
the C# is checked against, and the source of the per-intervention numbers in the report.

Four interventions, each acting on one block-area share:
  cool roofs      dark and pale roofs coated white               (literature, per albedo change)
  street trees    dark ground -> vegetation, up to a cap        (our regression)
  cool pavements  remaining dark ground coated reflective       (literature, per albedo change)
  pocket parks    bare sand -> vegetation, up to a cap          (our regression)

All temperatures are land SURFACE temperature (LST) as seen by Landsat, not air temperature.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from coolcairo.config import Config
from coolcairo.model import FitResult
from coolcairo.population import heat_exposure


@dataclass(frozen=True)
class CoolRoofDeltas:
    """Surface temperature change (deg C) per unit of block area coated, by starting roof type."""

    dark: float
    pale: float


def cool_roof_surface_deltas(cfg: Config, fit: FitResult) -> CoolRoofDeltas:
    """Per-unit-area effect of coating dark and pale roofs.

    Literature: dTs/d(albedo) x (albedo_after - albedo_before), from config with sources.
    "regression" replaces only the dark term with -coef(dark_roof_frac); pale roofs are the
    model's reference category, so the model has no pale-roof term to use.
    A Landsat pixel's LST is close to the area-weighted mean of its surfaces' temperatures, so a
    block's change is these values times the share of block area coated.
    """
    cr = cfg["cool_roof"]
    pale = cr["dts_per_albedo"] * (cr["albedo_after"] - cr["albedo_pale_roof"])
    if cr["method"] == "literature":
        dark = cr["dts_per_albedo"] * (cr["albedo_after"] - cr["albedo_dark_roof"])
    elif cr["method"] == "regression":
        dark = -fit.coefficients["dark_roof_frac"]
    else:
        raise ValueError(f"Unknown cool_roof.method {cr['method']!r}")
    return CoolRoofDeltas(dark=dark, pale=pale)


def cool_roof_delta(
    deltas: CoolRoofDeltas,
    dark_roof_coated: pd.Series | float,
    pale_roof_coated: pd.Series | float,
) -> pd.Series | float:
    """Delta LST (deg C) when these shares of block area are coated with a cool roof."""
    return deltas.dark * dark_roof_coated + deltas.pale * pale_roof_coated


def tree_delta(fit: FitResult, ground_planted: pd.Series | float) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from dark ground to vegetation."""
    c = fit.coefficients
    return (c["veg_frac"] - c["dark_ground_frac"]) * ground_planted


def cool_pavement_surface_delta(cfg: Config) -> float:
    """Surface temperature change (deg C) per unit of block area of dark ground coated.

    Same physics and roof-derived sensitivity as cool roofs (config `cool_pavement`); a
    conservative choice for pavements, which field studies find respond more strongly.
    """
    cp = cfg["cool_pavement"]
    return cfg["cool_roof"]["dts_per_albedo"] * (cp["albedo_after"] - cp["albedo_before"])


def pocket_park_delta(fit: FitResult, sand_greened: pd.Series | float) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from bare sand to vegetation."""
    c = fit.coefficients
    return (c["veg_frac"] - c["soil_frac"]) * sand_greened


def full_adoption_deltas(cfg: Config, fit: FitResult, blocks: pd.DataFrame) -> pd.DataFrame:
    """Per-block Delta LST for each intervention at full adoption within its cap."""
    caps = cfg["interventions"]
    planted = caps["tree_max_share_of_dark_ground"] * blocks.dark_ground_frac
    return pd.DataFrame({
        "cool_roofs": cool_roof_delta(
            cool_roof_surface_deltas(cfg, fit), blocks.dark_roof_frac, blocks.pale_roof_frac
        ),
        "street_trees": tree_delta(fit, planted),
        # Pavements coat the dark ground trees do not take (here: all of it, trees not planted).
        "cool_pavements": cool_pavement_surface_delta(cfg) * blocks.dark_ground_frac,
        "pocket_parks": pocket_park_delta(fit, caps["park_max_share_of_sand"] * blocks.soil_frac),
    })


def full_adoption_summary(cfg: Config, fit: FitResult, blocks: pd.DataFrame) -> pd.DataFrame:
    """Distribution of the per-block effects: the "Delta T per intervention type" in the report."""
    return full_adoption_deltas(cfg, fit, blocks).describe()


def plausibility_warnings(cfg: Config, fit: FitResult) -> list[str]:
    """Sign checks. A failure here triggers the literature-coefficient fallback in CLAUDE.md."""
    c = fit.coefficients
    warnings = []
    if c["dark_roof_frac"] <= 0:
        note = "literature value in use" if cfg["cool_roof"]["method"] == "literature" else (
            "cool-roof effect UNUSABLE: set cool_roof.method to literature")
        warnings.append(f"Fitted dark roofs do not raise LST vs bright roofs ({note}).")
    if c["veg_frac"] >= c["dark_ground_frac"]:
        warnings.append("Vegetation is not cooler than dark ground: tree effect unusable.")
    if c["veg_frac"] >= c["soil_frac"]:
        warnings.append("Vegetation is not cooler than bare sand: pocket-park effect unusable.")
    return warnings


def heat_reference_c(cfg: Config, urban_blocks: pd.DataFrame) -> float:
    """Reference surface temperature for heat exposure (see `heat_reference` in config)."""
    if cfg["heat_reference"] != "urban_median":
        raise ValueError(f"Unknown heat_reference {cfg['heat_reference']!r}")
    return float(urban_blocks.lst_c.median())


def exposure_reduction_summary(
    cfg: Config, fit: FitResult, blocks: pd.DataFrame, reference_c: float
) -> pd.Series:
    """District heat exposure (person-degrees) now, and the % change for each intervention at
    full adoption. The report's "heat risk reduced by X%" figures come from here."""
    base = heat_exposure(blocks.lst_c, blocks.population, reference_c).sum()
    out = {
        "residents": blocks.population.sum(),
        "reference_c": reference_c,
        "exposure_person_degC": base,
    }
    for name, delta in full_adoption_deltas(cfg, fit, blocks).items():
        after = heat_exposure(blocks.lst_c + delta, blocks.population, reference_c).sum()
        out[f"{name}_pct"] = 100 * (after - base) / base if base else 0.0
    return pd.Series(out)


def targeted_plan(cfg: Config, result: FitResult, display: pd.DataFrame, ref: float) -> dict:
    """Same plan as the app screenshot: cool roofs + pocket parks on the riskiest third of
    valid blocks (ranked by baseline heat exposure)."""
    d = display.dropna(subset=["lst_c"]).copy()
    base = heat_exposure(d.lst_c, d.population.clip(lower=0), ref)
    chosen = base.sort_values(ascending=False).index[: len(d) // 3]
    delta = pd.Series(0.0, index=d.index)
    roofs = cool_roof_delta(
        cool_roof_surface_deltas(cfg, result), d.dark_roof_frac, d.pale_roof_frac)
    parks = pocket_park_delta(result, cfg["interventions"]["park_max_share_of_sand"] * d.soil_frac)
    delta[chosen] = (roofs + parks)[chosen]
    after = heat_exposure(d.lst_c + delta, d.population.clip(lower=0), ref)
    return {
        "blocks": len(chosen),
        "share_blocks": len(chosen) / len(d),
        "exposure_before": float(base.sum()),
        "exposure_after": float(after.sum()),
        "exposure_change_pct": 100 * (after.sum() - base.sum()) / base.sum(),
        "mean_lst_before": float(d.lst_c.mean()),
        "mean_lst_after": float((d.lst_c + delta).mean()),
        "residents_cooled": float(d.population.clip(lower=0)[chosen][delta[chosen] < -0.01].sum()),
    }
