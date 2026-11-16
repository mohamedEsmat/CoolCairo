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
| Dark roof | Same, darkest third | 342 |
| Asphalt / paved | ≥ 80 % on a major road (buffered by half its width), apron or car park; no roof; darkest third | 1,578 |
| Vegetation | Whole 3 × 3 patch with NDVI ≥ 0.45 | 239 |

Within each pool, the most homogeneous pixels come first, measured by the spectral angle to the
mean of their 8 neighbours. Picks are at least 300 m apart.

## Confirm the candidates

1. Open `candidates.kml` in Google Earth. Each candidate is its exact 30 m square, numbered.
   Alternatively, use the links in `candidates.xlsx`.
2. In `candidates.xlsx`, answer for each row whether the **whole** square is the proposed
   material.
3. Only rows answered "Yes, all of it" or "Mostly" enter the library (`library.read_sheet`, then
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
  brightness) cannot separate them. The next step tests brightness and the narrow absorption
  features (≈ 1730, 2310 and 2340 nm, dotted lines in `provisional_spectra.png`).

*Contains modified EnMAP data © DLR [2025] · © OpenStreetMap contributors (ODbL) · Google Open
Buildings 2.5D Temporal (CC BY 4.0).*
