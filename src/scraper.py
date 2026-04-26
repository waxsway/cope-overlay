"""MetaTFT scraper.

Stable layer: fetch_html(), parse_comp_list(), normalize_comp().
Brittle layer: the CSS selectors in parse_comp_list() — MetaTFT redesigns
periodically; when this breaks, fix selectors here, not the rest of the code.

If MetaTFT blocks scraping or you want a different source, swap fetch_html()
to point at lolchess.gg or tactics.tools — same downstream contract.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup

import config
from src import db

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)


def fetch_html(url: str = config.META_SOURCE_URL) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_comp_list(html: str, patch: str = "current") -> list[dict]:
    """Parse MetaTFT's comp index page into our normalized comp dicts.

    NOTE: selectors are best-effort. If MetaTFT changed structure, run this
    in a Python REPL with the HTML and adjust below. The output contract
    is what matters — keep it returning the dict shape db.insert_comp expects.
    """
    soup = BeautifulSoup(html, "lxml")
    comps: list[dict] = []

    # MetaTFT-style comp cards. Update selectors if their markup changes.
    for card in soup.select('[data-testid="comp-card"], .comp-card, article.comp'):
        name_el = card.select_one('.comp-name, h3, [data-field="name"]')
        tier_el = card.select_one('.tier, [data-field="tier"]')
        avg_el = card.select_one('[data-field="avg-place"], .avg-place')
        play_el = card.select_one('[data-field="play-rate"], .play-rate')
        top4_el = card.select_one('[data-field="top4"], .top4-rate')
        unit_els = card.select('[data-unit], .unit-portrait')

        if not name_el or not unit_els:
            continue

        units = []
        for u in unit_els:
            unit_name = u.get("data-unit") or (u.get("alt") or "").strip()
            star = int(u.get("data-star", "2") or 2)
            is_carry = "carry" in (u.get("class") or [])
            if unit_name:
                units.append({"name": unit_name, "star_target": star, "is_carry": is_carry})

        comp = {
            "name": name_el.get_text(strip=True),
            "patch": patch,
            "tier": (tier_el.get_text(strip=True) if tier_el else None),
            "avg_placement": _parse_float(avg_el),
            "play_rate": _parse_pct(play_el),
            "top4_rate": _parse_pct(top4_el),
            "win_rate": None,
            "target_level": _infer_level(card),
            "play_style": _infer_style(card),
            "notes": None,
            "units": units,
            "items": _parse_items(card),
        }
        comps.append(comp)

    return comps


def _parse_float(el) -> float | None:
    if not el:
        return None
    m = re.search(r"[\d.]+", el.get_text())
    return float(m.group()) if m else None


def _parse_pct(el) -> float | None:
    if not el:
        return None
    m = re.search(r"([\d.]+)\s*%?", el.get_text())
    if not m:
        return None
    val = float(m.group(1))
    return val / 100.0 if val > 1 else val


def _infer_level(card) -> int | None:
    txt = card.get_text(" ", strip=True).lower()
    m = re.search(r"level\s*(\d)", txt)
    return int(m.group(1)) if m else None


def _infer_style(card) -> str | None:
    txt = card.get_text(" ", strip=True).lower()
    if "reroll" in txt:
        return "reroll"
    if "fast 8" in txt or "fast-8" in txt:
        return "fast8"
    if "fast 9" in txt or "fast-9" in txt:
        return "fast9"
    return None


def _parse_items(card) -> list[dict]:
    items = []
    for slot in card.select('[data-item], .item-icon'):
        item_name = slot.get("data-item") or (slot.get("alt") or "").strip()
        unit_name = slot.get("data-unit") or ""
        if item_name and unit_name:
            items.append({"unit": unit_name, "item": item_name, "priority": 1})
    return items


def scrape_and_store(patch: str = "current", set_number: int = 0) -> int:
    """Returns count of comps stored. Caller is responsible for handling exceptions."""
    db.init_db()
    html = fetch_html()
    comps = parse_comp_list(html, patch=patch)
    if not comps:
        print(
            "WARNING: scraper returned 0 comps. MetaTFT's HTML may have changed.\n"
            "Either fix selectors in src/scraper.py or use seed_comps.json fallback.",
            file=sys.stderr,
        )
        return 0
    for comp in comps:
        try:
            db.insert_comp(comp)
        except Exception as e:
            print(f"  skip {comp.get('name')!r}: {e}", file=sys.stderr)
    db.upsert_patch(patch, set_number)
    return len(comps)


if __name__ == "__main__":
    n = scrape_and_store()
    print(f"Stored {n} comps.")
