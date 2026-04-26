# TFT Intelligence Overlay

A real-time Teamfight Tactics overlay that scouts opponents via screen capture, recommends optimal comps based on the field, tells you what to buy/sell/build, and surfaces augment + shop guidance — all without alt-tabbing.

Built for personal use, designed for ranked TFT (Set 17 — Space Gods). Read-only — uses screen capture + Riot's official local APIs. **No risk of bans** (same techniques as Mobalytics / Blitz / OP.GG / Porofessor).

---

## What it does

| Feature | What you get |
|---|---|
| **Scout via click or hotkey** | Click an opponent's portrait → overlay auto-captures their board and updates the recommendation |
| **Field-aware comp recommendation** | Picks a comp based on what your opponents are running, not just a static tier list. Shows STAY THE COURSE / KEEP BUILDING / PIVOT / PLAY states |
| **Visual hex board** | True 4×7 hex layout showing exactly where each unit goes. Carry highlighted with gold glow. Owned units green, units to buy dashed |
| **Buy/Sell/Later tiers** | Level-progressive — at L4 only shows 1-2 cost units to buy now; higher costs move into "later" |
| **Win-streak detection** | If you're winning, it locks in your current comp instead of flipping recommendations |
| **Item priority** | Top 3 items to slam on your carry, in order |
| **Augment auto-recognition** | Press F5 — it screen-reads the 3 augment cards and recommends the best pick |
| **Shop scan** | Press F7 — scans your shop, labels each unit BUY / buy / consider / skip |
| **Live API integration** | Auto-pulls your level / HP / stage / dead opponents every 3s from Riot's local game server |
| **OCR player-name detection** | When you scout someone, OCR reads the name to auto-route the capture (you vs P3 vs P5 etc.) |
| **Multi-monitor aware** | Detects which monitor TFT is on (works for ultrawide + multi-display setups) |

---

## Install (10-15 minutes total)

### 1. Install prerequisites

| Prereq | Where to get it | Required? |
|---|---|---|
| **Python 3.11+** | https://python.org (check "Add to PATH" during install) | YES |
| **Tesseract OCR** | https://github.com/UB-Mannheim/tesseract/wiki (latest 64-bit installer; install to default `C:\Program Files\Tesseract-OCR\`) | Recommended (enables player-name auto-detection) |

### 2. Get the project

```
git clone https://github.com/YOUR_USERNAME/tft-overlay.git
cd tft-overlay
```

(Or download the ZIP from GitHub → extract.)

### 3. Run setup

**Double-click `setup.bat`** — it installs Python packages, downloads sprites (~50MB), and seeds the comp database. Takes 1-3 minutes.

### 4. Launch

**Double-click `start.bat`**. On first launch you'll be asked for your TFT in-game name (used for OCR self-detection). After that, the overlay appears in the corner of your screen.

