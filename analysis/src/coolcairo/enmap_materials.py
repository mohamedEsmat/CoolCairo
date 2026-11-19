"""EnMAP material fractions and the EnMAP heat model, for the app.

The confirmed spectral library (docs/spectral_library, checked by eye on 19 Nov 2026) unmixes
each 30 m EnMAP pixel into sand, pale roof, dusty roof, asphalt, vegetation and shade (FCLS);
the fractions are averaged over each 90 m display block. The heat model is the one
make_unmixing.py fitted and tested (docs/spectral_library/unmixing: same 2,538 blocks and
spatial folds as the PoC), read from its published coefficients rather than refitted here, so
the app and the documented result are the same model.

How the four measures use the fractions (all deltas are surface temperature per unit block area):
  cool roofs      footprint roofs coated to albedo 0.70: dTs/d(albedo) x (0.70 - albedo), split
                  into pale and dusty roof by EnMAP, each with its albedo MEASURED from its
                  library spectrum (treatable_areas: footprints say where roofs are)
  cool pavements  asphalt on the ground coated to albedo 0.40, asphalt's measured albedo
  street trees    asphalt -> vegetation, from the fitted model (vegetation minus asphalt)
  pocket parks    sand -> vegetation, from the fitted model (sand is the reference: vegetation)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from coolcairo import enmap
from coolcairo import library as lib
from coolcairo import separability as sep
from coolcairo.config import Config

SHADE = "Shade"
# Library class -> block column in the analysis / array name in district.json.
COLUMNS = {
    lib.SAND: ("enmap_sand", "enmapSand"),
    lib.PALE_ROOF: ("enmap_pale_roof", "enmapPaleRoof"),
    lib.DUSTY_ROOF: ("enmap_dusty_roof", "enmapDustyRoof"),
    lib.ASPHALT: ("enmap_asphalt", "enmapAsphalt"),
    lib.VEGETATION: ("enmap_vegetation", "enmapVegetation"),
    SHADE: ("enmap_shade", "enmapShade"),
}
SUN_K = 5778.0  # Blackbody temperature of the sun: shape of the solar spectrum for weighting.


def broadband_albedo(spectrum: pd.Series) -> float:
    """Solar-weighted mean reflectance over the library's wavelengths (nm).

    An approximation of broadband albedo: the sun's spectrum is taken as a 5778 K blackbody
    (no atmosphere), and the water-vapour windows dropped by preprocessing are left out.
    """
    wl = np.asarray(spectrum.index, dtype=float)
    lam = wl * 1e-9
    h, c, k = 6.626e-34, 2.998e8, 1.381e-23
    weight = 1.0 / (lam**5 * np.expm1(h * c / (lam * k * SUN_K))) * np.gradient(wl)
    return float((spectrum.to_numpy() * weight).sum() / weight.sum())


def confirmed_library(refl: xr.DataArray, library_dir: Path) -> tuple[pd.DataFrame, int]:
    """Library spectra (wavelength x class, plus shade) from the pixels a person confirmed,
    and how many pixels that is."""
    picks = pd.read_csv(library_dir / "candidates.csv", index_col="id")
    checked = lib.read_sheet(library_dir / "candidates.xlsx", picks, column=lib.PERSON_COLUMN)
    if not checked.accepted.any():
        raise ValueError("No confirmed library pixels: column F of candidates.xlsx is empty.")
    return lib.library_from_sheet(refl, checked), int(checked.accepted.sum())


def block_fractions(refl: xr.DataArray, endmembers: pd.DataFrame, blocks: pd.DataFrame,
                    block_size: float) -> pd.DataFrame:
    """Mean FCLS fraction per block (columns from COLUMNS), NaN where the scene has no data.

    Only the pixels under the given blocks are unmixed. Blocks are 3 x 3 EnMAP pixels.
    """
    half = block_size / 2
    sub = refl.sel(x=slice(blocks.x.min() - half, blocks.x.max() + half),
                   y=slice(blocks.y.max() + half, blocks.y.min() - half))
    frac, _ = lib.fcls(sub, endmembers)
    factor = int(round(block_size / abs(float(refl.x[1] - refl.x[0]))))
    values = sep.block_spectra(frac.rename(endmember="feature"), factor, blocks)
    names = list(frac.endmember.values)
    return pd.DataFrame(values, columns=[COLUMNS[n][0] for n in names], index=blocks.index)


def heat_model(unmixing_dir: Path) -> dict:
    """The tested EnMAP heat model (make_unmixing.py output): coefficients vs sand, scores."""
    coef = pd.read_csv(unmixing_dir / "coefficients.csv", index_col=0).iloc[:, 0]
    scores = pd.read_csv(unmixing_dir / "heat_model.csv")
    at_1km = scores[scores.tile_m == 1000].set_index("features")
    poc = at_1km.loc["PoC (Sentinel-2 shares + buildings)"]
    ours = at_1km.loc["EnMAP fractions + buildings"]
    return {
        "coefficients": coef.to_dict(),
        "r2_sentinel2": float(poc.r2_spatial_cv), "mae_sentinel2": float(poc.mae_c),
        "r2_enmap": float(ours.r2_spatial_cv), "mae_enmap": float(ours.mae_c),
    }


def app_materials(cfg: Config, refl: xr.DataArray, display: pd.DataFrame,
                  library_dir: Path) -> tuple[pd.DataFrame, dict]:
    """EnMAP block fractions for the display blocks and the `enmap` object of district.json."""
    endmembers, n_pixels = confirmed_library(refl, library_dir)
    fractions = block_fractions(refl, endmembers, display, cfg.block_size)
    model = heat_model(library_dir / "unmixing")
    coef = model["coefficients"]
    albedo = {name: broadband_albedo(endmembers[name]) for name in endmembers.columns}
    cr, cp = cfg["cool_roof"], cfg["cool_pavement"]
    per_albedo = cr["dts_per_albedo"]
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    info = {
        "available": 1,
        "sceneId": scene,
        "acquired": enmap.acquisition_date(scene),
        "libraryPixels": n_pixels,
        "library": f"{n_pixels} library pixels, each confirmed by eye (19 Nov 2026)",
        # Same blocks and held-out 1 km tiles as the PoC model.
        "r2Sentinel2": model["r2_sentinel2"], "maeSentinel2": model["mae_sentinel2"],
        "r2Enmap": model["r2_enmap"], "maeEnmap": model["mae_enmap"],
        # Broadband albedo measured from each library spectrum.
        "albedoPaleRoof": albedo[lib.PALE_ROOF],
        "albedoDustyRoof": albedo[lib.DUSTY_ROOF],
        "albedoAsphalt": albedo[lib.ASPHALT],
        "albedoSand": albedo[lib.SAND],
        # Surface temperature change per unit block area treated.
        "coolRoofPaleDeltaC": per_albedo * (cr["albedo_after"] - albedo[lib.PALE_ROOF]),
        "coolRoofDustyDeltaC": per_albedo * (cr["albedo_after"] - albedo[lib.DUSTY_ROOF]),
        "coolPavementDeltaC": per_albedo * (cp["albedo_after"] - albedo[lib.ASPHALT]),
        "treesDeltaC": coef[lib.VEGETATION] - coef[lib.ASPHALT],
        "pocketParkDeltaC": coef[lib.VEGETATION],  # Sand is the model's reference.
        # Fitted coefficients vs sand (deg C per unit block fraction), shown in the app.
        "coefPaleRoof": coef[lib.PALE_ROOF],
        "coefDustyRoof": coef[lib.DUSTY_ROOF],
        "coefAsphalt": coef[lib.ASPHALT],
        "coefVegetation": coef[lib.VEGETATION],
        "coefShade": coef[SHADE],
        "attribution": enmap.attribution(scene),
    }
    return fractions, info


def treatable_areas(blocks: pd.DataFrame) -> pd.DataFrame:
    """Block-area shares the measures can treat, with the EnMAP model.

    Footprints say WHERE the roofs are, EnMAP says WHAT they are made of: spectrally, pale
    paving and dusty ground look like roofs (EnMAP's roof fractions follow the footprints only
    loosely), so cool roofs coat the footprint area, split into pale and dusty roof in EnMAP's
    proportions (half and half where EnMAP sees neither). Asphalt and sand are capped at the
    ground (non-footprint) share of the block.
    """
    pale, dusty = blocks.enmap_pale_roof, blocks.enmap_dusty_roof
    both = pale + dusty
    pale_share = (pale / both.where(both > 0)).fillna(0.5)
    ground = (1 - blocks.roof_frac).clip(lower=0)
    return pd.DataFrame({
        "roof_pale": blocks.roof_frac * pale_share,
        "roof_dusty": blocks.roof_frac * (1 - pale_share),
        "asphalt": np.minimum(blocks.enmap_asphalt, ground),
        "sand": np.minimum(blocks.enmap_sand, ground),
    }, index=blocks.index)


def measure_deltas(cfg: Config, blocks: pd.DataFrame, info: dict) -> pd.DataFrame:
    """Delta LST per block for each measure at full adoption, on its own, with the EnMAP model.

    The app's InterventionModel (EnMAP source) does the same arithmetic; keep the two in sync.
    """
    caps = cfg["interventions"]
    area = treatable_areas(blocks)
    return pd.DataFrame({
        "cool_roofs": info["coolRoofDustyDeltaC"] * area.roof_dusty
        + info["coolRoofPaleDeltaC"] * area.roof_pale,
        "street_trees": info["treesDeltaC"] * caps["tree_max_share_of_dark_ground"] * area.asphalt,
        "cool_pavements": info["coolPavementDeltaC"] * area.asphalt,
        "pocket_parks": info["pocketParkDeltaC"] * caps["park_max_share_of_sand"] * area.sand,
    }, index=blocks.index)


def plan_figures(cfg: Config, display: pd.DataFrame, info: dict, reference_c: float) -> dict:
    """The app's headline figures with the EnMAP model: one measure in every block, and the
    targeted plan (cool roofs + pocket parks on the riskiest third of blocks, ranked by today's
    heat exposure, ties by temperature, as interventions.targeted_plan_delta)."""
    from coolcairo.population import heat_exposure

    d = display.dropna(subset=["lst_c"])
    people = d.population.clip(lower=0)
    base = heat_exposure(d.lst_c, people, reference_c)
    deltas = measure_deltas(cfg, d, info)
    everywhere = {name: float(100 * (heat_exposure(d.lst_c + deltas[name], people, reference_c).sum()
                                     - base.sum()) / base.sum()) for name in deltas}
    ranked = pd.DataFrame({"exposure": base, "lst": d.lst_c}).sort_values(
        ["exposure", "lst"], ascending=False, kind="stable")
    plan = pd.Series(0.0, index=d.index)
    chosen = ranked.index[: len(d) // 3]
    plan[chosen] = (deltas.cool_roofs + deltas.pocket_parks)[chosen]
    after = heat_exposure(d.lst_c + plan, people, reference_c)
    return {
        "exposureBefore": float(base.sum()),
        "pctCoolRoofs": everywhere["cool_roofs"],
        "pctStreetTrees": everywhere["street_trees"],
        "pctCoolPavements": everywhere["cool_pavements"],
        "pctPocketParks": everywhere["pocket_parks"],
        "targetedBlocks": len(chosen),
        "targetedExposureAfter": float(after.sum()),
        "targetedPct": float(100 * (after.sum() - base.sum()) / base.sum()),
        "targetedResidentsCooled": float(people[plan < -0.01].sum()),
    }
