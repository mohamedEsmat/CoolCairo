"""The example data in data/sample_input/ reproduces the published numbers, offline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run_example.py lives in analysis/
import run_example  # noqa: E402

pytestmark = pytest.mark.skipif(not run_example.SAMPLE.exists(), reason="no example data")


@pytest.fixture(scope="module")
def out():
    return run_example.run()


def test_heat_model_matches_report(out):
    assert out["model"]["n_blocks"] == 2538
    assert out["model"]["r2_spatial_cv"] == pytest.approx(0.25, abs=0.005)
    assert out["model"]["mae_spatial_cv"] == pytest.approx(1.2, abs=0.05)


def test_heat_risk_matches_report_and_app(out):
    r = out["heat_risk"]
    assert r["residents"] == pytest.approx(95141, abs=1)
    assert r["exposure_person_degC"] == pytest.approx(6460, abs=1)  # app self-test checks 6,460 too
    assert round(r["cool_roofs_pct"]) == -41
    assert round(r["pocket_parks_pct"]) == -60
    assert r["targeted_plan"]["exposure_after"] == pytest.approx(1686, abs=1)  # app screenshot


def test_growth_matches_report(out):
    g = out["growth"]
    assert g["newly_built_blocks"] == 988
    assert g["growth_pct"] == pytest.approx(5.7, abs=0.05)


def test_results_written(out):
    for name in ("model_fit.json", "heat_risk_nasr_city.json", "summary.md",
                 "nasr_city_heat_exposure.png"):
        assert (run_example.RESULTS / name).exists(), name
