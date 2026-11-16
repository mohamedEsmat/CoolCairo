"""Image-derived spectral library for the hyperspectral material map.

The library holds one reference spectrum per material in east Cairo. SAM classification and
linear unmixing (next steps) compare every EnMAP pixel with it, so it must come from pixels
that really are pure.

1. `candidates` proposes pure 30 m EnMAP pixels per class: the pixel meets the class rule from
   independent data (OSM footprints and roads, Open Buildings heights, NDVI, brightness), its
   modelled shadow cover is small, and its spectrum is close to its 8 neighbours (a
   homogeneous patch, so a small geolocation offset cannot change the material).
2. A person confirms each candidate in very-high-resolution imagery (`write_sheet`).
3. `library_from_sheet` averages the confirmed pixels into the library.

Shadow is not a library class: at this scene's sun elevation (about 70 degrees) a building
casts a shadow about 0.36 x its height, so no 30 m pixel is fully shadowed (`shadow_fraction`
measures it). Shadow enters the unmixing as a near-zero "shade" spectrum instead.

Dark roof is not a library class either (decided 16 Nov 2026): a visual pre-check of the
darkest pure-roof pixels found 0 of 12 real dark roofs (mixed pixels: gaps, courtyards, trees,
shadow; two OSM footprint errors). Unmixing expresses dark rooftops as roof + shade. Instead,
"dusty roof" (a roof whose spectrum is closest to sand) targets the project's main confusion.

EnMAP licence: library spectra are derived products ("Contains modified EnMAP data (c) DLR").
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from pyproj import Transformer
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt, minimum_filter

SAND, PALE_ROOF, DUSTY_ROOF, ASPHALT, VEGETATION = (
    "Sand / bare ground", "Pale roof", "Dusty roof", "Asphalt / paved", "Vegetation")
CLASSES = [SAND, PALE_ROOF, DUSTY_ROOF, ASPHALT, VEGETATION]
CLASS_HELP = {
    SAND: "Unbuilt sandy or dusty land, desert, empty plots",
    PALE_ROOF: "Light concrete or painted roofs: white, beige, light grey",
    DUSTY_ROOF: "Roofs covered in dust or sand-coloured (tan, beige), looking like the ground",
    ASPHALT: "Asphalt road, car park, airport apron or runway",
    VEGETATION: "Trees, grass, gardens, green fields",
}
ANSWERS = ["Yes, all of it", "Mostly (more than 3/4)", "No, mixed", "No, other material",
           "Unsure / can't tell"]
ACCEPT = ANSWERS[:2]

# Thresholds (30 m pixel). Pure roof: every 10 m cell inside an OSM footprint.
ROOF_PURE = 1.0
SAND_MIN_DIST_M = 300          # Same rule as separability.labels_30m (open ground).
NDVI_VEGETATION = 0.45
NDVI_NOT_VEGETATED = 0.2
ROAD_PURE = 0.8                # Share of 10 m cells on a road / apron / car park polygon.
SHADOW_MAX = 0.10              # Modelled shadow cover allowed in a candidate pixel.
MIN_SPACING_M = 300            # Between candidates of one class, to spread them out.
ROAD_HALF_WIDTH_M = {"motorway": 14, "trunk": 12, "primary": 9,
                     "motorway_link": 5, "trunk_link": 5, "taxiway": 10}


def ndvi(refl: xr.DataArray) -> np.ndarray:
    red = refl.sel(wavelength=slice(650, 680)).mean("wavelength")
    nir = refl.sel(wavelength=slice(800, 880)).mean("wavelength")
    return ((nir - red) / (nir + red)).values


def brightness(refl: xr.DataArray) -> np.ndarray:
    """Mean reflectance 450-900 nm (what the eye and the PoC's pale/dark split see)."""
    return refl.sel(wavelength=slice(450, 900)).mean("wavelength").values


def share_30m(mask_10m: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Share of the 3 x 3 cells of each 30 m pixel where a 10 m mask is set."""
    ny, nx = shape
    return mask_10m[: ny * 3, : nx * 3].reshape(ny, 3, nx, 3).mean(axis=(1, 3))


def paved_mask(paved: gpd.GeoDataFrame, geobox_10m: object) -> np.ndarray:
    """10 m mask of major roads (buffered by half their width), aprons, runways, car parks."""
    shapes = []
    for _, f in paved.iterrows():
        g = f.geometry
        if g.geom_type in ("LineString", "MultiLineString"):
            half = ROAD_HALF_WIDTH_M.get(f.get("highway"), 0) or \
                ROAD_HALF_WIDTH_M.get(f.get("aeroway"), 0)
            if half:
                shapes.append(g.buffer(half, cap_style="flat"))
        elif g.geom_type in ("Polygon", "MultiPolygon"):
            shapes.append(g)
    if not shapes:
        return np.zeros(geobox_10m.shape, dtype=bool)
    return rasterize(((s, 1) for s in shapes), out_shape=geobox_10m.shape,
                     transform=geobox_10m.affine, fill=0, dtype="uint8").astype(bool)


def shadow_mask(height: xr.DataArray, sun_elevation: float, sun_azimuth: float,
                step_m: float = 2.0) -> np.ndarray:
    """Cells in a cast shadow: some building towards the sun is tall enough to hide it.

    A cell P is shadowed when a cell Q at distance d towards the sun has H(Q) - H(P) greater
    than d x tan(sun elevation). `height` is a regular grid (y north to south) in metres.
    """
    h = np.nan_to_num(height.values.astype("float32"))
    res = abs(float(height.x[1] - height.x[0]))
    tan_e = np.tan(np.radians(sun_elevation))
    east, south = np.sin(np.radians(sun_azimuth)), -np.cos(np.radians(sun_azimuth))
    shadow = np.zeros(h.shape, dtype=bool)
    ny, nx = h.shape
    for d in np.arange(step_m, h.max() / tan_e + step_m, step_m):
        dr, dc = int(round(south * d / res)), int(round(east * d / res))
        q = np.zeros_like(h)  # q[r, c] = height of the cell d metres towards the sun
        q[max(0, -dr): ny - max(0, dr), max(0, -dc): nx - max(0, dc)] = \
            h[max(0, dr): ny + min(0, dr) or None, max(0, dc): nx + min(0, dc) or None]
        shadow |= (q - h) > d * tan_e
    return shadow


def to_pixels(values: np.ndarray, src: xr.DataArray, dst: xr.DataArray) -> np.ndarray:
    """Mean of a fine grid (`src` coords) within each pixel of the 30 m grid `dst`."""
    x0 = float(dst.x[0]) - 15.0
    y0 = float(dst.y[0]) + 15.0
    cols = np.floor((src.x.values - x0) / 30.0).astype(int)
    rows = np.floor((y0 - src.y.values) / 30.0).astype(int)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    ok = (rr >= 0) & (rr < dst.sizes["y"]) & (cc >= 0) & (cc < dst.sizes["x"])
    idx = rr[ok] * dst.sizes["x"] + cc[ok]
    n = dst.sizes["y"] * dst.sizes["x"]
    total = np.bincount(idx, weights=values[ok].astype(float), minlength=n)
    count = np.bincount(idx, minlength=n)
    with np.errstate(invalid="ignore"):
        return (total / count).reshape(dst.sizes["y"], dst.sizes["x"])


def building_distance_30m(height: xr.DataArray, dst: xr.DataArray,
                          min_height: float = 2.0) -> np.ndarray:
    """Mean distance (m) to the nearest Open Buildings building, per 30 m pixel of `dst`.

    OSM footprints are incomplete in dense east Cairo; this independent check keeps
    "open ground" labels away from unmapped buildings.
    """
    cell = abs(float(height.x[1] - height.x[0]))
    dist = distance_transform_edt(~(height.values > min_height)) * cell
    return to_pixels(dist, height, dst)


def neighbour_angle(refl: xr.DataArray) -> np.ndarray:
    """Spectral angle (degrees) between each pixel and the mean of its 8 neighbours."""
    v = np.nan_to_num(refl.values)  # (band, y, x)
    pad = np.pad(v, ((0, 0), (1, 1), (1, 1)), mode="edge")
    ny, nx = v.shape[1:]
    neigh = sum(pad[:, 1 + dy: 1 + dy + ny, 1 + dx: 1 + dx + nx]
                for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)) / 8.0
    cos = (v * neigh).sum(0) / (np.linalg.norm(v, axis=0) * np.linalg.norm(neigh, axis=0) + 1e-12)
    ang = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    ang[~np.isfinite(refl.values).all(0)] = np.nan
    return ang


def rule_masks(refl: xr.DataArray, roof_10m: np.ndarray, paved_10m: np.ndarray,
               shadow_30m: np.ndarray) -> dict[str, np.ndarray]:
    """Per class, the 30 m pixels whose independent data say the pixel is that material."""
    shape = (refl.sizes["y"], refl.sizes["x"])
    roof = share_30m(roof_10m.astype(float), shape)
    paved = share_30m(paved_10m.astype(float), shape)
    dist = distance_transform_edt(roof_10m == 0) * 10.0
    dist = dist[: shape[0] * 3, : shape[1] * 3].reshape(shape[0], 3, shape[1], 3).min(axis=(1, 3))
    nd, br = ndvi(refl), brightness(refl)
    low_shadow = np.nan_to_num(shadow_30m, nan=1.0) <= SHADOW_MAX
    grey = nd < NDVI_NOT_VEGETATED

    pure_roof = (roof >= ROOF_PURE) & grey & low_shadow
    hi = np.nanpercentile(br[pure_roof], 67) if pure_roof.any() else 0
    sand = (dist > SAND_MIN_DIST_M) & grey & (paved == 0)
    veg = nd >= NDVI_VEGETATION
    # Paved: darkest third only. OSM car parks and road edges in Cairo are often sandy, and
    # the most homogeneous paved pixels are the sandiest, so without this the picks are sand.
    paved_pure = (paved >= ROAD_PURE) & (roof == 0) & grey & low_shadow
    dark_paved = np.nanpercentile(br[paved_pure], 33) if paved_pure.any() else 0
    return {
        # Sand and vegetation: the whole 3 x 3 patch must meet the rule (they come in big areas).
        SAND: minimum_filter(sand.astype(np.uint8), size=3).astype(bool),
        VEGETATION: minimum_filter(veg.astype(np.uint8), size=3).astype(bool),
        PALE_ROOF: pure_roof & (br >= hi),
        DUSTY_ROOF: pure_roof & (br < hi),  # Ranked by closeness to sand in `candidates`.
        ASPHALT: paved_pure & (br <= dark_paved),
    }


def candidates(refl: xr.DataArray, masks: dict[str, np.ndarray], crs: str,
               per_class: int = 12) -> pd.DataFrame:
    """Best `per_class` pixels per class, spread `MIN_SPACING_M` apart.

    Ranking: most homogeneous first (smallest angle to the 8 neighbours). Dusty roof ranks by
    angle to the mean sand spectrum plus that homogeneity angle: uniform roofs that look most
    like sand, the confusion the material map has to resolve.
    """
    angle = neighbour_angle(refl)
    nd, br = ndvi(refl), brightness(refl)
    v = refl.values
    sand_ref = np.nanmean(v[:, masks[SAND]], axis=1) if masks[SAND].any() else None
    to_sand = np.full(angle.shape, np.nan)
    if sand_ref is not None and np.isfinite(sand_ref).all():
        cos = np.einsum("byx,b->yx", np.nan_to_num(v), sand_ref) / (
            np.linalg.norm(np.nan_to_num(v), axis=0) * np.linalg.norm(sand_ref) + 1e-12)
        to_sand = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    rows = []
    for cls in CLASSES:
        yy, xx = np.nonzero(masks[cls] & np.isfinite(angle))
        score = angle[yy, xx] + (to_sand[yy, xx] if cls == DUSTY_ROOF else 0)
        order = np.argsort(score)
        picked: list[tuple[float, float]] = []
        for k in order:
            x, y = float(refl.x[xx[k]]), float(refl.y[yy[k]])
            if all((x - px) ** 2 + (y - py) ** 2 >= MIN_SPACING_M ** 2 for px, py in picked):
                picked.append((x, y))
                rows.append({"class": cls, "row": int(yy[k]), "col": int(xx[k]), "x": x, "y": y,
                             "homogeneity_deg": round(float(angle[yy[k], xx[k]]), 2),
                             "ndvi": round(float(nd[yy[k], xx[k]]), 3),
                             "brightness": round(float(br[yy[k], xx[k]]), 3),
                             "angle_to_sand_deg": round(float(to_sand[yy[k], xx[k]]), 2),
                             "pool": int(len(yy))})
            if len(picked) == per_class:
                break
    out = pd.DataFrame(rows)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    out["lon"], out["lat"] = to_wgs.transform(out.x.values, out.y.values)
    return out


def class_spectra(refl: xr.DataArray, picks: pd.DataFrame) -> pd.DataFrame:
    """Mean reflectance per class over the given pixels: (wavelength x class)."""
    v = refl.values
    out = {cls: np.nanmean(v[:, g.row.values, g.col.values], axis=1)
           for cls, g in picks.groupby("class", sort=False)}
    return pd.DataFrame(out, index=pd.Index(refl.wavelength.values, name="wavelength_nm"))


def angle_matrix(spectra: pd.DataFrame) -> pd.DataFrame:
    """Spectral angle (degrees) between every pair of library spectra."""
    a = spectra.to_numpy().T
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    deg = np.degrees(np.arccos(np.clip(a @ a.T, -1, 1)))
    return pd.DataFrame(deg, index=spectra.columns, columns=spectra.columns).round(1)


# ---- Spectral Angle Mapper ------------------------------------------------------------------

UNCLASSIFIED = -1


def _unit(a: np.ndarray, axis: int) -> np.ndarray:
    return a / np.linalg.norm(a, axis=axis, keepdims=True)


def sam_angles(refl: xr.DataArray, spectra: pd.DataFrame) -> np.ndarray:
    """Spectral angle (degrees) of every pixel to every library spectrum: (class, y, x).

    The angle compares spectral shape only, so a shaded pixel keeps its material's angle.
    Pixels with any missing band get NaN.
    """
    nb, ny, nx = refl.shape
    pix = _unit(refl.values.reshape(nb, -1), axis=0)
    ref = _unit(spectra.to_numpy().T, axis=1)
    cos = np.clip(ref @ pix, -1, 1)
    return np.degrees(np.arccos(cos)).reshape(len(spectra.columns), ny, nx)


def sam_classify(angles: np.ndarray, max_angle: float) -> np.ndarray:
    """Index of the closest class per pixel, UNCLASSIFIED if even that is > max_angle or NaN."""
    valid = np.isfinite(angles).all(axis=0)
    best = np.where(valid, np.nanargmin(np.where(valid, angles, 0), axis=0), UNCLASSIFIED)
    best[valid & (np.nanmin(np.where(valid, angles, np.inf), axis=0) > max_angle)] = UNCLASSIFIED
    return best


def sam_leave_one_out(refl: xr.DataArray, picks: pd.DataFrame) -> pd.DataFrame:
    """Classify each library pixel with a library built without it.

    Returns one row per pixel: true class, predicted class, angle to its own class mean.
    """
    classes = list(dict.fromkeys(picks["class"]))
    v = refl.values
    spec = v[:, picks.row.values, picks.col.values].T  # (pixel, band)
    rows = []
    for i, cls in enumerate(picks["class"]):
        keep = np.arange(len(picks)) != i
        means = np.stack([spec[keep & (picks["class"].values == c)].mean(axis=0)
                          for c in classes])
        ang = np.degrees(np.arccos(np.clip(_unit(means, 1) @ _unit(spec[i], 0), -1, 1)))
        rows.append({"class": cls, "predicted": classes[int(np.argmin(ang))],
                     "angle_own_deg": float(ang[classes.index(cls)]),
                     "angle_best_deg": float(ang.min())})
    return pd.DataFrame(rows)


# ---- Angle + brightness + absorption depths -------------------------------------------------
# The spectral angle ignores brightness (good for shade), but east Cairo's sand, dusty roofs and
# asphalt differ mostly in brightness. These features add it back, plus narrow absorptions the
# angle averages away: bitumen/hydrocarbon near 1730 and 2310 nm, carbonate near 2340 nm.

ABSORPTIONS = {  # name: (centre, left shoulder, right shoulder), nm
    "depth_1730": (1730, 1660, 1770),
    "depth_2310": (2310, 2230, 2390),
    "depth_2340": (2340, 2230, 2390),
}


def _band(refl: xr.DataArray, nm: float, half: int = 1) -> np.ndarray:
    """Mean of the band nearest `nm` and its `half` neighbours on each side."""
    i = int(np.argmin(np.abs(refl.wavelength.values - nm)))
    return refl.isel(wavelength=slice(max(i - half, 0), i + half + 1)).mean("wavelength").values


def band_depth(refl: xr.DataArray, centre: float, left: float, right: float) -> np.ndarray:
    """Continuum-removed depth: 1 - R(centre) / straight line between the shoulders."""
    rl, rc, rr = _band(refl, left), _band(refl, centre), _band(refl, right)
    t = (centre - left) / (right - left)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 1 - rc / ((1 - t) * rl + t * rr)


def material_features(refl: xr.DataArray, depths: bool = True) -> dict[str, np.ndarray]:
    """Per-pixel features beside the angle: log brightness (shade scales it) and depths."""
    with np.errstate(invalid="ignore", divide="ignore"):
        out = {"log_brightness": np.log(brightness(refl))}
    if depths:
        out |= {k: band_depth(refl, *v) for k, v in ABSORPTIONS.items()}
    return out


def _fit(spec: np.ndarray, feats: np.ndarray, labels: np.ndarray, classes: list[str]) -> dict:
    """Class means and pooled within-class spreads. spec (n, band), feats (n, f)."""
    unit = _unit(spec, axis=1)
    means = np.stack([spec[labels == c].mean(axis=0) for c in classes])
    cents = np.stack([feats[labels == c].mean(axis=0) for c in classes])
    own = np.array([classes.index(c) for c in labels])
    ang = np.degrees(np.arccos(np.clip((unit * _unit(means, 1)[own]).sum(axis=1), -1, 1)))
    return {"means": means, "cents": cents,
            "angle_scale": float(np.sqrt(np.mean(ang ** 2))),
            "feat_scale": np.sqrt(np.mean((feats - cents[own]) ** 2, axis=0))}


def _distance(model: dict, spec: np.ndarray, feats: np.ndarray) -> np.ndarray:
    """(class, n) distance: angle and feature differences, each in units of their spread."""
    ang = np.degrees(np.arccos(np.clip(_unit(model["means"], 1) @ _unit(spec, 1).T, -1, 1)))
    d2 = (ang / model["angle_scale"]) ** 2
    if feats.shape[1]:
        z = (feats[None, :, :] - model["cents"][:, None, :]) / model["feat_scale"]
        d2 = d2 + (z ** 2).sum(axis=2)
    return np.sqrt(d2)


def _pixels(refl: xr.DataArray, feats: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    nb = refl.shape[0]
    spec = refl.values.reshape(nb, -1).T
    if not feats:
        return spec, np.empty((spec.shape[0], 0))
    f = np.stack([v.ravel() for v in feats.values()], axis=1)
    return spec, f


def fused_leave_one_out(refl: xr.DataArray, feats: dict[str, np.ndarray],
                        picks: pd.DataFrame) -> pd.DataFrame:
    """Like `sam_leave_one_out`, for the angle + features distance."""
    classes = list(dict.fromkeys(picks["class"]))
    spec, f = _pixels(refl, feats)
    flat = picks.row.values * refl.shape[2] + picks.col.values
    spec, f, labels = spec[flat], f[flat], picks["class"].values
    rows = []
    for i in range(len(picks)):
        keep = np.arange(len(picks)) != i
        model = _fit(spec[keep], f[keep], labels[keep], classes)
        d = _distance(model, spec[i:i + 1], f[i:i + 1])[:, 0]
        rows.append({"class": labels[i], "predicted": classes[int(np.argmin(d))],
                     "dist_own": float(d[classes.index(labels[i])])})
    return pd.DataFrame(rows)


def fused_classify(refl: xr.DataArray, feats: dict[str, np.ndarray], picks: pd.DataFrame,
                   max_dist: float) -> np.ndarray:
    """Closest class per pixel by the angle + features distance (y, x); UNCLASSIFIED beyond."""
    classes = list(dict.fromkeys(picks["class"]))
    spec, f = _pixels(refl, feats)
    flat = picks.row.values * refl.shape[2] + picks.col.values
    model = _fit(spec[flat], f[flat], picks["class"].values, classes)
    valid = np.isfinite(spec).all(axis=1) & np.isfinite(f).all(axis=1)
    out = np.full(spec.shape[0], UNCLASSIFIED)
    d = _distance(model, spec[valid], f[valid])
    best = np.argmin(d, axis=0)
    best[d.min(axis=0) > max_dist] = UNCLASSIFIED
    out[valid] = best
    return out.reshape(refl.shape[1:])


# ---- Confirmation sheet ---------------------------------------------------------------------

FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
AI_FILL = PatternFill("solid", fgColor="5B5B5B")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},60m/data=!3m1!1e3"


ANSWER_COLUMNS = range(6, 11)  # Person: F-H. AI pre-check (not a confirmation): I-J.


def _previous_answers(path: Path) -> dict[tuple, list]:
    """Answers already in a sheet, keyed by (material, lat, lon), so a rerun keeps them."""
    if not path.exists():
        return {}
    ws = load_workbook(path)["Candidates"]
    out = {}
    for r in range(2, ws.max_row + 1):
        key = (ws.cell(r, 2).value, ws.cell(r, 3).value, ws.cell(r, 4).value)
        values = [ws.cell(r, c).value for c in ANSWER_COLUMNS]
        if key[0] and any(v not in (None, "") for v in values):
            out[key] = values
    return out


def write_sheet(picks: pd.DataFrame, path: Path) -> Path:
    """Confirmation sheet. Answers for candidates that were already in `path` are kept."""
    previous = _previous_answers(path)
    wb = Workbook()
    _instructions(wb.active)
    ws = wb.create_sheet("Candidates")
    headers = ["#", "Proposed material", "Latitude", "Longitude", "Open in Google Maps",
               "Is the whole 30 m square this material?", "If not, what is it?", "Notes",
               "AI pre-check (NOT a confirmation)", "AI pre-check note"]
    widths = [5, 20, 11, 11, 20, 30, 24, 40, 26, 50]
    for col, (h, w) in enumerate(zip(headers, widths, strict=True), start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEADER_FILL if col <= 8 else AI_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = w
    ws.row_dimensions[1].height = 32
    answer = DataValidation(type="list", formula1='"' + ",".join(ANSWERS) + '"', allow_blank=True)
    choices = ",".join([*CLASSES, "Shadow", "Other"])
    other = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True)
    ws.add_data_validation(answer)
    ws.add_data_validation(other)
    for i, p in enumerate(picks.to_dict("records"), start=1):
        r = i + 1
        values = [i, p["class"], round(p["lat"], 6), round(p["lon"], 6), "Open satellite view"]
        for col, v in enumerate(values, start=1):
            ws.cell(row=r, column=col, value=v)
        ws.cell(row=r, column=5).hyperlink = maps_link(p["lat"], p["lon"])
        for col in (6, 7, 8):
            ws.cell(row=r, column=col).fill = INPUT_FILL
        answer.add(ws.cell(row=r, column=6))
        other.add(ws.cell(row=r, column=7))
        kept = previous.get((p["class"], round(p["lat"], 6), round(p["lon"], 6)), [])
        for col, v in zip(ANSWER_COLUMNS, kept, strict=False):
            ws.cell(row=r, column=col, value=v)
        for col in range(1, 11):
            cell = ws.cell(row=r, column=col)
            cell.border = BOX
            cell.font = Font(name=FONT, color="0563C1", underline="single") if col == 5 \
                else Font(name=FONT, italic=True, color="555555") if col > 8 else Font(name=FONT)
    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _instructions(ws: object) -> None:
    ws.title = "How to fill in"
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 80
    lines = [
        ("CoolCairo: spectral library check", None),
        ("", None),
        ("What this is", "We build reference spectra for east Cairo's materials from EnMAP "
         "(30 m pixels). Each row is a pixel the computer thinks is ONE material only. Please "
         "confirm by eye. Only confirmed pixels go into the library."),
        ("Time needed", "About 30-45 minutes for 60 rows."),
        ("Steps", "1. Easiest: open candidates.kml in Google Earth (desktop or web): every "
         "candidate is drawn as its exact 30 m square, labelled with its row number.\n"
         "2. Or click 'Open satellite view' in the sheet: the pixel is the 30 m square at the "
         "centre of the map (about the size of a 10-storey building's footprint).\n"
         "3. Choose in the yellow column whether the WHOLE square is the proposed material.\n"
         "4. If not, say what it is, and add a note (e.g. 'half roof, half street')."),
        ("Be strict", "'Yes' only if you would bet the whole square is that material. Mixed "
         "pixels spoil the library; rejecting a good pixel costs little."),
        ("Imagery date", "EnMAP scene: 22 April 2025. If the imagery shows construction since "
         "then, say so in the notes."),
        ("AI pre-check", "The grey columns I-J hold a first look by Claude (AI) at Esri World "
         "Imagery. It is NOT a confirmation: please still fill the yellow column yourself. Look "
         "carefully at rows marked Mostly, No or Unsure; for rows marked Yes a glance is enough."),
        ("", None),
        ("Materials", None),
        *[(k, v) for k, v in CLASS_HELP.items()],
    ]
    for r, (a, b) in enumerate(lines, start=1):
        ca = ws.cell(row=r, column=1, value=a)
        ca.font = Font(name=FONT, bold=True, size=14 if r == 1 else 11)
        ca.alignment = Alignment(vertical="top")
        if b is not None:
            cb = ws.cell(row=r, column=2, value=b)
            cb.font = Font(name=FONT)
            cb.alignment = Alignment(wrap_text=True, vertical="top")


def write_kml(picks: pd.DataFrame, crs: str, path: Path) -> Path:
    """Each candidate as its exact 30 m pixel square, for Google Earth."""
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    colours = {SAND: "ff5ab4f0", PALE_ROOF: "ffffffff", DUSTY_ROOF: "ff7896b4",
               ASPHALT: "ffff00ff", VEGETATION: "ff00c800"}  # aabbggrr
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           "<name>CoolCairo spectral library candidates (EnMAP 30 m pixels)</name>"]
    for cls, colour in colours.items():
        out.append(f'<Style id="s{CLASSES.index(cls)}"><LineStyle><color>{colour}</color>'
                   "<width>3</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>")
    for i, p in enumerate(picks.to_dict("records"), start=1):
        cls, x, y = p["class"], p["x"], p["y"]
        corners = [(x - 15, y - 15), (x + 15, y - 15), (x + 15, y + 15),
                   (x - 15, y + 15), (x - 15, y - 15)]
        coords = " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in
                          (to_wgs.transform(cx, cy) for cx, cy in corners))
        out.append(f"<Placemark><name>{i}</name><description>{cls}</description>"
                   f"<styleUrl>#s{CLASSES.index(cls)}</styleUrl><Polygon><outerBoundaryIs>"
                   f"<LinearRing><coordinates>{coords}</coordinates></LinearRing>"
                   "</outerBoundaryIs></Polygon></Placemark>")
    out.append("</Document></kml>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


PERSON_COLUMN, AI_PRECHECK_COLUMN = 6, 9


def read_sheet(path: Path, picks: pd.DataFrame, column: int = PERSON_COLUMN) -> pd.DataFrame:
    """Candidates joined with the answers in `column`; `accepted` marks library pixels.

    The default is the person's confirmation (column F). `AI_PRECHECK_COLUMN` (I) gives a
    provisional library before anyone has checked the candidates.
    """
    ws = load_workbook(path)["Candidates"]
    answers = [ws.cell(r, column).value for r in range(2, len(picks) + 2)]
    out = picks.reset_index(drop=True).copy()
    out["answer"] = answers
    out["accepted"] = out.answer.isin(ACCEPT)
    return out


def library_from_sheet(refl: xr.DataArray, checked: pd.DataFrame) -> pd.DataFrame:
    """Library spectra from confirmed pixels only, plus a near-zero shade spectrum."""
    lib = class_spectra(refl, checked[checked.accepted])
    lib["Shade"] = 0.01  # Flat, near zero: photometric shade endmember for unmixing.
    return lib
