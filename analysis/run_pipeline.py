"""Run the whole pipeline headless: rasters -> blocks -> model -> export/district.json.

Usage (from /analysis):  uv run python run_pipeline.py
The notebooks call the same functions step by step with plots.
"""

from __future__ import annotations

import json
import time

from coolcairo.config import EXPORT_DIR, load_config
from coolcairo.export import grid_origin, grid_shape, write_district
from coolcairo.interventions import (
    cool_roof_surface_deltas,
    full_adoption_summary,
    plausibility_warnings,
)
from coolcairo.model import fit, training_rows
from coolcairo.pipeline import build_blocks, display_subset


def main() -> None:
    cfg = load_config()
    t0 = time.time()
    blocks, _, buildings = build_blocks(cfg)
    print(f"[{time.time() - t0:.0f}s] {len(blocks)} blocks, {len(buildings)} buildings")
    print(buildings.height_source.value_counts(normalize=True).round(3).to_dict())

    train = training_rows(blocks, cfg["min_building_coverage"])
    result = fit(train, cfg["cv_tile_size"], cfg["cv_folds"])
    print(json.dumps(result.to_dict(), indent=2))
    roof = cool_roof_surface_deltas(cfg, result)
    print(f"Cool roof per unit block area coated: dark {roof.dark:+.2f} C, "
          f"pale {roof.pale:+.2f} C ({cfg['cool_roof']['method']})")
    for w in plausibility_warnings(cfg, result):
        print("WARNING:", w)
    print(full_adoption_summary(cfg, result, train).round(2))

    disp_blocks, disp_buildings = display_subset(cfg, blocks, buildings)
    rows, cols = grid_shape(disp_blocks)
    write_district(
        EXPORT_DIR / "district.json",
        name=cfg["display_aoi"]["name"],
        crs=cfg.crs,
        origin=grid_origin(disp_blocks, cfg.block_size),
        block_size=cfg.block_size,
        rows=rows,
        cols=cols,
        blocks=disp_blocks,
        buildings=disp_buildings,
        fit=result,
        cool_roof=roof,
        cool_roof_method=cfg["cool_roof"]["method"],
        provenance={
            "lst": "Landsat 8/9 C2 L2 ST_B10, summer median",
            "materials": "Sentinel-2 L2A interim 4-class rules (EnMAP pending)",
            "cool_roof": "Wang, Huang & Li 2020, GRL 47, e2020GL087853 (see aoi.yaml)",
            "buildings": "OpenStreetMap",
        },
    )
    print(f"[{time.time() - t0:.0f}s] display: {rows}x{cols} blocks, "
          f"{len(disp_buildings)} buildings -> export/district.json")


if __name__ == "__main__":
    main()
