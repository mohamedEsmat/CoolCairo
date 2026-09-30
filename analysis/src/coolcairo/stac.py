"""Stream Landsat and Sentinel-2 from Microsoft Planetary Computer onto the common grid.

No account or API key is needed: Planetary Computer signs public asset URLs anonymously.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import odc.stac
import planetary_computer
import pystac
import pystac_client
import xarray as xr
from odc.geo.geobox import GeoBox

from coolcairo.config import Config

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Landsat Collection 2 Level-2 surface temperature scaling (USGS product guide).
LANDSAT_ST_SCALE = 0.00341802
LANDSAT_ST_OFFSET = 149.0
# QA_PIXEL bits to reject: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow.
LANDSAT_QA_REJECT_MASK = 0b11111

# Sentinel-2 L2A scene classes to reject: no data, saturated, shadow, cloud (med/high), cirrus.
S2_SCL_REJECT = [0, 1, 3, 8, 9, 10]
S2_BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]

LANDSAT_COLLECTION = "landsat-c2-l2"
LANDSAT_QUERY = {"platform": {"in": ["landsat-8", "landsat-9"]}}
S2_COLLECTION = "sentinel-2-l2a"

# How each satellite's archive preview is rendered by the Planetary Computer data API.
# Landsat is shown as thermal (what we use it for), Sentinel-2 as true colour.
PREVIEW_QUERY = {
    LANDSAT_COLLECTION: "assets=lwir11&rescale=44000,52000&colormap_name=inferno",
    S2_COLLECTION: "assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0",
}
SATELLITE_NAMES = {
    "landsat-8": "Landsat 8",
    "landsat-9": "Landsat 9",
    "Sentinel-2A": "Sentinel-2A",
    "Sentinel-2B": "Sentinel-2B",
    "Sentinel-2C": "Sentinel-2C",
}


def _client() -> pystac_client.Client:
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


def _date_ranges(cfg: Config) -> Iterable[str]:
    months = cfg["dates"]["months"]
    for year in cfg["dates"]["years"]:
        last_day = {2: 28, 4: 30, 6: 30, 9: 30, 11: 30}.get(max(months), 31)
        yield f"{year}-{min(months):02d}-01/{year}-{max(months):02d}-{last_day}"


def search(
    cfg: Config, collection: str, bbox_wgs84: list[float], query: dict | None = None
) -> list[pystac.Item]:
    client = _client()
    items: list[pystac.Item] = []
    for dt in _date_ranges(cfg):
        found = client.search(
            collections=[collection],
            bbox=bbox_wgs84,
            datetime=dt,
            query={"eo:cloud_cover": {"lt": cfg["max_cloud_cover"]}, **(query or {})},
        ).item_collection()
        items.extend(found)
    return items


def landsat_lst(cfg: Config, geobox: GeoBox, bbox_wgs84: list[float]) -> xr.DataArray:
    """Median summer land surface temperature (deg C) from Landsat 8/9 Collection 2 Level-2.

    Uses the USGS surface-temperature product (band ST_B10, `lwir11` on Planetary Computer)
    rather than deriving LST from raw thermal radiance: it is already emissivity- and
    atmosphere-corrected, and it is the product the literature compares against.
    Native thermal resolution is 100 m; the 30 m values are resampled by USGS.
    """
    items = search(cfg, LANDSAT_COLLECTION, bbox_wgs84, LANDSAT_QUERY)
    if not items:
        raise RuntimeError("No Landsat scenes matched the date window and cloud limit.")
    ds = odc.stac.load(
        items,
        bands=["lwir11", "qa_pixel"],
        geobox=geobox,
        groupby="solar_day",
        resampling={"qa_pixel": "nearest", "*": "bilinear"},
        chunks={"time": 1, "x": 2048, "y": 2048},
    )
    clear = (ds.qa_pixel & LANDSAT_QA_REJECT_MASK) == 0
    kelvin = ds.lwir11.where((ds.lwir11 > 0) & clear) * LANDSAT_ST_SCALE + LANDSAT_ST_OFFSET
    lst = (kelvin - 273.15).chunk({"time": -1}).median("time", skipna=True)
    lst = lst.compute()
    lst.name = "lst_c"
    lst.attrs.update(units="degC", scenes=len(ds.time), source="Landsat C2 L2 ST_B10")
    return lst


def _s2_offsets(items: list[pystac.Item], times: np.ndarray) -> xr.DataArray:
    """Per-date DN offset: processing baseline 04.00+ (Jan 2022 on) adds +1000 to reflectance."""
    by_day: dict[np.datetime64, float] = {}
    for item in items:
        day = np.datetime64(item.datetime.date() if item.datetime else None, "D")
        baseline = float(item.properties.get("s2:processing_baseline", "0"))
        by_day[day] = 1000.0 if baseline >= 4.0 else 0.0
    values = [by_day.get(np.datetime64(t, "D"), 1000.0) for t in times]
    return xr.DataArray(values, coords={"time": times}, dims="time")


def sentinel2_composite(cfg: Config, geobox: GeoBox, bbox_wgs84: list[float]) -> xr.Dataset:
    """Median summer surface reflectance (0-1) for the bands used in classification and NDVI."""
    items = search(cfg, S2_COLLECTION, bbox_wgs84)
    if not items:
        raise RuntimeError("No Sentinel-2 scenes matched the date window and cloud limit.")
    ds = odc.stac.load(
        items,
        bands=[*S2_BANDS, "SCL"],
        geobox=geobox,
        groupby="solar_day",
        resampling={"SCL": "nearest", "*": "bilinear"},
        chunks={"time": 1, "x": 2048, "y": 2048},
    )
    clear = ~ds.SCL.isin(S2_SCL_REJECT)
    offsets = _s2_offsets(items, ds.time.values)
    out = xr.Dataset()
    for band in S2_BANDS:
        refl = ((ds[band].where((ds[band] > 0) & clear) - offsets) / 10000.0).clip(0, 1)
        out[band] = refl.chunk({"time": -1}).median("time", skipna=True)
    out = out.compute()
    out.attrs.update(scenes=len(ds.time), source="Sentinel-2 L2A")
    return out


def ndvi(s2: xr.Dataset) -> xr.DataArray:
    result = (s2.B08 - s2.B04) / (s2.B08 + s2.B04)
    result.name = "ndvi"
    return result


def scene_inventory(cfg: Config, bbox_wgs84: list[float]) -> list[dict]:
    """Every archive scene the analysis used, grouped by satellite.

    The desktop app re-queries these exact scene IDs from the archive at startup, so its
    "downloaded / completed" status reflects the real inputs of the analysis.
    """
    per_platform: dict[str, list[pystac.Item]] = {}
    for collection, query in ((LANDSAT_COLLECTION, LANDSAT_QUERY), (S2_COLLECTION, None)):
        for item in search(cfg, collection, bbox_wgs84, query):
            per_platform.setdefault(item.properties["platform"], []).append(item)

    sources = []
    for platform in sorted(per_platform, key=lambda p: list(SATELLITE_NAMES).index(p)):
        items = sorted(per_platform[platform], key=lambda i: i.datetime)
        collection = items[0].collection_id
        sources.append({
            "satellite": SATELLITE_NAMES[platform],
            "collection": collection,
            "use": "Surface temperature" if collection == LANDSAT_COLLECTION
            else "Surface materials, vegetation",
            "sceneIds": [i.id for i in items],
            "firstDate": items[0].datetime.date().isoformat(),
            "lastDate": items[-1].datetime.date().isoformat(),
            "previewQuery": PREVIEW_QUERY[collection],
        })
    return sources


FLY_IN_HALF_SIZE_DEG = 0.12  # ~24 km box: fills the view at the end of the globe fly-in.


def fly_in_image(cfg: Config) -> dict:
    """Sharp true-colour image for the last part of the globe fly-in (Blue Marble is ~7 km/px).

    The clearest Sentinel-2 scene in the date window whose footprint fully covers a box around
    the display district; the app downloads it from the Planetary Computer data API.
    """
    min_lon, min_lat, max_lon, max_lat = cfg["display_aoi"]["bbox_wgs84"]
    cx, cy = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    h = FLY_IN_HALF_SIZE_DEG
    box = [round(cx - h, 5), round(cy - h, 5), round(cx + h, 5), round(cy + h, 5)]
    def covers(item: pystac.Item) -> bool:
        w, s, e, n = item.bbox
        return w <= box[0] and s <= box[1] and e >= box[2] and n >= box[3]

    items = [i for i in search(cfg, S2_COLLECTION, box) if covers(i)]
    if not items:
        raise RuntimeError("No single Sentinel-2 scene covers the fly-in box.")
    best = min(items, key=lambda i: (i.properties["eo:cloud_cover"], -i.datetime.timestamp()))
    return {
        "collection": S2_COLLECTION,
        "item": best.id,
        "date": best.datetime.date().isoformat(),
        "bbox": box,
        "query": PREVIEW_QUERY[S2_COLLECTION],
    }
