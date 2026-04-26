"""Screen capture. mss is fast (~30+ fps if you wanted streaming)."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any

import mss
import numpy as np

import config


def get_active_window_title() -> str:
    """Return the foreground window's title (Windows only). Empty string on error."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        return buf.value or ""
    except Exception:
        return ""


def get_active_window_rect() -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of the foreground window, in virtual
    desktop coordinates (which span all monitors). Used to figure out which
    monitor TFT is on when the user has multiple displays."""
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def find_active_monitor_index() -> int:
    """Return the mss monitor index containing the center of the foreground window.
    Falls back to config.CAPTURE_MONITOR (primary) if detection fails."""
    rect = get_active_window_rect()
    if rect is None:
        return config.CAPTURE_MONITOR
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors):
            if i == 0:
                continue  # index 0 = "all monitors combined"
            if m["left"] <= cx < m["left"] + m["width"] and \
               m["top"] <= cy < m["top"] + m["height"]:
                return i
    return config.CAPTURE_MONITOR


def get_active_window_process() -> str:
    """Return the foreground window's process EXE path (Windows only).
    Process names are stable identifiers — title can be spoofed by content
    (e.g. VS Code's title includes file/conversation text)."""
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_process:
            return ""
        try:
            size = wintypes.DWORD(512)
            buf = ctypes.create_unicode_buffer(512)
            # QueryFullProcessImageNameW signature requires DWORD* for size
            ok = kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size))
            return buf.value.lower() if ok else ""
        finally:
            kernel32.CloseHandle(h_process)
    except Exception:
        return ""


def is_tft_active() -> tuple[bool, str]:
    """Check whether TFT/League is the foreground process.

    Returns (is_tft, descriptive_string). Checks the EXE path because window titles
    can match by accident (e.g. our chat about Teamfight Tactics shows up in the
    VS Code window title).
    """
    proc = get_active_window_process()
    title = get_active_window_title()
    is_tft = ("league of legends" in proc) or ("leagueclient" in proc) or ("riotclient" in proc)
    descriptor = f"{title} [{proc.split(chr(92))[-1] if proc else 'unknown'}]"
    return is_tft, descriptor


def load_calibration() -> dict[str, Any] | None:
    if not config.CALIBRATION_PATH.exists():
        return None
    return json.loads(config.CALIBRATION_PATH.read_text())


def grab_full_monitor(monitor_index: int | None = None) -> np.ndarray:
    """Returns BGR numpy array of the entire monitor.
    If monitor_index is None, auto-detects the monitor containing the foreground window."""
    if monitor_index is None:
        monitor_index = find_active_monitor_index()
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        raw = np.array(sct.grab(monitor))
        return raw[:, :, :3]


def _pick_region_preset(width: int, height: int) -> dict:
    """Pick scout region percentage preset based on monitor aspect ratio."""
    aspect = width / max(height, 1)
    if aspect >= 3.0:
        return config.SCOUT_REGION_PCT_32_9
    if aspect >= 2.1:
        return config.SCOUT_REGION_PCT_21_9
    return config.SCOUT_REGION_PCT_16_9


def _pick_augment_preset(width: int, height: int) -> dict:
    aspect = width / max(height, 1)
    if aspect >= 3.0:
        return config.AUGMENT_REGION_PCT_32_9
    if aspect >= 2.1:
        return config.AUGMENT_REGION_PCT_21_9
    return config.AUGMENT_REGION_PCT_16_9


def _pick_shop_preset(width: int, height: int) -> dict:
    aspect = width / max(height, 1)
    if aspect >= 3.0:
        return config.SHOP_REGION_PCT_32_9
    if aspect >= 2.1:
        return config.SHOP_REGION_PCT_21_9
    return config.SHOP_REGION_PCT_16_9


def _grab_pct_region(picker) -> np.ndarray:
    """Generic capture using a percentage preset picker function."""
    with mss.mss() as sct:
        mon_idx = find_active_monitor_index()
        mon = sct.monitors[mon_idx]
        pct = picker(mon["width"], mon["height"])
        left = mon["left"] + int(mon["width"] * pct["left"])
        top = mon["top"] + int(mon["height"] * pct["top"])
        right = mon["left"] + int(mon["width"] * pct["right"])
        bottom = mon["top"] + int(mon["height"] * pct["bottom"])
        bbox = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        raw = np.array(sct.grab(bbox))
        return raw[:, :, :3]


def grab_augment_region() -> np.ndarray:
    return _grab_pct_region(_pick_augment_preset)


def grab_shop_region() -> np.ndarray:
    return _grab_pct_region(_pick_shop_preset)


def grab_scout_region() -> np.ndarray:
    """Returns BGR numpy array of the scout view region.

    Priority:
      1. Explicit pixels from data/calibration.json (set via scripts/calibrate.py)
      2. Aspect-ratio-aware percentage defaults applied to the monitor TFT is on
    """
    cal = load_calibration()
    with mss.mss() as sct:
        if cal and "scout_region" in cal:
            r = cal["scout_region"]
            bbox = {"left": r["left"], "top": r["top"], "width": r["width"], "height": r["height"]}
        else:
            mon_idx = find_active_monitor_index()
            mon = sct.monitors[mon_idx]
            pct = _pick_region_preset(mon["width"], mon["height"])
            left = mon["left"] + int(mon["width"] * pct["left"])
            top = mon["top"] + int(mon["height"] * pct["top"])
            right = mon["left"] + int(mon["width"] * pct["right"])
            bottom = mon["top"] + int(mon["height"] * pct["bottom"])
            bbox = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        raw = np.array(sct.grab(bbox))
        return raw[:, :, :3]


def list_monitors() -> list[dict]:
    with mss.mss() as sct:
        return list(sct.monitors)


def save_capture(img: np.ndarray, name: str) -> Path:
    """Save a capture for debugging. Returns the saved path."""
    import cv2
    config.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CAPTURES_DIR / f"{name}.png"
    cv2.imwrite(str(path), img)
    return path


def looks_like_tft(img: np.ndarray) -> tuple[bool, str]:
    """Heuristic: does this captured region look like a TFT board?
    Cheap check on average color saturation — TFT has colorful sprites and
    backgrounds, IDE / text apps are mostly desaturated gray.
    Returns (is_likely_tft, reason)."""
    import cv2
    if img is None or img.size == 0:
        return False, "empty image"
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    avg_sat = float(np.mean(hsv[:, :, 1]))
    avg_val = float(np.mean(hsv[:, :, 2]))
    # TFT scout views average ~80-160 brightness with rich color. IDEs in dark
    # theme average <50 brightness. Refuse anything that's both dim AND not super
    # saturated (saturation alone isn't enough — syntax highlighting has color).
    if avg_val < 55:
        return False, f"capture is too dark (val={avg_val:.0f}) — looks like IDE/text, not TFT scout view"
    if avg_sat < 20:
        return False, f"capture has very low color saturation (sat={avg_sat:.0f}) — looks like text/code, not TFT"
    return True, f"sat={avg_sat:.0f} val={avg_val:.0f}"