Drag it to your second monitor (or wherever it doesn't block your TFT view).

---

## How to use it

**Once at session start:**
1. Launch `start.bat`
2. Drag the overlay where you want it
3. Press **F12** to enable click-autoscout (so clicking portraits auto-fires captures)

**Each TFT round:**
1. **Planning phase** — click each opponent's portrait in TFT (left sidebar). Overlay auto-captures + updates the recommendation.
2. **Look at overlay** — see what to PLAY, what to BUY NOW, where to position your carry.
3. **Combat** — ignore overlay (or press F9 for compact mode).
4. **After combat** — press **F2** to reset opponents, then re-scout next round.

**Augment screens (rounds 2-1, 3-2, 4-2):**
- Press **F5**. Auto-detects the 3 augments shown; if it can't, opens a typing dialog.

**Shop guidance:**
- Press **F7** to scan your current shop. Each slot gets a BUY/buy/consider/skip label.

**Bare minimum:** F12 once, then click portraits, then F2 between rounds.

---

## All hotkeys

| Key | Action |
|---|---|
| **F1** | Manual scout (cycle: 1=YOU, 2-8=opponents) |
| **F2** | Reset round (clears opponent boards) |
| **F3** | Hide / show overlay |
| **F4** | Refresh meta data from MetaTFT (currently uses seed data, scraper is best-effort) |
| **F5** | Augment pick |
| **F6** | Manual game state (stage / level / gold / HP / dead players) — usually auto-filled by Live API |
| **F7** | Shop scan |
| **F8** | Quit overlay |
| **F9** | Compact mode (shrinks to corner during combat) |
| **F10** | Continuous polling (dumb 5s loop — F12 is usually better) |
| **F11** | Mute audio cues |
| **F12** | Click-autoscout toggle (clicks on portraits/board → auto-fire capture) |

---

## What changes per user

When sharing the project, each user has their own `data/user_config.json` (gitignored). On first launch you're prompted to set your in-game name. Other settings you might tweak:

```json
{
  "player_name": "Dr Fart MD#NA1",
  "tesseract_cmd": "",
  "scout_region_override": null
}
```

- `player_name` — your TFT/Riot name (case-insensitive substring match for OCR)
- `tesseract_cmd` — only set if you installed Tesseract somewhere other than `C:\Program Files\Tesseract-OCR\`
- `scout_region_override` — leave null unless you have an unusual resolution and need to manually pin the scout-view capture region

---

## Honest limitations

- **Recognition is template-based**, not ML — works most of the time but can miss units on the default own-board view (camera angle is tilted). Click your portrait first to switch to scout view for best results.
- **Comp data is for Set 17.** When Set 18 drops, `data/seed_comps.json` and the unit lists in `src/recommender.py` will need updating.
- **Tier rankings are best-effort** — sourced from web research. May differ from your usual meta source. Edit `data/seed_comps.json` to retier comps.
- **Augment library is 32 of ~150+** Set 17 augments. If your augment screen shows obscure picks, F5 will fall back to the typing dialog.
- **Shop / augment recognition regions** are tuned for 1080p / 1440p / 3440x1440 ultrawide. Other resolutions may need region tweaks in `config.py`.

---

## Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| "TFT isn't the active window" when pressing F1 | TFT process must be focused. Click on TFT first. |
| "Captured area doesn't look like TFT" | Another app is covering the center of your screen. Play TFT in fullscreen, or move other windows aside. |
| Recognition keeps failing in-game | Click your own portrait in TFT first (switches camera to scout view) before pressing F1 / clicking portraits |
| Overlay doesn't show live data | Riot's local API only runs while you're in a game — not in the lobby/client menus |
| Click-autoscout not firing | Press F12 to enable. Run `start.bat` as administrator if TFT is in fullscreen and blocking global hooks |
| OCR not detecting your name | Make sure Tesseract is installed and `data/user_config.json` has your correct in-game name |

---

## Architecture (for developers)

```
src/
  main.py            Entry point — wires hotkeys, polling, overlay
  capture.py         Screen capture (mss); active-monitor detection; TFT-active checks
  recognize.py       OpenCV template matching against unit/item sprites
  recommender.py     Comp scoring, stickiness, positioning, items, stage filters
  overlay.py         PyQt6 overlay window + dialogs + hex board renderer
  ui_design.py       Design tokens (color palette, fonts, spacing)
  live_client.py     Riot Live Client Data API poller (port 2999)
  ocr.py             Tesseract wrapper for player name detection
  user_config.py     Per-user settings (gitignored)
  hotkeys.py         Global F-key registrations
  sound.py           Windows MessageBeep audio cues
  scraper.py         MetaTFT scraper (best-effort, often needs HTML selector updates)
  db.py              SQLite schema + queries

data/
  seed_comps.json    Set 17 meta comps (12 currently)
  seed_augments.json Set 17 augments (32 currently)
  sprites/           Champion portraits (downloaded by setup)
  items/             Item icons (downloaded by setup)
  tft.db             SQLite database (created on first run)
  user_config.json   Per-user (gitignored)
  captures/          Debug screenshots (gitignored)

scripts/
  download_sprites.py   Pulls TFT assets from Community Dragon
  seed_comps.py         Loads seed_comps.json + seed_augments.json into SQLite
  calibrate.py          Optional: 2-click scout-region calibration

setup.bat              One-shot install for new users
start.bat              Launches the overlay
```

---

## License

Personal use. No warranty. Riot Games has no involvement in or endorsement of this project.
