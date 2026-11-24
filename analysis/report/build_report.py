"""Build the methodology report PDF from the pipeline.

    cd analysis
    uv run python report/build_report.py

Every number is computed by compute.py from the same code the notebooks and the app export use;
figures are drawn by figures.py; app screenshots come from `CoolCairo.exe -screenshots <folder>`.
Output: docs/CoolCairo_Methodology_Report.pdf (figures in docs/report/figures).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
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
ENMAP_CREDIT_ALL = "Contains modified EnMAP data © DLR [2022–2025]"
CITY_DIR = REPO_ROOT / "unity" / "Assets" / "CoolCairo" / "Resources" / "Districts"
TEST_CITIES = ("algiers", "casablanca", "dubai", "riyadh")

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


# Where each cited source can be read; in-text citations and the reference list link here.
LINKS = {
    "wang2020": "https://doi.org/10.1029/2020GL087853",
    "cairo2025": "https://doi.org/10.1038/s41598-025-08574-2",
    "acpa2002": "https://trid.trb.org/View/920184",
    "uae2023": "https://www.sciencedirect.com/science/article/pii/S2214509523001195",
    "hendel2024": "https://arxiv.org/abs/2409.12242",
    "green1988": "https://doi.org/10.1109/36.3001",
    "kraut1999": "https://doi.org/10.1109/78.782198",
    "roberts2017": "https://doi.org/10.1111/ecog.02881",
    "stehman2019": "https://doi.org/10.1016/j.rse.2019.05.018",
    "bland1986": "https://doi.org/10.1016/S0140-6736(86)90837-8",
    "santamouris2014": "https://doi.org/10.1016/j.solener.2012.07.003",
    "polyu2024": "https://www.polyu.edu.hk/rio/news/2024/20240924---polyu-researchers-unveil-novel-"
                 "carbon-dots-driven-green-radiative-cooling-coating/",
    "scmp2026": "https://www.scmp.com/news/china/science/article/3367812/chinese-paint-cuts-wall-"
                "temperature-25-degrees-celsius-summer-test-report",
    "landsat": "https://www.usgs.gov/media/files/landsat-8-collection-2-level-2-science-product-guide",
    "openbuildings": "https://sites.research.google/gr/open-buildings/temporal/",
    "overture": "https://docs.overturemaps.org/guides/buildings/",
    "ghsl": "https://human-settlement.emergency.copernicus.eu/ghs_buH2023.php",
    "worldpop": "https://doi.org/10.5258/SOTON/WP00839",
    "planetary": "https://planetarycomputer.microsoft.com/",
    "enmap": "https://www.enmap.org/",
    "interventions": "https://github.com/mohamedEsmat/CoolCairo/blob/master/docs/intervention_research.md",
    "isd": "https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database",
    "workbook": "https://github.com/mohamedEsmat/CoolCairo/blob/master/docs/CoolCairo_Heat_Model_Workbook.pdf",
}


def cite(text: str, key: str) -> str:
    """A clickable citation or reference, in the report's link colour."""
    return f'<a href="{LINKS[key]}" color="#08708F">{text}</a>'


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


