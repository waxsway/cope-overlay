"""One-time scout-region calibration.

Captures your primary monitor, opens an OpenCV window, and asks you to:
  1. Click top-left of the scout view's board
  2. Click bottom-right of the scout view's board

Then divides that rectangle into BOARD_ROWS × BOARD_COLS cells and saves
everything to data/calibration.json. recognize.py uses these per-cell
rectangles instead of guessing.

Tip: open TFT, scout an opponent, alt-tab here, then run this script.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

import config
from src import capture


_clicks: list[tuple[int, int]] = []
WINDOW = "TFT Calibration — click top-left then bottom-right of the scout board"


def _on_click(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        _clicks.append((x, y))
        print(f"  click {len(_clicks)}: ({x}, {y})")


def main() -> int:
    print("Capturing primary monitor...")
    img = capture.grab_full_monitor()
    h, w = img.shape[:2]

    # Downscale for display if huge — record scale so we map clicks back.
    max_dim = 1400
    scale = 1.0
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        display = cv2.resize(img, (int(w * scale), int(h * scale)))
    else:
        display = img.copy()

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, _on_click)

    print("Two-click calibration: top-left of board, then bottom-right.")
    print("Press Q to abort, any key to confirm after 2 clicks.")
    while True:
        preview = display.copy()
        for c in _clicks:
            cv2.circle(preview, c, 6, (0, 255, 0), 2)
        cv2.imshow(WINDOW, preview)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            print("Aborted.")
            cv2.destroyAllWindows()
            return 1
        if len(_clicks) >= 2:
            cv2.imshow(WINDOW, preview)
            cv2.waitKey(800)
            break

    (x0_d, y0_d), (x1_d, y1_d) = _clicks[0], _clicks[1]
    # Map back to full-resolution coords.
    x0, y0 = int(x0_d / scale), int(y0_d / scale)
    x1, y1 = int(x1_d / scale), int(y1_d / scale)
    if x1 < x0: x0, x1 = x1, x0
    if y1 < y0: y0, y1 = y1, y0

    region = {"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}
    cells = []
    cell_h = (y1 - y0) // config.BOARD_ROWS
    cell_w = (x1 - x0) // config.BOARD_COLS
    for row in range(config.BOARD_ROWS):
        for col in range(config.BOARD_COLS):
            cells.append({
                "row": row,
                "col": col,
                # cell coords are RELATIVE to the scout region (capture crops first)
                "y0": row * cell_h,
                "y1": (row + 1) * cell_h,
                "x0": col * cell_w,
                "x1": (col + 1) * cell_w,
            })

    payload = {}
    if config.CALIBRATION_PATH.exists():
        try:
            payload = json.loads(config.CALIBRATION_PATH.read_text())
        except Exception:
            payload = {}
    payload["scout_region"] = region
    payload["cells"] = cells
    config.CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CALIBRATION_PATH.write_text(json.dumps(payload, indent=2))
    cv2.destroyAllWindows()
    print(f"\nSaved calibration to {config.CALIBRATION_PATH}")
    print(f"  scout region: {region}")
    print(f"  {len(cells)} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
