"""Riot Live Client Data API poller.

Reads the local web server Riot exposes during games (port 2999). Officially
documented endpoint, used by Mobalytics/Blitz/OP.GG/Porofessor — purely
read-only, no ban risk.

For TFT specifically, field availability varies vs League proper. We pull
everything we can and let consumers handle missing fields gracefully.

Endpoints we try:
  /liveclientdata/activeplayer    — your level, gold, summoner name
  /liveclientdata/playerlist      — all 8 players (names, status)
  /liveclientdata/gamestats       — game mode, time, stage hints
  /liveclientdata/eventdata       — combat events, level-ups, deaths
"""
from __future__ import annotations

import warnings
from typing import Optional

import requests

# Riot's local server uses a self-signed cert; disable verification + warnings.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE = "https://127.0.0.1:2999/liveclientdata"
TIMEOUT = 1.5  # short — we poll often, can't block


def _get(path: str) -> Optional[dict]:
    try:
        r = requests.get(f"{BASE}{path}", verify=False, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def is_in_game() -> bool:
    """Quick probe — returns True only when a game is actively running."""
    return _get("/gamestats") is not None


def fetch_state() -> dict:
    """Pull whatever's available right now. Returns a dict with whichever fields
    we successfully got. Empty dict if not in a game.

    Returned keys (any may be missing):
      summoner_name      str
      level              int
      gold               int      (current gold; may not be exposed in TFT)
      stage              str      (e.g. "3-2"; derived from gameTime if needed)
      game_time          float    (seconds since game start)
      game_mode          str      (e.g. "TFT" or "CLASSIC")
      players            list[dict]   {summonerName, dead, ...}
      events             list[dict]   recent events
      hp                 int      (only available in TFT — may be missing)
    """
    out: dict = {}

    gs = _get("/gamestats")
    if not gs:
        return out
    out["game_time"] = gs.get("gameTime")
    out["game_mode"] = gs.get("gameMode")
    out["map_name"] = gs.get("mapName")

    # Try to derive stage from game time (TFT: each round is ~30-40s,
    # stages 1-1 → 1-4 are practice/carousel, 2-1 starts ~90s in).
    gt = out.get("game_time")
    if gt is not None:
        out["stage"] = _derive_stage(gt)

    ap = _get("/activeplayer")
    if ap:
        out["summoner_name"] = ap.get("summonerName") or ap.get("riotIdGameName")
        out["level"] = ap.get("level")
        # Gold and HP aren't always in activeplayer for TFT; try fields we know.
        cs = ap.get("championStats", {}) or {}
        if cs.get("currentHealth") is not None:
            out["hp"] = int(cs["currentHealth"])

    pl = _get("/playerlist")
    if pl:
        out["players"] = [
            {
                "name": p.get("summonerName") or p.get("riotIdGameName"),
                "level": p.get("level"),
                "team": p.get("team"),
                "dead": bool(p.get("isDead", False)),
            }
            for p in pl
        ]

    ev = _get("/eventdata")
    if ev:
        out["events"] = ev.get("Events", [])

    return out


_STAGE_BREAKPOINTS = [
    # (cumulative_seconds_at_stage_start, stage_label)
    # Approximate — TFT stage timing varies but these are typical for ranked games.
    (0,    "1-1"),
    (45,   "1-2"),
    (75,   "1-3"),
    (90,   "1-4"),  # carousel
    (115,  "2-1"),
    (155,  "2-2"),
    (185,  "2-3"),
    (215,  "2-4"),
    (250,  "2-5"),
    (290,  "2-6"),
    (320,  "2-7"),
    (355,  "3-1"),
    (390,  "3-2"),
    (420,  "3-3"),
    (450,  "3-4"),
    (485,  "3-5"),
    (520,  "3-6"),
    (555,  "3-7"),
    (600,  "4-1"),
    (640,  "4-2"),
    (680,  "4-3"),
    (720,  "4-4"),
    (760,  "4-5"),
    (800,  "4-6"),
    (840,  "4-7"),
    (890,  "5-1"),
    (940,  "5-2"),
    (990,  "5-3"),
    (1050, "5-4"),
    (1110, "5-5"),
    (1170, "5-6"),
    (1230, "5-7"),
    (1300, "6-1"),
    (1370, "6-2"),
    (1440, "6-3"),
    (1510, "6-4"),
]


def _derive_stage(game_time_seconds: float) -> str:
    """Best-guess current stage label from elapsed game time.
    Approximate — actual stage varies per game. User can override via F6."""
    last = "1-1"
    for cutoff, label in _STAGE_BREAKPOINTS:
        if game_time_seconds >= cutoff:
            last = label
        else:
            break
    return last


def get_my_player_summary(state: dict, my_name: str | None = None) -> Optional[dict]:
    """If we know the player's name, return their entry from the players list.
    Useful for HP/death detection."""
    players = state.get("players", [])
    if not players:
        return None
    if my_name:
        my_lower = my_name.lower()
        for p in players:
            if p.get("name") and my_lower in p["name"].lower():
                return p
    # Fall back to summoner_name from activeplayer
    ap_name = (state.get("summoner_name") or "").lower()
    if ap_name:
        for p in players:
            if p.get("name") and ap_name in p["name"].lower():
                return p
    return None


def detect_dead_opponents(state: dict, my_name: str | None = None) -> set[int]:
    """From the players list, identify which players are dead.
    Returns a set of player numbers (2-8) corresponding to dead opponents.
    Player order in the list is treated as P1=position 0 == us, P2=position 1, etc.
    Approximate — without a stable mapping from list order to opponent number,
    we just count dead opponents; caller may need to keep names → numbers map.
    """
    players = state.get("players", []) or []
    dead = set()
    if not players or len(players) < 2:
        return dead

    # Find own index
    my_idx = None
    candidates = [(my_name or ""), (state.get("summoner_name") or "")]
    for cand in candidates:
        if not cand:
            continue
        for i, p in enumerate(players):
            if p.get("name") and cand.lower() in p["name"].lower():
                my_idx = i
                break
        if my_idx is not None:
            break

    # Map other players to P2-P8 in their listing order, skipping ourselves.
    pnum = 2
    for i, p in enumerate(players):
        if i == my_idx:
            continue
        if p.get("dead"):
            dead.add(pnum)
        pnum += 1
        if pnum > 8:
            break
    return dead
