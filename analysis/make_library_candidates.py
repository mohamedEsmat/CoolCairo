"""Propose spectral-library pixels and write the sheet a person uses to confirm them.

Usage (from /analysis, after the pipeline has cached EnMAP, OSM and Open Buildings data):
    uv run python make_library_candidates.py

Writes docs/spectral_library/:
  candidates.xlsx         confirmation sheet (one row per candidate pixel, Google Maps links)
  candidates.kml          the same pixels as exact 30 m squares, for Google Earth
  candidates.csv          pixel positions and the values that selected them
  provisional_spectra.png class mean spectra BEFORE confirmation (preview only)
  provisional_angles.csv  spectral angle between those provisional spectra
  shadow_check.json       modelled shadow cover of the 30 m pixels at the scene's sun angles

Major roads, aprons and car parks come from a committed OSM snapshot (data/osm/); it is
fetched once if missing.
"""

from __future__ import annotations

import json
import re

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox

from coolcairo import enmap
from coolcairo import library as lib
from coolcairo.buildings import footprint_mask
from coolcairo.config import REPO_ROOT, geobox_for, load_config
from coolcairo.pipeline import (
    FINE_RESOLUTION,
    load_enmap,
    load_open_buildings_heights,
    load_osm_buildings,
)

OUT = REPO_ROOT / "docs" / "spectral_library"
PAVED_SNAPSHOT = REPO_ROOT / "data" / "osm" / "paved_osm_2026-11-16.gpkg"
PAVED_TAGS = {"highway": ["motorway", "trunk", "primary", "motorway_link", "trunk_link"],
              "aeroway": ["runway", "apron", "taxiway"], "amenity": ["parking"]}


def load_paved(cfg: object) -> gpd.GeoDataFrame:
    if not PAVED_SNAPSHOT.exists():
        raw = ox.features_from_bbox(tuple(cfg["model_aoi"]["bbox_wgs84"]), tags=PAVED_TAGS)
        keep = [c for c in ("highway", "aeroway", "amenity", "name") if c in raw]
        gdf = raw.reset_index()[["geometry", *keep]].to_crs(cfg.crs)
        PAVED_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(PAVED_SNAPSHOT, driver="GPKG")
    return gpd.read_file(PAVED_SNAPSHOT)


def sun_angles(scene_id: str) -> tuple[float, float]:
    """Scene-mean sun elevation and azimuth (degrees) from the EnMAP metadata."""
    text = enmap._file(scene_id, "METADATA").read_text(encoding="utf-8")

    def mean(tag: str) -> float:
        block = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S).group(1)
        return float(np.mean([float(v) for v in re.findall(r">([\d.]+)<", block)]))

    return mean("sunElevationAngle"), mean("sunAzimuthAngle")


def plot(spectra: object, path: object, scene: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    wl = spectra.index.to_numpy()
    gap = np.r_[False, np.diff(wl) > 30]  # Break the line over dropped water-vapour bands.
    colours = {lib.SAND: "#d9a441", lib.PALE_ROOF: "#9aa5b1", lib.DARK_ROOF: "#3b3b3b",
               lib.ASPHALT: "#b04fc4", lib.VEGETATION: "#2e9e44"}
    for cls in spectra.columns:
        y = spectra[cls].to_numpy().copy()
        x = wl.astype(float).copy()
        x, y = np.insert(x, np.flatnonzero(gap), np.nan), np.insert(y, np.flatnonzero(gap), np.nan)
        ax.plot(x, y, lw=1.8, color=colours.get(cls, "k"), label=cls)
    for w in (1730, 2310, 2340):
        ax.axvline(w, color="#999", lw=0.6, ls=":")
    ax.set(xlabel="Wavelength (nm)", ylabel="Reflectance",
           title="Provisional class spectra, east Cairo (before confirmation by eye)")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    ax.grid(alpha=0.25)
    fig.text(0.01, 0.01, enmap.attribution(scene), fontsize=7, color="#555")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    cfg = load_config()
    refl = load_enmap(cfg)
    scene = refl.attrs.get("scene") or enmap.scene_ids()[0]
    elevation, azimuth = sun_angles(scene)

    heights = load_open_buildings_heights(cfg)
    shadow_30m = lib.to_pixels(lib.shadow_mask(heights, elevation, azimuth).astype(float),
                               heights, refl)
    fine = geobox_for(cfg, "model_aoi", FINE_RESOLUTION)
    roof_10m = footprint_mask(load_osm_buildings(cfg), fine).values
    paved_10m = lib.paved_mask(load_paved(cfg), fine)

    masks = lib.rule_masks(refl, roof_10m, paved_10m, shadow_30m)
    picks = lib.candidates(refl, masks, cfg.crs)
    spectra = lib.class_spectra(refl, picks)

    OUT.mkdir(parents=True, exist_ok=True)
    lib.write_sheet(picks, OUT / "candidates.xlsx")
    lib.write_kml(picks, cfg.crs, OUT / "candidates.kml")
    picks.round({"lat": 6, "lon": 6}).to_csv(OUT / "candidates.csv", index_label="id")
    lib.angle_matrix(spectra).to_csv(OUT / "provisional_angles.csv")
    plot(spectra, OUT / "provisional_spectra.png", scene)
    (OUT / "shadow_check.json").write_text(json.dumps({
        "scene": scene, "sun_elevation_deg": round(elevation, 2),
        "sun_azimuth_deg": round(azimuth, 2),
        "shadow_length_per_metre_height": round(1 / np.tan(np.radians(elevation)), 3),
        "pixels": int(np.isfinite(shadow_30m).sum()),
        "max_shadow_fraction": round(float(np.nanmax(shadow_30m)), 3),
        "pixels_over_half_shadow": int((shadow_30m > 0.5).sum()),
        "pixels_over_quarter_shadow": int((shadow_30m > 0.25).sum()),
        "mean_shadow_fraction": round(float(np.nanmean(shadow_30m)), 4),
        "attribution": enmap.attribution(scene) + " · Google Open Buildings 2.5D (CC BY 4.0)",
    }, indent=2), encoding="utf-8")

    pools = {k: int(v.sum()) for k, v in masks.items()}
    print(f"sun {elevation:.1f}° elev, {azimuth:.1f}° az; pools {pools}")
    print(picks.groupby("class", sort=False).size().to_string())
    print(lib.angle_matrix(spectra).to_string())
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
