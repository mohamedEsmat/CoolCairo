"""Agreement metrics for continuous products (course week 3, session 3: validation).

R² alone hides an offset, so every comparison reports bias, MAE, RMSE, R² about the 1:1
line (not Pearson r², which ignores offset and slope) and Bland-Altman limits of agreement
(Bland & Altman 1986): the difference plotted against the mean shows error that grows or
shrinks with the value.

`stable_target_noise` measures how much a quantity changes between two dates on targets that
should not have changed (pseudo-invariant targets): a smaller change cannot be told from noise.
"""

from __future__ import annotations

import numpy as np


def agreement(reference: np.ndarray, estimate: np.ndarray) -> dict[str, float]:
    """Bias (estimate minus reference), MAE, RMSE, R² about 1:1, Pearson r², Bland-Altman."""
    ref, est = np.asarray(reference, float), np.asarray(estimate, float)
    ok = np.isfinite(ref) & np.isfinite(est)
    ref, est = ref[ok], est[ok]
    diff, mean = est - ref, (est + ref) / 2
    sd = float(diff.std(ddof=1))
    bias = float(diff.mean())
    return {
        "n": int(len(ref)),
        "bias": bias,
        "mae": float(np.abs(diff).mean()),
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "r2_1to1": float(1 - np.sum(diff**2) / np.sum((ref - ref.mean()) ** 2)),
        "pearson_r2": float(np.corrcoef(ref, est)[0, 1] ** 2),
        "loa_low": bias - 1.96 * sd,
        "loa_high": bias + 1.96 * sd,
        # Slope of difference on mean: 0 = error the same at every level.
        "ba_slope": float(np.polyfit(mean, diff, 1)[0]),
    }


def stable_target_noise(first: np.ndarray, second: np.ndarray) -> dict[str, float]:
    """Change between two dates on stable targets, after removing the scene-wide offset.

    The offset (median change) is weather, the same for every target; what is left is the noise
    a real local change must exceed. `threshold_95` = 95th percentile of the absolute residual.
    """
    a, b = np.asarray(first, float), np.asarray(second, float)
    ok = np.isfinite(a) & np.isfinite(b)
    change = b[ok] - a[ok]
    offset = float(np.median(change))
    resid = change - offset
    return {
        "n": int(ok.sum()),
        "offset": offset,
        "resid_sd": float(resid.std(ddof=1)),
        "resid_rmse": float(np.sqrt(np.mean(resid**2))),
        "threshold_95": float(np.percentile(np.abs(resid), 95)),
        "pearson_r": float(np.corrcoef(a[ok], b[ok])[0, 1]),
    }
