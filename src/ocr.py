"""OCR wrapper for Tesseract. Optional — gracefully no-ops if Tesseract isn't
installed.

Used to detect the player name shown in TFT's scout view, so the program can
auto-route a capture to your_units (when it's YOU) vs opponents[N] (someone else).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import config

_TESS_AVAILABLE: bool | None = None
_TESS_ERROR: str = ""


def _check_tesseract() -> bool:
    global _TESS_AVAILABLE, _TESS_ERROR
    if _TESS_AVAILABLE is not None:
        return _TESS_AVAILABLE
    try:
        import pytesseract
        from src import user_config
        # Resolve tesseract path: user_config first, then config.TESSERACT_CMD
        cmd = user_config.tesseract_cmd()
        if cmd:
            if Path(cmd).exists():
                pytesseract.pytesseract.tesseract_cmd = cmd
            else:
                _TESS_ERROR = f"Tesseract path {cmd} does not exist. Install from https://github.com/UB-Mannheim/tesseract/wiki or update config."
                _TESS_AVAILABLE = False
                return False
        pytesseract.get_tesseract_version()
        _TESS_AVAILABLE = True
        return True
    except ImportError:
        _TESS_ERROR = "pytesseract package not installed (pip install pytesseract)."
    except Exception as e:
        _TESS_ERROR = f"Tesseract executable not found. Install from https://github.com/UB-Mannheim/tesseract/wiki ({e})"
    _TESS_AVAILABLE = False
    return False


def is_available() -> tuple[bool, str]:
    return _check_tesseract(), _TESS_ERROR


def read_text(image: np.ndarray, region_pct: dict | None = None) -> str:
    """OCR the (optionally cropped) image and return raw text. Empty string on failure."""
    if not _check_tesseract():
        return ""
    try:
        import cv2
        import pytesseract
        if region_pct:
            h, w = image.shape[:2]
            x0 = int(w * region_pct["left"])
            x1 = int(w * region_pct["right"])
            y0 = int(h * region_pct["top"])
            y1 = int(h * region_pct["bottom"])
            crop = image[y0:y1, x0:x1]
        else:
            crop = image
        if crop.size == 0:
            return ""
        # Upscale + grayscale to help Tesseract with small game text.
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        # Light threshold helps text/background separation.
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return pytesseract.image_to_string(thresh, config="--psm 7").strip()
    except Exception:
        return ""


def is_my_board(image: np.ndarray) -> tuple[bool, str]:
    """Return (is_yours, detected_name). Uses player name from user_config."""
    from src import user_config
    name = read_text(image, getattr(config, "OCR_NAME_REGION_PCT", None))
    if not name:
        return False, ""
    expected = user_config.player_name().strip().lower()
    if not expected:
        return False, name
    return expected in name.lower(), name
