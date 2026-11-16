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

SAND, PALE_ROOF, DARK_ROOF, ASPHALT, VEGETATION = (
    "Sand / bare ground", "Pale roof", "Dark roof", "Asphalt / paved", "Vegetation")
CLASSES = [SAND, PALE_ROOF, DARK_ROOF, ASPHALT, VEGETATION]
CLASS_HELP = {
    SAND: "Unbuilt sandy or dusty land, desert, empty plots",
    PALE_ROOF: "Light concrete or painted roofs: white, beige, light grey",
    DARK_ROOF: "Dark roofs: bitumen, dark tiles, dark grey concrete, dark metal",
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
    lo, hi = np.nanpercentile(br[pure_roof], [33, 67]) if pure_roof.any() else (0, 0)
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
        DARK_ROOF: pure_roof & (br <= lo),
        ASPHALT: paved_pure & (br <= dark_paved),
    }


def candidates(refl: xr.DataArray, masks: dict[str, np.ndarray], crs: str,
               per_class: int = 12) -> pd.DataFrame:
    """Best `per_class` pixels per class: most homogeneous first, spread `MIN_SPACING_M` apart."""
    angle = neighbour_angle(refl)
    nd, br = ndvi(refl), brightness(refl)
    rows = []
    for cls in CLASSES:
        yy, xx = np.nonzero(masks[cls] & np.isfinite(angle))
        order = np.argsort(angle[yy, xx])
        picked: list[tuple[float, float]] = []
        for k in order:
            x, y = float(refl.x[xx[k]]), float(refl.y[yy[k]])
            if all((x - px) ** 2 + (y - py) ** 2 >= MIN_SPACING_M ** 2 for px, py in picked):
                picked.append((x, y))
                rows.append({"class": cls, "row": int(yy[k]), "col": int(xx[k]), "x": x, "y": y,
                             "homogeneity_deg": round(float(angle[yy[k], xx[k]]), 2),
                             "ndvi": round(float(nd[yy[k], xx[k]]), 3),
                             "brightness": round(float(br[yy[k], xx[k]]), 3),
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


# ---- Confirmation sheet ---------------------------------------------------------------------

FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},60m/data=!3m1!1e3"


def write_sheet(picks: pd.DataFrame, path: Path) -> Path:
    wb = Workbook()
    _instructions(wb.active)
    ws = wb.create_sheet("Candidates")
    headers = ["#", "Proposed material", "Latitude", "Longitude", "Open in Google Maps",
               "Is the whole 30 m square this material?", "If not, what is it?", "Notes"]
    widths = [5, 20, 11, 11, 20, 30, 24, 40]
    for col, (h, w) in enumerate(zip(headers, widths, strict=True), start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
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
        for col in range(1, 9):
            cell = ws.cell(row=r, column=col)
            cell.border = BOX
            cell.font = Font(name=FONT, color="0563C1", underline="single") if col == 5 \
                else Font(name=FONT)
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
    colours = {SAND: "ff5ab4f0", PALE_ROOF: "ffffffff", DARK_ROOF: "ff3c3c3c",
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


def read_sheet(path: Path, picks: pd.DataFrame) -> pd.DataFrame:
    """Candidates joined with the person's answers; `accepted` marks library pixels."""
    ws = load_workbook(path)["Candidates"]
    answers = [ws.cell(r, 6).value for r in range(2, len(picks) + 2)]
    out = picks.reset_index(drop=True).copy()
    out["answer"] = answers
    out["accepted"] = out.answer.isin(ACCEPT)
    return out


def library_from_sheet(refl: xr.DataArray, checked: pd.DataFrame) -> pd.DataFrame:
    """Library spectra from confirmed pixels only, plus a near-zero shade spectrum."""
    lib = class_spectra(refl, checked[checked.accepted])
    lib["Shade"] = 0.01  # Flat, near zero: photometric shade endmember for unmixing.
    return lib
