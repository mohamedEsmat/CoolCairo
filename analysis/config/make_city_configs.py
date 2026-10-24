"""Writes the configs of the cities beyond Cairo from aoi.yaml (24 Oct 2026).

Only geography, CRS, data switches and the WorldPop file change; every threshold and literature
value is Cairo's, so differences in the results come from the city, not the settings.
Districts (~2.2 x 2.2 km, dense residential like Nasr City) were placed from OpenStreetMap
Nominatim centres; model areas (~13 x 13 km) surround them.
Run once from analysis/:  python config/make_city_configs.py
Then each city:  COOLCAIRO_CONFIG=config/aoi_<key>.yaml COOLCAIRO_DATA_DIR=data/<key>
                 COOLCAIRO_EXPORT_DIR=../export/<key> python run_pipeline.py
"""
from pathlib import Path

HERE = Path(__file__).parent

CITIES = {
    # key: (city, district, UTM EPSG, ISO3, display bbox, model bbox, Open Buildings tile list or None)
    "casablanca": ("Casablanca", "Hay Mohammadi", 32629, "MAR",
                   [-7.569, 33.574, -7.545, 33.594], [-7.627, 33.520, -7.487, 33.637], None),
    "algiers": ("Algiers", "Bab El Oued", 32631, "DZA",
                [3.035, 36.772, 3.060, 36.792], [2.990, 36.700, 3.135, 36.817],
                "config/open_buildings_tiles_algiers.txt"),
    "dubai": ("Dubai", "Al Karama", 32640, "ARE",
              [55.294, 25.238, 55.316, 25.258], [55.240, 25.190, 55.370, 25.307], None),
    "riyadh": ("Riyadh", "Al Malaz", 32638, "SAU",
               [46.717, 24.646, 46.739, 24.666], [46.660, 24.600, 46.790, 24.717], None),
}

base = (HERE / "aoi.yaml").read_text(encoding="utf-8")


def swap(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


for key, (city, district, epsg, iso, display, model, tiles) in CITIES.items():
    zone = epsg - 32600
    t = base
    t = swap(t, "# Single source of truth for geography, dates and thresholds.",
             f"# {city} ({district}): written by make_city_configs.py from aoi.yaml; only geography, CRS,\n"
             f"# data switches and the WorldPop file differ from Cairo.")
    t = swap(t, '# Projected CRS for all analysis: WGS 84 / UTM zone 36N (Cairo sits at ~31.2 E).\ncrs: "EPSG:32636"',
             f'# Projected CRS for all analysis: WGS 84 / UTM zone {zone}N.\ncrs: "EPSG:{epsg}"')
    t = swap(t, '  name: "Nasr City"\n  bbox_wgs84: [31.325, 30.050, 31.346, 30.068]',
             f'  name: "{district}"\n  city: "{city}"\n  bbox_wgs84: {display}')
    t = swap(t, "  bbox_wgs84: [31.26, 30.00, 31.40, 30.12]", f"  bbox_wgs84: {model}")
    t = swap(t, "osm_refresh: false", "osm_refresh: true  # no committed extract for this city: live OSM, cached")
    t = swap(t, "/2024/EGY/v1/100m/constrained/egy_pop_2024", f"/2024/{iso}/v1/100m/constrained/{iso.lower()}_pop_2024")
    switches = "\n# Data available for this city (checked 24 Oct 2026).\n"
    switches += "# EnMAP needs a DLR login and a manual download: not processed for this city.\nenmap: false\n"
    if tiles:
        switches += f"# Google Open Buildings 2.5D Temporal covers it: heights and urban growth.\nopen_buildings_tiles: {tiles}\n"
    else:
        switches += ("# No Google Open Buildings 2.5D Temporal tiles here (HDX country lists, 24 Oct 2026):\n"
                     "# heights from OSM tags, else the default; no urban-growth view.\nopen_buildings: false\n")
    (HERE / f"aoi_{key}.yaml").write_text(t + switches, encoding="utf-8")
    print("wrote", f"aoi_{key}.yaml")
