"""Block-level regression: LST ~ material fractions + vegetation + built form.

A linear model is used on purpose: its coefficients are the whole model, so the Unity app can
compute the effect of an intervention as a weighted sum with no runtime solving, and every
coefficient is visible in the report.

Feature design (fractions of block area; bright paved ground is the reference category):
  veg_frac          vegetation
  dark_roof_frac    dark roofs     -> cool roof = move share from dark roof to bright roof
  dark_ground_frac  dark ground    -> street trees = move share from dark ground to vegetation
  soil_frac         bare soil / sand on the ground (hot by day in Cairo; kept separate so it
                    does not contaminate the bright-surface reference)
  roof_frac         building coverage
  mean_height_m     mean roof height (shading / canyon effect)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

FEATURES = [
    "veg_frac", "dark_roof_frac", "dark_ground_frac", "soil_frac", "roof_frac", "mean_height_m",
]
TARGET = "lst_c"


@dataclass
class FitResult:
    intercept: float
    coefficients: dict[str, float]
    r2_train: float
    r2_spatial_cv: float
    mae_spatial_cv: float
    n_blocks: int
    cv_folds: int
    cv_tile_size_m: int

    def to_dict(self) -> dict:
        return asdict(self)


def training_rows(blocks: pd.DataFrame, min_building_coverage: float) -> pd.DataFrame:
    """Urban blocks with a valid temperature and complete features."""
    rows = blocks.dropna(subset=[*FEATURES, TARGET])
    return rows[rows.roof_frac >= min_building_coverage]


def spatial_groups(blocks: pd.DataFrame, tile_size: float) -> np.ndarray:
    """Group id per block = which tile_size x tile_size square it falls in.

    Neighbouring blocks share heat, so random CV folds would leak and inflate R².
    """
    tx = np.floor(blocks.x.to_numpy() / tile_size).astype(int)
    ty = np.floor(blocks.y.to_numpy() / tile_size).astype(int)
    return tx * 100_000 + ty


def fit(blocks: pd.DataFrame, cv_tile_size: int, cv_folds: int) -> FitResult:
    X = blocks[FEATURES].to_numpy()
    y = blocks[TARGET].to_numpy()
    groups = spatial_groups(blocks, cv_tile_size)

    predicted = np.empty_like(y)
    for train, test in GroupKFold(n_splits=cv_folds).split(X, y, groups):
        predicted[test] = LinearRegression().fit(X[train], y[train]).predict(X[test])

    model = LinearRegression().fit(X, y)
    return FitResult(
        intercept=float(model.intercept_),
        coefficients={f: float(c) for f, c in zip(FEATURES, model.coef_, strict=True)},
        r2_train=float(model.score(X, y)),
        r2_spatial_cv=float(r2_score(y, predicted)),
        mae_spatial_cv=float(mean_absolute_error(y, predicted)),
        n_blocks=len(blocks),
        cv_folds=cv_folds,
        cv_tile_size_m=cv_tile_size,
    )
