"""Build the methodology report PDF from the pipeline.

    cd analysis
    uv run python report/build_report.py

Every number is computed by compute.py from the same code the notebooks and the app export use;
figures are drawn by figures.py; app screenshots come from `CoolCairo.exe -screenshots <folder>`.
Output: docs/CoolCairo_Methodology_Report.pdf (figures in docs/report/figures).
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    Image as RLImage,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).parent))
from compute import Results, compute  # noqa: E402
from figures import all_figures  # noqa: E402

from coolcairo.config import REPO_ROOT  # noqa: E402

OUT_PDF = REPO_ROOT / "docs" / "CoolCairo_Methodology_Report.pdf"
FIG_DIR = REPO_ROOT / "docs" / "report" / "figures"
SHOT_DIR = REPO_ROOT / "docs" / "report" / "screenshots"
ENMAP_CREDIT = "Contains modified EnMAP data © DLR [2025]"

INK, MUTED, ACCENT, RULE, SHADE = (colors.HexColor(c) for c in
                                   ("#1f2328", "#5f6670", "#2a78d6", "#d9dbde", "#f3f5f8"))

FONTS = Path("C:/Windows/Fonts")
for name, file in (("Arial", "arial.ttf"), ("Arial-Bold", "arialbd.ttf"),
                   ("Arial-Italic", "ariali.ttf"), ("Arial-BoldItalic", "arialbi.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic",
                              boldItalic="Arial-BoldItalic")

BODY = ParagraphStyle("body", fontName="Arial", fontSize=9.5, leading=13.6, textColor=INK,
                      spaceAfter=5, alignment=TA_LEFT)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10.5, textColor=MUTED)
CAPTION = ParagraphStyle("caption", parent=SMALL, spaceBefore=3, spaceAfter=10)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.3, leading=10.8, spaceAfter=0)
CELL_HEAD = ParagraphStyle("cellhead", parent=CELL, fontName="Arial-Bold")
H1 = ParagraphStyle("h1", parent=BODY, fontName="Arial-Bold", fontSize=15, leading=19,
                    spaceBefore=14, spaceAfter=7, keepWithNext=1)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Arial-Bold", fontSize=11, leading=14,
                    spaceBefore=9, spaceAfter=4, keepWithNext=1)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Arial-Bold", fontSize=30, leading=34)
SUBTITLE = ParagraphStyle("subtitle", parent=BODY, fontSize=13, leading=18, textColor=MUTED)

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
TEXT_W = PAGE_W - 2 * MARGIN


def m(v: float, d: int = 2) -> str:
    """Number with a true minus sign."""
    s = f"{v:,.{d}f}"
    return s.replace("-", "−")


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(t), leftIndent=12, value="•") for t in items],
                        bulletType="bullet", start="•", leftIndent=12, bulletFontSize=9)


def table(rows: list[list[str]], widths: list[float], shade_first_col: bool = False) -> Table:
    data = [[p(c, CELL_HEAD if i == 0 else CELL) for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=[w * TEXT_W for w in widths], repeatRows=1, hAlign="LEFT")
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if shade_first_col:
        style.append(("BACKGROUND", (0, 1), (0, -1), SHADE))
    t.setStyle(TableStyle(style))
    return t


def figure(path: Path, width: float, caption: str) -> KeepTogether:
    with Image.open(path) as im:
        w, h = im.size
    img = RLImage(str(path), width=width, height=width * h / w)
    img.hAlign = "LEFT"
    return KeepTogether([img, p(caption, CAPTION)])


def callout(paragraphs: list[str]) -> Table:
    t = Table([[[p(x) for x in paragraphs]]], colWidths=[TEXT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SHADE), ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def screenshot_grid(shots: list[tuple[str, str]]) -> Table:
    col_w = (TEXT_W - 6 * mm) / 2
    cells = []
    for name, caption in shots:
        with Image.open(SHOT_DIR / name) as im:
            w, h = im.size
        img = RLImage(str(SHOT_DIR / name), width=col_w, height=col_w * h / w)
        cells.append([img, p(caption, CAPTION)])
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    t = Table(rows, colWidths=[col_w + 3 * mm] * 2, hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "analysis/src",
                                "analysis/config"], cwd=REPO_ROOT, capture_output=True,
                               text=True).stdout.strip()
        return out.stdout.strip() + (" (with uncommitted analysis changes)" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def on_page(canvas, doc) -> None:
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 12 * mm, "CoolCairo · Methodology report · Team 46")
    canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, str(doc.page))
    canvas.setStrokeColor(RULE)
    canvas.line(MARGIN, 15 * mm, PAGE_W - MARGIN, 15 * mm)
    canvas.restoreState()


def story(r: Results, figs: dict[str, Path]) -> list:
    cfg, f, c = r.cfg, r.fit, r.fit.coefficients
    e, t, dl = r.exposure, r.targeted, r.deltas
    by_sat = Counter()
    for s in r.district["sources"]:
        by_sat[s["satellite"]] += len(s.get("sceneIds", []))
    n_landsat = by_sat["Landsat 8"] + by_sat["Landsat 9"]
    n_s2 = by_sat["Sentinel-2A"] + by_sat["Sentinel-2B"] + by_sat["Sentinel-2C"]
    years = cfg["dates"]["years"]
    period = f"June–August {years[0]}–{years[-1]}"
    hs = r.height_shares
    hv = r.heights
    sep = {row["features"]: row for row in r.separability.to_dict("records")}
    bsi_acc = sep["Sentinel-2, BSI index only (rule in use)"]["balanced_accuracy"]
    s2_acc = sep["Sentinel-2, 6 bands"]["balanced_accuracy"]
    en_sim = sep["EnMAP reduced to Sentinel-2 bands"]["balanced_accuracy"]
    en_full = sep["EnMAP full spectrum"]["balanced_accuracy"]
    en_bands = sep["EnMAP full spectrum"]["n_features"]
    h = r.heat_r2
    gr, gcfg = r.growth, cfg["growth"]
    g0, g1 = gr["first"], gr["last"]
    gam, gad = gr["area_model"], gr["area_display"]
    gheat = gr["heat"]
    gnew = gr["blocks"][gr["blocks"].transition == "Built 2016-2023"]
    gsens = gr["sensitivity"]
    osm_missing = float((gnew.roof_frac < 0.05).mean())
    a = r.adoption
    d = r.display
    caps = cfg["interventions"]
    cr, cp = cfg["cool_roof"], cfg["cool_pavement"]
    fly = r.district["flyIn"]
    m2 = r.m2
    if m2["checked"]:
        m2_text = (f"{m2['points']} stratified random points (5 per class) were compared with "
                   "Google Maps satellite imagery (Airbus, 2026). "
                   f"{m2['checked']} could be judged; the interim classes agree at "
                   f"{m2['agreement']:.0%} of them. The two misses are a dusty asphalt road and a "
                   "dusty concrete roof labelled bare sand (the model already counts soil-like "
                   "pixels inside building footprints as pale roofs). The two points that could not be judged were "
                   "a shadowed gap and a mixed edge. The check was done by an AI assistant that "
                   "could see the pipeline's labels, so it is not blind; the sheet "
                   "(<i>docs/m2_spot_check.xlsx</i>) records what was seen at every point for "
                   "review.")
    else:
        m2_text = (f"The sheet with {m2['points']} stratified random points is ready "
                   "(<i>docs/m2_spot_check.xlsx</i>) but has not been filled in yet, so no agreement "
                   "figure is reported. This report reads the sheet automatically when it is rebuilt.")

    m2_short = (f"{m2['agreement']:.0%} agreement" if m2["checked"]
                else "no agreement figure yet")
    s: list = []
    # ---------------------------------------------------------------- title page
    s += [Spacer(1, 38 * mm), p("CoolCairo", TITLE), Spacer(1, 4 * mm),
          p("Block-level urban heat decision support for MENA cities, starting with Nasr City, "
            "Cairo", SUBTITLE),
          Spacer(1, 2 * mm), p("Methodology report", SUBTITLE), Spacer(1, 14 * mm),
          callout([
              "<b>Problem statement.</b> We want to <b>map</b> summer heat risk (land surface "
              "temperature, the surface materials driving it, and the residents exposed to it) in "
              "<b>fast-growing cities across the Middle East and North Africa</b>, starting with "
              f"<b>Nasr City, Cairo</b> ({period}) as the first example, so that <b>city planners</b> "
              "can <b>decide which blocks to prioritise for cool roofs, street trees, cool pavements "
              "and pocket parks</b>."]),
          Spacer(1, 14 * mm),
          table([
              ["", ""],
              ["Event", "Arab Youth Space Hackathon 2026 (UAE Space Agency / Space42)"],
              ["Challenge", "813 Challenge: Urban Expansion, Land Use Change &amp; Heat Risk"],
              ["Team", "Team 46: Dr. Liquaa Mahmoud (team lead), Eng. Mohamed Esmat (technical lead), "
               "Eng. Mahmoud Abu Zaid (data & hyperspectral analyst)"],
              ["Deliverables", "Windows desktop app, reproducible Python analysis (notebooks 00–06), "
                               "this report, slides, demo video (youtu.be/DZX2JM0CVOk)"],
              ["Report built", f"{date.today():%d %B %Y} from commit {git_commit()}"],
          ], [0.2, 0.8], shade_first_col=True),
          PageBreak()]

    # ---------------------------------------------------------------- 1 summary
    s += [p("1  Summary", H1),
          p("Cities across the Middle East and North Africa sit on desert and grow fast; Cairo's "
            "eastern districts are a clear case. Summer surfaces there routinely pass 45 °C, but "
            "heat is not even: it follows what the ground is made of. CoolCairo turns open "
            "satellite data into a planning tool that answers one question per city block: <i>how "
            "hot is it, why, how many people live there, and what would a cooling measure "
            "change?</i> Nasr City is the first district built and tested; the free, region-wide "
            "data lets the same method run in any city."),
          p("We measure summer land surface temperature (LST) with Landsat 8/9, map surface "
            "materials with Sentinel-2, add building footprints and heights (OpenStreetMap, Google "
            "Open Buildings) and residents (WorldPop), and aggregate everything to 90 m blocks. A "
            "linear model links block temperature to materials and building height; published "
            "albedo physics and our model give the effect of four cooling measures. A Windows "
            "desktop app shows the district in 3D and lets a planner paint measures onto blocks "
            "and read the result live. We also tested whether EnMAP hyperspectral data adds value."),
          p("<b>Key results</b>"),
          bullets([
              f"<b>Heat model:</b> spatially cross-validated R² <b>{f.r2_spatial_cv:.2f}</b>, mean "
              f"absolute error ±{f.mae_spatial_cv:.1f} °C, {f.n_blocks:,} urban blocks, 1 km tiles "
              "held out together.",
              f"<b>Heat risk, Nasr City display district:</b> {e.residents:,.0f} residents and "
              f"{e.exposure_person_degC:,.0f} person·°C of heat exposure above the east-Cairo urban "
              f"median ({r.reference_c:.1f} °C).",
              f"<b>Cooling measures at full adoption</b> cut that exposure by "
              f"{-e.cool_roofs_pct:.0f}% (cool roofs), {-e.street_trees_pct:.0f}% (street trees), "
              f"{-e.cool_pavements_pct:.0f}% (cool pavements) and {-e.pocket_parks_pct:.0f}% "
              f"(pocket parks). Targeting cool roofs and pocket parks at the riskiest third of "
              f"blocks alone cuts it by <b>{-t['exposure_change_pct']:.0f}%</b>.",
              f"<b>Urban growth {g0}–{g1}:</b> building footprint area in east Cairo grew "
              f"{100 * (gam[g1] / gam[g0] - 1):.1f}% and {len(gnew):,} blocks turned from desert "
              f"to built-up. These new blocks run about "
              f"{gheat.loc['Built 2016-2023', 'mean_lst_c'] - gheat.loc['Built before 2016', 'mean_lst_c']:.0f} °C "
              "hotter than established neighbourhoods.",
              f"<b>Hyperspectral value:</b> EnMAP block spectra explain block surface temperature at "
              f"R² <b>{h.loc['Our features + EnMAP', 1000]:.2f}</b> (with our features) versus "
              f"{h.loc['Our features + Sentinel-2', 1000]:.2f} with Sentinel-2. For separating "
              "buildings from desert, EnMAP adds nothing beyond a multi-year Sentinel-2 composite.",
          ])]

    # ---------------------------------------------------------------- 2 use case
    s += [p("2  Problem and use case", H1),
          p("<b>Users.</b> City and district planners in MENA cities (first: Cairo Governorate), "
            "and the NGOs and consultancies that prepare greening and retrofit programmes for them."),
          p("<b>Decision.</b> Where to cool first, and with which measure in each block, so surface "
            "temperatures fall where people live, for their health and for the city's environment. "
            "A planner needs to see where heat and people coincide, what drives the heat in each "
            "block, and the expected effect of a measure before acting."),
          p("<b>Why satellites.</b> Field surveys of surface temperature and materials cannot "
            "cover a city block by block every summer. Landsat measures surface temperature every "
            "8 days (two satellites), Sentinel-2 sees materials and vegetation at 10 m every 5 days, "
            "and both archives are free, so the same method repeats each year and in any city."),
          p("<b>Why the MENA region.</b> Its cities share the problem: a desert climate, dark roofs "
            "and asphalt, sandy lots, and fast growth onto the desert. Every dataset used here is "
            "free and covers the whole region, so the method runs in any city. Nasr City is the "
            "first one built and tested; the other cities on the app's globe are the next step, "
            "not a result."),
          p("<b>Why Nasr City first.</b> A dense, planned district with flat concrete roofs, "
            "wide asphalt streets and leftover sandy lots: all four measures apply, and its regular "
            "grid makes block-level results easy to read. It borders open desert, which makes the "
            "material question (pale roof or bare sand?) hard and worth solving.")]

    # ---------------------------------------------------------------- 3 data
    s += [p("3  Study area and data", H1),
          p(f"The model is fitted over east Cairo (Heliopolis, Nasr City, Abbassia; "
            f"{cfg['model_aoi']['bbox_wgs84'][0]}–{cfg['model_aoi']['bbox_wgs84'][2]}° E, "
            f"{cfg['model_aoi']['bbox_wgs84'][1]}–{cfg['model_aoi']['bbox_wgs84'][3]}° N, "
            f"{r.extra['n_blocks_model']:,} blocks) so it sees real variation in materials and "
            f"vegetation. The app shows a Nasr City subset of {d.shape[0]} blocks "
            f"({d.row.max() + 1} × {d.col.max() + 1}) with {r.extra['n_display_buildings']:,} "
            "buildings. All analysis runs in WGS 84 / UTM zone 36N (EPSG:32636)."),
          figure(figs["study_area"], TEXT_W,
                 "<b>Figure 1.</b> Model area. (a) Sentinel-2 summer median true colour; (b) Landsat "
                 "summer median land surface temperature per 90 m block, centred on the urban "
                 "median. Desert and bare ground (orange) are hotter than the built and irrigated "
                 "city (blue). The box marks the district shown in the app."),
          CondPageBreak(60 * mm),
          table([
              ["Source", "Product and selection", "Use", "Licence / attribution"],
              ["Landsat 8/9 (USGS, via Microsoft Planetary Computer)",
               f"Collection 2 Level-2 surface temperature (ST_B10), {period}, cloud cover "
               f"≤ {cfg['max_cloud_cover']}%: {n_landsat} scenes (Landsat 8: {by_sat['Landsat 8']}, "
               f"Landsat 9: {by_sat['Landsat 9']})", "Surface temperature", "Public domain"],
              ["Sentinel-2 L2A (ESA Copernicus, via Planetary Computer)",
               f"Same window: {n_s2} granules (2A: {by_sat['Sentinel-2A']}, 2B: "
               f"{by_sat['Sentinel-2B']}, 2C: {by_sat['Sentinel-2C']}) on "
               f"{r.extra['s2_scenes']} acquisition days; bands B02, B03, B04, B08, B11, B12",
               "Materials, vegetation, imagery", "Contains modified Copernicus Sentinel data "
                                                 f"[{years[0]}–{years[-1]}]"],
              ["EnMAP L2A (DLR EOC Geoservice)",
               f"One scene, {r.district['hyperspectral']['acquired']}, {en_bands} usable bands "
               "(420–2400 nm, water-vapour windows removed)", "Hyperspectral tests",
               f"{ENMAP_CREDIT}. Raw data not redistributed"],
              ["OpenStreetMap (osmnx)", f"{r.extra['n_buildings_model']:,} building footprints, "
               "height and level tags", "Roofs, heights", "© OpenStreetMap contributors, ODbL"],
              ["Google Open Buildings 2.5D Temporal", "Annual layers 2016–2023, 4 m: heights (2023), building presence (growth)",
               "Heights, urban growth", "CC BY 4.0 / ODbL"],
              ["WorldPop Global2 R2025A", "2024, 100 m, constrained", "Residents per block",
               "CC BY 4.0"],
              ["NASA Blue Marble Next Generation", "July 2004; 2.4 km globe, 500 m over Egypt and the Middle East", "Globe in the app", "Public domain"],
          ], [0.21, 0.37, 0.15, 0.27]),
          p("<b>Table 1.</b> Data sources. All satellite data are streamed from public STAC "
            "archives except EnMAP, which needs a free DLR account and is downloaded manually.",
            CAPTION)]

    # ---------------------------------------------------------------- 4 methods
    s += [CondPageBreak(70 * mm), p("4  Methods", H1),
          p("The pipeline is a Python package (<i>analysis/src/coolcairo</i>); notebooks 01–06 are "
            "thin drivers, and every threshold, date and literature value sits in one config file "
            "(<i>analysis/config/aoi.yaml</i>) with its source."),
          p("4.1  Grid and blocks", H2),
          p(f"Rasters share a {cfg['pixel_size']} m analysis grid (Sentinel-2 also on a 10 m grid). "
            f"Every number shown to a user is per <b>{cfg.block_size} m block</b> (3 × 3 Landsat "
            "pixels), close to Landsat's native 100 m thermal resolution, so no result claims "
            "detail the thermal sensor cannot see."),
          p("4.2  Land surface temperature", H2),
          p("We use the USGS Collection 2 Level-2 surface temperature product (already corrected for "
            "atmosphere and emissivity) rather than deriving LST ourselves. Pixels flagged as fill, "
            "cloud, dilated cloud, cirrus or cloud shadow in QA_PIXEL are removed; the per-pixel "
            f"median over all {n_landsat} summer scenes gives a robust typical summer daytime "
            "(about 10:30 local overpass) surface temperature, averaged to blocks."),
          p("4.3  Surface materials", H2),
          p("A transparent rule set classifies each 10 m Sentinel-2 pixel of the summer median "
            "composite (clouds, shadows and saturated pixels removed via the scene "
            "classification layer):"),
          bullets([
              f"<b>Vegetation:</b> NDVI &gt; {cfg['s2_classification']['ndvi_vegetation']}.",
              f"<b>Dark surface</b> (asphalt, dark roofs): mean visible reflectance "
              f"≤ {cfg['s2_classification']['brightness_dark_max']}.",
              f"<b>Bare sand / soil:</b> remaining pixels with Bare Soil Index "
              f"&gt; {cfg['s2_classification']['bsi_soil_min']}.",
              "<b>Pale surface</b> (light concrete, pale roofs): everything else.",
          ]),
          p("Pale roofs and desert sand have the same brightness in Cairo, so brightness alone "
            "cannot separate them. The BSI threshold was chosen as the best single cut between "
            "pixels inside mapped OSM footprints and open ground more than 300 m from any "
            f"footprint: threshold {r.soil['threshold']:.3f}, balanced accuracy "
            f"{r.soil['balanced_accuracy']:.0%} (notebook 02 re-derives it). OSM footprints then "
            "split each class into roof and ground, giving the block shares used by the model: "
            "vegetation, dark roof, pale roof, dark ground and bare sand (soil-like pixels inside a "
            "footprint count as dusty pale roofs)."),
          p("4.4  Buildings and heights", H2),
          p("Heights follow a priority chain: OSM <i>height</i> tag, then OSM <i>building:levels</i> "
            f"× {cfg['storey_height_m']} m, then the median Google Open Buildings 2.5D height inside "
            f"the footprint (at least {cfg['open_buildings_min_pixels']} pixels), then a default of "
            f"{cfg['default_levels']} storeys. Over the model area {hs.get('open_buildings', 0):.0%} "
            f"of buildings take Open Buildings heights, {hs.get('default', 0):.0%} the default and "
            f"{hs.get('osm_height', 0) + hs.get('osm_levels', 0):.1%} OSM tags."),
          p("4.5  Residents and heat exposure", H2),
          p("WorldPop 2024 residents (100 m) are resampled to the 30 m grid by area averaging and "
            "summed per block. <b>Heat risk</b> is the screening indicator <i>residents × degrees "
            "above a reference</i> (person·°C), with the reference set to the median summer LST of "
            f"urban blocks in the model area ({r.reference_c:.2f} °C). Blocks cooler than typical "
            "built-up east Cairo therefore count zero, and the indicator rises with both heat and "
            "people."),
          p("4.6  Heat model", H2),
          p("Block LST is modelled by ordinary least squares on six features: the shares of "
            "vegetation, dark roof, dark ground, bare sand and all roofs, and mean building height. "
            "Only urban blocks (≥ "
            f"{cfg['min_building_coverage']:.0%} roof cover, valid LST) are used, n = {f.n_blocks:,}. "
            "Pale ground is the reference category, so each coefficient is the change in LST when "
            "a whole block switched from pale ground to that surface. A linear model was chosen on "
            "purpose: the app evaluates measures as a weighted sum in real time, and every "
            "coefficient can be read and checked."),
          p(f"Neighbouring blocks share heat, so random cross-validation would leak and inflate R². "
            f"We report <b>spatial cross-validation</b>: blocks are grouped into "
            f"{f.cv_tile_size_m / 1000:.0f} km tiles and whole tiles are held out "
            f"({f.cv_folds}-fold GroupKFold)."),
          p("4.7  Cooling measures", H2),
          p("Landsat LST of a block is close to the area-weighted mean of its surfaces, so each "
            "measure's effect is a <i>per-unit-area</i> temperature change times the share of block "
            "area treated. Where our regression gives a physically plausible value we use it; "
            "where it does not, we use published albedo physics."),
          table([
              ["Measure", "What changes", "Effect per unit block area", "Basis"],
              ["Cool roofs", "Dark and pale roofs coated white (albedo → "
                             f"{cr['albedo_after']})",
               f"{m(dl['cool_roof_dark'])} °C (dark) / {m(dl['cool_roof_pale'])} °C (pale)",
               f"{m(cr['dts_per_albedo'], 1)} K per unit albedo (Wang et al. 2020) × albedo change; "
               f"dark {cr['albedo_dark_roof']} (Cairo study, 2025), pale {cr['albedo_pale_roof']} "
               "(ACPA 2002)"],
              ["Street trees", f"Up to {caps['tree_max_share_of_dark_ground']:.0%} of dark ground "
                               "planted", f"{m(dl['trees'])} °C",
               "Our regression: vegetation minus dark ground"],
              ["Cool pavements", f"Dark ground coated, albedo {cp['albedo_before']} → "
                                 f"{cp['albedo_after']}", f"{m(dl['pavement'])} °C",
               "Same albedo sensitivity as roofs; conservative against a UAE desert field "
               "study (60 → 47 °C)"],
              ["Pocket parks", f"Up to {caps['park_max_share_of_sand']:.0%} of bare sand greened",
               f"{m(dl['park'])} °C", "Our regression: vegetation minus bare sand"],
          ], [0.15, 0.27, 0.2, 0.38]),
          p("<b>Table 2.</b> Cooling measures. Caps are assumptions stated in the app: trees leave "
            "room for traffic, parks leave room for paths and facilities.", CAPTION),
          p("The fitted dark-roof coefficient is negative (dark roofs look <i>cooler</i> than pale "
            "roofs), which is physically implausible and most likely building shadow being "
            "classified as dark roof at 10 m. An automatic sign check flags this and the model "
            "therefore uses the literature value for cool roofs; switching to the regression is "
            "one config line if better material data fixes the sign."),
          p("<b>Cool coatings in practice.</b> Reflective coatings are proven and entering mass "
            "production. A radiative-cooling coating kept container-house roofs about 24 °C cooler "
            "at the surface than concrete in a 2.5-year field trial in Hong Kong and cut "
            "air-conditioning energy by 10% (PolyU 2024); a similar radiative-cooling paint entered "
            "mass production in China in 2026, reported as up to 25 °C cooler on surfaces in a "
            "six-month test (SCMP 2026, citing <i>Science and Technology Daily</i>; not yet "
            "independently verified). These are peak surface temperatures of the coated surface "
            "itself and are not comparable with our block-average summer medians. Such coatings "
            "reflect and emit more than the white paint we model, so our cool-roof effects are "
            "conservative."),
          p("4.8  Does hyperspectral data add value?", H2),
          p("Two controlled tests compare EnMAP with Sentinel-2 on identical pixels, the same "
            "classifier and the same spatial folds, so only the spectra differ. EnMAP is also "
            "reduced to Sentinel-2's six passbands (box-car average) to separate the effect of "
            "spectral detail from that of a different sensor and date."),
          bullets([
              "<b>Built vs desert.</b> 30 m pixels ≥ 90% inside OSM footprints (built, n = "
              f"{r.extra['labels_built']:,}) versus pixels more than 300 m from any footprint and "
              f"not vegetated (open, n = {r.extra['labels_open']:,}); logistic regression with "
              "balanced class weights (PCA to 20 components for EnMAP), balanced accuracy.",
              "<b>Block heat.</b> Mean spectrum per block as predictors of block LST, alone and "
              "added to our model features; ridge regression with the penalty chosen by inner "
              "cross-validation; spatial R² with 1, 2 and 3 km held-out tiles.",
          ])]

    s += [p("4.9  Urban growth", H2),
          p(f"Google Open Buildings 2.5D Temporal gives one building map per year ({g0}–{g1}, "
            "dated 30 June), predicted from Sentinel-2 at an effective 4 m. Its "
            "<i>building presence</i> band is a model confidence from 0 to 1; a pixel counts as "
            f"built at ≥ {gcfg['presence_min']} (values are strongly two-peaked; 0.4 and 0.6 are "
            "reported as a check). Built pixels are averaged to the same 10 m and 90 m grid as "
            "every other layer, giving each block a building cover per year. A block is "
            f"built-up at ≥ {gcfg['built_block_min']:.0%} cover, the model's urban cut-off, so "
            f"blocks fall into <i>built before {g0}</i>, <i>built {g0}–{g1}</i> or <i>still "
            f"open</i>. The app also marks built-up blocks whose cover rose by ≥ "
            f"{gcfg['denser_min'] * 100:.0f} percentage points as <i>denser</i>.")]

    # ---------------------------------------------------------------- 5 results
    coef_rows = [["Feature", "Coefficient", "Reading"],
                 ["Intercept", f"{m(f.intercept)} °C", "Block of pale ground, no buildings"],
                 ["Vegetation share", m(c["veg_frac"]), "Vegetation cools"],
                 ["Dark roof share", m(c["dark_roof_frac"]), "Implausible sign: shadow (see 4.7)"],
                 ["Dark ground share", m(c["dark_ground_frac"]), "About as hot as pale ground"],
                 ["Bare sand share", m(c["soil_frac"]), "Sand is the hottest surface"],
                 ["Roof share", m(c["roof_frac"]), "Pale roofs warmer than pale ground"],
                 ["Mean building height", f"{m(c['mean_height_m'], 3)} per m",
                  "Taller blocks are cooler (shade)"]]
    s += [CondPageBreak(90 * mm), p("5  Results", H1),
          p("5.1  Heat model", H2),
          p(f"The model explains a quarter of the block-to-block variation in held-out areas "
            f"(spatial R² {f.r2_spatial_cv:.2f}; {f.r2_train:.2f} in-sample) with a mean error of "
            f"±{f.mae_spatial_cv:.1f} °C, against a spread of {r.train.lst_c.std():.1f} °C "
            "(standard deviation) between urban blocks. It is good enough to rank drivers and "
            "compare measures, not to predict a single block's temperature exactly; its "
            "predictions are compressed towards the mean (Figure 2)."),
          table(coef_rows, [0.3, 0.2, 0.5]),
          p("<b>Table 3.</b> Fitted coefficients (°C per unit share of block area, or per metre "
            "of height).", CAPTION),
          figure(figs["model_fit"], 0.55 * TEXT_W,
                 "<b>Figure 2.</b> Observed block LST against predictions for blocks in held-out "
                 "1 km tiles."),
          p("5.2  Heat risk in Nasr City", H2),
          p(f"Most of the display district is cooler than the east-Cairo urban median (mean block "
            f"LST {t['mean_lst_before']:.1f} °C against a {r.reference_c:.1f} °C reference). Heat "
            "risk therefore concentrates in a few places: a band along the district's northern "
            "edge, a handful of isolated blocks in the east, and the south-west corner "
            "(Figure 3). These are the blocks a planner would look at first."),
          figure(figs["district"], 0.9 * TEXT_W,
                 "<b>Figure 3.</b> Nasr City display district. (a) Sentinel-2 true colour; (b) "
                 "interim material classes; (c) block LST; (d) heat exposure per block, residents "
                 "× °C above the reference. White blocks in (d) are cooler than the reference."),
          p("5.3  Effect of cooling measures", H2),
          p(f"Averaged over all {f.n_blocks:,} urban blocks, full adoption changes block LST by "
            f"{m(a.loc['mean', 'cool_roofs'])} °C (cool roofs), {m(a.loc['mean', 'street_trees'])} °C "
            f"(street trees), {m(a.loc['mean', 'cool_pavements'])} °C (cool pavements) and "
            f"{m(a.loc['mean', 'pocket_parks'])} °C (pocket parks); the strongest single blocks "
            f"cool by up to {-a.loc['min', 'cool_roofs']:.1f} °C with roofs and "
            f"{-a.loc['min', 'pocket_parks']:.1f} °C with parks. Measured in heat exposure, the "
            "measures matter more than these averages suggest: exposure counts only degrees above "
            "the reference, so one or two degrees of cooling removes most of a hot block's "
            "exposure (Figure 4)."),
          p(f"Targeting is the point of the tool. Cool roofs and pocket parks on only the "
            f"{t['blocks']} riskiest blocks (a third of the district, {t['residents_cooled']:,.0f} "
            f"residents) cut district heat exposure from {t['exposure_before']:,.0f} to "
            f"{t['exposure_after']:,.0f} person·°C (<b>{m(t['exposure_change_pct'], 0)}%</b>), more "
            "than any single measure applied everywhere."),
          figure(figs["interventions"], 0.92 * TEXT_W,
                 "<b>Figure 4.</b> Change in Nasr City heat exposure. Blue: each measure at full "
                 "adoption within its cap in every block. Orange: the targeted plan shown in the "
                 "app screenshots (Section 8)."),
          p("5.4  Value of hyperspectral data", H2),
          p(f"<b>Block heat: EnMAP adds clear value.</b> EnMAP block spectra alone explain block LST "
            f"at R² {h.loc['EnMAP full spectrum', 1000]:.2f}, against "
            f"{h.loc['Sentinel-2 (6 bands)', 1000]:.2f} for Sentinel-2 and "
            f"{h.loc['EnMAP reduced to Sentinel-2 bands', 1000]:.2f} for the same EnMAP scene "
            "reduced to Sentinel-2's bands, so the gain comes from spectral detail, not from the "
            f"sensor or date. Added to our features: {h.loc['Our features + EnMAP', 1000]:.2f} "
            f"versus {h.loc['Our features + Sentinel-2', 1000]:.2f}. The advantage holds with 2 and "
            f"3 km held-out tiles ({h.loc['Our features + EnMAP', 2000]:.2f} and "
            f"{h.loc['Our features + EnMAP', 3000]:.2f} versus "
            f"{h.loc['Our features + Sentinel-2', 2000]:.2f} and "
            f"{h.loc['Our features + Sentinel-2', 3000]:.2f})."),
          figure(figs["hyperspectral"], 0.95 * TEXT_W,
                 "<b>Figure 5.</b> Spatial cross-validated R² of block LST by predictor set and "
                 f"held-out tile size. {ENMAP_CREDIT}."),
          p(f"<b>Built vs desert: EnMAP adds nothing here.</b> The single BSI index reaches a "
            f"balanced accuracy of {bsi_acc:.2f}; all six Sentinel-2 bands reach {s2_acc:.2f}, "
            f"more than EnMAP's full spectrum ({en_full:.2f}) or EnMAP reduced to Sentinel-2 bands "
            f"({en_sim:.2f}). Adding EnMAP to Sentinel-2 changes accuracy from {r.fused[0]:.3f} to "
            f"{r.fused[1]:.3f} (fold spread ±{r.fused[2]:.3f}). A {r.extra['s2_scenes']}-day "
            "Sentinel-2 median beats a single EnMAP date for this task; the remaining confusion is "
            "spatial (mixed pixels), not spectral."),
          p("<b>Decision.</b> The app's materials stay on Sentinel-2, which covers every summer "
            "and every city. EnMAP's value is in explaining heat: the app reports the EnMAP result "
            "with its attribution, and a hyperspectral-based model is the main upgrade path once "
            "more cloud-free summer EnMAP scenes over Cairo exist.")]

    s += [p("5.5  Urban growth and heat", H2),
          p(f"Across the model area, building footprint area grew from {gam[g0]:.1f} km² in {g0} "
            f"to {gam[g1]:.1f} km² in {g1} (<b>+{gam[g1] - gam[g0]:.1f} km², "
            f"+{100 * (gam[g1] / gam[g0] - 1):.1f}%</b>), almost every year (Figure 6b). "
            f"{len(gnew):,} blocks ({len(gnew) * cfg.block_size**2 / 1e6:.1f} km²) changed from "
            f"open land to built-up; WorldPop counts {gr['new_residents']:,.0f} residents in them "
            "in 2024. They are partly scattered infill inside the existing city (single blocks "
            "crossing the 10% cut-off, some of which will be noise) and partly compact new "
            "clusters on the southern desert edge (Figure 6a). Nasr City itself was already "
            "built: its building area rose only "
            f"from {gad[g0]:.2f} to {gad[g1]:.2f} km², mostly by densification."),
          p(f"<b>New development runs hot.</b> Newly built blocks average "
            f"{gheat.loc['Built 2016-2023', 'mean_lst_c']:.1f} °C in summer, against "
            f"{gheat.loc['Built before 2016', 'mean_lst_c']:.1f} °C for blocks built before {g0} "
            f"and {gheat.loc['Still open', 'mean_lst_c']:.1f} °C for open desert (Figure 6c). "
            "Building on sand cools the surface somewhat, but new districts stay about "
            f"{gheat.loc['Built 2016-2023', 'mean_lst_c'] - gheat.loc['Built before 2016', 'mean_lst_c']:.0f} °C "
            "hotter than mature neighbourhoods with their trees and shade, so cooling measures "
            "are best designed in while these areas are still being built. This is a "
            "comparison across places in one period, not a measured change over time."),
          figure(figs["urban_growth"], TEXT_W,
                 f"<b>Figure 6.</b> Urban growth {g0}–{g1} from Google Open Buildings Temporal. "
                 "(a) Block classes, same colours as the app's Growth view; the box marks Nasr "
                 "City. (b) Building footprint area per year. (c) Mean summer LST (2023–25) by "
                 "class, with block counts."),
          table([["Presence cut-off", f"Footprint area {g0}", f"Footprint area {g1}",
                  "Newly built-up blocks"]]
                + [[f"{t:.1f}" + (" (used)" if t == gcfg["presence_min"] else ""),
                    f"{row.area_first:.1f} km²", f"{row.area_last:.1f} km²",
                    f"{row.newly_built_blocks:,.0f}"] for t, row in gsens.iterrows()],
                [0.25, 0.25, 0.25, 0.25]),
          p("<b>Table 4.</b> Sensitivity to the building-presence cut-off: absolute areas "
            "shift, but growth and the number of newly built blocks stay similar.", CAPTION)]

    # ---------------------------------------------------------------- 6 quality
    s += [p("6  Quality control and validation", H1),
          bullets([
              "<b>Spatial cross-validation</b> for every reported R² and accuracy, with tile sizes "
              "of 1 km and, for the hyperspectral tests, 2 and 3 km.",
              "<b>Coefficient sign checks</b> run with every fit: dark roofs warmer than pale "
              "roofs, vegetation cooler than dark ground and than bare sand. A failed check "
              "switches the measure to literature values (the case for cool roofs today).",
              f"<b>Building heights</b> checked against OSM-tagged heights (n = {hv['n']}): bias "
              f"{m(hv['bias_m'], 1)} m, mean absolute error {hv['mae_m']:.1f} m, median "
              f"{hv['median_abs_err_m']:.1f} m, correlation r = {hv['correlation']:.2f}.",
              "<b>Data provenance</b>: the app's start-up screen queries the archives for the exact "
              "scene IDs used here and shows a live preview from each satellite; scene lists are "
              "exported with the data.",
              "<b>Unit tests</b> (pytest) cover classification rules, block aggregation, the model, "
              "intervention arithmetic and the export format.",
              f"<b>Material classes (milestone M2).</b> {m2_text}",
          ])]

    # ---------------------------------------------------------------- 7 limitations
    s += [p("7  Limitations and other measures considered", H1),
          bullets([
              "<b>Surface, not air, temperature.</b> Satellites measure how hot surfaces get, at "
              "about 10:30. Studies suggest city-wide cool roofs lower air temperature by roughly "
              "0.1–0.33 °C per +0.1 roof albedo (Santamouris 2014, cited in Wang et al. 2020); "
              "the effect on air is smaller and spreads beyond the treated blocks.",
              "<b>Block level only.</b> Landsat's thermal band is 100 m, so no per-building "
              "temperature is claimed.",
              f"<b>Modest model fit</b> (spatial R² {f.r2_spatial_cv:.2f}). Effects are averages "
              "for blocks like the treated one, not guarantees for a single block.",
              "<b>Interim material classes.</b> Rules on Sentinel-2 confuse dark roofs with "
              f"shadow and dusty surfaces with sand; the spot check found {m2_short}, from "
              "20 points checked non-blind.",
              "<b>Growth comes from yearly model predictions</b> (Open Buildings Temporal), so "
              "small year-to-year changes are partly noise; only the 2016 → 2023 change is used. "
              f"{osm_missing:.0%} of newly built blocks have almost no OpenStreetMap footprints "
              "yet, so the heat model's roof features under-represent the newest areas.",
              "<b>One EnMAP scene</b> (April, not summer). The hyperspectral result is a strong "
              "signal, not yet a production model.",
              "<b>Heat risk is a screening indicator</b> (heat × residents). It leaves out "
              "vulnerability such as age, housing quality and access to cooling, and WorldPop "
              "counts are modelled, not census.",
              "<b>Costs are not in the app.</b> Researched ranges (Egyptian and international "
              "prices) are in <i>docs/intervention_research.md</i>.",
          ]),
          p("<b>Measures researched and left out of the app.</b> <i>Green roofs</i> cool roofs "
            "strongly but cost about EGP 5,500–11,000 per m² and need irrigation and structural "
            "capacity that most Nasr City roofs lack. <i>Shade sails</i> cool the ground beneath "
            "them sharply, but a satellite sees the sail's hot upper surface, so the effect "
            "cannot be measured or validated with this method. <i>Water features</i> (fountains, "
            "small lakes) were not modelled: their cooling is local, they use scarce water, and "
            "open water was absent from the training blocks.")]

    # ---------------------------------------------------------------- 8 tool
    s += [PageBreak(), p("8  The decision-support tool", H1),
          p("CoolCairo is a Windows desktop app (Unity 6). It loads the exported district "
            "(<i>export/district.json</i>: blocks, buildings, model coefficients, provenance) and "
            "evaluates the same linear model in real time. Screenshots below are captured by the "
            "app itself (<i>CoolCairo.exe -screenshots</i>) from the release build."),
          screenshot_grid([
              ("01_loading.png", "<b>a</b> Satellite archive sync: the app queries Planetary "
                                 "Computer and DLR for the scenes used and shows a live preview "
                                 "from each satellite."),
              ("02_globe.png", "<b>b</b> MENA globe (NASA Blue Marble, 2.4 km). Nasr City is the "
                               "analysed district; other cities show where the method scales next."),
              ("02b_approach.png", "<b>c</b> Approach, ~760 km up: a 500 m Blue Marble image of "
                                   "Egypt and the Middle East keeps the descent sharp."),
              ("03_flyin.png", f"<b>d</b> End of the fly-in: 10 m Sentinel-2 image of Cairo "
                               f"({fly['date']}), Nasr City in the centre."),
              ("05_materials_today.png", "<b>e</b> Materials view: vegetation, dark, pale and "
                                         "sand per block, 3D buildings with estimated heights."),
              ("04_heat_today.png", "<b>f</b> Surface heat view: summer LST per block."),
              ("06_risk_today.png", "<b>g</b> Heat risk view: residents × °C above the "
                                    "reference."),
              ("06b_growth.png", "<b>h</b> Growth view: building cover 2016 → 2023 per block "
                                 "(Google Open Buildings Temporal)."),
              ("07_risk_after_plan.png", "<b>i</b> After a plan (cool roofs and pocket parks on "
                                         "the riskiest third of blocks): live before → after "
                                         "card; coloured rings mark the treated blocks."),
              ("08_heat_after_plan.png", "<b>j</b> Surface heat after the same plan; the ring "
                                         "key is in the legend."),
          ])]

    # ---------------------------------------------------------------- 9 reproducibility
    s += [p("9  Reproducibility", H1),
          p("Everything in this report is rebuilt from code. Python 3.12 dependencies are locked "
            "with uv; satellite data stream from public archives without an account."),
          table([
              ["Step", "Command (in <i>analysis/</i>)"],
              ["Install locked dependencies", "uv sync"],
              ["Unit tests", "uv run pytest"],
              ["Data, model, export for the app", "uv run python run_pipeline.py"],
              ["Notebooks 01–06", "uv run jupyter lab"],
              ["This report", "uv run python report/build_report.py"],
              ["App", "Unity 6000.0.83f1: CoolCairo → Setup project and scene, then Build Windows "
                      "desktop app"],
          ], [0.38, 0.62]),
          Spacer(1, 6),
          p("EnMAP is optional: with a free DLR EOC Geoservice account, download the scene listed in "
            "<i>analysis/config/enmap_scenes.txt</i> into <i>analysis/data/enmap/</i>. Without it "
            "the pipeline runs and skips the hyperspectral results. Raw EnMAP data are not in the "
            "repository (licence).")]

    # ---------------------------------------------------------------- references
    refs = [
        "Wang, Y., Huang, J. &amp; Li, D. (2020). Where are white roofs more effective in cooling "
        "the surface? <i>Geophysical Research Letters</i> 47, e2020GL087853.",
        "The impact of increasing urban surface albedo on outdoor air and surface temperatures "
        "during summer in newly developed areas (2025). <i>Scientific Reports</i>. "
        "doi:10.1038/s41598-025-08574-2.",
        "American Concrete Pavement Association (2002). Albedo: a measure of pavement surface "
        "reflectance. <i>R&amp;T Update</i> 3.05.",
        "Evaluation and thermal performance of cool pavement under desert weather conditions "
        "(2023). <i>Case Studies in Construction Materials</i>. "
        "sciencedirect.com/science/article/pii/S2214509523001195.",
        "Hendel, M. (2024). Cool pavements. arXiv:2409.12242.",
        "Santamouris, M. (2014). Cooling the cities: a review of reflective and green roof "
        "mitigation technologies. <i>Solar Energy</i> 103 (as cited in Wang et al. 2020).",
        "The Hong Kong Polytechnic University (2024). PolyU researchers unveil novel carbon "
        "dots-driven green radiative cooling coating. News release, 24 September 2024. "
        "polyu.edu.hk/rio/news/2024/20240924---polyu-researchers-unveil-novel-carbon-dots-driven-"
        "green-radiative-cooling-coating/",
        "South China Morning Post (2026). Chinese paint cuts wall temperature 25 degrees Celsius "
        "in summer test: report. September 2026. scmp.com/news/china/science/article/3367812.",
        "U.S. Geological Survey. Landsat 8–9 Collection 2 Level-2 Science Product Guide.",
        "Google Research. Open Buildings 2.5D Temporal Dataset.",
        "WorldPop. Global2 R2025A population counts, Egypt 2024, 100 m constrained.",
        "Microsoft Planetary Computer STAC API (Landsat C2 L2, Sentinel-2 L2A).",
        "DLR Earth Observation Center. EnMAP HSI L2A, EOC Geoservice.",
        "Further intervention and cost sources: <i>docs/intervention_research.md</i>.",
    ]
    s += [p("References", H1),
          ListFlowable([ListItem(p(x, SMALL), leftIndent=16) for x in refs], bulletType="1",
                       leftIndent=16, bulletFontName="Arial", bulletFontSize=8),
          Spacer(1, 8),
          p("<b>Data attribution.</b> Contains modified Copernicus Sentinel data "
            f"[{years[0]}–{years[-1]}]. Landsat courtesy of the U.S. Geological Survey. "
            f"{ENMAP_CREDIT}. Building footprints © OpenStreetMap contributors (ODbL). Google Open "
            "Buildings (CC BY 4.0 / ODbL). WorldPop (CC BY 4.0). NASA Blue Marble.", SMALL)]
    return s


def build(out: Path = OUT_PDF) -> Path:
    print("Computing results (cached stages make this quick after the first run)...")
    r = compute()
    print("Drawing figures...")
    figs = all_figures(r, FIG_DIR)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=22 * mm,
                          title="CoolCairo methodology report", author="Team 46",
                          subject="Block-level urban heat decision support for Nasr City, Cairo")
    frame = Frame(MARGIN, 22 * mm, TEXT_W, PAGE_H - MARGIN - 22 * mm, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=on_page)])
    doc.build(story(r, figs))
    print(f"Wrote {out}")
    return out


if __name__ == "__main__":
    build()
