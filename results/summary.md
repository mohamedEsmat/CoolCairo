# Example results

Written by `analysis/run_example.py` from `data/sample_input/blocks_east_cairo.csv` (offline). Surface temperature, not air temperature.

## Heat model (east-Cairo urban blocks)
- Spatial cross-validated R² **0.25**, mean error ±1.2 °C, 2,538 blocks, 5 folds of 1 km tiles. Coefficients: `model_fit.json`.

## Cooling per block at full adoption (mean °C, model area)
- cool roofs: -1.01 °C
- street trees: -0.09 °C
- cool pavements: -0.25 °C
- pocket parks: -0.74 °C

## Heat risk, Nasr City display district
- 95,141 residents, typical block 45.7 °C, heat exposure **6,460 person·°C** today.
- One measure in every block: cool roofs -41%, street trees -24%, cool pavements -52%, pocket parks -60%.
- Targeted plan (cool roofs + pocket parks on the riskiest third, 192 blocks): 6,460 → 1,686 person·°C (**-74%**), 22,588 residents cooled.

## Urban growth 2016–2023 (model area)
- Building footprint 37.1 → 39.2 km² (+5.7%); 988 newly built blocks, ~61,145 residents.
- Mean summer surface temperature: Built before 2016 46.0 °C, Built 2016-2023 46.9 °C, Still open 48.6 °C.

## Files
| File | What |
| --- | --- |
| `model_fit.json` | Heat model coefficients and validation |
| `cooling_effects_per_block_degC.csv` | Per-block cooling of each measure, statistics |
| `heat_risk_nasr_city.json` | Exposure today, per measure and for the targeted plan |
| `urban_growth_heat_by_class.csv` | Blocks and surface temperature by growth class |
| `nasr_city_*.png` | Maps: surface temperature, heat exposure, after the plan |
