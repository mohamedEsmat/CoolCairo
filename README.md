# CoolCairo

**Block-level urban heat decision support for Nasr City, Cairo.**
Arab Youth Space Hackathon 2026 (UAE Space Agency / Space42), 813 Challenge: *Urban Expansion, Land Use Change & Heat Risk*. Team 46.

> We want to **map** summer heat risk, meaning land surface temperature, the surface materials driving it, and the population exposed to it, in **Nasr City, Cairo** during **June–August 2023–2025** so that **city planners** can decide **which blocks to prioritise for cool roofs, street trees, cool pavements and pocket parks**.

CoolCairo is a Windows desktop app backed by a reproducible Python analysis. A planner sees the district in 3D from real satellite data, switches between surface materials, surface temperature and heat risk, paints cooling measures onto 90 m blocks, and reads the predicted effect live.

## What the app does

1. **Satellite archive sync.** At start-up the app queries the real archives for the exact scenes the analysis used (65 Landsat 8/9 and 70 Sentinel-2 scenes via Microsoft Planetary Computer, the EnMAP scene via DLR) and downloads a live preview of Cairo from each satellite. Offline, it says so and uses the prepared data.
2. **MENA globe.** NASA Blue Marble Earth with the region's major cities; Nasr City is the one analysed district, the others show where the method scales next.
3. **Fly-in.** From space down to Nasr City, ending on a sharp 10 m Sentinel-2 image of Cairo.
4. **3D district** (about 1,900 buildings with estimated heights) with three views:
   - **Materials:** vegetation, dark surfaces, pale surfaces and bare sand per block.
   - **Surface heat:** summer land surface temperature per block.
   - **Heat risk:** residents × degrees above a typical east-Cairo block.
5. **Four cooling tools**, painted per block, with live results (average block temperature before → after, heat exposure, residents in cooled blocks):

| Tool | What it changes | Effect per unit of block area | Basis |
| --- | --- | --- | --- |
| Cool roofs | Dark and pale roofs coated white | −4.6 °C (dark) / −3.6 °C (pale) | Published values |
| Street trees | Up to 25% of dark ground planted | −3.3 °C | Our regression |
| Cool pavements | Asphalt coated reflective (albedo 0.12 → 0.40) | −2.2 °C | Published values (conservative) |
| Pocket parks | Up to 50% of bare sand greened | −6.5 °C | Our regression |

## Key results

- **Heat model:** block surface temperature from material fractions and building height, spatial cross-validated R² **0.25** (mean error ±1.2 °C, 2,538 urban blocks, 1 km tiles held out).
- **Hyperspectral adds value for heat:** EnMAP block spectra explain block surface temperature at R² **0.58** (with our features) vs **0.40** with Sentinel-2, and **0.53 vs 0.33** for the same EnMAP scene reduced to Sentinel-2's bands. The advantage holds with 2–3 km held-out tiles. For separating buildings from desert, EnMAP adds nothing beyond a 70-scene Sentinel-2 composite. See `analysis/notebooks/05_hyperspectral_value.ipynb`.
- **Heat risk in the display district:** 95,141 residents, 6,460 person·°C of heat exposure today. At full adoption within each tool's limits, exposure falls by 41% (cool roofs), 24% (street trees), 52% (cool pavements) and 60% (pocket parks).
- **Building heights:** Google Open Buildings 2.5D estimates checked against OSM-tagged heights: bias −1.4 m, mean error 6.2 m, r = 0.60.

## Data

| Source | Use | Licence / attribution |
| --- | --- | --- |
| Landsat 8/9 Collection 2 Level-2 (USGS, via Planetary Computer) | Surface temperature, summer median 2023–2025 | Public domain (USGS) |
| Sentinel-2 L2A (ESA Copernicus, via Planetary Computer) | Surface materials, vegetation, fly-in image | Contains modified Copernicus Sentinel data [2023–2025] |
| EnMAP L2A, 22 Apr 2025 (DLR EOC Geoservice) | Hyperspectral heat drivers | Contains modified EnMAP data © DLR [2025]. Raw data may not be redistributed and is **not** in this repository |
| OpenStreetMap (via osmnx) | Building footprints | © OpenStreetMap contributors, ODbL |
| Google Open Buildings 2.5D Temporal | Building heights | CC BY 4.0 / ODbL |
| WorldPop Global2 R2025A, 2024 | Residents per block | CC BY 4.0 |
| NASA Blue Marble (July 2004) | Globe texture | Public domain |

Intervention effects, costs researched for later, and all sources: `docs/intervention_research.md`.

## Reproduce

**Analysis** (Python 3.12 via [uv](https://docs.astral.sh/uv/)):

```bash
cd analysis
uv sync                        # locked dependencies
uv run pytest                  # unit tests
uv run python run_pipeline.py  # stream data, fit model, write export/district.json
uv run jupyter lab             # notebooks 01–05, same steps with plots
uv run python report/build_report.py  # methodology report PDF in docs/
```

No account or API key is needed for the core pipeline. **EnMAP is optional:** it needs a free DLR EOC Geoservice account subscribed to the "EnMAP Access Service"; download the files for the scene in `analysis/config/enmap_scenes.txt` into `analysis/data/enmap/`. Without them the pipeline runs and skips the hyperspectral results.

**App** (Unity 6000.0.83f1, URP, Windows):

1. Open `unity/` in Unity.
2. Run **CoolCairo → Setup project and scene**. It imports `export/district.json` and builds the `Intro` (globe) and `Main` (district) scenes, including the UI.
3. Run **CoolCairo → Build Windows desktop app**. Output: `unity/Builds/Windows/CoolCairo.exe`.

Starting the app with `-autotest` makes it drive itself through the whole flow in a loop, for soak testing.

## Repository layout

| Path | What |
| --- | --- |
| `analysis/src/coolcairo` | Pipeline modules; notebooks are thin drivers |
| `analysis/config/aoi.yaml` | Areas, CRS, dates, thresholds and every literature value, with sources |
| `analysis/notebooks` | 01 data · 02 classification and M2 spot check · 03 model and heat risk · 04 export · 05 hyperspectral value |
| `export/district.json` | Handoff from analysis to the app |
| `unity/Assets/CoolCairo` | Globe intro, 3D district, interventions, UI |
| `docs` | Research notes, M2 spot-check sheet, EnMAP licence |

## Limitations

- **Surface, not air, temperature.** Satellites measure how hot surfaces get. Studies suggest city-wide cool roofs lower air temperature by about 0.1–0.33 °C per +0.1 roof albedo; the effect on air is smaller and spreads beyond the district.
- **Block level only (90 m).** Landsat's thermal band is 100 m, so no per-building temperatures are claimed.
- **Modest model fit** (R² 0.25 with Sentinel-2 features). Cool roofs and cool pavements therefore use published values; trees and pocket parks use our own estimates.
- **Materials come from Sentinel-2 rules;** visual validation against 20 spot-checked points (milestone M2) is in progress.
- **Heat risk is a screening indicator** (heat × residents). It does not include vulnerability such as age, housing or access to cooling.
- **Costs are not yet in the app;** researched ranges are in `docs/intervention_research.md`.

## Team

Liquaa Mahmoud (team lead), Mohamed Esmat (technical lead), Mahmoud.
