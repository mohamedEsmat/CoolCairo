"""Air-temperature check: Landsat surface temperature vs Cairo Airport air temperature, per scene.

Usage (from /analysis):  uv run python air_check.py
Writes results/air_temperature_check.csv (one row per clear summer Landsat morning) and
results/air_temperature_check.json (summary). See coolcairo.air for the method and its limits.
"""

from __future__ import annotations

import json

from coolcairo.air import air_check
from coolcairo.config import REPO_ROOT, load_config


def main() -> None:
    cfg = load_config()
    table, summary = air_check(cfg)
    out = REPO_ROOT / "results"
    table.round(2).to_csv(out / "air_temperature_check.csv", index=False)
    (out / "air_temperature_check.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                     encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
