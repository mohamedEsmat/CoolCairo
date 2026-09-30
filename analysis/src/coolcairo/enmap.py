"""EnMAP L2A surface reflectance on the project grid.

Files come from DLR's EOC Geoservice (login required, so downloaded manually) into
analysis/data/enmap/; scene IDs are listed in config/enmap_scenes.txt.
Licence: EnMAP data (c) DLR. Derived outputs must say "Contains modified EnMAP data (c) DLR
[year]"; raw data must never be published in downloadable form (see CLAUDE.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import rioxarray
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.enums import Resampling

from coolcairo.config import ANALYSIS_ROOT, DATA_DIR

ENMAP_DIR = DATA_DIR / "enmap"
SCENE_LIST = ANALYSIS_ROOT / "config" / "enmap_scenes.txt"
REFLECTANCE_SCALE = 1e-4  # <GainOfBand> in the scene metadata; offset 0.
NODATA = -32768
LAND_CLASS = 1  # QL_QUALITY_CLASSES: 1 land, 2 water, 3 background (checked against NDWI).

# Atmospheric water-vapour absorption and noisy detector edges: no ground signal.
BAD_WINDOWS_NM = [(0, 420), (1330, 1480), (1780, 1990), (2400, 3000)]


def scene_ids(path: Path = SCENE_LIST) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _file(scene_id: str, kind: str) -> Path:
    matches = sorted(ENMAP_DIR.glob(f"{scene_id}-{kind}*"))
    if not matches:
        raise FileNotFoundError(
            f"Missing {kind} for {scene_id} in {ENMAP_DIR}. Download it from EOC Geoservice "
            "(see config/enmap_scenes.txt)."
        )
    return matches[0]


def wavelengths_nm(scene_id: str) -> np.ndarray:
    text = _file(scene_id, "METADATA").read_text(encoding="utf-8")
    return np.array(
        [float(v) for v in re.findall(r"<wavelengthCenterOfBand>([\d.]+)<", text)]
    )


def good_band_mask(wavelengths: np.ndarray) -> np.ndarray:
    bad = np.zeros(wavelengths.shape, dtype=bool)
    for lo, hi in BAD_WINDOWS_NM:
        bad |= (wavelengths >= lo) & (wavelengths <= hi)
    return ~bad


def reflectance_on_grid(geobox: GeoBox, scene_id: str | None = None) -> xr.DataArray:
    """Surface reflectance (0-1) as (band, y, x) on `geobox`, land pixels only, bad bands dropped.

    Nearest-neighbour resampling: EnMAP is already a 30 m UTM 36N grid like ours, and
    nearest keeps each pixel's spectrum unmixed (bilinear would blend neighbours).
    """
    scene_id = scene_id or scene_ids()[0]
    wl = wavelengths_nm(scene_id)
    keep = good_band_mask(wl)

    target = xr.DataArray(
        np.zeros(geobox.shape, dtype="float32"),
        dims=("y", "x"),
        coords={"y": geobox.coordinates["y"].values, "x": geobox.coordinates["x"].values},
    ).rio.write_crs(geobox.crs.to_wkt()).rio.write_transform(geobox.affine)

    cube = rioxarray.open_rasterio(_file(scene_id, "SPECTRAL_IMAGE"))
    cube = cube.isel(band=np.flatnonzero(keep)).rio.reproject_match(
        target, resampling=Resampling.nearest
    )
    quality = rioxarray.open_rasterio(_file(scene_id, "QL_QUALITY_CLASSES")).sel(band=1)
    land = quality.rio.reproject_match(target, resampling=Resampling.nearest) == LAND_CLASS

    refl = cube.where((cube != NODATA) & land).astype("float32") * REFLECTANCE_SCALE
    refl = refl.assign_coords(band=wl[keep], x=target.x, y=target.y).rename(band="wavelength")
    refl.name = "reflectance"
    refl.attrs.update(scene=scene_id, source="EnMAP L2A, (c) DLR")
    return refl


# Sentinel-2 band passbands (nm), used to simulate Sentinel-2 from EnMAP so a comparison can
# isolate spectral resolution from sensor, date and geometry differences.
S2_PASSBANDS_NM = {
    "B02": (458, 523),
    "B03": (543, 578),
    "B04": (650, 680),
    "B08": (785, 900),
    "B11": (1565, 1655),
    "B12": (2100, 2280),
}


def simulate_sentinel2(refl: xr.DataArray) -> xr.Dataset:
    """Average EnMAP bands inside each Sentinel-2 passband (box-car approximation)."""
    out = xr.Dataset()
    for name, (lo, hi) in S2_PASSBANDS_NM.items():
        inside = (refl.wavelength >= lo) & (refl.wavelength <= hi)
        out[name] = refl.sel(wavelength=inside).mean("wavelength")
    return out


DLR_STAC_ITEMS = "https://geoservice.dlr.de/eoc/ogc/stac/v1/collections/ENMAP_HSI_L2A/items/"


def acquisition_date(scene_id: str) -> str:
    """ISO date from an EnMAP scene id (..._20250422T091720Z_...)."""
    m = re.search(r"_(\d{4})(\d{2})(\d{2})T\d{6}Z_", scene_id)
    if not m:
        raise ValueError(f"No acquisition time in {scene_id}")
    return "-".join(m.groups())


def attribution(scene_id: str) -> str:
    return f"Contains modified EnMAP data © DLR [{acquisition_date(scene_id)[:4]}]"


def archive_source(scene_id: str) -> dict:
    """Loading-screen source entry. DLR's catalogue search ignores id filters, so the app
    verifies the scene by fetching its item URL (public; downloads need a login)."""
    date = acquisition_date(scene_id)
    return {
        "satellite": "EnMAP",
        "collection": "ENMAP_HSI_L2A",
        "use": "Hyperspectral heat drivers",
        "sceneIds": [scene_id],
        "firstDate": date,
        "lastDate": date,
        "previewQuery": "",
        "itemUrl": DLR_STAC_ITEMS + scene_id,
    }
