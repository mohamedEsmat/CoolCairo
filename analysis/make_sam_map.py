"""Spectral Angle Mapper material map of east Cairo from the spectral library.

Usage (from /analysis, after make_library_candidates.py):
    uv run python make_sam_map.py               # library = pixels confirmed by a person (column F)
    uv run python make_sam_map.py --provisional # library = AI pre-check (column I), NOT confirmed

Writes docs/spectral_library/sam[_provisional]/:
  sam_map.png         material map (unclassified = grey)
  leave_one_out.csv   each library pixel classified by a library built without it
  sam_summary.json    threshold, class shares, leave-one-out and independent-check confusion

The independent check uses pixels labelled from OSM footprints, not from spectra: pure-roof
pixels (>= 90 % footprint) should come out as a roof class, open ground (> 300 m from any
building, not vegetated) as sand. Library pixels and their 8 neighbours are left out.
"""

from __future__ import annotations

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from scipy.ndimage import binary_dilation

from coolcairo import enmap
from coolcairo import library as lib
from coolcairo import separability as sep
from coolcairo.buildings import footprint_mask
from coolcairo.config import REPO_ROOT, geobox_for, load_config
from coolcairo.pipeline import FINE_RESOLUTION, load_enmap, load_osm_buildings

LIB_DIR = REPO_ROOT / "docs" / "spectral_library"
COLOURS = {lib.SAND: "#d9a441", lib.PALE_ROOF: "#9aa5b1", lib.DUSTY_ROOF: "#b4966e",
           lib.ASPHALT: "#b04fc4", lib.VEGETATION: "#2e9e44"}
ROOFS = {lib.PALE_ROOF, lib.DUSTY_ROOF}
THRESHOLD_PERCENTILE = 95  # Of library pixels' leave-one-out angle to their own class.


def plot(classes: list[str], cmap_idx: np.ndarray, path: object, scene: str, title: str) -> None:
    show = np.where(cmap_idx == lib.UNCLASSIFIED, len(classes), cmap_idx).astype(float)
    show[np.isnan(cmap_idx.astype(float))] = np.nan
    cmap = ListedColormap([COLOURS[c] for c in classes] + ["#d0d0d0"])
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    ax.imshow(show, cmap=cmap, vmin=-0.5, vmax=len(classes) + 0.5, interpolation="nearest")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    handles = [Patch(color=COLOURS[c], label=c) for c in classes]
    handles.append(Patch(color="#d0d0d0", label="Unclassified"))
    ax.legend(handles=handles, loc="lower left", fontsize=7, frameon=True)
    fig.text(0.01, 0.01, enmap.attribution(scene) + " · © OpenStreetMap contributors (ODbL)",
             fontsize=6, color="#555")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def confusion(truth: pd.Series, pred: pd.Series) -> dict:
    return pd.crosstab(truth, pred).to_dict(orient="index")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provisional", action="store_true",
                    help="use the AI pre-check (column I) instead of the person's answers")
    args = ap.parse_args()
    column = lib.AI_PRECHECK_COLUMN if args.provisional else lib.PERSON_COLUMN
    out = LIB_DIR / ("sam_provisional" if args.provisional else "sam")

    cfg = load_config()
    refl = load_enmap(cfg)
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=column)
    used = checked[checked.accepted].reset_index(drop=True)
    if used.empty:
        raise SystemExit(f"No accepted rows in column {column}: confirm the candidates first.")
    classes = list(dict.fromkeys(used["class"]))
    spectra = lib.class_spectra(refl, used)[classes]

    loo = lib.sam_leave_one_out(refl, used)
    max_angle = float(np.percentile(loo.angle_own_deg, THRESHOLD_PERCENTILE))

    angles = lib.sam_angles(refl, spectra)
    idx = lib.sam_classify(angles, max_angle)
    valid = np.isfinite(angles).all(axis=0)
    names = np.array(classes + ["Unclassified"])
    labelled = names[np.where(idx == lib.UNCLASSIFIED, len(classes), idx)]

    # Independent check against OSM-derived roof / open-ground pixels.
    fine = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    roof_10m = footprint_mask(load_osm_buildings(cfg), fine).values
    truth = sep.labels_30m(roof_10m, lib.ndvi(refl), lib.NDVI_NOT_VEGETATED)
    near_library = np.zeros(truth.shape, bool)
    near_library[used.row.values, used.col.values] = True
    near_library = binary_dilation(near_library, iterations=1)
    test = valid & (truth >= 0) & ~near_library
    t = pd.Series(np.where(truth[test] == sep.BUILT, "OSM roof", "Open ground"), name="osm")
    p = pd.Series(labelled[test], name="sam")
    roof_ok = float(p[t == "OSM roof"].isin(ROOFS).mean())
    ground_ok = float((p[t == "Open ground"] == lib.SAND).mean())

    out.mkdir(parents=True, exist_ok=True)
    loo.round(3).to_csv(out / "leave_one_out.csv", index=False)
    shares = pd.Series(labelled[valid]).value_counts(normalize=True).round(4).to_dict()
    summary = {
        "library": "AI pre-check, NOT confirmed (provisional)" if args.provisional
                   else "confirmed by eye",
        "scene": scene,
        "library_pixels": used["class"].value_counts().to_dict(),
        "max_angle_deg": round(max_angle, 2),
        "max_angle_rule": f"{THRESHOLD_PERCENTILE}th percentile of library pixels' "
                          "leave-one-out angle to their own class",
        "class_shares": shares,
        "leave_one_out_accuracy": round(float((loo["class"] == loo.predicted).mean()), 3),
        "leave_one_out_confusion": confusion(loo["class"], loo.predicted),
        "osm_check_pixels": {"OSM roof": int((t == "OSM roof").sum()),
                             "Open ground": int((t == "Open ground").sum())},
        "osm_roof_as_roof_class": round(roof_ok, 3),
        "open_ground_as_sand": round(ground_ok, 3),
        "osm_check_confusion": confusion(t, p),
        "attribution": enmap.attribution(scene) + " · © OpenStreetMap contributors (ODbL)",
    }
    (out / "sam_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    kind = "provisional library (AI pre-check, not confirmed)" if args.provisional \
        else "confirmed library"
    plot(classes, np.where(valid, idx, np.nan), out / "sam_map.png", scene,
         f"SAM material map, east Cairo, EnMAP 22 Apr 2025: {kind}, max angle {max_angle:.1f}°")

    print(json.dumps({k: summary[k] for k in (
        "library_pixels", "max_angle_deg", "class_shares", "leave_one_out_accuracy",
        "osm_roof_as_roof_class", "open_ground_as_sand")}, indent=1))
    print(pd.crosstab(loo["class"], loo.predicted).to_string())
    print(pd.crosstab(t, p).to_string())
    print(f"-> {out}")


if __name__ == "__main__":
    main()
