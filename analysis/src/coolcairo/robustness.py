"""Robustness checks for the heat model (course week 3, session 1: GeoAI methods).

1. Buffered spatial cross-validation (slide 19; Roberts et al. 2017): the same held-out tiles,
   but training blocks within `buffer_m` of any test block are dropped, so training and test
   never share a Landsat thermal pixel (about 100 m).
2. Domain shift (slides 29-32): a model fitted in one city applied unchanged to another.
3. A random-forest baseline next to our linear models (slide 21).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
from sklearn.base import RegressorMixin
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold


def buffered_cv_predict(
    x: np.ndarray, y: np.ndarray, xy: np.ndarray, groups: np.ndarray, folds: int,
    buffer_m: float, make: Callable[[], RegressorMixin],
    n_train: int | None = None, seed: int = 0,
) -> tuple[np.ndarray, float]:
    """Out-of-fold predictions with GroupKFold on spatial tiles.

    Training blocks whose centre is within `buffer_m` of any test block are dropped. With
    `n_train`, each fold trains on that many randomly chosen remaining blocks (few local labels).
    Returns the predictions and the mean number of training blocks per fold.
    """
    pred = np.empty_like(y, dtype=float)
    rng = np.random.default_rng(seed)
    sizes = []
    for train, test in GroupKFold(n_splits=folds).split(x, y, groups):
        if buffer_m > 0:
            dist, _ = cKDTree(xy[test]).query(xy[train], k=1)
            train = train[dist > buffer_m]
        if n_train is not None and n_train < len(train):
            train = rng.choice(train, n_train, replace=False)
        sizes.append(len(train))
        pred[test] = make().fit(x[train], y[train]).predict(x[test])
    return pred, float(np.mean(sizes))


def scores(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    """R², mean absolute error, mean bias (prediction minus truth) and rank correlation."""
    return {
        "r2": float(r2_score(y, pred)),
        "mae_c": float(mean_absolute_error(y, pred)),
        "bias_c": float(np.mean(pred - y)),
        "spearman": float(spearmanr(pred, y).statistic),
    }


def transfer_scores(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    """Scores of a model from elsewhere, also after removing its mean bias (a climate offset
    that one local number would fix): what is left is the block-to-block pattern."""
    out = scores(y, pred)
    out["r2_bias_removed"] = float(r2_score(y, pred - np.mean(pred - y)))
    return out


def random_forest() -> RandomForestRegressor:
    """The baseline forest: fixed seed, leaves of >= 5 blocks, a third of features per split."""
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=5, max_features=0.33,
                                 n_jobs=-1, random_state=0)
