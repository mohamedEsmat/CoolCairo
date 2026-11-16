# Spectral library (hyperspectral upgrade, step 1)

Reference spectra for east Cairo's materials, taken from the EnMAP scene of 22 April 2025 (30 m).
The next steps compare every EnMAP pixel with them: Spectral Angle Mapper classification
and linear unmixing into material fractions for the heat model.

**Status (16 Nov 2026): candidates proposed, waiting for confirmation by eye.**

## How the candidates were chosen

[`make_library_candidates.py`](../../analysis/make_library_candidates.py) and
[`library.py`](../../analysis/src/coolcairo/library.py) propose 12 pixels per material, using data
that is independent of the EnMAP spectrum wherever possible:

| Material | Rule (30 m pixel) | Pool |
|---|---|---|
| Sand / bare ground | Whole 3 × 3 patch > 300 m from any building, not vegetated, not on a road or car park | 52,751 |
| Pale roof | Every 10 m cell inside an OSM footprint, not vegetated, modelled shadow ≤ 10 %, brightest third of such roofs | 342 |
| Dusty roof | Same rule, the other two thirds; ranked by homogeneity plus angle to the sand mean, so sand-like roofs come first | 693 |
| Asphalt / paved | ≥ 80 % on a major road (buffered by half its width), apron or car park; no roof; darkest third | 1,578 |
| Vegetation | Whole 3 × 3 patch with NDVI ≥ 0.45 | 239 |

Within each pool, the most homogeneous pixels come first, measured by the spectral angle to the
mean of their 8 neighbours. Picks are at least 300 m apart.

### Why there is no "dark roof" class

