"""Material maps of east Cairo from the spectral library: spectral angle, then brightness and
absorption depths added back.

Usage (from /analysis, after make_library_candidates.py):
    uv run python make_sam_map.py               # library = pixels confirmed by a person (column F)
    uv run python make_sam_map.py --provisional # library = AI pre-check (column I), NOT confirmed

Three methods, each the nearest library class by a distance:
  angle                    spectral angle only (SAM): ignores brightness, so shade cannot fool it
  angle_brightness         + log brightness (450-900 nm)
  angle_brightness_depths  + continuum-removed depths at 1730, 2310, 2340 nm
Each term is divided by its spread within the library classes. A pixel stays unclassified
beyond the 95th percentile of the library pixels' leave-one-out distance to their own class.

Writes docs/spectral_library/sam[_provisional]/:
  comparison.csv, summary.json     scores of the three methods side by side
  <method>/sam_map.png             material map (unclassified = grey)
  <method>/leave_one_out.csv       each library pixel classified by a library built without it

Checks, all on data independent of the library spectra:
  leave-one-out   library pixels, each left out in turn
  OSM check       pure-roof pixels (>= 90 % OSM footprint) should be a roof class, open ground
                  (> 300 m from any OSM building AND from any Open Buildings building, not
                  vegetated) should be sand; library pixels and their 8 neighbours are left
                  out. OSM alone misses many buildings: 57 % of its "open ground" pixels have
                  an Open Buildings building within 30 m.
  shade check     the same roof pixels split by modelled building shadow (Open Buildings
                  heights, the scene's sun angles): < 5 % vs > 25 % shadow. Brightness drops
                  in shade, so adding it back must not turn shaded roofs into asphalt.
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
from coolcairo.pipeline import (
    FINE_RESOLUTION,
    load_enmap,
    load_open_buildings_heights,
    load_osm_buildings,
)
from make_library_candidates import sun_angles

LIB_DIR = REPO_ROOT / "docs" / "spectral_library"
COLOURS = {lib.SAND: "#d9a441", lib.PALE_ROOF: "#9aa5b1", lib.DUSTY_ROOF: "#b4966e",
           lib.ASPHALT: "#b04fc4", lib.VEGETATION: "#2e9e44"}
ROOFS = {lib.PALE_ROOF, lib.DUSTY_ROOF}
THRESHOLD_PERCENTILE = 95  # Of library pixels' leave-one-out distance to their own class.
METHODS = {"angle": None, "angle_brightness": False, "angle_brightness_depths": True}
SHADE_LOW, SHADE_HIGH = 0.05, 0.25
OPEN_MIN_M = 300  # Open ground must also be this far from any Open Buildings building.


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


def independent_labels(cfg: object, refl: object, scene: str,
                       used: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Labels that do not come from the library spectra, on the 30 m EnMAP grid.

    Returns (truth, shade, near_library): truth is sep.BUILT for pure OSM roofs, sep.OPEN for
    open ground far from both OSM and Open Buildings, -1 otherwise; shade is the modelled
    building-shadow fraction; near_library marks library pixels and their 8 neighbours.
    """
    fine = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    roof_10m = footprint_mask(load_osm_buildings(cfg), fine).values
    truth = sep.labels_30m(roof_10m, lib.ndvi(refl), lib.NDVI_NOT_VEGETATED)
    heights = load_open_buildings_heights(cfg)
    truth[(truth == sep.OPEN) & ~(lib.building_distance_30m(heights, refl) > OPEN_MIN_M)] = -1
    shade = lib.to_pixels(lib.shadow_mask(heights, *sun_angles(scene)).astype(float),
                          heights, refl)
    near_library = np.zeros(truth.shape, bool)
    near_library[used.row.values, used.col.values] = True
    return truth, shade, binary_dilation(near_library, iterations=1)


