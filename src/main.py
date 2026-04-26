"""Entry point. Wires capture → recognize → recommend → render.

Hotkeys:
  F1  scout (cycle: 1=YOU, 2-8=opponents)
  F2  reset round
  F3  toggle overlay visibility
  F4  refresh meta from MetaTFT
  F5  augment pick (auto-recognize, manual fallback)
  F6  game state (stage / level / gold / HP)
  F7  shop scan (recommend buys)
  F8  quit
  F9  toggle compact combat-mode
  F10 toggle continuous auto-detect polling

Usage:
  python -m src.main
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

import mouse

import config
from src import capture, db, hotkeys, live_client, ocr, recognize, recommender, scraper, sound, user_config
from src.overlay import (
    AugmentInputDialog,
    FirstRunDialog,
    GameStateDialog,
    OverlayWindow,
    make_app,
)
from src.recommender import GameContext, Recommendation


class GameState:
    def __init__(self):
        self.your_units: list[str] = []
        self.your_items: list[str] = []
        self.opponents: dict[int, list[str]] = {}
        self.prev_opponents: dict[int, list[str]] = {}
        self.capture_cursor: int = 1

        # Manual game-state inputs (set via F6)
        self.stage: str | None = None
        self.level: int | None = None
        self.gold: int | None = None
        self.hp: int | None = None
        self.dead_players: set[int] = set()  # 2-8; survives F2 round reset

        # Win-streak / stickiness tracking
        self.hp_history: list[int] = []     # last N HP samples
        self.last_rec_comp_name: str | None = None
        self.win_streak: int = 0            # combats won in a row (HP didn't drop)
        self.loss_streak: int = 0           # combats lost in a row (HP dropped)

    def record_hp(self, new_hp: int) -> None:
        """Append HP sample, recompute streaks. Call from live_tick when HP changes."""
        prev = self.hp_history[-1] if self.hp_history else None
        self.hp_history.append(new_hp)
        if len(self.hp_history) > 12:
            self.hp_history = self.hp_history[-12:]
        if prev is None:
            return
        if new_hp >= prev:
            self.win_streak += 1
            self.loss_streak = 0
        elif new_hp < prev - 2:  # tolerance for minor effects
            self.loss_streak += 1
            self.win_streak = 0

    def is_winning(self) -> bool:
        """Heuristic: on a win streak of 2+ AND HP hasn't dropped in last 3 samples."""
        if self.win_streak < 2:
            return False
        recent = self.hp_history[-3:]
        return len(recent) < 2 or all(recent[i] >= recent[i-1] - 2 for i in range(1, len(recent)))

    def reset_round(self):
        self.prev_opponents = {k: list(v) for k, v in self.opponents.items()}
        self.opponents.clear()
        self.your_units.clear()
        self.capture_cursor = self._next_alive(0)

    def _next_alive(self, from_cursor: int) -> int:
        """Return next cursor position skipping dead opponents. 1=YOU is never dead."""
        c = from_cursor
        for _ in range(8):
            c = 1 if c >= 8 else c + 1
            if c == 1 or c not in self.dead_players:
                return c
        return 1  # everyone dead — shouldn't happen mid-game

    def advance_capture_cursor(self):
        self.capture_cursor = self._next_alive(self.capture_cursor)

    def mark_dead(self, players: set[int]):
        """Set the eliminated set. Removes them from current scouts."""
        self.dead_players = {p for p in players if 2 <= p <= 8}
        for p in self.dead_players:
            self.opponents.pop(p, None)
        # If cursor lands on a dead player, advance it
        if self.capture_cursor in self.dead_players:
            self.capture_cursor = self._next_alive(self.capture_cursor)

    def alive_opponents(self) -> dict[int, list[str]]:
        """opponents minus the dead ones — used for recommendation context."""
        return {p: u for p, u in self.opponents.items() if p not in self.dead_players}

    def store_capture(self, units: list[str], force_self: bool | None = None) -> str:
        """Store a captured unit list. If force_self is True/False, route accordingly,
        ignoring the cursor. Otherwise use cursor (1=YOU, 2-8=opponents).
        Returns label string.
        """
        if force_self is True:
            self.your_units = units
            label = "YOU"
            # Don't advance cursor — OCR confirmed it's you, leave next pointer as-is
            return label
        if force_self is False:
            self.prev_opponents.setdefault(self.capture_cursor, list(self.opponents.get(self.capture_cursor, [])))
            self.opponents[self.capture_cursor] = units
            label = f"P{self.capture_cursor}"
            self.advance_capture_cursor()
            return label
        # Default: cursor-driven
        if self.capture_cursor == 1:
            self.your_units = units
            label = "YOU"
        else:
            self.prev_opponents.setdefault(self.capture_cursor, list(self.opponents.get(self.capture_cursor, [])))
            self.opponents[self.capture_cursor] = units
            label = f"P{self.capture_cursor}"
        self.advance_capture_cursor()
        return label

    def to_context(self) -> GameContext:
        return GameContext(
            your_units=list(self.your_units),
            your_items=list(self.your_items),
            opponents=self.alive_opponents(),
            your_level=self.level,
            your_gold=self.gold,
            your_hp=self.hp,
            stage=self.stage,
            last_rec_comp_name=self.last_rec_comp_name,
            is_winning=self.is_winning(),
            win_streak=self.win_streak,
            loss_streak=self.loss_streak,
        )

    def state_dict(self) -> dict:
        return {
            "stage": self.stage, "level": self.level, "gold": self.gold, "hp": self.hp,
            "dead": ",".join(str(p) for p in sorted(self.dead_players)),
        }


