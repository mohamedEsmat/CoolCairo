"""Refinement checks from the course's advanced-analytics session (week 4, 25 Nov 2026).

The session's case study was change detection, but four of its checks apply to a one-date
material map and a cooling plan:

1. Threshold sensitivity (`plan_curve`): the targeted plan treats "the riskiest third" of blocks.
   That share is a choice, so measure it: heat exposure removed against blocks treated.
2. Uncertainty (`plan_pct`, used by make_refinement.py's Monte Carlo): rerun the plan with the
   uncertain inputs redrawn many times and report a range, not one number.
3. Co-registration (`phase_correlation`): the sub-pixel shift between two images of the same
   ground, by FFT phase correlation (Kuglin & Hines 1975).
4. Two dates (`two_date_check`): before comparing two scenes, measure and remove their shift,
   then the offset on a control area that did not change (illumination, atmosphere, sensor).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import ndimage

from coolcairo.config import Config
from coolcairo.enmap_materials import measure_deltas, treatable_areas
from coolcairo.population import heat_exposure

PLANS = ("targeted", "no_water")  # roofs + trees + pavements; roofs + pavements


def _plan_deltas(cfg: Config, d: pd.DataFrame, info: dict) -> dict[str, pd.Series]:
    """Per-block temperature change of each plan at full adoption (as plan_figures)."""
    deltas, area = measure_deltas(cfg, d, info), treatable_areas(d)
    planted = cfg["interventions"]["tree_max_share_of_dark_ground"] * area.asphalt
    return {
        "targeted": deltas.cool_roofs + deltas.street_trees
        + info["coolPavementDeltaC"] * (area.asphalt - planted),
        "no_water": deltas.cool_roofs + deltas.cool_pavements,
    }


def _ranking(d: pd.DataFrame, lst: pd.Series, reference_c: float) -> pd.Index:
    """Blocks from riskiest to least (today's heat exposure, ties by temperature)."""
    people = d.population.clip(lower=0)
    ranked = pd.DataFrame({"exposure": heat_exposure(lst, people, reference_c), "lst": lst})
    return ranked.sort_values(["exposure", "lst"], ascending=False, kind="stable").index


def plan_pct(cfg: Config, display: pd.DataFrame, info: dict, reference_c: float,
             n_blocks: int | None = None, lst: pd.Series | None = None) -> dict[str, float]:
    """% change in heat exposure of each plan on the `n_blocks` riskiest blocks.

    Defaults reproduce plan_figures (a third of the blocks, the measured temperature). `lst`
    lets the Monte Carlo redraw the temperatures; `info` carries the per-measure deltas.
    """
    d = display.dropna(subset=["lst_c"])
    lst = d.lst_c if lst is None else lst.reindex(d.index)
    people = d.population.clip(lower=0)
    base = heat_exposure(lst, people, reference_c).sum()
    chosen = _ranking(d, lst, reference_c)[: len(d) // 3 if n_blocks is None else n_blocks]
    out = {}
    for name, delta in _plan_deltas(cfg, d, info).items():
        change = pd.Series(0.0, index=d.index)
        change[chosen] = delta[chosen]
        after = heat_exposure(lst + change, people, reference_c).sum()
        out[name] = float(100 * (after - base) / base)
    return out


def plan_curve(cfg: Config, display: pd.DataFrame, info: dict, reference_c: float,
               block_size_m: float, shares: np.ndarray | None = None) -> pd.DataFrame:
    """Heat exposure removed against the share of blocks treated (riskiest first).

    One row per share: blocks treated, hectares of roof and asphalt treated, residents in them,
    and the % change of both plans. The marginal column is the extra exposure removed per extra
    hectare, the point where more treatment stops paying off.
    """
    d = display.dropna(subset=["lst_c"])
    shares = np.round(np.arange(0.05, 1.0001, 0.05), 2) if shares is None else shares
    order = _ranking(d, d.lst_c, reference_c)
    area = treatable_areas(d)
    ha_per_block = (area.roof_pale + area.roof_dusty + area.asphalt) * (block_size_m / 100) ** 2
    people = d.population.clip(lower=0)
    rows = []
    for share in shares:
        n = int(round(share * len(d)))
        chosen = order[:n]
        pct = plan_pct(cfg, display, info, reference_c, n_blocks=n)
        rows.append({"share": float(share), "blocks": n,
                     "hectares": float(ha_per_block[chosen].sum()),
                     "residents": float(people[chosen].sum()),
                     "targeted_pct": pct["targeted"], "no_water_pct": pct["no_water"]})
    out = pd.DataFrame(rows)
    gained = -out.targeted_pct.diff().fillna(-out.targeted_pct)
    out["pct_per_extra_ha"] = gained / out.hectares.diff().fillna(out.hectares)
    return out


def phase_correlation(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Shift (dy, dx) in pixels that moves image `b` onto image `a`, and the peak height (0-1).

    NaNs are filled with the image mean; a Hann window tapers the edges; the peak is refined to
    sub-pixel with a parabola through it and its two neighbours on each axis. A peak height near
    1 is a clean match; near 0 means the images do not share structure.
    """
    def prep(img: np.ndarray) -> np.ndarray:
        img = np.where(np.isfinite(img), img, np.nanmean(img))
        img = img - img.mean()
        return img * np.outer(np.hanning(img.shape[0]), np.hanning(img.shape[1]))

    r = np.fft.fft2(prep(a)) * np.conj(np.fft.fft2(prep(b)))
    corr = np.fft.ifft2(r / (np.abs(r) + 1e-12)).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    shift = []
    for axis, p in ((0, py), (1, px)):
        n = corr.shape[axis]
        if axis == 0:
            idx = [((p - 1) % n, px), (p, px), ((p + 1) % n, px)]
        else:
            idx = [(py, (p - 1) % n), (py, p), (py, (p + 1) % n)]
        lo, mid, hi = (corr[i] for i in idx)
        denom = lo - 2 * mid + hi
        frac = 0.5 * (lo - hi) / denom if denom != 0 else 0.0
        s = p + frac
        shift.append(s - n if s > n / 2 else s)
    return float(shift[0]), float(shift[1]), float(corr[py, px])


def shift_image(img: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Move a 2-D image (or a cube's last two axes) by (dy, dx) pixels: bilinear, NaN outside."""
    shifts = (0,) * (img.ndim - 2) + (dy, dx)
    filled = np.where(np.isfinite(img), img, 0.0)
    valid = ndimage.shift(np.isfinite(img).astype(float), shifts, order=1, cval=0.0)
    out = ndimage.shift(filled, shifts, order=1, cval=np.nan)
    return np.where(valid > 0.999, out, np.nan)


def tiled_shifts(a: np.ndarray, b: np.ndarray, tile: int) -> pd.DataFrame:
    """Phase-correlation shift per tile x tile window: does the shift vary across the scene?"""
    rows = []
    for r0 in range(0, a.shape[0] - tile + 1, tile):
        for c0 in range(0, a.shape[1] - tile + 1, tile):
            wa, wb = a[r0:r0 + tile, c0:c0 + tile], b[r0:r0 + tile, c0:c0 + tile]
            if np.isfinite(wa).mean() < 0.9 or np.isfinite(wb).mean() < 0.9:
                continue
            dy, dx, peak = phase_correlation(wa, wb)
            rows.append({"row0": r0, "col0": c0, "dy": dy, "dx": dx, "peak": peak})
    return pd.DataFrame(rows)


def two_date_check(before: np.ndarray, after: np.ndarray, control: np.ndarray,
                   band: int) -> dict:
    """Prepare two co-located cubes (band, y, x) for comparison, the course's way.

    1. Shift: phase correlation on one band (pick a band with structure, e.g. red or NIR).
    2. Move `after` onto `before` by that shift.
    3. Offset: the mean spectrum change on `control` pixels (a boolean mask of ground known not to
       have changed), which is illumination, atmosphere and calibration, not real change.
    Returns the shift, the peak height, the control offset per band, and `after` corrected for
    both (shift, then minus the offset), ready to compare with `before`.
    """
    dy, dx, peak = phase_correlation(before[band], after[band])
    moved = shift_image(after, dy, dx)
    ok = control & np.isfinite(before).all(axis=0) & np.isfinite(moved).all(axis=0)
    offset = np.nanmean(moved[:, ok] - before[:, ok], axis=1)
    return {"dy": dy, "dx": dx, "peak": peak, "control_pixels": int(ok.sum()),
            "offset": offset, "after_corrected": moved - offset[:, None, None]}
