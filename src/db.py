"""SQLite schema and queries.

v1 uses meta tables (units, items, comps, comp_units, comp_items, meta_patch).
v2 tables (games, decisions, combat_outcomes) are created now so adding the
learning loop later is additive, not a rewrite.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_patch (
    patch TEXT PRIMARY KEY,
    set_number INTEGER,
    scraped_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS units (
    name TEXT PRIMARY KEY,
    cost INTEGER,
    traits TEXT,
    set_number INTEGER
);

CREATE TABLE IF NOT EXISTS items (
    name TEXT PRIMARY KEY,
    components TEXT,
    is_radiant INTEGER DEFAULT 0,
    is_artifact INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    patch TEXT NOT NULL,
    tier TEXT,
    avg_placement REAL,
    play_rate REAL,
    top4_rate REAL,
    win_rate REAL,
    target_level INTEGER,
    play_style TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS comp_units (
    comp_id INTEGER NOT NULL REFERENCES comps(id) ON DELETE CASCADE,
    unit_name TEXT NOT NULL,
    star_target INTEGER DEFAULT 2,
    is_carry INTEGER DEFAULT 0,
    PRIMARY KEY (comp_id, unit_name)
);

CREATE TABLE IF NOT EXISTS comp_items (
    comp_id INTEGER NOT NULL REFERENCES comps(id) ON DELETE CASCADE,
    unit_name TEXT NOT NULL,
    item_name TEXT NOT NULL,
    priority INTEGER DEFAULT 1,
    PRIMARY KEY (comp_id, unit_name, item_name)
);

CREATE TABLE IF NOT EXISTS augments (
    name TEXT PRIMARY KEY,
    tier_rarity TEXT,         -- Silver | Gold | Prismatic
    general_tier TEXT,        -- S | A | B | C
    notes TEXT
);

CREATE TABLE IF NOT EXISTS augment_synergies (
    augment_name TEXT NOT NULL REFERENCES augments(name) ON DELETE CASCADE,
    comp_name TEXT NOT NULL,
    PRIMARY KEY (augment_name, comp_name)
);

-- v2: not written to in v1, schema reserved
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    patch TEXT,
    set_number INTEGER,
    comp_played TEXT,
    augments TEXT,
    placement INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    round_stage TEXT,
    board_state_hash TEXT,
    recommendation TEXT,
    recommendation_type TEXT,
    accepted INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS combat_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    round_stage TEXT,
    opponent_player INTEGER,
    damage_taken INTEGER,
    units_died TEXT,
    result TEXT,
    captured_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comp_units_unit ON comp_units(unit_name);
CREATE INDEX IF NOT EXISTS idx_decisions_game ON decisions(game_id);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_patch(patch: str, set_number: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta_patch(patch, set_number, scraped_at) VALUES (?, ?, ?)",
            (patch, set_number, int(time.time())),
        )


def upsert_unit(name: str, cost: int, traits: list[str], set_number: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO units(name, cost, traits, set_number) VALUES (?, ?, ?, ?)",
            (name, cost, ",".join(traits), set_number),
        )


def upsert_item(name: str, components: list[str], is_radiant: bool = False, is_artifact: bool = False) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO items(name, components, is_radiant, is_artifact) VALUES (?, ?, ?, ?)",
            (name, ",".join(components), int(is_radiant), int(is_artifact)),
        )


def insert_comp(comp: dict) -> int:
    """Insert a comp + its units + items. Returns comp_id.

    Expected dict shape:
      {
        "name": "Sorcerer Reroll",
        "patch": "14.8",
        "tier": "S",
        "avg_placement": 3.9,
        "play_rate": 0.07,
        "top4_rate": 0.55,
        "win_rate": 0.18,
        "target_level": 7,
        "play_style": "reroll",
        "notes": "...",
        "units": [{"name": "Ahri", "star_target": 3, "is_carry": True}, ...],
        "items": [{"unit": "Ahri", "item": "Jeweled Gauntlet", "priority": 1}, ...]
      }
    """
    with connect() as conn:
        conn.execute("DELETE FROM comps WHERE name = ?", (comp["name"],))
        cur = conn.execute(
            """INSERT INTO comps(name, patch, tier, avg_placement, play_rate,
               top4_rate, win_rate, target_level, play_style, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                comp["name"],
                comp["patch"],
                comp.get("tier"),
                comp.get("avg_placement"),
                comp.get("play_rate"),
                comp.get("top4_rate"),
                comp.get("win_rate"),
                comp.get("target_level"),
                comp.get("play_style"),
                comp.get("notes"),
            ),
        )
        comp_id = cur.lastrowid
        for u in comp.get("units", []):
            conn.execute(
                "INSERT OR REPLACE INTO comp_units(comp_id, unit_name, star_target, is_carry) VALUES (?, ?, ?, ?)",
                (comp_id, u["name"], u.get("star_target", 2), int(u.get("is_carry", False))),
            )
        for it in comp.get("items", []):
            conn.execute(
                "INSERT OR REPLACE INTO comp_items(comp_id, unit_name, item_name, priority) VALUES (?, ?, ?, ?)",
                (comp_id, it["unit"], it["item"], it.get("priority", 1)),
            )
        return comp_id


