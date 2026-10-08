# CoolCairo

[![Open the quick example in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/mohamedEsmat/CoolCairo/blob/master/analysis/notebooks/00_quick_example.ipynb)

**Block-level urban heat decision support for MENA cities, starting with Nasr City, Cairo.**
Arab Youth Space Hackathon 2026 (UAE Space Agency / Space42), 813 Challenge. **Theme:** Urban Expansion, Land Use Change & Heat Risk. **Team 46**, Egypt.

CoolCairo maps summer heat risk block by block from free satellite data (how hot each 90 m block's surfaces get, what they are made of, and how many people live there) and gives city planners a 3D desktop app in which they paint cool roofs, street trees, cool pavements and pocket parks onto blocks and see the predicted effect live.

**Quick links:** [quick example notebook (runs in seconds, offline)](analysis/notebooks/00_quick_example.ipynb) · [slides (PDF)](docs/CoolCairo_Slides.pdf) · [methodology report (PDF)](docs/CoolCairo_Methodology_Report.pdf) · [example results](results/summary.md)

## 1. Business use case

- **User:** city and district planners: governorate planning departments, new-city developers, and climate-adaptation programmes that fund cooling.
- **Decision:** where to cool first, and with which measure in each block (cool roofs, street trees, cool pavements or pocket parks), so surface temperatures fall where people live, for their health and for the city's environment.
- **What they have today:** at best city-wide heat maps or individual site studies. Nothing shows, block by block, where heat, the surfaces causing it and the people exposed to it overlap, or what a measure would change before money is spent.
- **What CoolCairo gives them:** a ranked, block-level picture of heat risk and a tool to test plans. In Nasr City, cool roofs and pocket parks on only the riskiest third of blocks remove **74%** of the district's heat exposure, more than any single measure applied everywhere: cooling goes where it helps people most.
- **Business model:** heat-risk planning as a service, city by city: a setup fee per city and a yearly licence for updates, paid pilots, and plan reports for funded cooling programmes; input data is free, so costs are mainly team time and light cloud compute. First step: a pilot with one Cairo district authority or new-city developer.
- **SDG fit:** SDG 11 (sustainable cities), SDG 13 (climate action), SDG 3 (good health).

The app: at start-up it checks the real satellite archives for the scenes the analysis used, shows a MENA globe, flies into Nasr City and shows the district in 3D (about 1,900 buildings with estimated heights) with four views (surface materials, surface heat, heat risk, urban growth 2016–2023), the matching analysis maps, and four cooling tools with live result cards (average block temperature before → after, heat exposure, residents in cooled blocks).

## 2. The problem

> We want to **map** summer heat risk (land surface temperature, the surface materials driving it, and the residents exposed to it) in **fast-growing cities across the Middle East and North Africa**, starting with **Nasr City, Cairo** (June–August 2023–2025) as the first example, so that **city planners** can **decide which blocks to prioritise for cool roofs, street trees, cool pavements and pocket parks**.

- **What is wrong now:** cities across the region share desert climate, dark roofs and asphalt, sandy lots and fast growth onto the desert. A typical east-Cairo block reaches **45.7 °C** at the surface in summer, open desert 48.6 °C.
- **Scale:** the 13 × 13 km east-Cairo model area has 23,103 blocks and about 3.9 million residents; the Nasr City district shown in the app (2.2 × 2.2 km) has 95,141 residents and 6,460 person·°C of heat exposure. Building footprint grew 5.7% from 2016 to 2023, and the new blocks run about 1 °C hotter than established neighbourhoods.
- **Who is affected:** residents of dense blocks on hot surfaces, old and new; heat hits older people, young children and outdoor workers hardest.
- **Why satellite data:** only satellites measure surface temperature and surface materials for every block of a city, repeatedly and for free, and the same data covers every MENA city. A few weather stations cannot show block-to-block differences; a hyperspectral sensor (EnMAP) adds detail about which surfaces drive heat.

## 3. Data used

| Product | Provider and access | Dates | Processing level | Used for | Licence / attribution |
| --- | --- | --- | --- | --- | --- |
| Landsat 8/9 Collection 2, band ST_B10 | USGS, via Microsoft Planetary Computer | Jun–Aug 2023–2025, 65 scenes, scene cloud cover < 10% | Level-2 surface temperature (atmospherically corrected) | Summer surface temperature | Public domain (USGS) |
| Sentinel-2 MSI, bands B02 B03 B04 B08 B11 B12 + SCL | ESA Copernicus, via Microsoft Planetary Computer | Jun–Aug 2023–2025, 70 granules from 58 acquisition days, cloud cover < 10% | Level-2A surface reflectance | Surface materials, vegetation, app fly-in image | Contains modified Copernicus Sentinel data [2023–2025] |
| EnMAP hyperspectral | DLR EOC Geoservice (free account) | 22 Apr 2025, 1 scene | Level-2A surface reflectance, 30 m | Testing whether hyperspectral explains heat better | Contains modified EnMAP data © DLR [2025]; raw data may not be redistributed and is **not** in this repository |
| OpenStreetMap buildings | OpenStreetMap, via osmnx | extract of 23 Sep 2026, committed in [`data/osm/`](data/osm) (15,129 buildings) so results reproduce | Vector footprints, `height` / `building:levels` tags | Roofs vs ground, 3D buildings | © OpenStreetMap contributors, ODbL |
| Google Open Buildings 2.5D Temporal | Google, public tiles | annual, 2016–2023 | 4 m building presence and height rasters | Building heights, urban growth | CC BY 4.0 |
| WorldPop Global2 R2025A | WorldPop | 2024 | 100 m constrained population | Residents per block | CC BY 4.0 |
| NASA Blue Marble | NASA Earth Observatory | July 2004 | True-colour mosaic | App globe only | Public domain |

**Why EnMAP and not Satellite 813:** 813 hyperspectral imagery of a team's own study area is available only in the incubation phase (organizers' answer to our question, 1 Oct 2026), so the PoC uses EnMAP, the closest freely available hyperspectral data; 813 data for Cairo is our first incubation step.

No account or API key is needed except for EnMAP (optional, see [Installation](#5-installation)). Intervention effects, costs researched for later and all literature sources: [`docs/intervention_research.md`](docs/intervention_research.md); every parameter below is in [`analysis/config/aoi.yaml`](analysis/config/aoi.yaml) with its source.

## 4. Technical approach

In execution order (code in `analysis/src/coolcairo`, run by `analysis/run_pipeline.py` or notebooks 01–06):

1. **Areas and grid.** Model area: east Cairo (31.26–31.40° E, 30.00–30.12° N; Heliopolis, Nasr City, Abbassia), where the model learns. Display district: Nasr City (24 × 24 blocks). All data on one grid in UTM 36N (EPSG:32636); **90 m blocks** = 3 × 3 Landsat pixels = 9 × 9 Sentinel-2 pixels, matching the thermal band's resolution.
2. **Surface temperature (Landsat).** Every summer scene 2023–2025 with < 10% cloud; clouds removed per pixel with the QA_PIXEL band (fill, dilated cloud, cirrus, cloud, cloud shadow); value × 0.00341802 + 149.0 − 273.15 = °C; **median per pixel** across the 65 scenes.
3. **Surface materials (Sentinel-2).** Same window; per-pixel mask from the scene classification layer (no data, saturated, shadow, cloud, cirrus); median composite at 10 m. Rules: **NDVI > 0.30** → vegetation; brightness (mean of B02, B03, B04) **≤ 0.14** → dark (asphalt, dark roofs); bright pixels with Bare Soil Index ((B11 + B04) − (B08 + B02)) / ((B11 + B04) + (B08 + B02)) **> 0.137** → sand (the cut-off that best separates roofs from open ground, 75% balanced accuracy); the rest → pale surfaces.
4. **Buildings.** OpenStreetMap footprints (the committed 23 Sep 2026 extract; `osm_refresh: true` in the config downloads live OSM instead) split each block into roof and ground, so dark and pale pixels become dark/pale roofs vs dark ground; sand counts only outside footprints. Heights: OSM `height` → `building:levels` × 3.2 m → Google Open Buildings 2.5D (median of at least 3 pixels in the footprint) → default 5 storeys.
5. **Block table.** Per block: share of area of each surface, building cover, mean height, mean NDVI, median surface temperature, and residents (WorldPop resampled by area, totals kept within 0.3%).
6. **Heat model.** Linear regression: surface temperature ~ vegetation + dark roof + dark ground + sand + building cover + mean height, on the **2,538 urban blocks** (≥ 10% building cover). Tested with **spatial cross-validation**: 5 folds of whole 1 km tiles, because neighbouring blocks share heat. Linear on purpose: the app computes every effect as a weighted sum.
7. **Heat risk.** Heat exposure = residents × max(0, block temperature − **45.7 °C**), the median of the urban blocks (person·°C).
8. **Cooling measures** (°C per unit of block area converted):
   - **Cool roofs:** −8 °C per unit of albedo (Wang, Huang & Li 2020, *GRL* 47) × albedo 0.12 → 0.70 for dark roofs (**−4.64**) and 0.25 → 0.70 for pale roofs (**−3.60**). Published values, because the fitted dark-roof coefficient is implausible (shadow read as dark roof).
   - **In practice:** reflective coatings are proven and entering mass production. A radiative-cooling coating kept roofs about 24 °C cooler at the surface than concrete in a 2.5-year Hong Kong field trial and cut air-conditioning energy by 10% ([PolyU 2024](https://www.polyu.edu.hk/rio/news/2024/20240924---polyu-researchers-unveil-novel-carbon-dots-driven-green-radiative-cooling-coating/)); a similar paint entered mass production in China in 2026, reported as up to 25 °C cooler on surfaces ([SCMP 2026](https://www.scmp.com/news/china/science/article/3367812/chinese-paint-cuts-wall-temperature-25-degrees-celsius-summer-test-report), not yet independently verified). These are peak temperatures of the coated surface itself, not comparable with our block-average summer medians; such coatings are stronger than the white paint we model, so our cool-roof effects are conservative.
   - **Cool pavements:** same physics, asphalt albedo 0.12 → 0.40 (**−2.24**).
   - **Street trees:** our model, vegetation minus dark ground (**−3.28**), on up to 25% of dark ground.
   - **Pocket parks:** our model, vegetation minus sand (**−6.51**), on up to 50% of sand.
9. **Urban growth.** Google Open Buildings presence ≥ 0.5 per 4 m pixel = built; a block is built-up at ≥ 10% cover; classes 2016 → 2023: newly built, denser (+5 points), built before, still open.
10. **Hyperspectral test.** EnMAP block spectra vs Sentinel-2 bands vs EnMAP reduced to Sentinel-2's bands, same blocks and same spatial cross-validation (notebook 05).
11. **Export and app.** Nasr City's 576 blocks, 1,901 buildings, the model coefficients and data sources go to `export/district.json`; the Unity 6 app reads it and evaluates the same model live.

## 5. Installation

Requires **Python 3.12**. With [uv](https://docs.astral.sh/uv/) (recommended; installs Python 3.12 and the exact locked versions):

```bash
git clone https://github.com/mohamedEsmat/CoolCairo.git
cd CoolCairo/analysis
uv sync
```

With pip (versions pinned in `requirements.txt`):

```bash
git clone https://github.com/mohamedEsmat/CoolCairo.git
cd CoolCairo
python3.12 -m venv .venv
.venv\Scripts\activate                 # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps -e ./analysis
```

With conda or mamba: `conda env create -f environment.yml`, then `conda activate coolcairo` (same pinned versions). In Google Colab: click the badge at the top; the notebook's first cell installs everything.

No environment variables or API keys are needed. **EnMAP is optional:** it needs a free DLR EOC Geoservice account subscribed to the "EnMAP Access Service"; download the files for the scene in `analysis/config/enmap_scenes.txt` into `analysis/data/enmap/`. Without them the pipeline, notebooks 01–04 and 06 and the example run, and skip the hyperspectral results; only notebook 05 and the report script need them.

**The app** (Windows): to build it, open `unity/` in Unity 6000.0.83f1, run **CoolCairo → Setup project and scene**, then **CoolCairo → Build Windows desktop app** (output `unity/Builds/Windows/CoolCairo.exe`).

## 6. How to run

**Start here: the quick example** (nothing to edit, offline, about **10 seconds**):

```bash
cd analysis
uv run jupyter lab notebooks/00_quick_example.ipynb
```

Run all cells (Kernel › Restart Kernel and Run All Cells). It reads `data/sample_input/blocks_east_cairo.csv`, fits the heat model, computes the cooling effects, Nasr City's heat risk and urban growth, and writes [`results/`](results/summary.md): `model_fit.json`, `heat_risk_nasr_city.json`, two CSV tables, three maps and `summary.md`; the maps also appear in the notebook. The same steps as a script: `uv run python run_example.py`. Without uv, run the same commands without `uv run` inside the activated environment.

**The full pipeline from satellite archives** (notebooks 01–06 in order, or headless):

```bash
uv run python run_pipeline.py          # stream data, fit model, write export/district.json
uv run pytest                          # unit tests (23), including the example's numbers
uv run python report/build_report.py   # methodology report PDF in docs/ (needs the EnMAP files)
```

The first run streams about 1 GB from the public archives into `analysis/data/` (a cache, git-ignored); later runs read the cache. **Tested on a second, clean Windows machine** (8 Oct 2026, fresh clone, `uv sync`, each notebook run from a restarted kernel): all six ran without errors in about **29 minutes** in total (01: 18 min, mostly downloads; 06: 7.5 min; 04: 2.3 min; 02, 03 and 05 under a minute). No GPU needed.

**The app:** run `CoolCairo.exe`, choose Nasr City on the globe, switch views on the left, paint with the tools at the bottom (left-drag paint, right-drag erase, Alt-drag or middle-drag orbit, scroll zoom), and read the result cards at the top right. `CoolCairo.exe -selftest -logFile selftest.log` runs 51 automated checks and exits with code 0 when all pass; `-screenshots <folder>` takes the screenshots used in the report; `-autotest` drives the whole flow in a loop.

**Where things are:**

| Path | What |
| --- | --- |
| `analysis/notebooks` | 00 quick example (offline, with outputs) · 01 data · 02 classification and M2 spot check · 03 model and heat risk · 04 export · 05 hyperspectral value · 06 urban growth |
| `analysis/src/coolcairo` | Pipeline modules; notebooks are thin drivers |
| `analysis/config/aoi.yaml` | Areas, dates, thresholds and every literature value, with sources |
| `data/sample_input` | Example input; `analysis/make_sample.py` recreates it |
| `data/osm` | The OpenStreetMap building extract behind the published results (ODbL) |
| `results` | Example output, written by notebook 00 / `analysis/run_example.py` |
| `export/district.json` | Handoff from the analysis to the app |
| `unity/Assets/CoolCairo` | The app: globe intro, 3D district, cooling tools, UI |
| `docs` | Slides and methodology report (PDF), research notes, M2 spot-check sheet, EnMAP licence |

## 7. Example input and output

**Input:** [`data/sample_input/`](data/sample_input/README.md), real data clipped to our area: `blocks_east_cairo.csv` (every 90 m block of the east-Cairo model area: surface shares, building height, summer surface temperature, residents, building cover 2016/2023; 2.7 MB), plus Landsat surface temperature, a 6-band Sentinel-2 composite and building footprints for Nasr City (`nasr_city/`). No EnMAP data (licence).

**Output:** [`results/`](results/summary.md), written by notebook 00. The numbers match the report and the app; `uv run pytest` checks that.

| Result (from the example data) | Value |
| --- | --- |
| Heat model, spatial cross-validated R² | 0.25 (±1.2 °C, 2,538 blocks) |
| Nasr City heat exposure today | 6,460 person·°C (95,141 residents) |
| One measure in every block | cool roofs −41%, street trees −24%, cool pavements −52%, pocket parks −60% |
| Cool roofs + pocket parks on the riskiest third of blocks | −74% (6,460 → 1,686 person·°C, 22,588 residents in cooled blocks) |
| Urban growth 2016–2023 | +5.7% building footprint, 988 newly built blocks at 46.9 °C vs 46.0 °C established |

![Nasr City heat exposure per 90 m block, today](results/nasr_city_heat_exposure.png)

## 8. Results and limitations

**What we measured:**

- **Heat model:** spatial cross-validated R² **0.25**, mean error ±1.2 °C (2,538 urban blocks, 1 km tiles held out). Vegetation cools (−3.2 °C for a fully green block vs pale ground), sand heats (+3.4 °C).
- **Hyperspectral adds value for heat:** with our features, EnMAP block spectra explain block surface temperature at R² **0.58** vs **0.40** with Sentinel-2. Spectra alone: **0.53** for EnMAP's full spectrum vs **0.33** for the same scene reduced to Sentinel-2's bands, so the gain comes from spectral detail, not the sensor or date. The advantage holds with 2–3 km held-out tiles. For separating buildings from desert, EnMAP adds nothing beyond the Sentinel-2 summer composite. See notebook 05.
- **Heat risk in Nasr City:** 95,141 residents, 6,460 person·°C today. One measure in every block (within its limits): −41% (cool roofs), −24% (street trees), −52% (cool pavements), −60% (pocket parks). Cool roofs and pocket parks on only the riskiest third of blocks: **−74%** (6,460 → 1,686 person·°C, 22,588 residents in cooled blocks).
- **Urban growth 2016–2023:** building footprint in east Cairo +5.7% (37.1 → 39.2 km²); 988 blocks turned from open land to built-up and now house about 61,000 residents. They average 46.9 °C, about 1 °C hotter than established neighbourhoods (46.0 °C) and cooler than open desert (48.6 °C). See notebook 06.

**How we validated it:**

- **Heat model:** spatial cross-validation (above), so the score reflects areas the model never saw.
- **Materials:** a spot check of 20 random points (fixed seed) against Google Maps satellite imagery (milestone M2) agrees at 16 of 18 judgeable points (89%); the misses are dusty asphalt and a dusty roof read as sand. The check was not blind (done by an AI assistant that could see the labels); details per point in [`docs/m2_spot_check.xlsx`](docs/m2_spot_check.xlsx).
- **Building heights:** Google Open Buildings 2.5D vs 165 OSM-tagged heights: bias −1.4 m, mean error 6.2 m, r = 0.60.
- **App:** 51 automated checks run inside the built app; the example's numbers are checked by unit tests against the report.

**Where it breaks:**

- **Surface, not air, temperature.** Satellites measure how hot surfaces get. Studies suggest city-wide cool roofs lower air temperature by about 0.1–0.33 °C per +0.1 roof albedo; the effect on air is smaller and spreads beyond the district.
- **Block level only (90 m).** Landsat's thermal band is 100 m, so no per-building temperatures are claimed.
- **Modest model fit** (R² 0.25). Fine for comparing measures, not for predicting one block exactly; cool roofs and cool pavements therefore use published values. The score also depends on which blocks are mapped: with live OpenStreetMap on 8 Oct 2026 (six more buildings, six more urban blocks) the same code gives R² 0.30 and 6,277 person·°C, which is why the published results use the committed 23 Sep extract.
- **Dusty roofs vs sand, shadows as dark roofs.** The single-index material rules confuse them (the spot-check misses; the implausible dark-roof coefficient).
- **OpenStreetMap gaps in Cairo.** Only 3.4% of east Cairo is mapped as roof, so the model learns from the 2,538 well-mapped blocks.
- **Heat risk is a screening indicator** (heat × residents, WorldPop is modelled). No vulnerability yet: age, housing, access to cooling.
- **One EnMAP scene** (April), so hyperspectral is a strong signal, not yet the main model.
- **Costs are not yet in the app;** researched ranges are in `docs/intervention_research.md`.

How we would overcome each one (effort and evidence) is on slide 13 of [the slides](docs/CoolCairo_Slides.pdf).

## 9. Team, licence and attribution

**Team 46, Egypt:** Liquaa Mahmoud (team lead), Mohamed Esmat (technical lead), Mahmoud Abu Zaid (data & hyperspectral analyst).

**Licence:** code under [MIT](LICENSE). The data keep their own licences and attributions (see [Data used](#3-data-used)); raw EnMAP data is not included.

**Attribution:** Landsat (USGS) · Contains modified Copernicus Sentinel data [2023–2025] · Contains modified EnMAP data © DLR [2025] · © OpenStreetMap contributors (ODbL; the extract in `data/osm/` is shared under the same licence) · Google Open Buildings 2.5D Temporal (CC BY 4.0) · WorldPop 2024 (CC BY 4.0) · NASA Blue Marble · data access via Microsoft Planetary Computer and DLR EOC Geoservice. Cool-roof and cool-pavement effects: Wang, Huang & Li (2020), *Geophysical Research Letters* 47, e2020GL087853, and the sources in `docs/intervention_research.md`. Built with Python (xarray, rioxarray, odc-stac, geopandas, osmnx, scikit-learn) and Unity 6.
