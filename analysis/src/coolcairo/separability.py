"""Does hyperspectral data add value over Sentinel-2? Two controlled tests.

1. Separating built surfaces from bare desert (`compare`, `fused_accuracy`).
2. Explaining block surface temperature (`heat_r2`).

Test 1 detail:

This is the project's documented reason for using EnMAP: with Sentinel-2, the best single
index (BSI) separates roofs from open ground at only ~75% balanced accuracy, and bright
desert soil contaminates the "bright surface" class.

Labels (30 m pixels):
  1 = built:  >= 90% covered by mapped OSM footprints (roof pixels, little mixing)
  0 = open:   > 300 m from any mapped footprint and not vegetated (desert / bare ground)
Every feature set is tested with the same pixels, the same classifier and the same
spatial cross-validation (1 km tiles held out together), so only the spectra differ.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr
from scipy.ndimage import distance_transform_edt
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression, RidgeCV
from sklearn.metrics import balanced_accuracy_score, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

BUILT, OPEN = 1, 0
PURE_ROOF_SHARE = 0.9
OPEN_GROUND_DISTANCE_M = 300


def labels_30m(roof_10m: np.ndarray, ndvi_30m: np.ndarray, ndvi_max: float) -> np.ndarray:
    """Per 30 m pixel: BUILT, OPEN, or -1 (unlabelled). `roof_10m` is a 0/1 footprint mask."""
    ny, nx = ndvi_30m.shape
    roof = roof_10m[: ny * 3, : nx * 3].reshape(ny, 3, nx, 3).mean(axis=(1, 3))
    dist = distance_transform_edt(roof_10m == 0) * 10.0
    dist = dist[: ny * 3, : nx * 3].reshape(ny, 3, nx, 3).min(axis=(1, 3))
    out = np.full((ny, nx), -1, dtype=np.int8)
    out[roof >= PURE_ROOF_SHARE] = BUILT
    out[(dist > OPEN_GROUND_DISTANCE_M) & (ndvi_30m < ndvi_max)] = OPEN
    return out


def _classifier(n_features: int) -> object:
    steps = [StandardScaler()]
    if n_features > 20:
        steps.append(PCA(n_components=20))  # Hyperspectral bands are highly correlated.
    steps.append(LogisticRegression(class_weight="balanced", max_iter=5000))
    return make_pipeline(*steps)


def spatial_cv_accuracy(
    x: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int
) -> tuple[float, float]:
    """Mean and std of balanced accuracy over spatial folds."""
    scores = []
    for train, test in GroupKFold(n_splits=folds).split(x, y, groups):
        model = _classifier(x.shape[1]).fit(x[train], y[train])
        scores.append(balanced_accuracy_score(y[test], model.predict(x[test])))
    return float(np.mean(scores)), float(np.std(scores))


def compare(
    feature_sets: dict[str, xr.DataArray],
    labels: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    tile_size: float,
    folds: int,
) -> pd.DataFrame:
    """Balanced accuracy per feature set, on the pixels labelled and valid in every set.

    Each feature set is a (feature, y, x) array on the same 30 m grid.
    """
    valid = labels >= 0
    for fs in feature_sets.values():
        valid &= np.isfinite(fs.values).all(axis=0)
    yy, xx = np.nonzero(valid)
    gx = np.floor(x_coords[xx] / tile_size).astype(int)
    gy = np.floor(y_coords[yy] / tile_size).astype(int)
    groups = gx * 100_000 + gy
    y = labels[valid].astype(int)

    rows = []
    for name, fs in feature_sets.items():
        x = fs.values[:, valid].T
        mean, std = spatial_cv_accuracy(x, y, groups, folds)
        rows.append({"features": name, "n_features": x.shape[1], "balanced_accuracy": mean,
                     "std_across_folds": std})
    table = pd.DataFrame(rows)
    table.attrs.update(n_built=int((y == BUILT).sum()), n_open=int((y == OPEN).sum()))
    return table


def fused_accuracy(
    base: xr.DataArray,
    extra: xr.DataArray,
    labels: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    tile_size: float,
    folds: int,
    extra_components: int = 50,
) -> tuple[float, float, float]:
    """Does `extra` (e.g. EnMAP) add information to `base` (e.g. Sentinel-2)?

    Returns (base-only accuracy, base+extra accuracy, std of the fused folds), on identical
    pixels and folds. `extra` is compressed with PCA fitted inside each training fold.
    """
    valid = (labels >= 0) & np.isfinite(base.values).all(0) & np.isfinite(extra.values).all(0)
    yy, xx = np.nonzero(valid)
    groups = (np.floor(x_coords[xx] / tile_size).astype(int) * 100_000
              + np.floor(y_coords[yy] / tile_size).astype(int))
    y = labels[valid].astype(int)
    nb = base.shape[0]
    x = np.hstack([base.values[:, valid].T, extra.values[:, valid].T])

    def logistic() -> LogisticRegression:
        return LogisticRegression(class_weight="balanced", max_iter=5000)

    def base_only() -> object:
        return make_pipeline(StandardScaler(), logistic())

    def fused() -> object:
        cols = ColumnTransformer([
            ("base", StandardScaler(), list(range(nb))),
            ("extra", make_pipeline(StandardScaler(), PCA(extra_components)),
             list(range(nb, x.shape[1]))),
        ])
        return make_pipeline(cols, logistic())

    base_scores, fused_scores = [], []
    for train, test in GroupKFold(n_splits=folds).split(x, y, groups):
        m = base_only().fit(x[train][:, :nb], y[train])
        base_scores.append(balanced_accuracy_score(y[test], m.predict(x[test][:, :nb])))
        m = fused().fit(x[train], y[train])
        fused_scores.append(balanced_accuracy_score(y[test], m.predict(x[test])))
    return float(np.mean(base_scores)), float(np.mean(fused_scores)), float(np.std(fused_scores))


def block_spectra(spectra: xr.DataArray, factor: int, blocks: pd.DataFrame) -> np.ndarray:
    """Mean spectrum per block, as (n_blocks, n_features) in the row order of `blocks`.

    `spectra` is (feature, y, x); `factor` pixels span one block edge; blocks are matched by
    their centre coordinates.
    """
    agg = spectra.coarsen(x=factor, y=factor, boundary="trim").mean()
    col = {round(float(v)): j for j, v in enumerate(agg.x.values)}
    row = {round(float(v)): i for i, v in enumerate(agg.y.values)}
    ii = np.array([row[round(v)] for v in blocks.y])
    jj = np.array([col[round(v)] for v in blocks.x])
    return agg.values[:, ii, jj].T


def heat_r2(
    feature_sets: dict[str, np.ndarray],
    lst_c: np.ndarray,
    groups: np.ndarray,
    folds: int,
) -> pd.Series:
    """Spatial-CV R2 of block LST from each feature set (ridge regression, alpha chosen by
    inner CV), on the blocks valid in every set."""
    ok = np.isfinite(lst_c)
    for x in feature_sets.values():
        ok &= np.isfinite(x).all(axis=1)
    y, g = lst_c[ok], groups[ok]
    out = {}
    for name, x in feature_sets.items():
        x = x[ok]
        pred = np.empty_like(y)
        for train, test in GroupKFold(n_splits=folds).split(x, y, g):
            model = make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13)))
            pred[test] = model.fit(x[train], y[train]).predict(x[test])
        out[name] = r2_score(y, pred)
    result = pd.Series(out, name="r2_spatial_cv")
    result.attrs["n_blocks"] = int(ok.sum())
    return result
