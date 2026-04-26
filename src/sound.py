"""Audio cues. Uses Windows MessageBeep so no sound files needed.

Each cue type maps to a system sound; user hears a distinct beep for each event.
Falls back to silence on non-Windows or if disabled in config.
"""
from __future__ import annotations

import threading

import config

# Windows MB_* constants for distinct system sounds
_BEEP_TYPES = {
    "augment": 0x40,    # Information
    "level": 0x40,
    "pivot": 0x30,      # Exclamation
    "contest": 0x10,    # Hand (stop)
    "info": 0x40,
}


_muted = {"on": False}


def is_muted() -> bool:
    return _muted["on"]


def toggle_mute() -> bool:
    _muted["on"] = not _muted["on"]
    return _muted["on"]


def cue(kind: str) -> None:
    """Fire a non-blocking audio cue. Safe to call from any thread."""
    if _muted["on"]:
        return
    if not getattr(config, "SOUNDS_ENABLED", True):
        return
    flag = _BEEP_TYPES.get(kind, 0x40)

    def _play():
        try:
            import ctypes
            ctypes.windll.user32.MessageBeep(flag)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()
