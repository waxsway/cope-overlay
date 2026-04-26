"""Central config. Tweak hotkeys, paths, thresholds here."""
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
SPRITES_DIR = DATA_DIR / "sprites"
ITEMS_DIR = DATA_DIR / "items"
CAPTURES_DIR = DATA_DIR / "captures"
DB_PATH = DATA_DIR / "tft.db"
CALIBRATION_PATH = DATA_DIR / "calibration.json"
SEED_COMPS_PATH = DATA_DIR / "seed_comps.json"

HOTKEY_CAPTURE_SCOUT = "f1"
HOTKEY_RESET_ROUND = "f2"
HOTKEY_TOGGLE_OVERLAY = "f3"
HOTKEY_REFRESH_META = "f4"
HOTKEY_AUGMENT_PICK = "f5"
HOTKEY_GAME_STATE = "f6"     # set stage / level / gold / HP via dialog
HOTKEY_SHOP_SCAN = "f7"      # capture shop, recommend buys
HOTKEY_QUIT = "f8"
HOTKEY_COMPACT_TOGGLE = "f9" # toggle compact combat-mode overlay
HOTKEY_AUTO_TOGGLE = "f10"   # toggle continuous auto-detect polling
HOTKEY_MUTE_TOGGLE = "f11"   # toggle audio cues on/off
HOTKEY_CLICK_AUTOSCOUT = "f12"  # toggle: clicking a player portrait auto-triggers F1

# Player portrait list — narrow column on the left side of the TFT playable area.
# On ultrawide, TFT keeps the playable area centered (with black/UI bars on the
# sides), so the portrait list is OFFSET from the absolute monitor left edge.
PORTRAIT_LIST_REGION_PCT_16_9 = {"left": 0.00, "top": 0.10, "right": 0.10, "bottom": 0.90}
PORTRAIT_LIST_REGION_PCT_21_9 = {"left": 0.10, "top": 0.10, "right": 0.20, "bottom": 0.90}
PORTRAIT_LIST_REGION_PCT_32_9 = {"left": 0.20, "top": 0.10, "right": 0.27, "bottom": 0.90}

# Delay (ms) between click and capture — gives TFT time to render the scout view.
CLICK_CAPTURE_DELAY_MS = 500

# Live Client API polling interval (ms). Lower = faster updates, more CPU.
LIVE_CLIENT_POLL_MS = 3000
LIVE_CLIENT_ENABLED = True

# Click-to-scout: extend region from just-the-portrait-list to also include
# the full opponent board area (so clicking on the rendered board also fires).
CLICK_BOARD_REGION_PCT_16_9 = {"left": 0.20, "top": 0.10, "right": 0.80, "bottom": 0.85}
CLICK_BOARD_REGION_PCT_21_9 = {"left": 0.30, "top": 0.10, "right": 0.70, "bottom": 0.85}
CLICK_BOARD_REGION_PCT_32_9 = {"left": 0.38, "top": 0.10, "right": 0.62, "bottom": 0.85}

# Default capture region — aspect-ratio aware. TFT keeps the playable area near
# the screen center; ultrawide just adds black/UI margins on the sides, so the
# board takes up a SMALLER percentage of an ultrawide screen than a 16:9 one.
# Calibration is OPTIONAL — only needed if defaults miss the board.
CAPTURE_MONITOR = 1  # mss monitor index; 0 is "all", 1 is primary
SCOUT_REGION_PCT_16_9 = {  # 1920x1080, 2560x1440, 3840x2160
    "left": 0.21,
    "top": 0.22,
    "right": 0.79,
    "bottom": 0.70,
}
SCOUT_REGION_PCT_21_9 = {  # 3440x1440, 2560x1080, 5120x2160
    "left": 0.36,
    "top": 0.22,
    "right": 0.64,
    "bottom": 0.70,
}
SCOUT_REGION_PCT_32_9 = {  # 5120x1440 super-ultrawide
    "left": 0.42,
    "top": 0.22,
    "right": 0.58,
    "bottom": 0.70,
}

