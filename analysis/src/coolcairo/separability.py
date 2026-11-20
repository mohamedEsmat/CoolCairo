"""Does hyperspectral data add value over Sentinel-2? Two controlled tests.

1. Separating built surfaces from bare desert (`compare`, `fused_accuracy`).
2. Explaining block surface temperature (`heat_r2`).
Plus a robustness check of both with the spectra compressed by PCA or MNF (`compression_check`).

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
from sklearn.base import BaseEstimator, TransformerMixin
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
        # Hyperspectral bands are highly correlated. random_state: with < 10 samples per
        # feature sklearn picks a randomized solver, which would vary between runs.
        steps.append(PCA(n_components=20, random_state=0))
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
            ("extra", make_pipeline(StandardScaler(), PCA(extra_components, random_state=0)),
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


# --------------------------------------------------------------------------------------------
# MNF vs PCA (course notebook 13): does a noise-aware compression of the spectra change either
# test? PCA ranks components by variance, MNF (Green et al. 1988) by signal-to-noise.

def noise_covariance(
    cube: np.ndarray, wavelengths: np.ndarray, band_nm: float = 1650.0, window: int = 40,
    step: int = 10,
) -> tuple[np.ndarray, dict]:
    """Band noise covariance from shift differences in the most homogeneous window.

    `cube` is (band, y, x). Neighbouring pixels in a uniform area share the same signal, so
    their difference is noise with covariance 2 * Sigma_N (course notebook 13, section 4).
    The window is the fully valid `window` x `window` square with the lowest coefficient of
    variation at `band_nm`.
    """
    b = int(np.argmin(np.abs(wavelengths - band_nm)))
    img = cube[b]
    best = None
    for i in range(0, img.shape[0] - window + 1, step):
        for j in range(0, img.shape[1] - window + 1, step):
            block = cube[:, i:i + window, j:j + window]
            if not np.isfinite(block).all():
                continue
            w = img[i:i + window, j:j + window]
            cv = float(w.std() / w.mean())
            if best is None or cv < best[0]:
                best = (cv, i, j)
    if best is None:
        raise ValueError("No fully valid window for the noise estimate.")
    cv, i, j = best
    win = cube[:, i:i + window, j:j + window]
    diff = (win[:, :, 1:] - win[:, :, :-1]).reshape(cube.shape[0], -1).T
    diff = diff[np.abs(diff).sum(axis=1) > 0]   # Duplicated pixels from resampling carry no noise.
    return np.cov(diff, rowvar=False) / 2, {"row": i, "col": j, "cv": cv,
                                            "band_nm": float(wavelengths[b])}


class MNF(BaseEstimator, TransformerMixin):
    """Minimum Noise Fraction: PCA after whitening the noise (course notebook 13's mnf_fit).

    The noise covariance is given (from `noise_covariance`, label-free); the signal covariance
    and mean are fitted on the training rows only. `eigenvalues_` are about SNR + 1.
    """

    def __init__(self, sigma_n: np.ndarray, n_components: int = 20, ridge: float = 1e-3) -> None:
        self.sigma_n = sigma_n
        self.n_components = n_components
        self.ridge = ridge

    def fit(self, x: np.ndarray, y: np.ndarray | None = None) -> MNF:
        n = len(self.sigma_n)
        s = self.sigma_n + np.eye(n) * self.ridge * np.trace(self.sigma_n) / n
        ev_n, v_n = np.linalg.eigh(s)
        whiten = v_n / np.sqrt(ev_n)
        self.mean_ = x.mean(axis=0)
        ev, v = np.linalg.eigh(np.cov((x - self.mean_) @ whiten, rowvar=False))
        order = np.argsort(ev)[::-1]
        self.eigenvalues_ = ev[order]
        self.components_ = (whiten @ v[:, order])[:, : self.n_components]
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean_) @ self.components_


class _AppendCompressed(BaseEstimator, TransformerMixin):
    """Keep the first `n_keep` columns, compress the rest with `compressor` (fitted per fold)."""

    def __init__(self, n_keep: int, compressor: object) -> None:
        self.n_keep = n_keep
        self.compressor = compressor

    def fit(self, x: np.ndarray, y: np.ndarray | None = None) -> _AppendCompressed:
        self.compressor.fit(x[:, self.n_keep:])
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        return np.hstack([x[:, : self.n_keep], self.compressor.transform(x[:, self.n_keep:])])


def _compressor(method: str, k: int, sigma_n: np.ndarray) -> object:
    if method == "PCA":   # Standardised PCA, as in the built-vs-desert test.
        return make_pipeline(StandardScaler(), PCA(k, random_state=0))
    return MNF(sigma_n, k)


def compression_check(
    refl: xr.DataArray,
    labels: np.ndarray,
    tile_size: float,
    folds: int,
    block_spec: np.ndarray,
    block_features: np.ndarray,
    lst_c: np.ndarray,
    block_groups: np.ndarray,
    components: tuple[int, ...] = (20, 48),
) -> dict:
    """Both hyperspectral tests with EnMAP compressed by standardised PCA or by MNF.

    Same pixels, labels, blocks and spatial folds as `compare` and `heat_r2`; every compression
    is fitted inside the training folds. Returns the noise estimate, MNF eigenvalue counts and
    one row per (method, components) with built-vs-desert accuracy and block-heat R².
    """
    cube = refl.values
    sigma_n, window = noise_covariance(cube, refl.wavelength.values)
    finite = np.isfinite(cube).all(axis=0)
    eig = MNF(sigma_n, cube.shape[0]).fit(cube[:, finite].T).eigenvalues_

    valid = (labels >= 0) & finite
    yy, xx = np.nonzero(valid)
    groups = (np.floor(refl.x.values[xx] / tile_size).astype(int) * 100_000
              + np.floor(refl.y.values[yy] / tile_size).astype(int))
    y = labels[valid].astype(int)
    x = cube[:, valid].T

    ok = np.isfinite(lst_c) & np.isfinite(block_spec).all(axis=1)
    spec, ours, lst, g = block_spec[ok], block_features[ok], lst_c[ok], block_groups[ok]
    both = np.hstack([ours, spec])

    def ridge() -> RidgeCV:
        return RidgeCV(alphas=np.logspace(-3, 3, 13))

    def cv_r2(x_: np.ndarray, make: callable) -> float:
        pred = np.empty_like(lst)
        for tr, te in GroupKFold(n_splits=folds).split(x_, lst, g):
            pred[te] = make().fit(x_[tr], lst[tr]).predict(x_[te])
        return float(r2_score(lst, pred))

    rows = []
    for method in ("PCA", "MNF"):
        for k in components:
            scores = []
            for tr, te in GroupKFold(n_splits=folds).split(x, y, groups):
                m = make_pipeline(_compressor(method, k, sigma_n), StandardScaler(),
                                  LogisticRegression(class_weight="balanced", max_iter=5000))
                m.fit(x[tr], y[tr])
                scores.append(balanced_accuracy_score(y[te], m.predict(x[te])))
            rows.append({
                "method": method, "components": k,
                "built_vs_desert": float(np.mean(scores)),
                "built_vs_desert_std": float(np.std(scores)),
                "heat_spectra": cv_r2(spec, lambda m=method, k=k: make_pipeline(
                    _compressor(m, k, sigma_n), StandardScaler(), ridge())),
                "heat_with_features": cv_r2(both, lambda m=method, k=k: make_pipeline(
                    _AppendCompressed(ours.shape[1], _compressor(m, k, sigma_n)),
                    StandardScaler(), ridge())),
            })
    return {"window": window, "n_bands": int(cube.shape[0]),
            "eig_above_10": int((eig > 10).sum()), "eig_above_3": int((eig > 3).sum()),
            "rows": rows}
