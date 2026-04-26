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
