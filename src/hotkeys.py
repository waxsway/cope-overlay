"""Global hotkey wiring. Uses the `keyboard` library — Windows-friendly, no admin
needed for F-keys in most setups. If hotkeys silently don't fire, run the program
as administrator (some games steal raw input from non-elevated processes).
"""
from __future__ import annotations

from typing import Callable

import keyboard

import config


def register_hotkeys(
    on_capture: Callable[[], None],
    on_reset: Callable[[], None],
    on_toggle_overlay: Callable[[], None],
    on_refresh_meta: Callable[[], None],
    on_augment_pick: Callable[[], None],
    on_game_state: Callable[[], None],
    on_shop_scan: Callable[[], None],
    on_compact_toggle: Callable[[], None],
    on_auto_toggle: Callable[[], None],
    on_mute_toggle: Callable[[], None],
    on_click_autoscout: Callable[[], None],
    on_quit: Callable[[], None],
) -> None:
    keyboard.add_hotkey(config.HOTKEY_CAPTURE_SCOUT, _safe(on_capture))
    keyboard.add_hotkey(config.HOTKEY_RESET_ROUND, _safe(on_reset))
    keyboard.add_hotkey(config.HOTKEY_TOGGLE_OVERLAY, _safe(on_toggle_overlay))
    keyboard.add_hotkey(config.HOTKEY_REFRESH_META, _safe(on_refresh_meta))
    keyboard.add_hotkey(config.HOTKEY_AUGMENT_PICK, _safe(on_augment_pick))
    keyboard.add_hotkey(config.HOTKEY_GAME_STATE, _safe(on_game_state))
    keyboard.add_hotkey(config.HOTKEY_SHOP_SCAN, _safe(on_shop_scan))
    keyboard.add_hotkey(config.HOTKEY_COMPACT_TOGGLE, _safe(on_compact_toggle))
    keyboard.add_hotkey(config.HOTKEY_AUTO_TOGGLE, _safe(on_auto_toggle))
    keyboard.add_hotkey(config.HOTKEY_MUTE_TOGGLE, _safe(on_mute_toggle))
    keyboard.add_hotkey(config.HOTKEY_CLICK_AUTOSCOUT, _safe(on_click_autoscout))
    keyboard.add_hotkey(config.HOTKEY_QUIT, _safe(on_quit))


def _safe(fn: Callable[[], None]) -> Callable[[], None]:
    """Wrap callbacks so a single exception doesn't kill the listener."""
    def wrapped():
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"[hotkey error] {e}")
            traceback.print_exc()
    return wrapped
