# CoolCairo

Urban heat decision-support tool for one Cairo district. Built for the Arab Youth Space Hackathon 2026 (Challenge 813), Theme 5 — Urban Expansion, Land Use Change & Heat Risk, Hyperspectral Data Track.

**Hard deadline: proof of concept due 11 October 2026, 23:59.**

## What we are building

A browser-based 3D tool where a city planner sees a real Cairo district rendered from satellite data, colour-coded by what each surface is made of, with a land-surface-temperature overlay. They apply interventions — reflective roof coating, street trees, shade structures — and the predicted temperature drop updates live.

Output for the judges: a deployed WebGL link, reproducible notebooks, a methodology report, and a pitch video.

## Problem statement (official template, chosen 30 Sep)

> We want to **map** summer heat risk, meaning land surface temperature, the surface materials driving it, and the population exposed to it, in **Nasr City, Cairo** during **June–August 2023–2025** so that **city planners** can decide **which blocks to prioritise for cool roofs and street trees**.

Official challenge text (Cockpit): *"Quantify urban growth, map land-use transitions, and assess urban heat island intensity and heat risk for cities across the Arab world. Fuse 813 imagery with SAR and thermal data to track impervious surface growth, characterize land-use change, and build heat risk maps to support climate-resilient urban planning."*

## Architecture

```
EnMAP hyperspectral ──┐
Landsat thermal ──────┼──> regression model ──┐
Sentinel-2 NDVI ──────┘                       ├──> Unity WebGL app
OpenStreetMap footprints ─────────────────────┘
```

| Path | Stack | Purpose |
| --- | --- | --- |
| `/analysis` | Python 3.12, uv, Jupyter | Stages 1–4: data acquisition, classification, LST, model fitting |
| `/unity` | Unity 6000.0.83f1, URP, C#, WebGL | Stages 5–6: 3D district, intervention tools, live recalculation |
| `/export` | JSON | Handoff artifact from analysis to Unity (`district.json`) |

Headless run: `cd analysis && uv run python run_pipeline.py`. Unity: menu **CoolCairo → Setup project and scene**.

## Decisions (23 Sep 2026)

- **District: Nasr City**, ~2 × 2 km display area. The regression is fitted on a larger east-Cairo **model area** (Heliopolis, Nasr City, Abbassia) for thousands of training blocks; the display district is cut from the same grid. Both bboxes live in `analysis/config/aoi.yaml`.
- **CRS: EPSG:32636** (UTM 36N), declared only in `aoi.yaml`.
- **Blocks: 90 m grid cells** (3 × 3 Landsat/EnMAP pixels, 9 × 9 Sentinel-2 pixels), snapped to 90 m multiples so all sources aggregate cleanly. Grid, not street blocks: statistically honest and matches thermal resolution.
- **LST: Landsat C2 Level-2 ST_B10 product** (USGS-corrected), not self-derived from radiance. **Median of all clear summer (Jun–Aug) scenes 2023–2025**, not a single date — lower noise, better R².
- **Material classes are interim until EnMAP arrives**: vegetation / dark / bright / bare soil from Sentinel-2 rules. Crossed with OSM footprints → dark roof vs dark ground fractions; soil counts only outside footprints.
- **Bare soil** = bright pixel with Bare Soil Index > 0.137 (best roof-vs-open-ground split, 75% balanced accuracy; derived in notebook 02). Brightness alone cannot separate pale roofs from desert (identical medians), and open desert is ~2 °C hotter than the built-up area by day.
- **Model: linear regression** on `veg_frac, dark_roof_frac, dark_ground_frac, soil_frac, roof_frac, mean_height_m`; bright paved ground is the reference category.
- **Cool roof uses literature values** (`cool_roof.method: literature` in `aoi.yaml`): −8 K roof surface temperature per unit albedo (Wang, Huang & Li 2020, GRL 47, e2020GL087853, top of the JJA daily-mean range) × albedo 0.12 → 0.70 = **−4.64 °C per unit block area of dark roof coated**. Conservative for a 10:30 overpass. **Pale roofs are coatable too**: weathered gray concrete albedo 0.25 (ACPA R&T Update 3.05, Table 1: 0.20–0.30) → 0.70 = **−3.60 °C per unit area**. The cool-roof tool coats all roofs in a block; full adoption averages −1.0 °C per block. Reason: with soil separated, spatial-CV R² = 0.15 but the fitted dark-roof coefficient is still negative (dark roofs look cooler), suspected building shadow in Sentinel-2 "dark" roof pixels. Switch to `regression` if EnMAP fixes the sign. Trees remain data-derived. **R² reported with spatial CV** (1 km tiles, GroupKFold). Linear so Unity computes ΔT as a weighted sum.
- **Cool roof** = moving block area from dark roof to bright roof → ΔT = −coef(dark_roof) × share. Data-derived; literature values used as a sanity check only. **Trees** = dark ground → vegetation, capped at 25% of dark ground. **Shade structures are cut** (not in the model).
- **UI language: "surface temperature" / "land surface temperature"** everywhere, never "air temperature".
- **Building heights**: OSM `height` → `building:levels` × 3.2 m → **Google Open Buildings 2.5D Temporal 2023** (median of 4 m pixels inside the footprint; public GCS tiles listed in `analysis/config/open_buildings_tiles.txt`, no account) → default 5 storeys. Coverage: 74% Open Buildings, 25% default, 1% OSM. Validated against 165 OSM-tagged buildings: bias −1.4 m, MAE 6.2 m, r = 0.60. Adding real heights raised spatial-CV R² from 0.15 to 0.25.
- **Heat risk (30 Sep)** = heat exposure = residents × max(0, LST − reference) in person·°C. Residents: WorldPop Global2 R2025A 100 m constrained 2024 (CC BY 4.0), resampled by area-weighted density (totals preserved within 0.3%) and summed per block. Reference: median LST of urban training blocks (45.7 °C). Display district: 95,141 residents, 6,460 person·°C; coating all roofs −41%, trees on 25% of dark ground −24%. Screening indicator only: no vulnerability factors. Unity "Heat risk" view mirrors `population.heat_exposure`.
- **Target: Windows desktop app** (changed 30 Sep; the hackathon names no required format). WebGL stays possible from the same project but is no longer the deliverable. Judges download an .exe, so the pitch video carries more weight.
- **App flow (30 Sep)**: `Intro.unity` (build index 0) → loading screen that queries the real archive (Planetary Computer STAC search by the exact scene IDs in `district.json` `sources`) and downloads a live preview crop of the model area per satellite, marking each ✓ Completed; offline falls back to prepared data and says so → MENA globe (NASA Blue Marble, public domain) with city markers, only Nasr City live, others "coming soon" → fly-in → `Main.unity` district. The loading screen never claims live analysis: the analysis is precomputed.
- **Validation imagery**: no PlanetScope access → use Google Earth / Esri World Imagery for the 20-roof spot check.

