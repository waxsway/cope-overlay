"""Template matching: identify units (and items) on a captured board image.

Approach: for each known unit sprite in data/sprites/, compute matchTemplate
score against the captured region. Take the best-scoring sprite per board cell.

Tuning: thresholds in config.UNIT_MATCH_THRESHOLD. Calibration script saves
per-cell coordinates so we don't waste time scanning the whole image.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import config


@dataclass
class UnitDetection:
    unit_name: str
    confidence: float
    cell_row: int
    cell_col: int


@dataclass
class BoardSnapshot:
    units: list[UnitDetection]
    raw_image_path: Optional[Path] = None

    def unit_names(self) -> list[str]:
        return [d.unit_name for d in self.units]


_NON_UNIT_SLUGS = {
    "training_dummy", "tome_of_traits", "mercenary_chest", "rift_scuttler",
    "golem", "the_mighty_mech",  # Mech is technically a unit but transforms — exclude for now
    "mini_black_hole", "timebreakercore",
}
_NON_UNIT_PREFIXES = ("artifact_item_", "completed_item_", "component_", "support_item_",
                      "cosmic_")  # "cosmic_*" are board mechanics / boss units, not draftable champs


def _is_unit_sprite(slug: str) -> bool:
    """Filter to actual draftable champions; exclude items, dummies, board features."""
    if slug in _NON_UNIT_SLUGS:
        return False
    return not any(slug.startswith(p) for p in _NON_UNIT_PREFIXES)


def _load_sprite_library() -> dict[str, np.ndarray]:
    """Loads all unit sprites as grayscale templates keyed by unit name.
    Excludes non-champion sprites (anvils, dummies, board features)."""
    library: dict[str, np.ndarray] = {}
    if not config.SPRITES_DIR.exists():
        return library
    for sprite_path in config.SPRITES_DIR.glob("*.png"):
        slug = sprite_path.stem
        if not _is_unit_sprite(slug):
            continue
        img = cv2.imread(str(sprite_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        library[slug] = img
    return library


_SPRITE_CACHE: dict[str, np.ndarray] | None = None


def sprite_library() -> dict[str, np.ndarray]:
    global _SPRITE_CACHE
    if _SPRITE_CACHE is None:
        _SPRITE_CACHE = _load_sprite_library()
    return _SPRITE_CACHE


def _board_cell_regions(image_shape: tuple[int, int]) -> list[tuple[int, int, int, int, int, int]]:
    """Return list of (row, col, y0, y1, x0, x1) cell rectangles.

    Without calibration, naively divides the image into BOARD_ROWS × BOARD_COLS.
    Calibration JSON can override with explicit cell rectangles.
    """
    h, w = image_shape[:2]
    cal = _load_calibration()
    if cal and "cells" in cal:
        return [
            (c["row"], c["col"], c["y0"], c["y1"], c["x0"], c["x1"])
            for c in cal["cells"]
        ]
    cell_h = h // config.BOARD_ROWS
    cell_w = w // config.BOARD_COLS
    cells = []
    for row in range(config.BOARD_ROWS):
        for col in range(config.BOARD_COLS):
            y0 = row * cell_h
            y1 = y0 + cell_h
            x0 = col * cell_w
            x1 = x0 + cell_w
            cells.append((row, col, y0, y1, x0, x1))
    return cells


def _load_calibration() -> dict | None:
    if not config.CALIBRATION_PATH.exists():
        return None
    return json.loads(config.CALIBRATION_PATH.read_text())


def _slug(name: str) -> str:
    import re
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[\s-]+", "_", s)


def _load_specific_icons(name_list: list[str], icons_dir) -> dict[str, np.ndarray]:
    """Load just the icons we care about (not all 3000 items). Faster matching."""
    library: dict[str, np.ndarray] = {}
    for name in name_list:
        slug = _slug(name)
        path = icons_dir / f"{slug}.png"
        if path.exists():
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                library[name] = img
    return library


def recognize_augments(image: np.ndarray, augment_names: list[str]) -> list[tuple[str, float]]:
    """Split the augment-select region into 3 horizontal cards, find best-matching
    augment icon in each. Returns [(name_or_None, confidence)] x3."""
    library = _load_specific_icons(augment_names, config.ITEMS_DIR)
    if not library:
        return [(None, 0.0)] * 3

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    card_w = w // 3
    results: list[tuple[str, float]] = []

    for i in range(3):
        x0 = i * card_w
        x1 = x0 + card_w
        # Augment icon sits in the top half of each card.
        card = gray[: h // 2, x0:x1]
        if card.size == 0:
            results.append((None, 0.0))
            continue
        best_name, best_score = None, -1.0
        for aug_name, template in library.items():
            th, tw = template.shape[:2]
            scale = min(card.shape[0] / th, card.shape[1] / tw, 1.0)
            if scale <= 0:
                continue
            resized = cv2.resize(template, (max(1, int(tw * scale)), max(1, int(th * scale))))
            if resized.shape[0] > card.shape[0] or resized.shape[1] > card.shape[1]:
                continue
            res = cv2.matchTemplate(card, resized, cv2.TM_CCOEFF_NORMED)
            _, mx, _, _ = cv2.minMaxLoc(res)
            if mx > best_score:
                best_score = mx
                best_name = aug_name
        if best_name and best_score >= config.AUGMENT_MATCH_THRESHOLD:
            results.append((best_name, float(best_score)))
        else:
            results.append((None, float(best_score)))
    return results


def recognize_shop(image: np.ndarray) -> list[tuple[str, float]]:
    """Split the shop into 5 horizontal slots, identify each unit (or None for empty/locked).
    Returns [(unit_slug_or_None, confidence)] x5."""
    library = sprite_library()
    if not library:
        return [(None, 0.0)] * 5

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    slot_w = w // 5
    results: list[tuple[str, float]] = []

    for i in range(5):
        x0 = i * slot_w
        x1 = x0 + slot_w
        slot = gray[:, x0:x1]
        if slot.size == 0:
            results.append((None, 0.0))
            continue
        best_name, best_score = None, -1.0
        for unit_name, template in library.items():
            th, tw = template.shape[:2]
            scale = min(slot.shape[0] / th, slot.shape[1] / tw, 1.0)
            if scale <= 0:
                continue
            resized = cv2.resize(template, (max(1, int(tw * scale)), max(1, int(th * scale))))
            if resized.shape[0] > slot.shape[0] or resized.shape[1] > slot.shape[1]:
                continue
            res = cv2.matchTemplate(slot, resized, cv2.TM_CCOEFF_NORMED)
            _, mx, _, _ = cv2.minMaxLoc(res)
            if mx > best_score:
                best_score = mx
                best_name = unit_name
        if best_name and best_score >= config.SHOP_MATCH_THRESHOLD:
            results.append((best_name, float(best_score)))
        else:
            results.append((None, float(best_score)))
    return results


def recognize_board(image: np.ndarray) -> BoardSnapshot:
    """Scan each board cell, return best-matching unit per cell above threshold.

    Adds two filters to reduce false positives:
    - Margin check: best match must beat 2nd-best by config.UNIT_MATCH_MARGIN.
      Reduces "any sprite matches noise" cases (background pixels picking some
      random unit at borderline confidence).
    - Deduplication: each unit can only be claimed once. If two cells match the
      same unit, the higher-confidence cell wins (the loser tries its 2nd-best).
    """
    library = sprite_library()
    if not library:
        return BoardSnapshot(units=[])

    gray_full = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Per-cell top-3 candidates, so we can fall back if a winner gets dedup'd
    candidates: list[tuple[int, int, list[tuple[str, float]]]] = []

    for row, col, y0, y1, x0, x1 in _board_cell_regions(image.shape):
        cell = gray_full[y0:y1, x0:x1]
        if cell.size == 0:
            continue
        scores: list[tuple[str, float]] = []
        for unit_name, template in library.items():
            th, tw = template.shape[:2]
            if th < 8 or tw < 8 or th > cell.shape[0] or tw > cell.shape[1]:
                scale = min(cell.shape[0] / th, cell.shape[1] / tw, 1.0)
                if scale <= 0:
                    continue
                resized = cv2.resize(template, (max(1, int(tw * scale)), max(1, int(th * scale))))
            else:
                resized = template
            if resized.shape[0] > cell.shape[0] or resized.shape[1] > cell.shape[1]:
                continue
            res = cv2.matchTemplate(cell, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            scores.append((unit_name, float(max_val)))

        scores.sort(key=lambda x: x[1], reverse=True)
        if not scores:
            continue
        # Margin check on the per-cell top vs runner-up
        if len(scores) > 1 and scores[0][1] - scores[1][1] < config.UNIT_MATCH_MARGIN:
            continue  # ambiguous; skip this cell
        candidates.append((row, col, scores[:3]))

    # Dedup: highest-confidence claim wins each unit name globally.
    # Cells whose top pick is taken fall back to 2nd or 3rd choice (if also above threshold + margin).
    claimed: dict[str, tuple[int, int, float]] = {}
    detections: list[UnitDetection] = []

    # Sort cells by their top score so strongest claims go first
    candidates.sort(key=lambda c: c[2][0][1], reverse=True)

    for row, col, top3 in candidates:
        for name, score in top3:
            if score < config.UNIT_MATCH_THRESHOLD:
                break
            existing = claimed.get(name)
            if existing is None or score > existing[2]:
                # Claim or overtake.
                if existing is not None:
                    # Remove the old detection that previously claimed this name.
                    detections = [d for d in detections if d.unit_name != name]
                claimed[name] = (row, col, score)
                detections.append(UnitDetection(
                    unit_name=name, confidence=score, cell_row=row, cell_col=col,
                ))
                break

    return BoardSnapshot(units=detections)
