# CoolCairo

Block-level urban heat decision support for Nasr City, Cairo. Arab Youth Space Hackathon 2026, Theme 5.

A planner sees the district in 3D, coloured by surface material or by land surface temperature,
paints cool roofs or street trees onto blocks, and reads the predicted surface-temperature change live.

## Reproduce from a clean checkout

Requires [uv](https://docs.astral.sh/uv/) and Unity 6000.0.83f1 with WebGL support.

```bash
cd analysis
uv sync                        # Python 3.12 + locked dependencies
uv run pytest                  # unit tests
uv run python run_pipeline.py  # stream data, fit model, write export/district.json
```

Notebooks in `analysis/notebooks/` walk through the same steps with plots (`uv run jupyter lab`).
No account or API key is needed: Landsat and Sentinel-2 stream from Microsoft Planetary Computer,
buildings from OpenStreetMap.

Then open `unity/` in Unity and run **CoolCairo → Setup project and scene**, which imports
`export/district.json` and builds `Assets/CoolCairo/Main.unity`.

## Layout

| Path | What |
| --- | --- |
| `analysis/src/coolcairo` | Importable pipeline modules (notebooks are thin drivers) |
| `analysis/config/aoi.yaml` | CRS, areas, dates, thresholds: the single source of configuration |
| `export/district.json` | Handoff from analysis to Unity (schema in `analysis/src/coolcairo/export.py`) |
| `unity/Assets/CoolCairo` | 3D district, heat overlay, intervention brush |

## What the numbers mean

- Temperatures are **land surface temperature** (Landsat), not air temperature.
- Every value is per **90 m block**. Landsat thermal is 100 m native, so no per-roof claims are made.
- Model R² is reported with spatial cross-validation (1 km tiles held out).
