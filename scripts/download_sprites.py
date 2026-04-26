"""Pull TFT unit + item portraits from Community Dragon.

Community Dragon hosts Riot's raw assets and exposes a TFT JSON index at:
  https://raw.communitydragon.org/latest/cdragon/tft/en_us.json

That JSON lists units with squareIcon paths and items with icon paths. We
download each as PNG into data/sprites/ (units) and data/items/ (items),
named by the unit's display name (lowercased, spaces → underscores).

Run once after install. Re-run when a new set drops (or whenever recognition
quality drops because portraits changed).
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config

INDEX_URL = "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"
ASSET_BASE = "https://raw.communitydragon.org/latest/game/"
USER_AGENT = "tft-overlay/0.1 (personal use)"


def slugify(name: str) -> str:
    name = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[\s-]+", "_", name)


def download(url: str, dest: Path) -> tuple[Path, bool, str]:
    if dest.exists() and dest.stat().st_size > 0:
        return dest, True, "cached"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code != 200:
            return dest, False, f"HTTP {r.status_code}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest, True, "downloaded"
    except Exception as e:
        return dest, False, str(e)


def asset_url(asset_path: str) -> str:
    """Community Dragon expects paths in lowercase, .dds → .png."""
    p = asset_path.lower().replace(".dds", ".png").replace(".tex", ".png")
    if p.startswith("/"):
        p = p[1:]
    return ASSET_BASE + p


def latest_set_units(index: dict) -> tuple[int, list[dict]]:
    """Pick the highest-numbered set in the index and return its units."""
    sets = index.get("sets") or {}
    if not sets:
        # Older index shape uses 'setData'
        set_data = index.get("setData") or []
        if not set_data:
            return 0, []
        latest = max(set_data, key=lambda s: int(s.get("number") or 0))
        return int(latest.get("number") or 0), latest.get("champions") or []
    set_num = max(int(k) for k in sets.keys() if str(k).isdigit())
    return set_num, sets[str(set_num)].get("champions", [])


def latest_items(index: dict) -> list[dict]:
    """Items don't have set numbers — pull all from items list."""
    return index.get("items") or []


def main() -> int:
    print(f"Fetching index from {INDEX_URL} ...")
    r = requests.get(INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    index = r.json()

    set_num, units = latest_set_units(index)
    items = latest_items(index)
    print(f"Found set {set_num} with {len(units)} units, {len(items)} items.")

    config.SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    config.ITEMS_DIR.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, Path]] = []
    for u in units:
        name = u.get("name") or u.get("apiName")
        icon = u.get("squareIcon") or u.get("icon") or u.get("tileIcon")
        if not name or not icon:
            continue
        dest = config.SPRITES_DIR / f"{slugify(name)}.png"
        jobs.append((asset_url(icon), dest))

    for it in items:
        name = it.get("name") or it.get("apiName")
        icon = it.get("icon") or it.get("squareIcon")
        if not name or not icon:
            continue
        dest = config.ITEMS_DIR / f"{slugify(name)}.png"
        jobs.append((asset_url(icon), dest))

    ok = 0
    fail = 0
    cached = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(download, url, dest) for url, dest in jobs]
        for fut in as_completed(futures):
            dest, success, status = fut.result()
            if success:
                ok += 1
                cached += 1 if status == "cached" else 0
            else:
                fail += 1
                print(f"  FAIL {dest.name}: {status}")

    print(f"\nDone: {ok} ok ({cached} cached), {fail} failed.")
    if fail and ok == 0:
        print(
            "\nAll downloads failed. Check that Community Dragon is reachable and that\n"
            "the index URL still resolves. You can also seed sprites manually by\n"
            f"dropping PNGs into {config.SPRITES_DIR}."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
