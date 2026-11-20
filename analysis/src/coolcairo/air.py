"""Air-temperature check: Landsat surface temperature against a weather station, scene by scene.

The heat model uses land SURFACE temperature. People feel AIR temperature, which satellites do not
measure. East Cairo has one weather station with hourly data for 2023-2025 (Cairo International
Airport, NOAA Integrated Surface Database), so block-to-block air differences cannot be checked;
what can be checked is whether the satellite's hot-surface mornings are also hot-air mornings,
and how much hotter the surfaces are than the air at the same time.

Station data: NOAA NCEI Global Hourly (ISD), public files on the NOAA Open Data Dissemination
bucket (no account). Downloaded once per year into the git-ignored data cache.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import odc.stac
import pandas as pd
import xarray as xr
from odc.geo.geobox import GeoBox
from pyproj import Transformer

from coolcairo import stac
from coolcairo.config import DATA_DIR, Config

ISD_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com/{year}/{station}.csv"
# ISD quality codes for suspect or erroneous values (all others are kept).
ISD_BAD_QUALITY = {"2", "3", "6", "7"}


def parse_isd_temperature(tmp: pd.Series) -> pd.Series:
    """ISD 'TMP' field ('+0310,1' = 31.0 deg C, quality 1) to deg C; missing or suspect -> NaN."""
    parts = tmp.astype(str).str.split(",", n=1, expand=True)
    value = pd.to_numeric(parts[0], errors="coerce")
    quality = parts[1] if parts.shape[1] > 1 else pd.Series("", index=tmp.index)
    bad = (value.abs() >= 9999) | quality.isin(ISD_BAD_QUALITY)
    return (value / 10).where(~bad)


def station_hourly(station: str, years: list[int], cache: Path = DATA_DIR / "air") -> pd.DataFrame:
    """Air temperature (deg C) with UTC times for one ISD station."""
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    for year in years:
        path = cache / f"{station}_{year}.csv"
        if not path.exists():
            urllib.request.urlretrieve(ISD_URL.format(year=year, station=station), path)
        df = pd.read_csv(path, usecols=["DATE", "TMP"], dtype=str)
        frames.append(pd.DataFrame({"time": pd.to_datetime(df.DATE),
                                    "air_c": parse_isd_temperature(df.TMP)}))
    out = pd.concat(frames).dropna().sort_values("time").reset_index(drop=True)
    return out


def _projected(tr: Transformer, box: list[float]) -> tuple[float, float, float, float]:
    x0, y0 = tr.transform(box[0], box[1])
    x1, y1 = tr.transform(box[2], box[3])
    return x0, y0, x1, y1


def scene_lst(cfg: Config, station_lonlat: tuple[float, float], radius_m: float) -> pd.DataFrame:
    """Per-scene median surface temperature: display district, model area, around the station."""
    cache = DATA_DIR / "air" / "lst_per_scene.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["overpass_utc"])
    tr = Transformer.from_crs("EPSG:4326", cfg.crs, always_xy=True)
    model = cfg["model_aoi"]["bbox_wgs84"]
    lon, lat = station_lonlat
    pad = 0.01  # The station sits just outside the model area's corner.
    box = [min(model[0], lon - pad), min(model[1], lat - pad),
           max(model[2], lon + pad), max(model[3], lat + pad)]
    geobox = GeoBox.from_bbox(_projected(tr, box), crs=cfg.crs, resolution=cfg.pixel_size)
    items = stac.search(cfg, stac.LANDSAT_COLLECTION, box, stac.LANDSAT_QUERY)
    ds = odc.stac.load(items, bands=["lwir11", "qa_pixel"], geobox=geobox, groupby="solar_day",
                       resampling={"qa_pixel": "nearest", "*": "bilinear"}, chunks={"time": 1})
    clear = (ds.qa_pixel & stac.LANDSAT_QA_REJECT_MASK) == 0
    lst = (ds.lwir11.where((ds.lwir11 > 0) & clear) * stac.LANDSAT_ST_SCALE
           + stac.LANDSAT_ST_OFFSET - 273.15).compute()

    overpass: dict[pd.Timestamp, pd.Timestamp] = {}
    for it in items:
        t = pd.Timestamp(it.datetime).tz_convert(None)
        overpass.setdefault(t.normalize(), t)

    sx, sy = tr.transform(lon, lat)
    near_station = np.hypot(lst.x - sx, lst.y - sy) <= radius_m

    def inside(a: xr.DataArray, b: list[float]) -> xr.DataArray:
        x0, y0, x1, y1 = _projected(tr, b)
        return a.where((a.x >= x0) & (a.x <= x1) & (a.y >= y0) & (a.y <= y1))

    rows = []
    for t in lst.time.values:
        day = pd.Timestamp(t).normalize()
        a = lst.sel(time=t)
        rows.append({"date": day.date(), "overpass_utc": overpass.get(day),
                     "lst_district_c": float(inside(a, cfg["display_aoi"]["bbox_wgs84"]).median()),
                     "lst_model_area_c": float(inside(a, model).median()),
                     "lst_station_c": float(a.where(near_station).median())})
    out = pd.DataFrame(rows).dropna(subset=["overpass_utc", "lst_district_c"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(cache, index=False)
    return out


def air_check(cfg: Config) -> tuple[pd.DataFrame, dict]:
    """Scene-by-scene table and summary (offset surface - air, correlation across mornings)."""
    c = cfg["air_check"]
    st = c["station"]
    scenes = scene_lst(cfg, (st["lon"], st["lat"]), c["station_radius_m"])
    air = station_hourly(st["id"], cfg["dates"]["years"])

    idx = np.searchsorted(air.time.to_numpy(), scenes.overpass_utc.to_numpy())
    rows = []
    for (_, s), i in zip(scenes.iterrows(), idx, strict=True):
        cand = air.iloc[max(0, i - 1):i + 1]
        if cand.empty:
            continue
        gap = (cand.time - s.overpass_utc).abs()
        best = cand.loc[gap.idxmin()]
        same_day = air[(air.time.dt.normalize() == s.overpass_utc.normalize())
                       & air.time.dt.hour.between(*c["daytime_hours_utc"])]
        rows.append({**s.to_dict(), "air_time_utc": best.time,
                     "gap_min": round(gap.min().total_seconds() / 60),
                     "air_c": best.air_c,
                     "air_daytime_max_c": same_day.air_c.max() if len(same_day) else np.nan})
    table = pd.DataFrame(rows)
    used = table[table.gap_min <= c["max_gap_min"]].copy()

    def stats(col: str) -> dict:
        diff = used[col] - used.air_c
        return {"n": int(diff.notna().sum()),
                "offset_mean_c": round(float(diff.mean()), 1),
                "offset_sd_c": round(float(diff.std()), 1),
                "r_air_at_overpass": round(float(used[col].corr(used.air_c)), 2),
                "r_air_daytime_max": round(float(used[col].corr(used.air_daytime_max_c)), 2)}

    summary = {
        "station": st["name"], "station_id": st["id"],
        "n_scenes": int(len(used)), "n_scenes_dropped": int(len(table) - len(used)),
        "first": str(used.date.min()), "last": str(used.date.max()),
        "air_at_overpass_mean_c": round(float(used.air_c.mean()), 1),
        "air_daytime_max_mean_c": round(float(used.air_daytime_max_c.mean()), 1),
        "district": stats("lst_district_c"),
        "model_area": stats("lst_model_area_c"),
        "around_station": stats("lst_station_c"),
    }
    return table, summary
