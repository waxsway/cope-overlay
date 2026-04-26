"""Per-user settings stored in data/user_config.json (gitignored).

Friends sharing the project keep their personal data (player name, optional
region tweaks, Tesseract path overrides) out of the shared repo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config

_USER_CONFIG_PATH = config.DATA_DIR / "user_config.json"

DEFAULTS = {
    "player_name": "",          # in-game riot name (used by OCR self-detection)
    "tesseract_cmd": "",        # override config.TESSERACT_CMD if set
    "scout_region_override": None,  # optional dict {left,top,right,bottom} — pixels
    "friends": [],              # list of friends' Riot names (e.g. ["Nate#NA1", ...])
                                # When a friend is on the same carry as your top rec,
                                # contest weighs 3x → recommender pivots harder so you
                                # don't all force the same comp and contest each other.
}


def load() -> dict:
    """Returns user config dict. Creates from defaults if missing."""
    if not _USER_CONFIG_PATH.exists():
        save(DEFAULTS)
        return dict(DEFAULTS)
    try:
        data = json.loads(_USER_CONFIG_PATH.read_text(encoding="utf-8"))
        # Ensure all default keys exist
        for k, v in DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULTS)


def save(data: dict) -> None:
    _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USER_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_value(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)


def player_name() -> str:
    """Returns the configured player name (preferred over the legacy
    config.MY_PLAYER_NAME constant)."""
    name = (load().get("player_name") or "").strip()
    if name:
        return name
    return getattr(config, "MY_PLAYER_NAME", "") or ""


def tesseract_cmd() -> str:
    cmd = (load().get("tesseract_cmd") or "").strip()
    if cmd:
        return cmd
    return getattr(config, "TESSERACT_CMD", "") or ""


def is_first_run() -> bool:
    """True if user_config.json doesn't exist OR player_name is blank."""
    if not _USER_CONFIG_PATH.exists():
        return True
    return not player_name()


def friends() -> list[str]:
    """Return the configured friends list (lowercase for matching)."""
    raw = load().get("friends") or []
    if isinstance(raw, str):
        raw = [raw]
    return [f.strip().lower() for f in raw if isinstance(f, str) and f.strip()]


def is_friend(name: str) -> bool:
    """Case-insensitive substring match against the configured friend list."""
    if not name:
        return False
    target = name.lower()
    for f in friends():
        if f and (f in target or target in f):
            return True
    return False