# Augment-select screen: 3 cards horizontally, centered. Roughly the middle 60-80%
# of width and middle 40-60% of height. We capture, split into 3 cards, and match
# augment icons in each card's top portion.
AUGMENT_REGION_PCT_16_9 = {"left": 0.18, "top": 0.28, "right": 0.82, "bottom": 0.78}
AUGMENT_REGION_PCT_21_9 = {"left": 0.28, "top": 0.28, "right": 0.72, "bottom": 0.78}
AUGMENT_REGION_PCT_32_9 = {"left": 0.36, "top": 0.28, "right": 0.64, "bottom": 0.78}

# Shop region (bottom of screen): 5 unit cards horizontally above your gold bar.
SHOP_REGION_PCT_16_9 = {"left": 0.20, "top": 0.83, "right": 0.80, "bottom": 0.96}
SHOP_REGION_PCT_21_9 = {"left": 0.30, "top": 0.83, "right": 0.70, "bottom": 0.96}
SHOP_REGION_PCT_32_9 = {"left": 0.38, "top": 0.83, "right": 0.62, "bottom": 0.96}

AUGMENT_MATCH_THRESHOLD = 0.55
SHOP_MATCH_THRESHOLD = 0.55

# Audio cue sound files (optional — drop WAVs into data/sounds/, leave empty to disable).
SOUND_AUGMENT = "augment.wav"
SOUND_LEVEL_UP = "level_up.wav"
SOUND_PIVOT = "pivot.wav"
SOUND_CONTEST = "contest.wav"
SOUNDS_ENABLED = True

# Number of opponents in a TFT match (you + 7 others = 8 total).
OPPONENT_COUNT = 7

# Overlay placement — drag to second monitor at runtime, position is saved.
OVERLAY_DEFAULT_X = 50
OVERLAY_DEFAULT_Y = 50
OVERLAY_WIDTH = 720
OVERLAY_HEIGHT = 920
OVERLAY_OPACITY = 0.85

# Template-matching thresholds (0.0–1.0). Lower = more permissive.
# Lowered defaults — easier to get matches; tighten later if false positives appear.
UNIT_MATCH_THRESHOLD = 0.45
ITEM_MATCH_THRESHOLD = 0.55
# Minimum margin between top match and 2nd-best — avoids ambiguous picks where
# multiple sprites match almost equally (a sign of background noise).
UNIT_MATCH_MARGIN = 0.02
# Stricter threshold required for a detected unit to be COMMITTED to your board
# (which then drives the "sell" list). Detections below this are still shown
# but won't generate spurious sell suggestions.
OWN_BOARD_CONFIDENCE = 0.55

# When True, every F1 capture saves the captured region (and full-screen on
# recognition failure) to data/captures/. Look at those PNGs to diagnose
# wrong region / wrong scale / wrong threshold issues.
DEBUG_SAVE_CAPTURES = True

# Scout board grid (rough fractions of scout-view region; calibration refines).
BOARD_ROWS = 4
BOARD_COLS = 7

META_SOURCE_URL = "https://www.metatft.com/comps"
SPRITE_SOURCE_BASE = "https://raw.communitydragon.org/latest/cdragon/tft"

CONTEST_THRESHOLD_MEDIUM = 1  # 1 other player on your carry → medium contest
CONTEST_THRESHOLD_HIGH = 2    # 2+ others → high

# Per-user player name now lives in data/user_config.json (gitignored).
# Set on first launch via the FirstRunDialog. This constant is the fallback only.
MY_PLAYER_NAME = ""

# OCR settings — only used if pytesseract + Tesseract.exe are installed.
OCR_ENABLED = True
# Optional: pin Tesseract executable path. If empty, pytesseract searches PATH.
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Region within the scout-view crop where the player name typically appears.
# (top: 0.85 = bottom 15% of scout image — adjust if name is elsewhere on your screen)
OCR_NAME_REGION_PCT = {"left": 0.55, "top": 0.85, "right": 1.0, "bottom": 1.0}
