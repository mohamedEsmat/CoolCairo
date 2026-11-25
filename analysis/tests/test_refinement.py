import json
import re

import numpy as np
import pandas as pd
import pytest
from scipy import ndimage

from coolcairo.config import REPO_ROOT, load_config
from coolcairo.enmap_materials import plan_figures
from coolcairo.refinement import (
    phase_correlation,
    plan_curve,
    plan_pct,
    shift_image,
    tiled_shifts,
    two_date_check,
)


def _texture(shape=(128, 128), seed=0):
    rng = np.random.default_rng(seed)
    return ndimage.gaussian_filter(rng.normal(size=shape), 2.0)


def test_phase_correlation_recovers_a_subpixel_shift():
    a = _texture()
    b = shift_image(a, 2.4, -1.3)  # b is a moved 2.4 px down, 1.3 px left
    dy, dx, peak = phase_correlation(a, b)
    back = shift_image(b, dy, dx)  # the returned shift moves b back onto a
    assert dy == pytest.approx(-2.4, abs=0.15) and dx == pytest.approx(1.3, abs=0.15)
    assert peak > 0.3
    inner = (slice(8, -8), slice(8, -8))
    # Interpolating twice (shift there and back) smooths a little: compare on average.
    assert np.nanmean(np.abs(back[inner] - a[inner])) < 0.1 * np.std(a)


def test_tiled_shifts_sees_a_uniform_shift_in_every_tile():
    a = _texture((256, 256), seed=1)
    tiles = tiled_shifts(a, shift_image(a, 1.0, 0.5), tile=128)
    assert len(tiles) == 4
    assert np.allclose(tiles.dy, -1.0, atol=0.2) and np.allclose(tiles.dx, -0.5, atol=0.2)


def test_two_date_check_removes_shift_and_control_offset():
    bands = np.stack([_texture(seed=s) for s in range(4)]) + 0.3
    offset = np.array([0.02, -0.01, 0.03, 0.0])
    after = shift_image(bands, 1.6, -0.7) + offset[:, None, None]
    control = np.zeros(bands.shape[1:], bool)
    control[20:60, 20:60] = True
    out = two_date_check(bands, after, control, band=0)
    assert out["dy"] == pytest.approx(-1.6, abs=0.15) and out["dx"] == pytest.approx(0.7, abs=0.15)
    assert np.allclose(out["offset"], offset, atol=0.01)
    inner = (slice(None), slice(8, -8), slice(8, -8))
    assert np.nanmean(np.abs(out["after_corrected"][inner] - bands[inner])) < 0.02


def _district():
    district = json.loads((REPO_ROOT / "export" / "district.json").read_text(encoding="utf-8"))
    snake = lambda k: re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()  # noqa: E731
    blocks = pd.DataFrame({snake(k): v for k, v in district["blocks"].items()})
    return district, blocks


def test_plan_pct_and_curve_reproduce_the_published_plan():
    cfg = load_config()
    district, blocks = _district()
    info, ref = district["enmap"], district["model"]["heatReferenceC"]
    pct = plan_pct(cfg, blocks, info, ref)
    assert pct["targeted"] == pytest.approx(plan_figures(cfg, blocks, info, ref)["targetedPct"])
    assert pct["targeted"] == pytest.approx(info["targetedPct"], abs=0.01)
    third = len(blocks.dropna(subset=["lst_c"])) // 3
    curve = plan_curve(cfg, blocks, info, ref, district["blockSize"])
    assert curve.targeted_pct.is_monotonic_decreasing  # more blocks never removes less
    assert curve.residents.is_monotonic_increasing
    at_third = plan_pct(cfg, blocks, info, ref, n_blocks=third)
    assert at_third["targeted"] == pytest.approx(pct["targeted"])
