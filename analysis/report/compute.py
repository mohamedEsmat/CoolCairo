"""Every number in the methodology report, computed from the pipeline (never typed by hand).

Used by build_report.py. Slow parts (block table, EnMAP tests) take a few minutes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.ndimage import distance_transform_edt
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold

from coolcairo import enmap, openbuildings, separability, validation
from coolcairo.buildings import footprint_mask
from coolcairo.classify import bare_soil_index, soil_threshold
from coolcairo.config import EXPORT_DIR, REPO_ROOT, geobox_for, load_config
from coolcairo.interventions import (
    cool_pavement_surface_delta,
    cool_roof_delta,
    cool_roof_surface_deltas,
    exposure_reduction_summary,
    full_adoption_deltas,
    heat_reference_c,
    pocket_park_delta,
)
from coolcairo.model import FEATURES, fit, spatial_groups, training_rows
from coolcairo.pipeline import (
    FINE_RESOLUTION,
    build_blocks,
    display_subset,
    load_enmap,
    load_lst,
    load_open_buildings_heights,
    load_osm_buildings,
    load_sentinel2,
)
from coolcairo.population import heat_exposure


@dataclass
class Results:
    cfg: object
    blocks: pd.DataFrame
    material: object
    buildings: object
    train: pd.DataFrame
    fit: object
    cv_pred: np.ndarray
    district: dict
    display: pd.DataFrame
    reference_c: float
    exposure: pd.Series
    adoption: pd.DataFrame
    targeted: dict
    deltas: dict
    heights: dict
    height_shares: dict
    soil: dict
    separability: pd.DataFrame
    fused: tuple
    heat_r2: pd.DataFrame
    m2: dict
    extra: dict = field(default_factory=dict)


def cv_predictions(train: pd.DataFrame, tile: int, folds: int) -> np.ndarray:
    """Out-of-fold predictions with the same spatial folds as model.fit."""
    x, y = train[FEATURES].to_numpy(), train.lst_c.to_numpy()
    pred = np.empty_like(y)
    for tr, te in GroupKFold(n_splits=folds).split(x, y, spatial_groups(train, tile)):
        pred[te] = LinearRegression().fit(x[tr], y[tr]).predict(x[te])
    return pred


def targeted_plan(cfg: object, result: object, display: pd.DataFrame, ref: float) -> dict:
    """Same plan as the app screenshot: cool roofs + pocket parks on the riskiest third of
    valid blocks (ranked by baseline heat exposure)."""
    d = display.dropna(subset=["lst_c"]).copy()
    base = heat_exposure(d.lst_c, d.population.clip(lower=0), ref)
    chosen = base.sort_values(ascending=False).index[: len(d) // 3]
    delta = pd.Series(0.0, index=d.index)
    roofs = cool_roof_delta(cool_roof_surface_deltas(cfg, result), d.dark_roof_frac, d.pale_roof_frac)
    parks = pocket_park_delta(result, cfg["interventions"]["park_max_share_of_sand"] * d.soil_frac)
    delta[chosen] = (roofs + parks)[chosen]
    after = heat_exposure(d.lst_c + delta, d.population.clip(lower=0), ref)
    return {
        "blocks": len(chosen),
        "share_blocks": len(chosen) / len(d),
        "exposure_before": float(base.sum()),
        "exposure_after": float(after.sum()),
        "exposure_change_pct": 100 * (after.sum() - base.sum()) / base.sum(),
        "mean_lst_before": float(d.lst_c.mean()),
        "mean_lst_after": float((d.lst_c + delta).mean()),
        "residents_cooled": float(d.population.clip(lower=0)[chosen][delta[chosen] < -0.01].sum()),
    }


def compute() -> Results:
    cfg = load_config()
    blocks, material, buildings = build_blocks(cfg)
    train = training_rows(blocks, cfg["min_building_coverage"])
    result = fit(train, cfg["cv_tile_size"], cfg["cv_folds"])
    district = json.loads((EXPORT_DIR / "district.json").read_text(encoding="utf-8"))
    display, _ = display_subset(cfg, blocks, buildings)
    ref = heat_reference_c(cfg, train)
    measured = display.dropna(subset=["lst_c"])

    roof = cool_roof_surface_deltas(cfg, result)
    c = result.coefficients
    deltas = {
        "cool_roof_dark": roof.dark,
        "cool_roof_pale": roof.pale,
        "trees": c["veg_frac"] - c["dark_ground_frac"],
        "pavement": cool_pavement_surface_delta(cfg),
        "park": c["veg_frac"] - c["soil_frac"],
    }

    # Building heights: provenance shares and validation against OSM tags.
    osm = load_osm_buildings(cfg)
    ob = openbuildings.footprint_heights(osm, load_open_buildings_heights(cfg),
                                         cfg["open_buildings_min_pixels"])
    heights = openbuildings.validate_against_osm(osm, ob)
    height_shares = buildings.height_source.value_counts(normalize=True).to_dict()

    # Soil threshold derivation (notebook 02).
    s2 = load_sentinel2(cfg)
    roof10 = footprint_mask(osm, geobox_for(cfg, "model_aoi", FINE_RESOLUTION)).values
    open_ground = distance_transform_edt(roof10 == 0) * FINE_RESOLUTION > 300
    thr, acc = soil_threshold(s2, roof10.astype(bool), open_ground,
                              cfg["s2_classification"]["ndvi_vegetation"])
    soil = {"threshold": thr, "balanced_accuracy": acc}

    # Hyperspectral tests (notebook 05).
    refl = load_enmap(cfg)
    s2_30 = s2.coarsen(x=3, y=3, boundary="trim").mean().assign_coords(x=refl.x, y=refl.y)
    ndvi30 = ((s2_30.B08 - s2_30.B04) / (s2_30.B08 + s2_30.B04)).values
    labels = separability.labels_30m(roof10, ndvi30, cfg["s2_classification"]["ndvi_vegetation"])
    bands = list(enmap.S2_PASSBANDS_NM)
    sep = separability.compare({
        "Sentinel-2, BSI index only (rule in use)": bare_soil_index(s2_30).expand_dims(feature=["BSI"]),
        "Sentinel-2, 6 bands": s2_30[bands].to_array("feature"),
        "EnMAP reduced to Sentinel-2 bands": enmap.simulate_sentinel2(refl).to_array("feature"),
        "EnMAP full spectrum": refl.rename(wavelength="feature"),
    }, labels, refl.x.values, refl.y.values, cfg["cv_tile_size"], cfg["cv_folds"])
    fused = separability.fused_accuracy(s2_30[bands].to_array("feature"), refl, labels,
                                        refl.x.values, refl.y.values, cfg["cv_tile_size"],
                                        cfg["cv_folds"])
    ours = train[FEATURES].to_numpy()
    spec = {
        "Sentinel-2 (6 bands)": separability.block_spectra(
            load_sentinel2(cfg)[bands].to_array("feature"), 9, train),
        "EnMAP reduced to Sentinel-2 bands": separability.block_spectra(
            enmap.simulate_sentinel2(refl).to_array("feature"), 3, train),
        "EnMAP full spectrum": separability.block_spectra(refl, 3, train),
    }
    sets = {"Our model features": ours, **spec,
            "Our features + Sentinel-2": np.hstack([ours, spec["Sentinel-2 (6 bands)"]]),
            "Our features + EnMAP": np.hstack([ours, spec["EnMAP full spectrum"]])}
    heat = pd.DataFrame({
        t: separability.heat_r2(sets, train.lst_c.to_numpy(), spatial_groups(train, t), cfg["cv_folds"])
        for t in (1000, 2000, 3000)
    })

    # M2 spot check (filled in by a person; may still be empty).
    sheet = REPO_ROOT / "docs" / "m2_spot_check.xlsx"
    r = validation.read_results(sheet)
    checked = int(r.match.notna().sum())
    m2 = {"points": len(r), "checked": checked,
          "agreement": float(r.match.mean()) if checked else None}

    lst = load_lst(cfg)
    extra = {
        "n_blocks_model": len(blocks),
        "n_buildings_model": len(buildings),
        "n_display_buildings": district["buildings"]["count"],
        "lst_scenes": lst.attrs.get("scenes"),
        "s2_scenes": s2.attrs.get("scenes"),
        "labels_built": int((labels == 1).sum()),
        "labels_open": int((labels == 0).sum()),
    }
    return Results(
        cfg=cfg, blocks=blocks, material=material, buildings=buildings, train=train, fit=result,
        cv_pred=cv_predictions(train, cfg["cv_tile_size"], cfg["cv_folds"]), district=district,
        display=display, reference_c=ref,
        exposure=exposure_reduction_summary(cfg, result, measured, ref),
        adoption=full_adoption_deltas(cfg, result, train).describe(),
        targeted=targeted_plan(cfg, result, display, ref), deltas=deltas, heights=heights,
        height_shares=height_shares, soil=soil, separability=sep, fused=fused, heat_r2=heat,
        m2=m2, extra=extra,
    )
