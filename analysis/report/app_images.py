"""Downloads the images the app's globe shows for each live city, so the app needs no network
for them: the Sentinel-2 fly-in close-up and one archive preview per satellite source, rendered
by the Planetary Computer Data API exactly as the app requests them live.

Run from analysis/:  python report/app_images.py
Writes unity/Assets/CoolCairo/Resources/Districts/<key>/flyin.png and preview_<satellite>.png.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "unity" / "Assets" / "CoolCairo" / "Resources" / "Districts"
DATA_BBOX = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/"
CITIES = {"cairo": REPO / "export" / "district.json",
          **{k: REPO / "export" / k / "district.json" for k in ("casablanca", "algiers", "dubai", "riyadh")}}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch(url: str, path: Path, tries: int = 3) -> bool:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                path.write_bytes(r.read())
            return True
        except Exception as e:  # noqa: BLE001 - report and retry any network error
            print(f"  retry {attempt + 1} for {path.name}: {e}", flush=True)
            time.sleep(3)
    return False


def main(only: list[str]) -> None:
    for key, src in CITIES.items():
        if only and key not in only:
            continue
        d = json.loads(src.read_text(encoding="utf-8"))
        folder = OUT / key
        folder.mkdir(parents=True, exist_ok=True)
        f = d.get("flyIn") or {}
        if f.get("item") and len(f.get("bbox", [])) == 4:
            box = ",".join(str(v) for v in f["bbox"])
            url = f"{DATA_BBOX}{box}/1024x1024.png?collection={f['collection']}&item={f['item']}&{f['query']}"
            ok = fetch(url, folder / "flyin.png")
            print(key, "flyin", "ok" if ok else "FAILED", flush=True)
        box = ",".join(str(v) for v in d["previewBbox"])
        for s in d["sources"]:
            if s.get("itemUrl") or not s.get("previewQuery"):
                continue  # EnMAP: metadata only, no preview image (licence, login)
            url = (f"{DATA_BBOX}{box}/256x256.png?collection={s['collection']}"
                   f"&item={s['sceneIds'][-1]}&{s['previewQuery']}")
            ok = fetch(url, folder / f"preview_{slug(s['satellite'])}.png")
            print(key, s["satellite"], "ok" if ok else "FAILED", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