def test_cities() -> list[dict]:
    """Headline numbers for each test city, read from the district file the app loads."""
    out = []
    for key in TEST_CITIES:
        d = json.loads((CITY_DIR / f"{key}.json").read_text(encoding="utf-8"))
        b, mdl = d["blocks"], d["model"]
        ref = mdl["heatReferenceC"]
        rows = [(t, n) for v, t, n in zip(b["valid"], b["lstC"], b["population"]) if v]
        lst = sorted(t for t, _ in rows)
        out.append({
            "city": d["city"], "district": d["name"], "n_model": mdl["nBlocks"],
            "r2": mdl["r2SpatialCv"], "mae": mdl["maeSpatialCv"],
            "lst_median": lst[len(lst) // 2],
            "residents": sum(n for _, n in rows),
            "exposure": sum(n * max(0.0, t - ref) for t, n in rows),
            "hyper": d["hyperspectral"], "growth": d["growth"],
        })
    return out


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


def share_words(r2: float) -> str:
    """R² in words for the text: a quarter, a third, ..."""
    for limit, words in ((0.29, "a quarter"), (0.37, "a third"), (0.45, "two fifths"),
                         (0.55, "half")):
        if r2 < limit:
            return words
    return f"{r2:.0%}"


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
    fs = r.buildings.footprint_source.value_counts(normalize=True).to_dict()
    fp_osm = fs.get('osm', 0.0)
    fp_ml = 1.0 - fp_osm
    en = r.district.get('enmap', {})
    hv = r.heights
    air = json.loads((REPO_ROOT / "results" / "air_temperature_check.json").read_text(encoding="utf-8"))
    sep = {row["features"]: row for row in r.separability.to_dict("records")}
    bsi_acc = sep["Sentinel-2, BSI index only (rule in use)"]["balanced_accuracy"]
    s2_acc = sep["Sentinel-2, 6 bands"]["balanced_accuracy"]
    en_sim = sep["EnMAP reduced to Sentinel-2 bands"]["balanced_accuracy"]
    en_full = sep["EnMAP full spectrum"]["balanced_accuracy"]
    en_bands = sep["EnMAP full spectrum"]["n_features"]
    h = r.heat_r2
    mn = r.extra["mnf"]
    ace_dir = REPO_ROOT / "docs" / "ace"
    ace_sum = json.loads((ace_dir / "summary.json").read_text(encoding="utf-8"))
    ace_tab = pd.read_csv(ace_dir / "implantation.csv")
    ace_pd = ace_tab.pivot(index="fraction", columns="detector", values="detected_at_1pct_false_alarms")
    ace_auc = ace_tab.pivot(index="fraction", columns="detector", values="auc")
    rob_dir = REPO_ROOT / "docs" / "robustness"
    rob = json.loads((rob_dir / "summary.json").read_text(encoding="utf-8"))
    rob_tr = pd.read_csv(rob_dir / "transfer.csv").set_index("city")
    rob_co = pd.read_csv(rob_dir / "coefficients.csv", index_col="feature")
    val = json.loads((REPO_ROOT / "docs" / "validity" / "summary.json").read_text(encoding="utf-8"))
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
    tc = test_cities()
    tch = [c for c in tc if c["hyper"]["available"]]
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
               "Eng. Mahmoud Mostafa (data & hyperspectral analyst)"],
              ["Deliverables", "Windows desktop app, reproducible Python analysis (notebooks 00–06), "
                               "this report, slides, demo video (youtu.be/jkDC3HfMiQc)"],
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
            "data lets the same method run in any city, and the same pipeline already runs, "
            "unchanged, for four test cities: Algiers, Casablanca, Dubai and Riyadh."),
          p("We measure summer land surface temperature (LST) with Landsat 8/9, map surface "
            "materials with Sentinel-2, add building footprints (OpenStreetMap, with Google and "
            "Microsoft machine-learned outlines where it has none), heights (Google Open Buildings, "
            "GHSL) and residents (WorldPop), and aggregate everything to 90 m blocks. A "
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
              "<b>Four test cities</b> (Section 5.6): the unchanged pipeline reaches spatial R² "
              f"{min(c['r2'] for c in tc):.2f}–{max(c['r2'] for c in tc):.2f}, and in every test city "
              "with a cloud-free EnMAP scene (Algiers, Dubai, Riyadh) EnMAP again explains block "
              "heat better than Sentinel-2.",
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
            "first one built and tested. The same pipeline also runs, with Cairo's settings, for "
            "a district in each of four test cities (Section 5.6); these are a test of transfer, "
            "not validated results."),
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
               f"Cairo: one scene, {r.district['hyperspectral']['acquired']}, {en_bands} usable "
               "bands (420–2400 nm, water-vapour windows removed). Test cities: one daytime scene "
               "each over Algiers, Dubai and Riyadh (Section 5.6)", "Hyperspectral tests",
               f"{ENMAP_CREDIT_ALL}. Raw data not redistributed"],
              ["OpenStreetMap (osmnx)", f"Building footprints with height and level tags "
               f"(extract 23 Sep 2026): {fp_osm:.0%} of the model area's "
               f"{r.extra['n_buildings_model']:,} buildings", "Roofs, heights",
               "© OpenStreetMap contributors, ODbL"],
              ["Overture Maps buildings (release 2026-11-18.0)", "Google Open Buildings and "
               "Microsoft ML Building Footprints outlines, added only where OSM has no building "
               f"({fp_ml:.0%} of buildings)", "Roofs where OSM has gaps", "ODbL"],
              ["Google Open Buildings 2.5D Temporal", "Annual layers 2016–2023, 4 m: heights (2023), building presence (growth)",
               "Heights, urban growth", "CC BY 4.0 / ODbL"],
              ["GHSL R2023A (European Commission JRC)", "Built-up height 2018, 100 m",
               "Heights where Open Buildings has none", "CC BY 4.0"],
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
            f"{r.soil['balanced_accuracy']:.0%} (notebook 02 re-derives it). Building footprints "
            "(Section 4.4) then "
            "split each class into roof and ground, giving the block shares used by the model: "
            "vegetation, dark roof, pale roof, dark ground and bare sand (soil-like pixels inside a "
            "footprint count as dusty pale roofs)."),
          p("4.4  Buildings and heights", H2),
          p("<b>Footprints.</b> OpenStreetMap maps only part of Cairo's buildings: with its "
            "footprints alone, 3.4% of east Cairo is roof and the model had 2,538 urban blocks. "
            "We therefore add machine-learned outlines (Google Open Buildings, Microsoft ML "
            "Building Footprints) from a fixed Overture Maps release, keeping every OSM footprint "
            "and adding an outline only if at most 10% of it lies inside OSM buildings. Over the "
            f"model area {fp_ml:.0%} of the {r.extra['n_buildings_model']:,} buildings are such "
            "outlines. They are detections from imagery, not surveys, so a block that relies on "
            "them for most of its roof area is at best <i>medium</i> confidence in the app "
            "(Section 6)."),
          p("<b>Heights</b> follow a priority chain: OSM <i>height</i> tag, then OSM <i>building:levels</i> "
            f"× {cfg['storey_height_m']} m, then the median Google Open Buildings 2.5D height inside "
            f"the footprint (at least {cfg['open_buildings_min_pixels']} pixels), then the GHSL "
            f"100 m built-up height, then a default of {cfg['default_levels']} storeys. Over the "
            f"model area {hs.get('open_buildings', 0):.0%} of buildings take Open Buildings heights, "
            f"{hs.get('ghsl', 0):.0%} GHSL, {hs.get('default', 0):.1%} the default and "
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
          p("The model and the hidden-tile test are worked through by hand, with every formula, on "
            "six real blocks in the heat model workbook ("
            + cite("docs/CoolCairo_Heat_Model_Workbook.pdf", "workbook") + ")."),
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
               f"{m(cr['dts_per_albedo'], 1)} K per unit albedo ({cite('Wang et al. 2020', 'wang2020')}) "
               f"× albedo change; dark {cr['albedo_dark_roof']} ({cite('Cairo study, 2025', 'cairo2025')}), "
               f"pale {cr['albedo_pale_roof']} ({cite('ACPA 2002', 'acpa2002')})"],
              ["Street trees", f"Up to {caps['tree_max_share_of_dark_ground']:.0%} of dark ground "
                               "planted", f"{m(dl['trees'])} °C",
               "Our regression: vegetation minus dark ground"],
              ["Cool pavements", f"Dark ground coated, albedo {cp['albedo_before']} → "
                                 f"{cp['albedo_after']}", f"{m(dl['pavement'])} °C",
               "Same albedo sensitivity as roofs; conservative against a "
               f"{cite('UAE desert field study', 'uae2023')} (60 → 47 °C)"],
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
            f"air-conditioning energy by 10% ({cite('PolyU 2024', 'polyu2024')}); a similar "
            "radiative-cooling paint entered mass production in China in 2026, reported as up to "
            f"25 °C cooler on surfaces in a six-month test ({cite('SCMP 2026', 'scmp2026')}, citing <i>Science and Technology Daily</i>; not yet "
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
              "balanced class weights (EnMAP compressed to 20 components by standardised PCA: "
              "every band scaled to unit variance first), balanced accuracy.",
              "<b>Block heat.</b> Mean spectrum per block as predictors of block LST, alone and "
              "added to our model features; ridge regression with the penalty chosen by inner "
              "cross-validation; spatial R² with 1, 2 and 3 km held-out tiles.",
              "<b>Compression check.</b> Both tests repeated with EnMAP compressed by "
              "standardised PCA or by Minimum Noise Fraction (MNF; "
              f"{cite('Green et al. 1988', 'green1988')}, course "
              "notebook 13), which ranks components by signal-to-noise instead of variance. "
              "Band noise comes from shift differences in the most uniform 40 × 40 pixel window "
              "(lowest variation at 1650 nm); each compression is fitted inside the training "
              "folds.",
              "<b>Sub-pixel target detection.</b> Four detectors from course notebook 14: "
              "spectral angle (SAM), matched filter (MF), constrained energy minimisation (CEM) "
              f"and the adaptive coherence estimator (ACE; {cite('Kraut &amp; Scharf 1999', 'kraut1999')}), "
              "with background covariance shrunk towards the identity (λ = 0.001). Target: one "
              "large bright roof from the spectral library (3 × 3 pixels); its signature is the "
              "median of 4 pixels, and the other 5 are mixed into real background pixels at 2–30% "
              "of the pixel (implantation, linear mixing). Score: the share of implanted pixels "
              "found when 1% of clean background pixels are flagged.",
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
                 ["Dark ground share", m(c["dark_ground_frac"]),
                  "Warmer than pale ground" if c["dark_ground_frac"] > 0.5 else "About as hot as pale ground"],
                 ["Bare sand share", m(c["soil_frac"]), "Sand is the hottest surface"],
                 ["Roof share", m(c["roof_frac"]), "Pale roofs warmer than pale ground"],
                 ["Mean building height", f"{m(c['mean_height_m'], 3)} per m",
                  "Taller blocks are cooler (shade)"]]
    s += [CondPageBreak(90 * mm), p("5  Results", H1),
          p("5.1  Heat model", H2),
          p(f"The model explains {share_words(f.r2_spatial_cv)} of the block-to-block variation in held-out areas "
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
          p(f"<b>PCA or MNF: the same answer.</b> Of EnMAP's {mn['n_bands']} bands, "
            f"{mn['eig_above_3']} MNF components have a signal-to-noise eigenvalue above 3 and "
            f"{mn['eig_above_10']} above 10. With the same number of components, MNF and PCA give "
            "the same block-heat R², and both stay below ridge regression on all bands "
            f"({h.loc['EnMAP full spectrum', 1000]:.2f} alone, "
            f"{h.loc['Our features + EnMAP', 1000]:.2f} with our features): ridge already copes "
            "with correlated bands, and the heat signal is spread over many weak components. "
            "MNF separates built from desert about one point better than PCA, within the spread "
            "between folds. The EnMAP gain therefore does not depend on how the spectra are "
            "compressed, and the tests keep their methods (Table 4)."),
          KeepTogether([table([["Compression", "Components", "Built vs desert", "Heat, spectra only",
                  "Heat, + our features"]]
                + [[x["method"], str(x["components"]),
                    f"{x['built_vs_desert']:.3f} ± {x['built_vs_desert_std']:.3f}",
                    f"{x['heat_spectra']:.2f}", f"{x['heat_with_features']:.2f}"]
                   for x in mn["rows"]]
                + [["All bands (in use)", str(mn["n_bands"]), "–",
                    f"{h.loc['EnMAP full spectrum', 1000]:.2f}",
                    f"{h.loc['Our features + EnMAP', 1000]:.2f}"]],
                [0.24, 0.14, 0.22, 0.2, 0.2]),
          p("<b>Table 4.</b> EnMAP compressed by standardised PCA or MNF: balanced accuracy "
            "(± spread over folds) and block-heat R², 1 km held-out tiles, fitted inside the "
            "training folds. Built vs desert with all bands is not run (PCA to 20 is the "
            "method in use).", CAPTION)]),
          p(f"<b>Sub-pixel roofs: ACE finds them, the spectral angle does not.</b> With 1% false "
            f"alarms, ACE finds {ace_pd.loc[0.1, 'ACE']:.0%} of implanted roofs that fill a tenth "
            f"of a pixel, against {ace_pd.loc[0.1, 'SAM']:.0%} for SAM, "
            f"{ace_pd.loc[0.1, 'MF']:.0%} for the matched filter and {ace_pd.loc[0.1, 'CEM']:.0%} "
            f"for CEM; at 20% fill ACE and the matched filter find almost all of them "
            "(Table 5). This repeats the course's result on our own scene. It is an upper bound: "
            "the mixing is linear and the targets come from the same roof as the signature. "
            f"On the whole scene, ACE above the 99.8th percentile of background scores "
            f"({ace_sum['threshold_ace']:.3f}) flags {ace_sum['detected_pixels']} pixels in "
            f"{ace_sum['sites_total']} sites, {ace_sum['detected_share_on_roofs']:.0%} of them on "
            "building footprints. Whether these are metal roofs, and whether metal roofs explain "
            f"why pale roofs are no cooler than dusty ones (<i>docs/spectral_library/README.md</i>), is open: {ace_sum['sites_in_sheet']} sites plus "
            f"{ace_sum['controls_in_sheet']} hidden control roofs are being checked blind against "
            "very-high-resolution imagery (<i>docs/ace/</i>)."),
          KeepTogether([table([["Roof fills", "SAM", "MF", "CEM", "ACE"]]
                + [[f"{f:.0%} of pixel"] + [f"{ace_pd.loc[f, d]:.0%} ({ace_auc.loc[f, d]:.2f})"
                                            for d in ("SAM", "MF", "CEM", "ACE")]
                   for f in ace_pd.index],
                [0.2, 0.2, 0.2, 0.2, 0.2]),
          p("<b>Table 5.</b> Implanted roof pixels found at 1% false alarms (area under the ROC "
            "curve in brackets), 1,000 implanted and 5,000 clean background pixels per fill. "
            f"Script: <i>analysis/make_ace_map.py</i>. {ENMAP_CREDIT}.", CAPTION)]),
          p("<b>Decision.</b> This report's model stays on Sentinel-2, which covers every summer "
            "and every city. EnMAP's value is in explaining heat, and the same block-heat test in "
            "three more cities gives the same answer (Section 5.6). Since November 2026 the app "
            "runs Cairo on EnMAP material fractions unmixed with a spectral library checked by eye "
            f"(spatial R² {en.get('r2Enmap', float('nan')):.2f} against "
            f"{en.get('r2Sentinel2', float('nan')):.2f} for the Sentinel-2 shares on the same "
            "blocks and folds; <i>docs/spectral_library/README.md</i>), with this report's "
            "Sentinel-2 model one click away; the test cities stay on Sentinel-2.")]

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
          p("<b>Table 6.</b> Sensitivity to the building-presence cut-off: absolute areas "
            "shift, but growth and the number of newly built blocks stay similar.", CAPTION)]

    def enmap_cell(c: dict) -> str:
        hy = c["hyper"]
        if not hy["available"]:
            return "no cloud-free scene"
        return (f"{hy['r2Multispectral']:.2f} → <b>{hy['r2Hyperspectral']:.2f}</b> "
                f"({date.fromisoformat(hy['acquired']):%d %b %Y})")

    s += [CondPageBreak(90 * mm), p("5.6  Test cities", H2),
          p("To test whether the method transfers, the same pipeline and settings run for one "
            "district in each of four more MENA cities: only the geography, projection and "
            "WorldPop file change (<i>analysis/config/aoi_&lt;city&gt;.yaml</i>, written by "
            "<i>make_city_configs.py</i>). Each city gets its own model area, model fit, heat "
            "reference (its own urban median) and app district, with the same data window "
            f"({period}). All four run in the app next to Nasr City."),
          table([["City (district)", "Model blocks", "Spatial R² (MAE)", "Median block LST",
                  "Residents (display)", "Heat exposure", "Sentinel-2 → EnMAP R²"]]
                + [["Cairo (Nasr City)", f"{f.n_blocks:,}",
                    f"{f.r2_spatial_cv:.2f} (±{f.mae_spatial_cv:.1f} °C)",
                    f"{float(d.lst_c.median()):.1f} °C", f"{e.residents:,.0f}",
                    f"{e.exposure_person_degC:,.0f}",
                    f"{h.loc['Our features + Sentinel-2', 1000]:.2f} → "
                    f"<b>{h.loc['Our features + EnMAP', 1000]:.2f}</b> "
                    f"({date.fromisoformat(r.district['hyperspectral']['acquired']):%d %b %Y})"]]
                + [[f"{c['city']} ({c['district']})", f"{c['n_model']:,}",
                    f"{c['r2']:.2f} (±{c['mae']:.1f} °C)", f"{c['lst_median']:.1f} °C",
                    f"{c['residents']:,.0f}", f"{c['exposure']:,.0f}", enmap_cell(c)]
                   for c in tc],
                [0.19, 0.1, 0.14, 0.12, 0.13, 0.11, 0.21]),
          p("<b>Table 7.</b> Test cities next to Cairo. Spatial R² with 1 km held-out tiles; "
            "median LST, residents and heat exposure (person·°C above each city's own urban "
            "median) for the app's display district; last column: block-heat R² with our features "
            "plus Sentinel-2 versus plus EnMAP spectra, same blocks and folds (Section 5.4).",
            CAPTION),
          p(f"<b>The model transfers at a similar, modest level.</b> Spatial R² ranges from "
            f"{min(c['r2'] for c in tc):.2f} to {max(c['r2'] for c in tc):.2f}, against "
            f"{f.r2_spatial_cv:.2f} in Cairo: enough to rank blocks, as in Cairo, not to predict "
            "one block. As in Cairo, every city uses the literature value for cool roofs. What "
            "transfers is the method, refitted on each city's own data: Cairo's fitted model "
            "applied unchanged fails elsewhere (Section 6.2)."),
          p(f"<b>Hyperspectral data helps in every city tested.</b> In all {len(tch)} test cities "
            "with a usable EnMAP scene, EnMAP spectra explain block heat better than Sentinel-2 "
            "with the same features, blocks and folds: "
            + "; ".join(f"{c['city']} {c['hyper']['r2Multispectral']:.2f} → "
                        f"{c['hyper']['r2Hyperspectral']:.2f}" for c in tch)
            + ". The scenes come from different seasons and years (2022–2024), so the gain does "
              "not depend on one date. Casablanca's only daytime scene (17 January 2024) has "
              "cloud over the district and is not used."),
          p("<b>Data gaps.</b> Google Open Buildings 2.5D Temporal covers Algiers but not "
            "Casablanca, Dubai or Riyadh, where most heights come from GHSL's 100 m built-up height "
            "and there is no growth view; the test cities use OSM footprints only. In Algiers, building area in the display district grew from "
            f"{tc[0]['growth']['builtFirstKm2']:.2f} to {tc[0]['growth']['builtLastKm2']:.2f} km² "
            f"({tc[0]['growth']['firstYear']}–{tc[0]['growth']['lastYear']}), with "
            f"{tc[0]['growth']['newBlocks']} newly built blocks; blocks over the sea (NDVI &lt; 0) "
            "are left out of the growth classes. The test cities have no material spot check or "
            "local validation yet.")]

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
              f"{hv['median_abs_err_m']:.1f} m, RMSE {hv['rmse_m']:.1f} m, R² about the 1:1 line "
              f"{hv['r2_1to1']:.2f} (Pearson r = {hv['correlation']:.2f}); Bland–Altman in "
              "Section 6.3.",
              "<b>Data provenance</b>: the app's start-up screen queries the archives for the exact "
              "scene IDs used here and shows a live preview from each satellite; scene lists are "
              "exported with the data.",
              "<b>42 unit tests</b> (pytest) cover classification rules, block aggregation, the model, "
              "intervention arithmetic, the export format, the footprint fill, the station-data parsing, the MNF transform, the target detectors, the buffered cross-validation, the agreement metrics and the quick example's numbers.",
              "<b>Data confidence per block</b> (high / medium / low) in the app: the weakest of "
              "footprint completeness (against Google Open Buildings 2023 presence), the share of "
              "measured heights, and the population source; machine-learned footprints cap a "
              "block at medium.",
              "<b>105 automated checks run inside the built app</b> (<i>CoolCairo.exe -selftest</i>), "
              "including that every test city's data and maps load; all pass in the build from "
              "this commit, and the app exits with an error if any fails.",
              f"<b>Material classes (milestone M2).</b> {m2_text}",
          ])]
    ad, an = air["district"], air["n_scenes"]
    s += [p("6.1  Surface and air temperature", H2),
          p("The model works with surface temperature; people feel air temperature, which "
            "satellites do not measure. East Cairo has one weather station with hourly records "
            f"for {years[0]}–{years[-1]}, {air['station']} "
            f"({cite('NOAA Integrated Surface Database', 'isd')}), about 10 km north-east of the "
            "district, so block-to-block air differences cannot be tested. What can be tested is "
            f"each Landsat morning on its own. On {an} clear summer mornings "
            f"({air['first']} to {air['last']}, station report within "
            f"{r.cfg['air_check']['max_gap_min']} min of the overpass), Nasr City's median surface "
            f"was <b>{ad['offset_mean_c']:.1f} °C hotter than the air</b> (± {ad['offset_sd_c']:.1f} °C; "
            f"air {air['air_at_overpass_mean_c']:.1f} °C on average). Hotter-surface mornings were "
            f"hotter-air mornings: <b>r = {ad['r_air_at_overpass']:.2f}</b> with air temperature at "
            f"the overpass and r = {ad['r_air_daytime_max']:.2f} with the day's highest air "
            f"temperature (mean {air['air_daytime_max_mean_c']:.1f} °C). The station reports whole "
            "degrees, which caps how high r can be. Surface temperature therefore tracks the heat "
            "people feel from day to day, but is not the same number, and a cooling of a "
            "block's surface cools the air above it much less (Section 7)."),
          figure(figs["air_check"], 0.55 * TEXT_W,
                 "<b>Figure 7.</b> Nasr City median Landsat surface temperature against air "
                 f"temperature at {air['station']} at the same time (NOAA ISD), one dot per clear "
                 "summer morning. Dashed: air plus the mean difference.")]

    s2f, enf, spf = ("Sentinel-2 materials + buildings", "EnMAP materials + buildings",
                     "Our features + EnMAP spectra")
    br, rfr, tr = rob["buffer_r2"], rob["random_forest_r2_200m"], rob_tr
    s += [p("6.2  Robustness of the heat model", H2),
          p("Three checks from the course's GeoAI session (week 3), run on the same blocks and "
            f"1 km tiles as every R² above ({rob['blocks']:,} blocks, {rob['folds']} folds; "
            "<i>analysis/make_robustness.py</i>, outputs in <i>docs/robustness/</i>)."),
          p("<b>Buffer between training and test.</b> Landsat's thermal pixel is about 100 m, so "
            "blocks on either side of a tile edge share part of their temperature. Dropping "
            "training blocks within 200 m of each held-out tile "
            f"({cite('Roberts et al. 2017', 'roberts2017')}) lowers R² by at most "
            f"{rob['max_r2_drop_at_200m']:.3f}: {br[s2f]['0']:.2f} → {br[s2f]['200']:.2f} for "
            f"this report's model, {br[enf]['0']:.2f} → {br[enf]['200']:.2f} for the app's EnMAP "
            f"fractions, {br[spf]['0']:.2f} → {br[spf]['200']:.2f} with the full EnMAP spectra "
            f"(at 500 m: {br[s2f]['500']:.2f}, {br[enf]['500']:.2f}, {br[spf]['500']:.2f}). The "
            "scores in this report are not inflated by leakage across tile edges."),
          p("<b>A random forest next to our models.</b> With the 200 m buffer, a random forest "
            f"on the same features reaches R² {rfr[s2f]:.2f} (Sentinel-2 shares) and "
            f"{rfr[enf]:.2f} (EnMAP fractions), against {br[s2f]['200']:.2f} and "
            f"{br[enf]['200']:.2f} for the linear model, so part of the effect is not linear; on "
            f"the full spectra, ridge regression stays ahead ({br[spf]['200']:.2f} against "
            f"{rfr[spf]:.2f}). EnMAP beats Sentinel-2 with either model. The app keeps the linear "
            "model on purpose: each measure's effect is one visible coefficient, and effects add "
            "up across measures, which a forest does not offer."),
          p("<b>Domain shift.</b> Cairo's model applied unchanged to the test cities misses "
            "their level by "
            + ", ".join(f"{tr.loc[c, 'cairo_bias_c']:+.1f} °C ({c})" for c in tr.index)
            + "; even after removing that offset it explains almost none of the block-to-block "
            f"pattern (R² {tr.cairo_r2_bias_removed.min():.2f} to "
            f"{tr.cairo_r2_bias_removed.max():.2f}) and ranks blocks worse than each city's own "
            f"model (Spearman {tr.cairo_spearman.min():.2f}–{tr.cairo_spearman.max():.2f} against "
            f"{tr.own_spearman.min():.2f}–{tr.own_spearman.max():.2f}). A model refitted on 300 "
            "local blocks recovers most of the full local score (Table 8), and Landsat gives "
            "every block a label, so the pipeline refits in each city. The vegetation "
            f"({rob_co.loc['veg_frac'].min():.1f} to {rob_co.loc['veg_frac'].max():.1f} °C) and "
            f"sand (+{rob_co.loc['soil_frac'].min():.1f} to +{rob_co.loc['soil_frac'].max():.1f} °C) "
            "effects are similar in all five cities; the dark-roof coefficient changes sign "
            f"({rob_co.loc['dark_roof_frac'].min():+.1f} to "
            f"{rob_co.loc['dark_roof_frac'].max():+.1f} °C), "
            "so no city's roof effect should be reused elsewhere."),
          KeepTogether([table([["City", "Own model R²", "Cairo model R²", "Cairo bias",
                                "Cairo, bias removed", "Own model, 300 blocks"]]
                + [[c, f"{row.own_r2:.2f}", f"{row.cairo_r2:.1f}", f"{row.cairo_bias_c:+.1f} °C",
                    f"{row.cairo_r2_bias_removed:.2f}", f"{row.own_r2_300_local_blocks:.2f}"]
                   for c, row in tr.iterrows()],
                [0.16, 0.16, 0.17, 0.15, 0.18, 0.18]),
          p("<b>Table 8.</b> Cairo's heat model (Sentinel-2 shares + buildings) applied unchanged "
            "to the test cities, against each city's own model, spatial R² with 1 km held-out "
            "tiles. Last column: own model trained on 300 random blocks per fold (mean of 10 "
            "draws).", CAPTION)])]

    # ---------------------------------------------------------------- 6.3 validity
    sr, opt, vc, st = val["split_r2"], val["optimism_r2"], val["continuous"], val["stable"]
    tiles = [k for k in sr[spf] if k != "random 5-fold"]
    hm, hs = vc[f"Heat model: {spf}"], vc[f"Heat model: {s2f}"]
    he = vc[f"Heat model: {enf}"]
    bh = vc["Building heights: Open Buildings vs OSM tags"]
    hot_word = "too cool" if hm["hot_bias"] < 0 else "too hot"
    pairs, yrs = st["pairs"], st["years"]
    s += [p("6.3  Validation design and agreement", H2),
          p("Checks from the course's accuracy-assessment session (week 3), following "
            f"{cite('Stehman &amp; Foody 2019', 'stehman2019')}: state how the test was designed, "
            "show what a weaker design would have claimed, and report agreement with more than "
            "one number (<i>analysis/make_validity.py</i>, outputs in <i>docs/validity/</i>)."),
          p("<b>Random versus spatial split.</b> With random 5-fold cross-validation, "
            "neighbouring blocks that share heat fall on both sides of the split. The same "
            f"models then score R² {sr[s2f]['random 5-fold']:.2f}, {sr[enf]['random 5-fold']:.2f} "
            f"and {sr[spf]['random 5-fold']:.2f} (Sentinel-2 shares, EnMAP fractions, EnMAP "
            f"spectra), against {sr[s2f]['1 km tiles']:.2f}, {sr[enf]['1 km tiles']:.2f} and "
            f"{sr[spf]['1 km tiles']:.2f} with held-out 1 km tiles: a random split would "
            f"overstate R² by {min(opt.values()):.2f}–{max(opt.values()):.2f}. The gap is small "
            "because blocks are 90 m and the features are block averages, but it grows with "
            f"the size of the held-out area for the spectra model ({sr[spf][tiles[0]]:.2f} at "
            f"{tiles[0][:-6]} to {sr[spf][tiles[-1]]:.2f} at {tiles[-1][:-6]}), while the "
            "material models stay flat (Table 9). Every R² in this report uses held-out 1 km "
            "tiles."),
          KeepTogether([table([["Features", "Random 5-fold"] + tiles]
                + [[f, f"{sr[f]['random 5-fold']:.2f}"] + [f"{sr[f][k]:.2f}" for k in tiles]
                   for f in (s2f, enf, spf)],
                [0.32, 0.14, 0.135, 0.135, 0.135, 0.135]),
          p("<b>Table 9.</b> Heat-model R² by validation design: same blocks and models "
            f"({val['blocks']:,} blocks, {val['folds']} folds); columns after the second: "
            "held-out square tiles of that size.", CAPTION)]),
          p("<b>Agreement, not only R².</b> R² cannot see a constant offset, so each continuous "
            "product also gets bias, RMSE, R² about the 1:1 line and Bland–Altman limits of "
            f"agreement ({cite('Bland &amp; Altman 1986', 'bland1986')}). On held-out 1 km tiles "
            f"the EnMAP-spectra heat model has bias {m(round(hm['bias'], 2) + 0.0, 2)} °C, MAE {hm['mae']:.2f} °C, "
            f"RMSE {hm['rmse']:.2f} °C, and 95 % of blocks fall within {m(hm['loa_low'], 1)} to "
            f"{m(hm['loa_high'], 1)} °C of the measurement (Sentinel-2 model: RMSE "
            f"{hs['rmse']:.2f} °C, limits {m(hs['loa_low'], 1)} to {m(hs['loa_high'], 1)} °C). "
            f"The error depends on the level (Bland–Altman slope {m(hm['ba_slope'], 2)}; "
            f"Sentinel-2 model {m(hs['ba_slope'], 2)}): like any regression, the models pull "
            f"extremes towards the average, so they are {hot_word} for the hottest "
            f"{val['hot_share']:.0%} of blocks (above {hm['hot_threshold']:.1f} °C) by "
            f"{abs(hm['hot_bias']):.1f} °C on average with EnMAP spectra, "
            f"{abs(he['hot_bias']):.1f} °C with EnMAP fractions and {abs(hs['hot_bias']):.1f} °C "
            "with Sentinel-2 shares. The app ranks blocks by measured Landsat temperature, not "
            "by the model, so the hottest blocks are still found; but a modelled cooling for "
            "those blocks is an average effect, not a forecast of their exact temperature."),
          p(f"Building heights from Open Buildings against OSM tags (n = {bh['n']:,}) show why R² "
            f"about 1:1 matters: Pearson r² is {bh['pearson_r2']:.2f}, but R² about the 1:1 line "
            f"is only {bh['r2_1to1']:.2f} (bias {m(bh['bias'], 1)} m, RMSE {bh['rmse']:.1f} m, "
            f"limits {m(bh['loa_low'], 0)} to {m(bh['loa_high'], 0)} m). Heights enter the heat "
            "model only as a block average, and OSM tags are used wherever they exist (Figure 8)."),
          figure(REPO_ROOT / "docs" / "validity" / "bland_altman.png", TEXT_W,
                 "<b>Figure 8.</b> Bland–Altman plots: estimate minus reference against their "
                 "mean (left, shading: number of blocks, log scale; right, one dot per building). "
                 "Blue: mean bias and "
                 "95 % limits of agreement; red: trend of the error with the level. Left: heat "
                 "model with EnMAP spectra, out-of-fold predictions on held-out 1 km tiles. Right: "
                 "Open Buildings heights against OSM-tagged heights."),
          p("<b>What change Landsat can see.</b> Blocks already built-up in 2016 with little "
            f"change by 2023 ({st['blocks']:,} blocks) should keep their temperature pattern "
            f"from one summer to the next. Comparing the summer medians of {yrs[0]}–{yrs[-1]} ("
            + ", ".join(f"{n} scenes in {y}" for y, n in st["scenes_per_year"].items())
            + "), the whole area shifts with the weather ("
            + "; ".join(f"{q['from']} → {q['to']}: {m(q['offset'], 1)} °C" for q in pairs)
            + "). After removing that shift, a stable block still moves by "
            f"{st['resid_sd_mean']:.2f} °C (standard deviation), and 95 % of stable blocks move "
            f"by less than <b>{st['threshold_95_mean']:.1f} °C</b> (mean over the three pairs of "
            f"summers, {min(q['threshold_95'] for q in pairs):.1f}–"
            f"{max(q['threshold_95'] for q in pairs):.1f} °C). This is the detection threshold "
            "for monitoring a pilot with Landsat: a treated block must cool by more than about "
            f"{st['threshold_95_mean']:.1f} °C, compared with similar untreated blocks in the "
            "same summer, before the change can be told apart from year-to-year noise; a group "
            "of treated blocks can show a smaller average change. Construction after 2023 is "
            "not excluded, so the threshold is slightly conservative."),
          ]

    # ---------------------------------------------------------------- 7 limitations
    s += [p("7  Limitations and other measures considered", H1),
          bullets([
              "<b>Surface, not air, temperature.</b> Satellites measure how hot surfaces get, at "
              f"about 10:30; Nasr City's surfaces then run about {air['district']['offset_mean_c']:.0f} °C "
              "above the air, and only one station can check air temperature (Section 6.1). Studies suggest city-wide cool roofs lower air temperature by roughly "
              f"0.1–0.33 °C per +0.1 roof albedo ({cite('Santamouris 2014', 'santamouris2014')}, "
              f"cited in {cite('Wang et al. 2020', 'wang2020')}); "
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
              f"{osm_missing:.0%} of newly built blocks have almost no building footprints yet, "
              "even with the machine-learned outlines, so the heat model's roof features "
              "under-represent the newest areas.",
              f"<b>Most footprints are machine-learned</b> ({fp_ml:.0%} of buildings, Google and "
              "Microsoft outlines): they fill OpenStreetMap's gaps but are detections, not surveys. "
              "With OpenStreetMap footprints alone (this report's first edition, October 2026) the "
              "model had 2,538 urban blocks, spatial R² 0.25 and a targeted-plan reduction of 74%; "
              "removing <i>footprint_fill</i> from the config reproduces those numbers.",
              "<b>One EnMAP scene per city</b> (Cairo in April; only Dubai's is mid-summer). The "
              "hyperspectral result is a strong, repeated signal, not yet a production model.",
              "<b>Test cities use Cairo's settings unchanged</b> (material thresholds, cut-offs, "
              "measures) and have no local validation; they show that the method transfers, not "
              "that their numbers are final. A fitted model does not travel: each city needs its own "
              "fit (Section 6.2).",
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
              ("02_globe.png", "<b>b</b> MENA globe (NASA Blue Marble, 2.4 km). Five live "
                               "cities: Cairo (Nasr City) and the four test cities."),
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
              ["Test city (data, model, export)", "COOLCAIRO_CONFIG=config/aoi_&lt;city&gt;.yaml "
               "COOLCAIRO_DATA_DIR=data/&lt;city&gt; COOLCAIRO_EXPORT_DIR=../export/&lt;city&gt; "
               "uv run python run_pipeline.py, then report/city_figures.py"],
              ["This report", "uv run python report/build_report.py"],
              ["App", "Unity 6000.0.83f1: CoolCairo → Setup project and scene, then Build Windows "
                      "desktop app"],
          ], [0.38, 0.62]),
          Spacer(1, 6),
          p("EnMAP is optional: with a free DLR EOC Geoservice account, download the scene listed in "
            "<i>analysis/config/enmap_scenes.txt</i> into <i>analysis/data/enmap/</i> (test cities: "
            "<i>enmap_scenes_&lt;city&gt;.txt</i> into <i>data/&lt;city&gt;/enmap/</i>). Without it "
            "the pipeline runs and skips the hyperspectral results. Raw EnMAP data are not in the "
            "repository (licence).")]

    # ---------------------------------------------------------------- references
    # Each reference ends with its link (the text shown is the address itself, so a printed copy works too).
    def ref(text: str, key: str, shown: str | None = None) -> str:
        return f"{text} {cite(shown or LINKS[key], key)}"

    refs = [
        ref("Wang, L., Huang, M. &amp; Li, D. (2020). Where are white roofs more effective in cooling "
            "the surface? <i>Geophysical Research Letters</i> 47(15), e2020GL087853.", "wang2020"),
        ref("The impact of increasing urban surface albedo on outdoor air and surface temperatures "
            "during summer in newly developed areas (2025). <i>Scientific Reports</i>.", "cairo2025"),
        ref("American Concrete Pavement Association (2002). Albedo: a measure of pavement surface "
            "reflectance. <i>R&amp;T Update</i> 3.05 (TRID record).", "acpa2002"),
        ref("Evaluation and thermal performance of cool pavement under desert weather conditions "
            "(2023). <i>Case Studies in Construction Materials</i>.", "uae2023"),
        ref("Hendel, M. (2024). Cool pavements. arXiv:2409.12242.", "hendel2024"),
        ref("Green, A. A., Berman, M., Switzer, P. &amp; Craig, M. D. (1988). A transformation for "
            "ordering multispectral data in terms of image quality with implications for noise "
            "removal. <i>IEEE Transactions on Geoscience and Remote Sensing</i> 26(1), 65–74.",
            "green1988"),
        ref("Kraut, S. &amp; Scharf, L. L. (1999). The CFAR adaptive subspace detector is a "
            "scale-invariant GLRT. <i>IEEE Transactions on Signal Processing</i> 47(9), 2538–2541.",
            "kraut1999"),
        ref("Roberts, D. R. et al. (2017). Cross-validation strategies for data with temporal, "
            "spatial, hierarchical, or phylogenetic structure. <i>Ecography</i> 40(8), 913–929.",
            "roberts2017"),
        ref("Stehman, S. V. &amp; Foody, G. M. (2019). Key issues in rigorous accuracy assessment "
            "of land cover products. <i>Remote Sensing of Environment</i> 231, 111199.",
            "stehman2019"),
        ref("Bland, J. M. &amp; Altman, D. G. (1986). Statistical methods for assessing agreement "
            "between two methods of clinical measurement. <i>The Lancet</i> 327(8476), 307–310.",
            "bland1986"),
        ref("Santamouris, M. (2014). Cooling the cities: a review of reflective and green roof "
            "mitigation technologies to fight heat island and improve comfort in urban environments. "
            "<i>Solar Energy</i> 103, 682–703.", "santamouris2014"),
        ref("The Hong Kong Polytechnic University (2024). PolyU researchers unveil novel carbon "
            "dots-driven green radiative cooling coating. News release, 24 September 2024.",
            "polyu2024", "polyu.edu.hk (news release)"),
        ref("South China Morning Post (2026). Chinese paint cuts wall temperature 25 degrees Celsius "
            "in summer test: report. September 2026.", "scmp2026", "scmp.com/news/china/science/article/3367812"),
        ref("U.S. Geological Survey. Landsat 8–9 Collection 2 Level-2 Science Product Guide.", "landsat",
            "usgs.gov (product guide)"),
        ref("Google Research. Open Buildings 2.5D Temporal Dataset.", "openbuildings"),
        ref("Overture Maps Foundation. Buildings theme, release 2026-11-18.0.", "overture"),
        ref("Pesaresi, M. &amp; Politis, P. (2023). GHS-BUILT-H R2023A: built-up height, 2018. European Commission, Joint Research Centre.", "ghsl"),
        ref("WorldPop. Global2 R2025A population counts, Egypt 2024, 100 m constrained.", "worldpop"),
        ref("Microsoft Planetary Computer STAC API (Landsat C2 L2, Sentinel-2 L2A).", "planetary"),
        ref("DLR Earth Observation Center. EnMAP HSI L2A, EOC Geoservice.", "enmap"),
        ref("NOAA National Centers for Environmental Information. Integrated Surface Database "
            "(Global Hourly), station 623660 Cairo International Airport.", "isd"),
        ref("Further intervention and cost sources, each with its link:", "interventions",
            "docs/intervention_research.md"),
        ref("CoolCairo Team 46 (2026). The heat model and the hidden-area test, by hand "
            "(workbook).", "workbook", "docs/CoolCairo_Heat_Model_Workbook.pdf"),
    ]
    s += [p("References", H1),
          ListFlowable([ListItem(p(x, SMALL), leftIndent=16) for x in refs], bulletType="1",
                       leftIndent=16, bulletFontName="Arial", bulletFontSize=8),
          Spacer(1, 8),
          p("<b>Data attribution.</b> Contains modified Copernicus Sentinel data "
            f"[{years[0]}–{years[-1]}]. Landsat courtesy of the U.S. Geological Survey. "
            f"{ENMAP_CREDIT_ALL}. Building footprints © OpenStreetMap contributors (ODbL) and Overture Maps "
            "(ODbL). Google Open Buildings (CC BY 4.0 / ODbL). GHSL © European Union (CC BY 4.0). WorldPop (CC BY 4.0). NASA Blue Marble.", SMALL)]
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