def confusion(truth: pd.Series, pred: pd.Series) -> dict:
    return pd.crosstab(truth, pred).to_dict(orient="index")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provisional", action="store_true",
                    help="use the AI pre-check (column I) instead of the person's answers")
    args = ap.parse_args()
    column = lib.AI_PRECHECK_COLUMN if args.provisional else lib.PERSON_COLUMN
    out = LIB_DIR / ("sam_provisional" if args.provisional else "sam")
    kind = ("provisional library (AI pre-check, not confirmed)" if args.provisional
            else "confirmed library")

    cfg = load_config()
    refl = load_enmap(cfg)
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    picks = pd.read_csv(LIB_DIR / "candidates.csv", index_col="id")
    checked = lib.read_sheet(LIB_DIR / "candidates.xlsx", picks, column=column)
    used = checked[checked.accepted].reset_index(drop=True)
    if used.empty:
        raise SystemExit(f"No accepted rows in column {column}: confirm the candidates first.")
    classes = list(dict.fromkeys(used["class"]))
    names = np.array(classes + ["Unclassified"])
    has_data = np.isfinite(refl.values).all(axis=0)

    truth, shade, near_library = independent_labels(cfg, refl, scene, used)
    test = has_data & (truth >= 0) & ~near_library
    t = pd.Series(np.where(truth[test] == sep.BUILT, "OSM roof", "Open ground"), name="osm")
    roof_test = has_data & (truth == sep.BUILT) & ~near_library
    sunlit, shaded = roof_test & (shade < SHADE_LOW), roof_test & (shade > SHADE_HIGH)

    rows, details = [], {}
    for method, depths in METHODS.items():
        feats = {} if depths is None else lib.material_features(refl, depths=depths)
        loo = lib.fused_leave_one_out(refl, feats, used)
        max_dist = float(np.percentile(loo.dist_own, THRESHOLD_PERCENTILE))
        idx = lib.fused_classify(refl, feats, used, max_dist)
        labelled = names[np.where(idx == lib.UNCLASSIFIED, len(classes), idx)]
        p = pd.Series(labelled[test], name=method)
        roofish = np.isin(labelled, list(ROOFS))
        rows.append({
            "method": method,
            "leave_one_out_accuracy": (loo["class"] == loo.predicted).mean(),
            "osm_roof_as_roof_class": p[t == "OSM roof"].isin(ROOFS).mean(),
            "open_ground_as_sand": (p[t == "Open ground"] == lib.SAND).mean(),
            "unclassified_share": (labelled[has_data] == "Unclassified").mean(),
            "sunlit_roof_as_roof": roofish[sunlit].mean(),
            "shaded_roof_as_roof": roofish[shaded].mean(),
            "shaded_roof_as_asphalt": (labelled[shaded] == lib.ASPHALT).mean(),
        })
        details[method] = {
            "max_distance": round(max_dist, 2),
            "leave_one_out_confusion": confusion(loo["class"], loo.predicted),
            "osm_check_confusion": confusion(t, p),
            "class_shares": pd.Series(labelled[has_data]).value_counts(normalize=True)
                              .round(4).to_dict(),
        }
        (out / method).mkdir(parents=True, exist_ok=True)
        loo.round(3).to_csv(out / method / "leave_one_out.csv", index=False)
        plot(classes, np.where(has_data, idx, np.nan), out / method / "sam_map.png", scene,
             f"Material map ({method.replace('_', ' + ')}), east Cairo, EnMAP 22 Apr 2025: {kind}")

    table = pd.DataFrame(rows).set_index("method").round(3)
    table.to_csv(out / "comparison.csv")
    summary = {
        "library": kind, "scene": scene,
        "library_pixels": used["class"].value_counts().to_dict(),
        "threshold_rule": f"{THRESHOLD_PERCENTILE}th percentile of library pixels' "
                          "leave-one-out distance to their own class",
        "check_pixels": {"OSM roof": int((t == "OSM roof").sum()),
                         "Open ground": int((t == "Open ground").sum()),
                         f"roof, shadow < {SHADE_LOW:.0%}": int(sunlit.sum()),
                         f"roof, shadow > {SHADE_HIGH:.0%}": int(shaded.sum())},
        "comparison": table.to_dict(orient="index"),
        "methods": details,
        "attribution": enmap.attribution(scene) + " · Google Open Buildings 2.5D (CC BY 4.0)"
                       " · © OpenStreetMap contributors (ODbL)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(table.T.to_string())
    print(summary["check_pixels"])
    for m in METHODS:
        print(m, details[m]["osm_check_confusion"])
    print(f"-> {out}")


if __name__ == "__main__":
    main()
