"""One-off: building outlines from Overture Maps over a city's model area, to fill OSM gaps.

Overture's buildings theme merges OpenStreetMap with machine-learned outlines (Google Open
Buildings, Microsoft ML Building Footprints, Esri). The pipeline keeps OSM's own footprints and
adds only the machine-learned ones that do not overlap them (buildings.fill_footprints).
Licence: ODbL v1.0 (Overture buildings theme), like the OSM extract.

Needs only `duckdb` (not part of the analysis environment): run it once with any Python that has
it, e.g.  python -m venv ovenv && ovenv/Scripts/pip install duckdb
          ovenv/Scripts/python fetch_footprints.py config/aoi.yaml ../data/footprints
It writes overture_buildings_<release>_<city>.csv.gz (hex WKB + sources + height), which is
committed so results do not change with each monthly Overture release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb

RELEASE = "2026-11-18.0"
SOURCE = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=buildings/type=building/*.parquet"


def model_bbox(config: Path) -> list[float]:
    """The model area's [min_lon, min_lat, max_lon, max_lat] (read without PyYAML)."""
    text = config.read_text(encoding="utf-8")
    block = text[text.index("model_aoi:"):]
    nums = re.search(r"bbox_wgs84:\s*\[([^\]]+)\]", block).group(1)
    return [float(v) for v in nums.split(",")]


def main(config: Path, out_dir: Path) -> None:
    w, s, e, n = model_bbox(config)
    city = "cairo" if config.name == "aoi.yaml" else config.stem.removeprefix("aoi_")
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"overture_buildings_{RELEASE}_{city}.csv.gz"
    con.execute(f"""
        COPY (
            SELECT id,
                   list_distinct([src.dataset FOR src IN sources]) AS datasets,
                   list_max([src.confidence FOR src IN sources]) AS confidence,
                   height, num_floors,
                   hex(geometry::BLOB) AS wkb_hex
            FROM read_parquet('{SOURCE}', hive_partitioning = false)
            WHERE bbox.xmin < {e} AND bbox.xmax > {w} AND bbox.ymin < {n} AND bbox.ymax > {s}
        ) TO '{out.as_posix()}' (HEADER, COMPRESSION gzip)
    """)
    rows = con.execute(f"SELECT count(*) FROM read_csv('{out.as_posix()}')").fetchone()[0]
    print(f"wrote {out} ({rows} buildings, release {RELEASE})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
