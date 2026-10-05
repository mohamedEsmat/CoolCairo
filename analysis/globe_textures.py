"""Make the app's globe textures from NASA Blue Marble Next Generation (July 2004, public domain).

Usage (from /analysis):  uv run python globe_textures.py

Downloads (once, git-ignored, ~98 MB) into data/bluemarble/:
  world.200407.3x21600x10800.jpg     whole world, ~1.9 km/px
  world.200407.3x21600x21600.C1.jpg  tile 0-90 E, 0-90 N, ~500 m/px
Writes into unity/Assets/CoolCairo/Globe/:
  BlueMarble_2004-07_16384.jpg  whole globe at Unity's maximum texture size (~2.4 km/px)
  BlueMarble_2004-07_MENA.jpg   500 m/px patch over Egypt and the Middle East, laid on the
                                globe so the fly-in to Cairo stays sharp (bbox in GlobePatch.cs)
"""

from __future__ import annotations

import urllib.request

from PIL import Image

from coolcairo.config import DATA_DIR, REPO_ROOT

SOURCE = "https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74092/"
WORLD = "world.200407.3x21600x10800.jpg"
TILE_C1 = "world.200407.3x21600x21600.C1.jpg"
C1_WEST, C1_NORTH, PX_PER_DEG = 0.0, 90.0, 240  # Tile C1 spans 0-90 E, 90-0 N.
# Must match GlobePatch.Bbox in Unity: [min_lon, min_lat, max_lon, max_lat].
MENA_BBOX = (20.0, 18.0, 43.0, 40.0)
GLOBE_WIDTH = 16384  # Unity's maximum texture size.
OUT_DIR = REPO_ROOT / "unity" / "Assets" / "CoolCairo" / "Globe"

Image.MAX_IMAGE_PIXELS = None  # The C1 tile is 466 Mpx, above PIL's bomb-check default.


def fetch(name: str) -> object:
    path = DATA_DIR / "bluemarble" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {name}...")
        urllib.request.urlretrieve(SOURCE + name, path)
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(fetch(WORLD)) as im:
        globe = im.resize((GLOBE_WIDTH, GLOBE_WIDTH // 2), Image.LANCZOS)
    globe.save(OUT_DIR / "BlueMarble_2004-07_16384.jpg", quality=90, optimize=True)
    print(f"Globe {globe.size}")

    min_lon, min_lat, max_lon, max_lat = MENA_BBOX
    box = tuple(round(v * PX_PER_DEG) for v in (min_lon - C1_WEST, C1_NORTH - max_lat,
                                                max_lon - C1_WEST, C1_NORTH - min_lat))
    with Image.open(fetch(TILE_C1)) as im:
        patch = im.crop(box)
    patch.save(OUT_DIR / "BlueMarble_2004-07_MENA.jpg", quality=92, optimize=True)
    print(f"MENA patch {patch.size} from C1 pixels {box}")


if __name__ == "__main__":
    main()