def all_comps() -> list[dict]:
    with connect() as conn:
        comps = [dict(r) for r in conn.execute("SELECT * FROM comps").fetchall()]
        for c in comps:
            c["units"] = [
                dict(r) for r in conn.execute(
                    "SELECT unit_name, star_target, is_carry FROM comp_units WHERE comp_id = ?",
                    (c["id"],),
                ).fetchall()
            ]
            c["items"] = [
                dict(r) for r in conn.execute(
                    "SELECT unit_name, item_name, priority FROM comp_items WHERE comp_id = ?",
                    (c["id"],),
                ).fetchall()
            ]
        return comps


def current_patch() -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT patch FROM meta_patch ORDER BY scraped_at DESC LIMIT 1").fetchone()
        return row["patch"] if row else None


def insert_augment(aug: dict) -> None:
    """Insert/replace an augment + its synergies. Expected dict shape:
       {"name": "...", "tier_rarity": "Silver|Gold|Prismatic", "general_tier": "S|A|B",
        "synergies": ["CompName1", ...], "notes": "..."}"""
    with connect() as conn:
        conn.execute("DELETE FROM augments WHERE name = ?", (aug["name"],))
        conn.execute(
            "INSERT INTO augments(name, tier_rarity, general_tier, notes) VALUES (?, ?, ?, ?)",
            (aug["name"], aug.get("tier_rarity"), aug.get("general_tier"), aug.get("notes")),
        )
        for comp_name in aug.get("synergies", []):
            conn.execute(
                "INSERT OR REPLACE INTO augment_synergies(augment_name, comp_name) VALUES (?, ?)",
                (aug["name"], comp_name),
            )


def all_augments() -> list[dict]:
    with connect() as conn:
        augs = [dict(r) for r in conn.execute("SELECT * FROM augments").fetchall()]
        for a in augs:
            a["synergies"] = [
                r["comp_name"] for r in conn.execute(
                    "SELECT comp_name FROM augment_synergies WHERE augment_name = ?",
                    (a["name"],),
                ).fetchall()
            ]
        return augs


def find_augment(name_query: str) -> dict | None:
    """Lookup an augment by name (case-insensitive prefix or substring match)."""
    q = name_query.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM augments WHERE LOWER(name) = ?", (q,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM augments WHERE LOWER(name) LIKE ? ORDER BY LENGTH(name) ASC LIMIT 1",
                (q + "%",),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM augments WHERE LOWER(name) LIKE ? ORDER BY LENGTH(name) ASC LIMIT 1",
                ("%" + q + "%",),
            ).fetchone()
        if row is None:
            return None
        a = dict(row)
        a["synergies"] = [
            r["comp_name"] for r in conn.execute(
                "SELECT comp_name FROM augment_synergies WHERE augment_name = ?",
                (a["name"],),
            ).fetchall()
        ]
        return a