class Bridge(QObject):
    request_capture = pyqtSignal()
    request_reset = pyqtSignal()
    request_toggle = pyqtSignal()
    request_refresh = pyqtSignal()
    request_augment = pyqtSignal()
    request_game_state = pyqtSignal()
    request_shop = pyqtSignal()
    request_compact = pyqtSignal()
    request_auto = pyqtSignal()
    request_mute = pyqtSignal()
    request_click_autoscout = pyqtSignal()
    request_quit = pyqtSignal()


def main():
    db.init_db()
    app = make_app()
    overlay = OverlayWindow()
    overlay.show()

    # First-run: prompt for player name if user_config is fresh
    if user_config.is_first_run():
        dlg = FirstRunDialog(parent=overlay)
        if dlg.exec() == dlg.DialogCode.Accepted:
            name = dlg.get_name()
            if name:
                user_config.set_value("player_name", name)
                overlay.set_recommendations([Recommendation(
                    headline=f"Welcome — name set to '{name}'",
                    detail_lines=["Tip: edit data/user_config.json anytime to change."],
                )])

    state = GameState()
    bridge = Bridge()
    auto_polling = {"on": False}
    click_autoscout = {"on": False, "hook": None}

    def _ts() -> str:
        return time.strftime("%H%M%S")

    def _check_tft_active() -> bool:
        is_tft, active_title = capture.is_tft_active()
        if not is_tft:
            overlay.set_recommendations([Recommendation(
                headline="Hotkey ignored — TFT isn't the active window",
                detail_lines=[
                    f"Active window: {active_title or '(unknown)'}",
                    "Switch to TFT (in front, focused), then press the hotkey again.",
                ],
                severity="warn",
            )])
            return False
        return True

    def do_capture():
        try:
            if not _check_tft_active():
                return
            # Capture the process that's foreground RIGHT NOW (so we know later
            # if mss captured the same app the check approved).
            active_proc = capture.get_active_window_process().split("\\")[-1]
            mon_idx = capture.find_active_monitor_index()
            scout_img = capture.grab_scout_region()
            if config.DEBUG_SAVE_CAPTURES:
                capture.save_capture(scout_img, f"scout_p{state.capture_cursor}_{_ts()}")

            # Content-based gate: if the captured pixels don't look like TFT
            # (e.g., VS Code visually overlapping the scout region), refuse with
            # a clear message instead of attempting recognition that will fail.
            is_tft_like, why = capture.looks_like_tft(scout_img)
            if not is_tft_like:
                fail_scout = capture.save_capture(scout_img, f"FAIL_scout_p{state.capture_cursor}_{_ts()}")
                full_img = capture.grab_full_monitor()
                fail_full = capture.save_capture(full_img, f"FAIL_full_p{state.capture_cursor}_{_ts()}")
                overlay.set_recommendations([Recommendation(
                    headline=f"Captured area doesn't look like TFT — F1 ignored",
                    detail_lines=[
                        f"Active process: {active_proc}",
                        f"Monitor captured: index {mon_idx} (auto-detected from foreground window)",
                        why,
                        "If TFT is on a DIFFERENT monitor than what was captured,",
                        "click on the TFT window to make it the foreground BEFORE pressing F1.",
                        f"Saved → {fail_scout.name}",
                    ],
                    severity="warn",
                )])
                return

            snapshot = recognize.recognize_board(scout_img)
            unit_names = snapshot.unit_names()
            high_conf_names = [
                d.unit_name for d in snapshot.units
                if d.confidence >= config.OWN_BOARD_CONFIDENCE
            ]

            if not unit_names:
                full_img = capture.grab_full_monitor()
                fail_scout = capture.save_capture(scout_img, f"FAIL_scout_p{state.capture_cursor}_{_ts()}")
                fail_full = capture.save_capture(full_img, f"FAIL_full_p{state.capture_cursor}_{_ts()}")
                overlay.set_recommendations([Recommendation(
                    headline=f"P{state.capture_cursor}: nothing recognized",
                    detail_lines=[
                        f"Active process at capture: {active_proc}",
                        f"Captured region → {fail_scout.name}",
                        f"Full screen → {fail_full.name}",
                        "If process is NOT League → restart didn't take effect or another app stole focus.",
                        "If process IS League → wrong region or threshold for this resolution.",
                    ],
                    severity="warn",
                )])
                return

            # OCR the player name from this capture (if Tesseract available + enabled).
            force_self = None
            ocr_note = ""
            if getattr(config, "OCR_ENABLED", False):
                is_yours, detected_name = ocr.is_my_board(scout_img)
                if detected_name:
                    if is_yours:
                        force_self = True
                        ocr_note = f"OCR: '{detected_name}' = YOU"
                    else:
                        force_self = False
                        ocr_note = f"OCR: '{detected_name}' (not you)"

            prev_opp_for_player = state.opponents.get(state.capture_cursor, [])
            # When storing as YOUR board, use the stricter high-confidence list to
            # avoid spurious sell suggestions for false-positive detections.
            committing_to_self = (force_self is True) or (force_self is None and state.capture_cursor == 1)
            units_for_storage = high_conf_names if committing_to_self else unit_names
            label = state.store_capture(units_for_storage, force_self=force_self)
            recs = recommender.recommend(state.to_context())

            # Add diff line if this isn't the first scout of this player this round
            extra: list[Recommendation] = []
            if prev_opp_for_player and state.capture_cursor != 1:
                old_set = {recommender._slug(u) for u in prev_opp_for_player}
                new_set = {recommender._slug(u) for u in unit_names}
                added = new_set - old_set
                removed = old_set - new_set
                if added or removed:
                    diff_str = ""
                    if added:
                        diff_str += f"+{', '.join(sorted(added))} "
                    if removed:
                        diff_str += f"-{', '.join(sorted(removed))}"
                    extra.append(Recommendation(
                        headline=f"{label} board changed: {diff_str}",
                        severity="warn",
                    ))

            progress_head = f"Got {label}: {len(unit_names)} units → next: " + (
                "YOU" if state.capture_cursor == 1 else f"P{state.capture_cursor}"
            )
            progress = Recommendation(
                headline=progress_head,
                detail_lines=([ocr_note] if ocr_note else []),
            )
            overlay.set_recommendations([progress] + extra + recs)
            # Remember the recommended comp so stickiness logic can lock in
            for r in recs:
                if r.play_view and r.play_view.get("comp_name"):
                    state.last_rec_comp_name = r.play_view["comp_name"]
                    break

            # Audio cues: pivot or high-contest hit
            for r in recs:
                if r.play_view:
                    notes = r.play_view.get("notes", [])
                    for note in notes:
                        if "PIVOT" in note:
                            sound.cue("pivot")
                        elif "CONTEST" in note:
                            sound.cue("contest")
        except Exception as e:
            overlay.set_recommendations([Recommendation(
                headline="Capture error",
                detail_lines=[str(e), "See terminal for traceback."],
                severity="urgent",
            )])
            traceback.print_exc()

    def do_reset():
        state.reset_round()
        overlay.set_recommendations([Recommendation(
            headline="Round reset — cursor back to YOU",
        )])

    def do_toggle():
        overlay.toggle_visible()

    def do_refresh():
        overlay.set_recommendations([Recommendation(
            headline="Refreshing meta data...",
            detail_lines=["This may take 10-30s. Overlay updates when done."],
        )])

        def worker():
            try:
                n = scraper.scrape_and_store()
                QTimer.singleShot(0, lambda: overlay.set_recommendations([Recommendation(
                    headline=f"Meta refresh complete: {n} comps stored.",
                    detail_lines=["Patch: " + (db.current_patch() or "?")],
                )]))
            except Exception as e:
                QTimer.singleShot(0, lambda: overlay.set_recommendations([Recommendation(
                    headline="Meta refresh failed",
                    detail_lines=[str(e)],
                    severity="urgent",
                )]))
        threading.Thread(target=worker, daemon=True).start()

    def _resolve_target_comp_name(ctx: GameContext) -> str | None:
        comps = db.all_comps()
        if len(ctx.opponents) >= 6:
            picks = recommender._best_counter_pick(ctx.opponents, comps, your_units=ctx.your_units)
            if picks:
                return picks[0][0]["name"]
        if ctx.your_units:
            closest = recommender._closest_comps(ctx.your_units, comps, top_k=1)
            if closest:
                return closest[0][0]["name"]
        return None

    def do_augment():
        if not _check_tft_active():
            return
        ctx = state.to_context()
        target_name = _resolve_target_comp_name(ctx)

        # Try auto-recognize first.
        try:
            aug_img = capture.grab_augment_region()
            if config.DEBUG_SAVE_CAPTURES:
                capture.save_capture(aug_img, f"augment_{_ts()}")
            aug_names = [a["name"] for a in db.all_augments()]
            results = recognize.recognize_augments(aug_img, aug_names)
            recognized = [name for name, _ in results if name]

            if len(recognized) >= 2:
                # Auto path
                sound.cue("augment")
                recs = recommender.recommend_augment(recognized, ctx, recommended_comp_name=target_name)
                head = Recommendation(
                    headline=f"Auto-detected augments: {', '.join(recognized)}",
                    detail_lines=[f"Confidence: {' / '.join(f'{c:.2f}' for _, c in results)}"],
                )
                overlay.set_recommendations([head] + recs)
                return
        except Exception:
            traceback.print_exc()

        # Manual fallback
        dlg = AugmentInputDialog(parent=overlay)
        if dlg.exec() == dlg.DialogCode.Accepted:
            choices = dlg.get_choices()
            if not choices:
                return
            recs = recommender.recommend_augment(choices, ctx, recommended_comp_name=target_name)
            overlay.set_recommendations(recs)

    def do_game_state():
        dlg = GameStateDialog(current=state.state_dict(), parent=overlay)
        if dlg.exec() == dlg.DialogCode.Accepted:
            new = dlg.get_state()
            state.stage = new.get("stage", state.stage)
            state.level = new.get("level", state.level)
            state.gold = new.get("gold", state.gold)
            state.hp = new.get("hp", state.hp)
            if "dead" in new:
                state.mark_dead(new["dead"])
            alive_count = config.OPPONENT_COUNT - len(state.dead_players)
            recs = recommender.recommend(state.to_context())
            head = Recommendation(
                headline=(f"State: stage {state.stage or '?'} · L{state.level or '?'} · "
                          f"{state.gold or '?'}g · {state.hp or '?'}HP · "
                          f"{alive_count} alive" +
                          (f" (dead: {','.join(f'P{p}' for p in sorted(state.dead_players))})"
                           if state.dead_players else "")),
            )
            overlay.set_recommendations([head] + recs)
            for r in recs:
                if r.play_view:
                    for note in r.play_view.get("notes", []):
                        if "Level" in note or "level" in note:
                            sound.cue("level")
                            break

    def do_shop():
        if not _check_tft_active():
            return
        try:
            shop_img = capture.grab_shop_region()
            if config.DEBUG_SAVE_CAPTURES:
                capture.save_capture(shop_img, f"shop_{_ts()}")
            results = recognize.recognize_shop(shop_img)
            slugs = [name for name, _ in results]
            ctx = state.to_context()
            target_name = _resolve_target_comp_name(ctx)
            recs = recommender.recommend_shop(slugs, ctx, target_comp_name=target_name)
            overlay.set_recommendations(recs)
        except Exception as e:
            overlay.set_recommendations([Recommendation(
                headline="Shop scan error",
                detail_lines=[str(e)],
                severity="urgent",
            )])
            traceback.print_exc()

    def do_compact():
        overlay.toggle_compact()

    def do_auto():
        auto_polling["on"] = not auto_polling["on"]
        msg = "ON" if auto_polling["on"] else "OFF"
        overlay.set_recommendations([Recommendation(
            headline=f"Auto-polling: {msg}",
            detail_lines=[
                "Captures scout view every 5s while TFT is active.",
                "Press F10 to toggle. Press F2 to reset round.",
            ] if auto_polling["on"] else ["Press F10 to enable."],
        )])

    def auto_tick():
        if not auto_polling["on"]:
            return
        try:
            is_tft, _ = capture.is_tft_active()
            if not is_tft:
                return
            scout_img = capture.grab_scout_region()
            snapshot = recognize.recognize_board(scout_img)
            unit_names = snapshot.unit_names()
            if not unit_names:
                return
            new_slugs = sorted(recommender._slug(u) for u in unit_names)
            cursor = state.capture_cursor
            existing = state.your_units if cursor == 1 else state.opponents.get(cursor, [])
            existing_slugs = sorted(recommender._slug(u) for u in existing)
            if new_slugs == existing_slugs:
                return  # no change, no update
            state.store_capture(unit_names)
            recs = recommender.recommend(state.to_context())
            overlay.set_recommendations(recs)
        except Exception:
            traceback.print_exc()

    def do_mute():
        muted = sound.toggle_mute()
        overlay.set_recommendations([Recommendation(
            headline=f"Sound: {'MUTED' if muted else 'ON'}",
            detail_lines=["F11 to toggle."],
        )])

    def _click_in_scout_region(x: int, y: int) -> bool:
        """Check if (x, y) is in either the player-portrait list OR the centered
        scouting board area. Both signal 'I'm trying to scout someone.'"""
        try:
            mon_idx = capture.find_active_monitor_index()
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[mon_idx]
            aspect = mon["width"] / max(mon["height"], 1)
            if aspect >= 3.0:
                portrait_pct = config.PORTRAIT_LIST_REGION_PCT_32_9
                board_pct = config.CLICK_BOARD_REGION_PCT_32_9
            elif aspect >= 2.1:
                portrait_pct = config.PORTRAIT_LIST_REGION_PCT_21_9
                board_pct = config.CLICK_BOARD_REGION_PCT_21_9
            else:
                portrait_pct = config.PORTRAIT_LIST_REGION_PCT_16_9
                board_pct = config.CLICK_BOARD_REGION_PCT_16_9
            for pct in (portrait_pct, board_pct):
                left = mon["left"] + int(mon["width"] * pct["left"])
                top = mon["top"] + int(mon["height"] * pct["top"])
                right = mon["left"] + int(mon["width"] * pct["right"])
                bottom = mon["top"] + int(mon["height"] * pct["bottom"])
                if left <= x <= right and top <= y <= bottom:
                    return True
            return False
        except Exception:
            return False

    # Backward-compat alias
    _click_in_portrait_region = _click_in_scout_region

    def _on_left_click():
        # Fired by mouse listener thread. Schedule capture on Qt main thread after delay.
        try:
            x, y = mouse.get_position()
            in_region = _click_in_portrait_region(x, y)
            # Show debug feedback every click so user can see what's detected.
            mon_idx = capture.find_active_monitor_index()
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[mon_idx]
            aspect = mon["width"] / max(mon["height"], 1)
            if aspect >= 3.0:
                pct = config.PORTRAIT_LIST_REGION_PCT_32_9
            elif aspect >= 2.1:
                pct = config.PORTRAIT_LIST_REGION_PCT_21_9
            else:
                pct = config.PORTRAIT_LIST_REGION_PCT_16_9
            region_left = mon["left"] + int(mon["width"] * pct["left"])
            region_right = mon["left"] + int(mon["width"] * pct["right"])
            region_top = mon["top"] + int(mon["height"] * pct["top"])
            region_bottom = mon["top"] + int(mon["height"] * pct["bottom"])
            msg = (f"Click ({x},{y}) " +
                   ("→ FIRING capture" if in_region else "→ outside portrait region") +
                   f" | region x:{region_left}-{region_right}, y:{region_top}-{region_bottom}")
            QTimer.singleShot(0, lambda: overlay.set_recommendations([Recommendation(
                headline="Click autoscout debug",
                detail_lines=[msg, "Adjust PORTRAIT_LIST_REGION_PCT in config.py if needed."],
                severity="info" if in_region else "warn",
            )]))
            if not in_region:
                return
            QTimer.singleShot(config.CLICK_CAPTURE_DELAY_MS, bridge.request_capture.emit)
        except Exception:
            traceback.print_exc()

    def do_click_autoscout():
        click_autoscout["on"] = not click_autoscout["on"]
        if click_autoscout["on"]:
            # Install mouse hook
            mouse.on_button(_on_left_click, buttons=("left",), types=("up",))
            click_autoscout["hook"] = True
            msg, sub = "Auto-scout on click: ON", [
                "Now: clicking a player portrait in TFT auto-fires F1 capture.",
                "Region: leftmost ~4% of the TFT monitor (the player list).",
                "F12 to toggle off.",
            ]
        else:
            try:
                mouse.unhook_all()
            except Exception:
                pass
            click_autoscout["hook"] = None
            msg, sub = "Auto-scout on click: OFF", ["F12 to enable."]
        overlay.set_recommendations([Recommendation(
            headline=msg, detail_lines=sub,
        )])

    def do_quit():
        QTimer.singleShot(0, app.quit)

    # Connect bridge signals to handlers (handlers run on Qt main thread)
    bridge.request_capture.connect(do_capture)
    bridge.request_reset.connect(do_reset)
    bridge.request_toggle.connect(do_toggle)
    bridge.request_refresh.connect(do_refresh)
    bridge.request_augment.connect(do_augment)
    bridge.request_game_state.connect(do_game_state)
    bridge.request_shop.connect(do_shop)
    bridge.request_compact.connect(do_compact)
    bridge.request_auto.connect(do_auto)
    bridge.request_mute.connect(do_mute)
    bridge.request_click_autoscout.connect(do_click_autoscout)
    bridge.request_quit.connect(do_quit)

    hotkeys.register_hotkeys(
        on_capture=bridge.request_capture.emit,
        on_reset=bridge.request_reset.emit,
        on_toggle_overlay=bridge.request_toggle.emit,
        on_refresh_meta=bridge.request_refresh.emit,
        on_augment_pick=bridge.request_augment.emit,
        on_game_state=bridge.request_game_state.emit,
        on_shop_scan=bridge.request_shop.emit,
        on_compact_toggle=bridge.request_compact.emit,
        on_auto_toggle=bridge.request_auto.emit,
        on_mute_toggle=bridge.request_mute.emit,
        on_click_autoscout=bridge.request_click_autoscout.emit,
        on_quit=bridge.request_quit.emit,
    )

    # Auto-poll timer (does nothing until F10 toggles auto_polling on)
    poll_timer = QTimer()
    poll_timer.setInterval(5000)
    poll_timer.timeout.connect(auto_tick)
    poll_timer.start()

    # Live Client Data API polling — automatically reads YOUR level/gold/HP/stage
    # from Riot's local web server (port 2999). Officially supported endpoint,
    # used by Mobalytics/Blitz/etc. Updates GameState whenever values change.
    live_state = {"connected": False, "last_state": {}}

    def live_tick():
        """Sync GameState from Riot Live API. Only RE-RENDERS the overlay when
        something tactically meaningful changes (death, level, stage) — NOT for
        routine HP/gold ticks, which would clobber the user's most recent
        scout result."""
        if not getattr(config, "LIVE_CLIENT_ENABLED", True):
            return
        new_state = live_client.fetch_state()
        was_connected = live_state["connected"]
        live_state["connected"] = bool(new_state)
        if not new_state:
            return

        # Always sync state (silent updates so next manual capture has fresh ctx)
        if new_state.get("hp") is not None:
            new_hp = new_state["hp"]
            if state.hp is None or new_hp != state.hp:
                state.record_hp(new_hp)
            state.hp = new_hp
        if new_state.get("level") is not None:
            new_level = new_state["level"]
            level_changed = new_level != state.level
            state.level = new_level
        else:
            level_changed = False

        stage_changed = False
        if new_state.get("stage") and new_state["stage"] != state.stage:
            state.stage = new_state["stage"]
            stage_changed = True

        my_name = getattr(config, "MY_PLAYER_NAME", None)
        dead = live_client.detect_dead_opponents(new_state, my_name)
        death_changed = bool(dead and dead != state.dead_players)
        if death_changed:
            state.dead_players = dead

        live_state["last_state"] = new_state

        # Only re-render on TACTICALLY MEANINGFUL changes — never on HP only.
        # HP fluctuates every combat tick; rebuilding the overlay constantly
        # erases scout results before user can read them.
        if level_changed or stage_changed or death_changed or not was_connected:
            sn = new_state.get("summoner_name", "?")
            reasons = []
            if level_changed:
                reasons.append(f"L{state.level}")
            if stage_changed:
                reasons.append(f"stage {state.stage}")
            if death_changed:
                reasons.append(f"dead: {','.join(f'P{p}' for p in sorted(state.dead_players))}")
            head = Recommendation(
                headline=f"⬢ Live: {sn} · L{state.level or '?'} · {state.hp or '?'}HP · stage {state.stage or '?'}",
                detail_lines=[f"Updated: {', '.join(reasons)}"] if reasons else [],
                severity="info",
            )
            recs = recommender.recommend(state.to_context())
            overlay.set_recommendations([head] + recs)

    live_timer = QTimer()
    live_timer.setInterval(getattr(config, "LIVE_CLIENT_POLL_MS", 3000))
    live_timer.timeout.connect(live_tick)
    live_timer.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
