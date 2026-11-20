"""Sub-pixel target detection (course notebook 14, section 3): matched filter, ACE, CEM, SAM.

Used to look for roofs like library candidate #14 (a large bright roof that looks like metal)
across the EnMAP scene, and to benchmark the detectors by implanting the target into real
background pixels. Formulas and shrinkage follow the course notebook.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def shrink(cov: np.ndarray, lam: float) -> np.ndarray:
    """Shrink a covariance matrix towards a scaled identity (keeps it invertible)."""
    p = cov.shape[0]
    return (1 - lam) * cov + lam * np.trace(cov) / p * np.eye(p)


def background_stats(background: np.ndarray, lam: float = 1e-3) -> tuple[np.ndarray, np.ndarray]:
    """Mean and inverse shrunk covariance of background pixels (n, bands)."""
    return background.mean(axis=0), np.linalg.inv(shrink(np.cov(background, rowvar=False), lam))


def matched_filter(x: np.ndarray, t: np.ndarray, mu: np.ndarray, ci: np.ndarray) -> np.ndarray:
    s = t - mu
    return ((x - mu) @ ci @ s) / (s @ ci @ s)


def ace(x: np.ndarray, t: np.ndarray, mu: np.ndarray, ci: np.ndarray) -> np.ndarray:
    """Adaptive coherence estimator (Kraut & Scharf 1999): 0-1, scale-invariant."""
    s = t - mu
    xc = x - mu
    return (xc @ ci @ s) ** 2 / ((s @ ci @ s) * np.einsum("ij,ij->i", xc @ ci, xc))


def cem(x: np.ndarray, t: np.ndarray, reference: np.ndarray, lam: float = 1e-3) -> np.ndarray:
    """Constrained energy minimisation, with the correlation matrix of `reference` pixels."""
    ri = np.linalg.inv(shrink(reference.T @ reference / len(reference), lam))
    w = ri @ t / (t @ ri @ t)
    return x @ w


def sam_score(x: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Minus the spectral angle (radians), so that larger means more target-like."""
    cos = x @ t / (np.linalg.norm(x, axis=1) * np.linalg.norm(t))
    return -np.arccos(np.clip(cos, -1, 1))


def implantation(
    background: np.ndarray, signature: np.ndarray, implants: np.ndarray,
    fractions: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2, 0.3), lam: float = 1e-3,
    n_clean: int = 5000, n_implanted: int = 1000, seed: int = 0,
) -> pd.DataFrame:
    """Course notebook 14, section 3.4: mix target spectra into real background pixels.

    x = (1 - f) * background + f * target, with targets drawn from `implants` (not the
    pixels that made `signature`). Returns AUC and the detection rate at 1 % false alarms
    per detector and fraction. Optimistic by design (linear mixing, same-site targets).
    """
    rng = np.random.default_rng(seed)
    mu, ci = background_stats(background, lam)
    clean = background[rng.choice(len(background), n_clean, replace=False)]
    reference = background[:: max(1, len(background) // 10_000)]
    rows = []
    for f in fractions:
        host = background[rng.choice(len(background), n_implanted, replace=False)]
        mixed = (1 - f) * host + f * implants[rng.integers(0, len(implants), n_implanted)]
        x = np.vstack([clean, mixed])
        y = np.r_[np.zeros(len(clean)), np.ones(len(mixed))]
        scores = {"SAM": sam_score(x, signature), "MF": matched_filter(x, signature, mu, ci),
                  "CEM": cem(x, signature, reference, lam), "ACE": ace(x, signature, mu, ci)}
        for name, sc in scores.items():
            thr = np.percentile(sc[y == 0], 99)
            rows.append({"fraction": f, "detector": name, "auc": roc_auc_score(y, sc),
                         "detected_at_1pct_false_alarms": float((sc[y == 1] > thr).mean())})
    return pd.DataFrame(rows)
