"""Translate interventions into feature changes and predicted surface-temperature change.

Unity implements the same arithmetic in C#; this module is the reference the C# is tested
against, and the source of the per-intervention numbers stated in the report (milestone M3).

All temperatures are land SURFACE temperature (LST) as seen by Landsat, not air temperature.
"""

from __future__ import annotations

import pandas as pd

from coolcairo.model import FitResult


def cool_roof_delta(fit: FitResult, dark_roof_converted: pd.Series | float) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from dark roof to bright roof.

    With bright surfaces as the reference category, that change is exactly
    `-dark_roof_converted` on `dark_roof_frac` with `roof_frac` unchanged.
    """
    return -fit.coefficients["dark_roof_frac"] * dark_roof_converted


def tree_delta(fit: FitResult, ground_planted: pd.Series | float) -> pd.Series | float:
    """Delta LST (deg C) when this share of block area changes from dark ground to vegetation."""
    c = fit.coefficients
    return (c["veg_frac"] - c["dark_ground_frac"]) * ground_planted


def full_adoption_summary(fit: FitResult, blocks: pd.DataFrame) -> pd.DataFrame:
    """Per-block Delta LST if every dark roof were coated / 25% of dark ground were planted.

    These are the "Delta T per intervention type" figures for the report. The 25% planting
    cap reflects that streets cannot be fully covered by canopy.
    """
    return pd.DataFrame(
        {
            "cool_roof_all_dark_roofs": cool_roof_delta(fit, blocks.dark_roof_frac),
            "trees_25pct_dark_ground": tree_delta(fit, 0.25 * blocks.dark_ground_frac),
        }
    ).describe()


def plausibility_warnings(fit: FitResult) -> list[str]:
    """Sign checks. A failure here triggers the literature-coefficient fallback in CLAUDE.md."""
    c = fit.coefficients
    warnings = []
    if c["dark_roof_frac"] <= 0:
        warnings.append("Dark roofs do not raise LST vs bright roofs: cool-roof effect unusable.")
    if c["veg_frac"] >= c["dark_ground_frac"]:
        warnings.append("Vegetation is not cooler than dark ground: tree effect unusable.")
    return warnings