The first list had a "dark roof" class (darkest third of pure roofs). An AI look at the 12 picks in
satellite imagery accepted none of them. Most were mixed (rooftops with courtyards, clutter, trees,
streets or a tower's shadow), two were roads or car parks wrongly inside an OSM footprint, and the
two large clean roofs were tan and dusty, not dark. At 30 m, darkness from shade is handled by the
shade fraction in the unmixing. The class was therefore replaced by a **dusty roof** class: roofs
covered in dust or coloured like the ground, which is the confusion the PoC map actually makes
(dusty roof vs sand).

## Confirm the candidates

1. Open `candidates.kml` in Google Earth. Each candidate is its exact 30 m square, numbered.
   Alternatively, use the links in `candidates.xlsx`.
2. In `candidates.xlsx`, answer for each row whether the **whole** square is the proposed
   material.
3. Columns I–J hold an **AI pre-check** of each square in satellite imagery. It is a hint, not a
   confirmation: it accepted 43 of 60 (sand 9, pale roof 8, dusty roof 6, asphalt 9,
   vegetation 11). Re-running the script keeps every answer already in the sheet.
4. Only rows answered "Yes, all of it" or "Mostly" enter the library (`library.read_sheet`, then
   `library.library_from_sheet`).

## What the first look shows

These results come from the candidates before anyone has checked them. They are provisional.

- **No pure shadow pixel exists.** The sun was 70.4° high, so a building's shadow is about
  0.36 × its height. Modelled from Open Buildings heights, the most shadowed 30 m pixel is
  79 % in shadow, only 70 of 205,650 pixels are more than half in shadow, and the mean is 2 %
  (`shadow_check.json`). Shadow is therefore not a library class. The unmixing uses a near-zero
  "shade" spectrum for it.
- **Roofs, asphalt and sand have almost the same spectral shape.** The angles between them are
  2–4° (`provisional_angles.csv`). Vegetation is 21–23° from everything else. Cairo's dusty
  surfaces differ mostly in brightness, so the Spectral Angle Mapper on its own (which ignores
  brightness) cannot separate them. The hardest pairs are dusty roof vs sand (1.2°) and dusty roof
  vs asphalt (1.3°). The next step tests brightness and the narrow absorption
  features (≈ 1730, 2310 and 2340 nm, dotted lines in `provisional_spectra.png`).

## First material maps (provisional)

[`make_sam_map.py`](../../analysis/make_sam_map.py) gives each pixel the nearest library class by
three distances: the spectral angle alone (SAM), + log brightness, and + continuum-removed depths
at 1730, 2310 and 2340 nm. Each term is divided by its spread within the library classes. Pixels
beyond the 95th percentile of the library's own leave-one-out distance stay unclassified.
`sam_provisional/` uses the **AI pre-check, not a confirmed library** (rerun without
`--provisional` after confirmation). Scores (`sam_provisional/comparison.csv`):

| Check | Angle | + brightness | + brightness + depths |
|---|---|---|---|
| Leave-one-out, 43 library pixels | 74 % | 88 % | 88 % |
| Pure OSM roof pixels (1,172) → a roof class | 59 % | 63 % | 68 % |
| Open ground (8,964) → sand | 64 % | 84 % | 81 % |
| Roofs with > 25 % modelled shadow (23) → a roof class | 52 % | 61 % | 83 % |
| … of which → asphalt | 9 % | 22 % | 9 % |
| Unclassified (whole scene) | 17 % | 9 % | 7 % |

- **Brightness is what the angle was missing.** It separates sand from dusty roofs and asphalt
  (open ground → sand 64 % → 84 %).
- **Brightness alone lets shade pass for asphalt** (shaded roofs → asphalt 9 % → 22 %), as the
  course warned; the absorption depths bring it back to 9 % (only 23 such pixels, so a weak test).
- **Remaining confusion:** dusty roof vs sand (13 % of open ground is called dusty roof) and
  roofs vs asphalt (13 % of OSM roofs). Unmixing (next step) can express these as fractions.
- **"Open ground" must also be far from Open Buildings.** OSM misses many buildings in east
  Cairo: 57 % of the pixels > 300 m from any OSM building have an Open Buildings building within
  30 m. With OSM alone, open ground → sand was only 28 %.

## Unmixing and the heat model (provisional)

[`make_unmixing.py`](../../analysis/make_unmixing.py) solves every pixel as a mix of the library
spectra plus a near-zero shade spectrum (fully constrained least squares: fractions ≥ 0, sum 1).
`unmixing_provisional/` uses the **AI pre-check library, not a confirmed one**.

**Heat model** (the PoC's linear model, 2,538 blocks, same spatial folds; the Sentinel-2 material
shares replaced by EnMAP fractions averaged per 90 m block; roof cover and height kept):

| Features | R², 1 km tiles | 2 km | 3 km | MAE (1 km) |
|---|---|---|---|---|
| PoC: Sentinel-2 shares + buildings | 0.250 | 0.342 | 0.259 | 1.20 °C |
| EnMAP fractions + buildings | **0.401** | 0.446 | 0.387 | **1.08 °C** |
| EnMAP fractions only | 0.343 | 0.355 | 0.336 | 1.12 °C |

**Pixel checks** (labels independent of the library):

- Shade fraction rises where the building-height model predicts shadow: 0.07 (< 5 % modelled
  shadow), 0.14 (5–25 %), 0.20 (> 25 %); Spearman 0.28.
- Pure OSM roof pixels: 56 % roof on average (pale 47 %, dusty 10 %), plus asphalt 16 %,
  shade 12 %, vegetation 9 %. 60 % of them are more than half roof.
- Open ground: 71 % sand, but 24 % "pale roof". The residual is highest in the bright desert and
  construction areas of the south-east: 9 sand pixels do not cover Cairo's desert surfaces.

**Coefficients (°C per unit fraction, instead of sand):** vegetation −8.9, shade −9.4, dusty roof
−3.1, asphalt −2.6, **pale roof +0.1**. Splitting fractions by OSM footprint gives pale roof on
footprints +4.2 and dusty roof on footprints −4.7. So pale roofs are *not* cooler than dusty ones,
and the cool-roof effect cannot yet come from our own data. Both roof classes contain warehouses
and factories, so "pale = bare metal" does not explain it on its own. Open; to revisit with the
confirmed library, more varied sand spectra and a metal-roof class.

*Contains modified EnMAP data © DLR [2025] · © OpenStreetMap contributors (ODbL) · Google Open
Buildings 2.5D Temporal (CC BY 4.0).*
