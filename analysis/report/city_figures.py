"""Analysis maps for a city beyond Cairo, drawn by the report's own figure code (figures.py).

The app shows them in "Analysis maps for this view". Only what the city's data supports is drawn:
no hyperspectral chart without EnMAP, no growth map without Google Open Buildings Temporal.
Run from analysis/ with the city's environment, as for run_pipeline.py:
  COOLCAIRO_CONFIG=config/aoi_<key>.yaml COOLCAIRO_DATA_DIR=data/<key>
  COOLCAIRO_EXPORT_DIR=../export/<key> python report/city_figures.py
Writes export/<key>/figures/*.png.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import figures  # noqa: E402
from compute import cv_predictions, growth_results  # noqa: E402

from coolcairo.config import EXPORT_DIR, load_config  # noqa: E402
from coolcairo.interventions import exposure_reduction_summary, heat_reference_c, targeted_plan  # noqa: E402
from coolcairo.model import fit, training_rows  # noqa: E402
from coolcairo.pipeline import build_blocks, display_subset  # noqa: E402


def main() -> None:
    cfg = load_config()
    blocks, material, buildings = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"])
    result = fit(train, cfg["cv_tile_size"], cfg["cv_folds"])
    display, _ = display_subset(cfg, blocks, buildings)
    ref = heat_reference_c(cfg, train)
    measured = display.dropna(subset=["lst_c"])
    has_growth = cfg.raw.get("open_buildings", True)
    r = SimpleNamespace(
        cfg=cfg, blocks=blocks, material=material, train=train, fit=result,
        cv_pred=cv_predictions(train, cfg["cv_tile_size"], cfg["cv_folds"]),
        display=display, reference_c=ref,
        exposure=exposure_reduction_summary(cfg, result, measured, ref),
        targeted=targeted_plan(cfg, result, display, ref),
        growth=growth_results(cfg, blocks, display) if has_growth else None,
    )
    out = EXPORT_DIR / "figures"
    drawn = [figures.study_area(r, out), figures.district(r, out), figures.model_fit(r, out),
             figures.interventions(r, out)]
    if has_growth:
        drawn.append(figures.urban_growth(r, out))
    for p in drawn:
        print("wrote", p)


if __name__ == "__main__":
    main()