## Pipeline stages

1. **Material classification** — EnMAP (~224 bands, 30 m). Spectral classification of urban surfaces: asphalt, concrete, metal roofing, vegetation, bare soil. Use Level-2A products. Consider spectral unmixing for mixed pixels. *Interim: Sentinel-2 3-class.*
2. **Land surface temperature** — Landsat 8/9 ST_B10. Note: 100 m native resolution.
3. **Vegetation fraction** — Sentinel-2, NDVI per block.
4. **Model** — LST ~ f(material fractions, vegetation fraction, built density). Report spatial-CV R². Output a coefficient set the Unity app queries without solving at runtime.
5. **3D district** — OSM building footprints extruded into one combined mesh, recoloured per block.
6. **Interaction** — intervention brush on blocks, live ΔT readout.

## Non-negotiable constraints

- **Block-level, not per-building.** Landsat thermal is 100 m/pixel. Never claim per-roof temperature precision. Phrase outputs as "this block is 60% dark roofing".
- **WebGL target.** Load under 10 seconds, build under 50 MB, a few thousand buildings max. One combined building mesh, block-level textures, compressed build. No per-frame regression solving — precompute.
- **One district only.**
- **Everything in English** — code, comments, report, UI.
- **Reproducibility is scored.** Notebooks must run end to end from a clean checkout (`uv sync` then run).

## Data access

Stream via STAC from Microsoft Planetary Computer (anonymous, no key). Cached to `analysis/data/` (git-ignored).

| Source | Use | Status |
| --- | --- | --- |
| EnMAP (geoservice.dlr.de) | Material classification — primary | Pending hackathon/DLR access |
| Landsat C2 L2 (Planetary Computer) | Thermal | Working |
| Sentinel-2 L2A (Planetary Computer) | NDVI, interim classes | Working |
| OpenStreetMap (osmnx) | Footprints and heights | Working |
| Google Open Buildings 2.5D Temporal (public GCS) | Building heights | Working |
| WorldPop Global2 R2025A (data.worldpop.org) | Residents per block, heat exposure | Working |
| Google Earth / Esri imagery | Visual validation | No PlanetScope access |

## Milestones

| ID | Target | Done when |
| --- | --- | --- |
| M1 | 27 Sep | All three scenes reprojected to a common grid |
| M2 | 30 Sep | Classified raster validated against 20 spot-checked roofs |
| M3 | 2 Oct | Regression fitted, R² reported, ΔT per intervention type stated |
| M4 | 5 Oct | 3D district renders, heat overlay toggles |
| M5 | 8 Oct | Cool-roof and tree-planting interventions update numbers live |
| M6 | 9 Oct | Notebooks documented, methodology report written |
| M7 | 11 Oct | WebGL deployed, everything submitted |

## Scope discipline

**Core:** material classification, block-level heat map, **heat risk = surface temperature × population exposed (WorldPop)** (required by the problem statement), 3D district with overlay, one working intervention type.

**Should have:** built-up growth 2016–2023 from Open Buildings Temporal (answers the challenge's "urban growth / land-use change" with data already in use).

**Cut first:** cost estimation, multiple intervention types beyond cool roofs and trees, ranked top-20 list, SAR.

## Fallbacks

- EnMAP access not granted / classification not working by 1 Oct → keep the Sentinel-2 3-class map, spend recovered days on the tool.
- ΔT predictions implausible (`plausibility_warnings`) → use published coefficients from literature, cite them.
- WebGL too slow → shrink display district, reduce building count.

## Conventions

- Python: type hints, `ruff` clean, no notebook-only logic — importable modules in `analysis/src/coolcairo`, notebooks as thin drivers.
- `interventions.py` and `InterventionModel.cs` implement the same arithmetic; change both together.
- Coordinate system declared once in `aoi.yaml`, never hardcoded per-script.
- No secrets in the repo. API keys via environment variables.
- Every number that appears in the UI must be traceable to a cell in a notebook.

## Team

- **Esmat** — technical lead: pipeline, analysis, Unity build
- **Liquaa Mahmoud** — team lead: 3D production, visual design, business case, ArcGIS Pro support
- **Mahmoud** — role TBC

## Links

- Hackathon: https://spaceacademy-hackathons.space.gov.ae/
- Data resources: https://spaceacademy-hackathons.space.gov.ae/data
