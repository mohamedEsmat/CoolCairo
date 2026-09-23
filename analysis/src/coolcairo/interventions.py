"""Translate interventions into feature changes and predicted surface-temperature change.

Unity implements the same arithmetic in C#; this module is the reference the C# is tested
against, and the source of the per-intervention numbers stated in the report (milestone M3).

All temperatures are land SURFACE temperature (LST) as seen by Landsat, not air temperature.
"""

from __future__ import annotations

import pandas as pd

from coolcairo.config import Config
from coolcairo.model import FitResult


def cool_roof_surface_delta(cfg: Config, fit: FitResult) -> float:
    """Surface temperature change (deg C) of one unit of block area going from dark to cool roof.

    "literature": dTs/d(albedo) x (albedo_after - albedo_before), from config with sources.
    "regression": -coef(dark_roof_frac); bright roofs are the model's reference.
    A Landsat pixel's LST is close to the area-weighted mean of its surfaces' temperatures, so a
    block's change is this value times the share of block area converted.
    """
    cr = cfg["cool_roof"]
    if cr["method"] == "literature":
        return cr["dts_per_albedo"] * (cr["albedo_after"] - cr["albedo_before"])
    if cr["method"] == "regression":
        return -fit.coefficients["dark_roof_frac"]
    raise ValueError(f"Unknown cool_roof.method {cr['method']!r}")


def cool_roof_delta(
    roof_surface_delta: float, dark_roof_converted: pd.Series | float
) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from dark roof to cool roof."""
    return roof_surface_delta * dark_roof_converted


def tree_delta(fit: FitResult, ground_planted: pd.Series | float) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from dark ground to vegetation."""
    c = fit.coefficients
    return (c["veg_frac"] - c["dark_ground_frac"]) * ground_planted


def full_adoption_summary(cfg: Config, fit: FitResult, blocks: pd.DataFrame) -> pd.DataFrame:
    """Per-block Delta LST if every dark roof were coated / 25% of dark ground were planted.

    These are the "Delta T per intervention type" figures for the report. The 25% planting
    cap reflects that streets cannot be fully covered by canopy.
    """
    roof_delta = cool_roof_surface_delta(cfg, fit)
    return pd.DataFrame(
        {
            "cool_roof_all_dark_roofs": cool_roof_delta(roof_delta, blocks.dark_roof_frac),
            "trees_25pct_dark_ground": tree_delta(fit, 0.25 * blocks.dark_ground_frac),
        }
    ).describe()


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
    return warnings
