"""Recommender. Given your board + opponent boards, suggest:
  - closest meta comp + how to pivot toward it
  - BiS items per carry (with what you can actually craft from your components)
  - contest score per opponent
  - counter warnings (their comp threatens yours)
  - positioning per unit
  - augment pick from a set of 3 choices (recommend_augment)

v1 is rule-based + similarity scoring. v2 layers personal placement weights
on top via the `decisions` and `games` tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

import config
from src import db


def _slug(name: str) -> str:
    """Normalize unit/comp names for comparison.
    'Bel'Veth' -> 'belveth', 'Kai'Sa' -> 'kaisa', 'Master Yi' -> 'master_yi'.
    Sprite filenames use this same form."""
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[\s-]+", "_", s)


# Set 17 unit cost tiers (1-5 gold). Keyed by slug. Used to filter recommendations
# to only suggest comps whose units the player can actually obtain at their stage/level.
UNIT_COSTS: dict[str, int] = {
    # 1-cost
    "briar": 1, "chogath": 1, "lissandra": 1, "poppy": 1, "veigar": 1,
    "aatrox": 1, "caitlyn": 1, "reksai": 1, "nasus": 1, "teemo": 1,
    "talon": 1, "twisted_fate": 1, "ezreal": 1,
    # 2-cost
    "jinx": 2, "leona": 2, "mordekaiser": 2, "gnar": 2, "meepsie": 2,
    "gragas": 2, "pyke": 2, "gwen": 2, "jax": 2, "milio": 2,
    "pantheon": 2, "akali": 2, "belveth": 2,
    # 3-cost
    "aurora": 3, "illaoi": 3, "zoe": 3, "diana": 3, "kaisa": 3,
    "maokai": 3, "fizz": 3, "lulu": 3, "ornn": 3, "samira": 3,
    "viktor": 3, "rhaast": 3, "urgot": 3, "morgana": 3, "shen": 3,
    "tahm_kench": 3,
    # 4-cost
    "leblanc": 4, "karma": 4, "corki": 4, "rammus": 4, "kindred": 4,
    "master_yi": 4, "nami": 4, "nunu": 4, "nunu_willump": 4, "xayah": 4,
    "aurelion_sol": 4, "the_mighty_mech": 4, "riven": 4, "vex": 4,
    # 5-cost
    "fiora": 5, "jhin": 5, "bard": 5, "sona": 5, "blitzcrank": 5,
}


def avg_cost_of(unit_names: list[str]) -> float:
    """Average gold-cost of a list of unit names. 0 for empty list."""
    if not unit_names:
        return 0.0
    return sum(UNIT_COSTS.get(_slug(u), 3) for u in unit_names) / len(unit_names)


def active_buy_costs(level: int | None, play_style: str | None) -> tuple[set[int], set[int]]:
    """Return (active_costs, next_costs) — which unit cost tiers the player
    should ACTIVELY buy right now vs. what's coming next level.

    Reroll comps stay low-cost longer. Fast-8/9 comps skip mid-tier rerolls.
    """
    style = (play_style or "standard").lower()
    is_reroll = "reroll" in style
    is_fast = "fast" in style

    if level is None:
        return ({1, 2, 3, 4, 5}, set())

    if level <= 4:
        active = {1, 2}
        nxt = {3}
    elif level == 5:
        active = {1, 2}
        nxt = {3}
    elif level == 6:
        active = ({1, 2, 3} if is_reroll else {2, 3})
        nxt = {3, 4}
    elif level == 7:
        active = ({1, 2, 3} if is_reroll else {3, 4})
        nxt = {4, 5}
    elif level == 8:
        active = {3, 4, 5} if not is_reroll else {1, 2, 3, 4}
        nxt = {5}
    else:  # 9+
        active = {4, 5}
        nxt = set()
    return active, nxt


def max_obtainable_cost(stage: str | None, level: int | None) -> int:
    """Return the highest unit cost the player can realistically obtain right now.
    1-cost always available; higher costs unlock as the player levels up.
    Stage acts as a fallback if level isn't set.
    """
    if level is not None:
        # Standard TFT shop odds make these cost ceilings practical, not absolute:
        if level <= 4:
            return 2
        if level == 5:
            return 3
        if level == 6:
            return 3
        if level == 7:
            return 4
        if level == 8:
            return 5
        return 5
    # Fallback: derive from stage if level not given.
    if not stage:
        return 5  # no info → don't filter
    try:
        s = int(stage.split("-")[0])
    except Exception:
        return 5
    if s <= 2:
        return 2
    if s == 3:
        return 3
    if s == 4:
        return 4
    return 5


_DISPLAY_OVERRIDES = {
    "belveth": "Bel'Veth", "kaisa": "Kai'Sa", "chogath": "Cho'Gath",
    "reksai": "Rek'Sai", "khazix": "Kha'Zix", "kogmaw": "Kog'Maw",
    "nunu_willump": "Nunu", "master_yi": "Master Yi", "twisted_fate": "Twisted Fate",
    "tahm_kench": "Tahm Kench", "the_mighty_mech": "The Mighty Mech",
    "aurelion_sol": "Aurelion Sol", "miss_fortune": "Miss Fortune",
    "bia_bayin": "Bia Bayin",
}


def _display_name(slug_or_name: str, comps: list[dict] | None = None) -> str:
    """Convert a slug back to a human-readable name.
    Uses overrides for special cases (Bel'Veth, Kai'Sa) then comp data, then title case."""
    s = _slug(slug_or_name)
    if s in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[s]
    if comps:
        for comp in comps:
            for u in comp["units"]:
                if _slug(u["unit_name"]) == s:
                    return u["unit_name"]
    return " ".join(p.capitalize() for p in s.split("_"))


# Each comp has STRENGTHS (what it does to enemies) and WEAKNESSES (what beats it).
# Scoring: a candidate comp's score increases when its strengths exploit field
# weaknesses, decreases when its weaknesses are exploited by field strengths.
COMP_PROFILE: dict[str, dict] = {
    # === Set 17 traits ===
    "rogue":           {"strengths": ["dives_backline", "burst_dmg"], "weaknesses": ["vs_taunt", "vs_aoe_shield", "vs_burst", "vs_aoe"]},
    "nova":            {"strengths": ["dives_backline", "burst_dmg"], "weaknesses": ["vs_taunt", "vs_burst", "vs_aoe"]},
    "doomer":          {"strengths": ["scales_late", "ap_dmg"], "weaknesses": ["vs_mr", "vs_dive", "vs_burst"]},
    "dark star":       {"strengths": ["ap_dmg", "executes_low_hp"], "weaknesses": ["vs_mr", "vs_burst_dive"]},
    "psionic":         {"strengths": ["ap_dmg", "cc"], "weaknesses": ["vs_mr", "vs_dive"]},
    "oracle":          {"strengths": ["ap_dmg"], "weaknesses": ["vs_mr"]},
    "space groove":    {"strengths": ["sustains", "tank_wall"], "weaknesses": ["vs_burn", "vs_shred", "vs_true_dmg"]},
    "mecha":           {"strengths": ["tank_wall", "absorbs_dmg"], "weaknesses": ["vs_burn", "vs_shred", "vs_burst", "vs_true_dmg"]},
    "vanguard":        {"strengths": ["tank_wall"], "weaknesses": ["vs_burn", "vs_burst", "vs_true_dmg"]},
    "bastion":         {"strengths": ["tank_wall", "armor"], "weaknesses": ["vs_burn", "vs_true_dmg", "vs_ap"]},
    "bulwark":         {"strengths": ["tank_wall"], "weaknesses": ["vs_burn", "vs_true_dmg"]},
    "brawler":         {"strengths": ["tank_wall"], "weaknesses": ["vs_shred", "vs_burst"]},
    "marauder":        {"strengths": ["true_dmg", "armor_pen"], "weaknesses": ["vs_aoe", "vs_dive", "vs_cc"]},
    "eradicator":      {"strengths": ["shred", "ad_dmg"], "weaknesses": ["vs_dive", "vs_armor"]},
    "sniper":          {"strengths": ["long_range_ad"], "weaknesses": ["vs_dive", "vs_assassins", "vs_burst_dive"]},
    "gun goddess":     {"strengths": ["ad_dmg", "long_range_ad"], "weaknesses": ["vs_dive", "vs_armor"]},
    "galaxy hunter":   {"strengths": ["ad_dmg"], "weaknesses": ["vs_armor", "vs_dive"]},
    "stargazer":       {"strengths": ["scales_late", "ad_dmg"], "weaknesses": ["vs_dive", "vs_burst", "vs_armor"]},
    "fateweaver":      {"strengths": ["scales_late", "ap_dmg"], "weaknesses": ["vs_dive", "vs_burst"]},
    "shepherd":        {"strengths": ["sustains", "ap_dmg"], "weaknesses": ["vs_burn", "vs_burst", "vs_dive"]},
    "primordian":      {"strengths": ["aoe_dmg", "burst_dmg"], "weaknesses": ["vs_taunt", "vs_grouped", "vs_burst_dive"]},
    "anima":           {"strengths": ["lose_streak_econ", "ad_dmg"], "weaknesses": ["vs_burst", "vs_dive"]},
    "commander":       {"strengths": ["tank_wall", "buffs"], "weaknesses": ["vs_shred", "vs_burn"]},
    "voyager":         {"strengths": ["scales_late"], "weaknesses": ["vs_dive", "vs_burst"]},
    "challenger":      {"strengths": ["dives_backline"], "weaknesses": ["vs_taunt", "vs_burst"]},
    "conduit":         {"strengths": ["mana_gen", "ap_dmg"], "weaknesses": ["vs_dive", "vs_mr"]},
}

# Counter map: STRENGTH X exploits WEAKNESS Y. Score +1 per match.
# (Roughly: damage type counters defensive type; range type counters approach type.)
EXPLOITS: dict[str, list[str]] = {
    "ap_dmg":          ["vs_mr"],
    "ad_dmg":          ["vs_armor"],
    "true_dmg":        ["vs_true_dmg"],
    "burst_dmg":       ["vs_burst_dive"],     # tightened: don't exploit generic vs_burst
    "shred":           ["vs_shred"],
    "burn":            ["vs_burn"],
    "armor_pen":       ["vs_armor"],
    "long_range_ad":   ["vs_aoe_shield"],
    "dives_backline":  ["vs_dive"],            # tightened: only vs_dive, not _burst_dive
    "tank_wall":       ["vs_aoe_shield"],
    "aoe_dmg":         ["vs_aoe", "vs_grouped"],
    "scales_late":     [],
    "executes_low_hp": ["vs_burn"],
    "sustains":        [],
    "lose_streak_econ":[],
    "buffs":           [],
    "mana_gen":        [],
    "cc":              ["vs_cc"],
    "absorbs_dmg":     [],
    "armor":           [],
}

# Legacy COUNTER_GRAPH kept for the old _counter_warnings function. New code uses
# COMP_PROFILE + EXPLOITS instead.
COUNTER_GRAPH: dict[str, list[str]] = {
    "ad_burst": ["squishy_backline", "low_armor_frontline"],
    "ap_burst": ["low_mr_frontline", "squishy_backline"],
    "true_damage": ["all"],
    "assassins_dive": ["squishy_backline"],
    "tank_stall": ["low_dps", "no_shred"],
    "reroll_3star": ["fast_late_game"],
    "fast_8_legendary": ["reroll_3star_no_scaling"],
    "shred": ["tank_stall"],
    "burst_aoe": ["clumped_backline"],
    "long_range": ["squishy_backline"],
}

# Tag inference rules: keyword in comp name/units → comp tag.
# Set 17 (Space Gods) traits: Anima, Arbiter, Bulwark, Commander, Dark Lady, Dark Star,
# Divine Duelist, Doomer, Eradicator, Factory New, Galaxy Hunter, Gun Goddess, Mecha,
# Meeple, N.O.V.A., Party Animal, Primordian, Oracle, Psionic, Redeemer, Space Groove,
# Stargazer, Timebreaker. Classes: Bastion, Brawler, Challenger, Conduit, Fateweaver,
# Marauder, Replicator, Rogue, Shepherd, Sniper, Vanguard, Voyager.
TAG_HINTS: list[tuple[str, str]] = [
    # Set 17 traits
    ("rogue", "assassins_dive"),
    ("nova", "assassins_dive"),
    ("doomer", "ap_burst"),
    ("dark star", "ap_burst"),
    ("psionic", "ap_burst"),
    ("oracle", "ap_burst"),
    ("space groove", "tank_stall"),
    ("mecha", "tank_stall"),
    ("vanguard", "tank_stall"),
    ("bastion", "tank_stall"),
    ("bulwark", "tank_stall"),
    ("brawler", "tank_stall"),
    ("marauder", "true_damage"),
    ("eradicator", "shred"),
    ("sniper", "long_range"),
    ("gun goddess", "ad_burst"),
    ("galaxy hunter", "ad_burst"),
    ("stargazer", "ad_burst"),
    ("fateweaver", "ap_burst"),
    ("shepherd", "ap_burst"),
    ("primordian", "burst_aoe"),
    ("anima", "ad_burst"),
    ("commander", "tank_stall"),
    ("voyager", "long_range"),
    # generic class fallbacks (work across sets)
    ("assassin", "assassins_dive"),
    ("sorcerer", "ap_burst"),
    ("mage", "ap_burst"),
    ("gunner", "ad_burst"),
    ("rapidfire", "ad_burst"),
    ("sentinel", "low_mr_frontline"),
    ("invoker", "ap_burst"),
    ("dragon", "fast_8_legendary"),
]


@dataclass
class Recommendation:
    headline: str
    detail_lines: list[str] = field(default_factory=list)
    severity: str = "info"  # info, warn, urgent
    # Structured payload for visual rendering. None = render text-only.
    play_view: dict | None = None

    def to_text(self) -> str:
        lines = [self.headline] + [f"  • {line}" for line in self.detail_lines]
        return "\n".join(lines)


@dataclass
class GameContext:
    """Snapshot of the round used by the recommender."""
    your_units: list[str]
    your_items: list[str]
    your_level: int | None = None
    your_gold: int | None = None
    your_hp: int | None = None
    stage: str | None = None  # e.g. "3-2", "4-1", "5-2"
    opponents: dict[int, list[str]] = field(default_factory=dict)

    # Stickiness signals — set by main.py from GameState
    last_rec_comp_name: str | None = None
    is_winning: bool = False
    win_streak: int = 0
    loss_streak: int = 0


def stage_phase(stage: str | None) -> str:
    """Categorize a stage string into a phase: early / mid / late / final."""
    if not stage:
        return "unknown"
    try:
        s = int(stage.split("-")[0])
    except Exception:
        return "unknown"
    if s <= 2:
        return "early"
    if s == 3:
        return "mid"
    if s == 4:
        return "late"
    return "final"


def level_advice(level: int | None, gold: int | None, hp: int | None, stage: str | None) -> str | None:
    """Return a single-line econ/level recommendation based on game state.
    Heuristics — not exact pro play, but close enough for ranked decisions."""
    if level is None or gold is None:
        return None
    phase = stage_phase(stage)
    s = int(stage.split("-")[0]) if stage and "-" in stage else 0

    # Critical HP — aggro at any phase
    if hp is not None and hp <= 25 and gold >= 50:
        return f"⚠ Low HP ({hp}). Roll down to stabilize — don't save gold to die."

    # Stage-specific guidance
    if phase == "early":
        if gold >= 50:
            return "Hit 50g interest cap. Spend the surplus — buy XP or roll a few times if you need a stabilizing 2-star."
        return f"Build econ. Save to 50g, level naturally to {min(level+1, 6)} on 2-5."
    if phase == "mid":
        if level < 6:
            return "Level to 6 by 3-2 if you haven't (4 XP spend on 3-1)."
        if level == 6 and gold >= 50:
            return "Level to 7 going into 4-1 (the 4-cost spike)."
        return "Hold gold for 4-1 roll if your comp wants 4-costs."
    if phase == "late":
        if level == 7 and gold >= 50:
            return "ROLL DOWN at 4-1: hit your 4-cost carry to 2 stars before 4-2."
        if level == 7 and gold < 30 and hp and hp > 50:
            return "Don't roll yet — econ to 50g, level 8 going into 5-1."
        if level >= 8:
            return f"At 8 with {gold}g. Roll for upgrades + level 9 if comp wants legendaries."
    if phase == "final":
        if level == 8 and gold >= 80:
            return "Level 9 + roll for legendaries. Final-board upgrades only."
        if level == 9:
            return "Roll for upgrades. Don't save — game ends soon."
    return None


def diff_opponents(prev: dict[int, list[str]], curr: dict[int, list[str]]) -> list[str]:
    """Return human-readable diff lines for opponents whose boards changed."""
    lines: list[str] = []
    for pnum in sorted(curr.keys()):
        old = set(_slug(u) for u in prev.get(pnum, []))
        new = set(_slug(u) for u in curr.get(pnum, []))
        added = new - old
        removed = old - new
        if added or removed:
            change_parts = []
            if added:
                change_parts.append(f"+{','.join(sorted(added))}")
            if removed:
                change_parts.append(f"-{','.join(sorted(removed))}")
            lines.append(f"P{pnum}: {' '.join(change_parts)}")
    return lines


def detect_pivot_signal(your_units: list[str], target_comp: dict | None) -> str | None:
    """If the user's current board is far from the target comp, signal a pivot.
    Returns a short pivot reason or None if board is on-track."""
    if not target_comp or not your_units:
        return None
    target_slugs = {_slug(u["unit_name"]) for u in target_comp["units"]}
    my_slugs = {_slug(u) for u in your_units}
    overlap = len(my_slugs & target_slugs) / max(1, len(my_slugs))
    if overlap < 0.35 and len(my_slugs) >= 4:
        return f"PIVOT — only {int(overlap*100)}% of your board fits {target_comp['name']}."
    return None


def _comp_tags(comp: dict) -> set[str]:
    blob = (comp.get("name", "") + " " + " ".join(u["unit_name"] for u in comp["units"])).lower()
    tags: set[str] = set()
    for hint, tag in TAG_HINTS:
        if hint in blob:
            tags.add(tag)
    return tags


def _similarity(my_units: set[str], comp_units: set[str]) -> float:
    """Jaccard-ish: weighted toward overlap with the comp's roster."""
    if not comp_units:
        return 0.0
    overlap = len(my_units & comp_units)
    return overlap / len(comp_units)


def _closest_comps(your_units: list[str], comps: list[dict], top_k: int = 3) -> list[tuple[dict, float]]:
    my_set = {_slug(u) for u in your_units}
    scored: list[tuple[dict, float]] = []
    for comp in comps:
        comp_unit_set = {_slug(u["unit_name"]) for u in comp["units"]}
        sim = _similarity(my_set, comp_unit_set)
        # Tier nudge — prefer S/A comps when similarity ties.
        tier_bonus = {"S": 0.05, "A": 0.03, "B": 0.0, "C": -0.02}.get(comp.get("tier") or "B", 0.0)
        scored.append((comp, sim + tier_bonus))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _identify_opponent_comp(opp_units: list[str], comps: list[dict]) -> dict | None:
    if not opp_units:
        return None
    matches = _closest_comps(opp_units, comps, top_k=1)
    if not matches:
        return None
    comp, score = matches[0]
    return comp if score >= 0.4 else None


def _contest_score(your_carries: set[str], opponents: dict[int, list[str]]) -> tuple[int, list[int]]:
    """Returns (contest_count, list of contesting player numbers).
    Both sides are slugged before comparison."""
    contesting = []
    for pnum, units in opponents.items():
        if your_carries & {_slug(u) for u in units}:
            contesting.append(pnum)
    return len(contesting), contesting


def _counter_warnings(your_tags: set[str], opponents: dict[int, list[str]], comps: list[dict]) -> list[str]:
    warnings = []
    for pnum, units in opponents.items():
        opp_comp = _identify_opponent_comp(units, comps)
        if not opp_comp:
            continue
        opp_tags = _comp_tags(opp_comp)
        for tag in opp_tags:
            threats = COUNTER_GRAPH.get(tag, [])
            if any(t in your_tags or t == "all" for t in threats):
                warnings.append(
                    f"P{pnum} ({opp_comp['name']}): threatens you via '{tag}'"
                )
                break
    return warnings


# Set 17 (Space Gods) per-unit role classification. Keyed by slugged name.
# Update each set; defaults to "flex" if unit isn't listed.
ROLE_HINTS: dict[str, str] = {
    # 1-cost
    "briar": "diver", "chogath": "tank", "lissandra": "caster", "poppy": "tank",
    "veigar": "caster", "aatrox": "tank", "caitlyn": "ranged_ad", "reksai": "tank",
    "nasus": "tank", "teemo": "caster", "talon": "diver", "twisted_fate": "caster",
    "ezreal": "ranged_ad",
    # 2-cost
    "jinx": "ranged_ad", "leona": "tank", "mordekaiser": "tank", "gnar": "ranged_ad",
    "meepsie": "support", "gragas": "tank", "pyke": "diver", "gwen": "diver",
    "jax": "tank", "milio": "support", "pantheon": "tank", "akali": "diver",
    "belveth": "diver",
    # 3-cost
    "aurora": "caster", "illaoi": "tank", "zoe": "caster", "diana": "diver",
    "kaisa": "ranged_ad", "maokai": "tank", "fizz": "diver", "lulu": "support",
    "ornn": "tank", "samira": "ranged_ad", "viktor": "caster", "rhaast": "tank",
    "urgot": "tank", "morgana": "caster", "shen": "tank", "tahm_kench": "tank",
    # 4-cost
    "leblanc": "caster", "karma": "support", "corki": "ranged_ad", "rammus": "tank",
    "kindred": "ranged_ad", "master_yi": "diver", "nami": "support",
    "nunu_willump": "tank", "nunu": "tank", "xayah": "ranged_ad",
    "aurelion_sol": "caster", "the_mighty_mech": "tank", "riven": "diver",
    "vex": "caster",
    # 5-cost
    "fiora": "diver", "jhin": "ranged_ad", "bard": "support", "sona": "support",
    "blitzcrank": "flex",
}


def _classify_role(unit_name: str, is_carry: bool) -> str:
    role = ROLE_HINTS.get(_slug(unit_name))
    if role:
        return role
    return "carry" if is_carry else "flex"


def _field_threats(opponents: dict[int, list[str]], comps: list[dict]) -> dict[str, list[int]]:
    """Returns {threat_type: [player_nums]} for positioning-relevant threats."""
    threats: dict[str, list[int]] = {"assassin": [], "ranged_reach": [], "aoe": []}
    for pnum, units in opponents.items():
        opp_comp = _identify_opponent_comp(units, comps)
        if not opp_comp:
            continue
        tags = _comp_tags(opp_comp)
        if "assassins_dive" in tags:
            threats["assassin"].append(pnum)
        if "ad_burst" in tags or "ap_burst" in tags:
            threats["ranged_reach"].append(pnum)
        # AOE detection would need finer trait data; skip in v1
    return threats


def _assign_positions(comp: dict, opponents: dict[int, list[str]], comps: list[dict]) -> list[tuple[dict, int, int]]:
    """Assign each unit in `comp` to a (row, col) on the 4×7 TFT board.

    Row 0 = front (closest to enemy), Row 3 = back. Col 0..6 left to right.

    Strategy:
    - Carry → back corner away from enemy assassin threats
    - Support buffer (Lulu, Bard, Karma, Nami, Milio, Sona) → ADJACENT to carry
    - Other backliners (casters, ranged_ad without carry tag) → row 2 (mid-back)
    - Off-tanks/divers → row 1 (mid-front) on flanks
    - Primary tanks → row 0 (front), middle then spread
    """
    threats = _field_threats(opponents, comps)
    has_assassins = bool(threats["assassin"])

    units = comp["units"]
    by_role: dict[str, list[dict]] = {
        "tank": [], "support": [], "caster": [], "ranged_ad": [],
        "diver": [], "carry": [], "flex": [],
    }
    for u in units:
        role = _classify_role(u["unit_name"], bool(u["is_carry"]))
        if u["is_carry"] and role not in ("ranged_ad", "caster"):
            role = "carry"
        by_role[role].append(u)

    placements: list[tuple[dict, int, int]] = []
    occupied: set[tuple[int, int]] = set()

    def claim(row: int, col: int, unit: dict) -> bool:
        for delta in [0, 1, -1, 2, -2, 3, -3]:
            c = col + delta
            if 0 <= c < 7 and (row, c) not in occupied:
                placements.append((unit, row, c))
                occupied.add((row, c))
                return True
        for c in range(7):
            if (row, c) not in occupied:
                placements.append((unit, row, c))
                occupied.add((row, c))
                return True
        return False

    # 1. Primary carry in back corner.
    carries = by_role["carry"] + [u for u in by_role["ranged_ad"] if u["is_carry"]]
    primary_carry = carries[0] if carries else None
    carry_col = 0 if has_assassins else 6
    if primary_carry:
        claim(3, carry_col, primary_carry)

    # 2. Supports adjacent to carry (back row).
    supports = list(by_role["support"])
    adj_dir = 1 if has_assassins else -1  # away from corner
    next_col = carry_col + adj_dir
    for sup in supports:
        if 0 <= next_col < 7:
            claim(3, next_col, sup)
            next_col += adj_dir

    # 3. Other carries / ranged_ad without carry tag → back row, opposite end if room.
    other_back = [u for u in carries[1:] if u not in placements_units(placements)]
    other_back += [u for u in by_role["ranged_ad"] if not u["is_carry"]]
    far_col = 6 if has_assassins else 0
    for u in other_back:
        claim(3, far_col, u)
        far_col += -1 if has_assassins else 1

    # 4. Casters → row 2 (mid-back), behind tanks.
    casters = list(by_role["caster"])
    caster_cols = [3, 2, 4, 1, 5, 0, 6]
    for u in casters:
        for c in caster_cols:
            if (2, c) not in occupied:
                claim(2, c, u)
                break

    # 5. Divers → row 1 flanks (they jump anyway, position to soak less AOE).
    divers = list(by_role["diver"])
    diver_cols = [0, 6, 1, 5, 3]
    for u in divers:
        for c in diver_cols:
            if (1, c) not in occupied:
                claim(1, c, u)
                break

    # 6. Primary tanks → row 0 front, middle first then spread to absorb hits.
    tanks = list(by_role["tank"]) + list(by_role["flex"])
    tank_cols = [3, 2, 4, 1, 5, 0, 6]
    for u in tanks:
        for c in tank_cols:
            if (0, c) not in occupied:
                claim(0, c, u)
                break

    # 7. Anything still unplaced → spill into nearest empty cell.
    placed_units = {id(u) for u, _, _ in placements}
    for u in units:
        if id(u) not in placed_units:
            for r in (1, 2, 0, 3):
                for c in range(7):
                    if (r, c) not in occupied:
                        claim(r, c, u)
                        break
                else:
                    continue
                break

    return placements


def placements_units(placements):
    return [u for u, _, _ in placements]


def _positioning(comp: dict, opponents: dict[int, list[str]], comps: list[dict]) -> list[str]:
    """Return one positioning instruction per unit, in placement order."""
    threats = _field_threats(opponents, comps)
    has_assassins = bool(threats["assassin"])

    units = comp["units"]
    by_role: dict[str, list[dict]] = {"tank": [], "support": [], "caster": [],
                                      "ranged_ad": [], "diver": [], "carry": [], "flex": []}
    for u in units:
        role = _classify_role(u["unit_name"], bool(u["is_carry"]))
        # Carries override role placement: they go in back row.
        if u["is_carry"] and role not in ("ranged_ad", "caster"):
            role = "carry"
        by_role[role].append(u)

    lines: list[str] = []

    # Back row: carries + ranged AD + supports
    backliners = by_role["carry"] + by_role["ranged_ad"] + by_role["caster"] + by_role["support"]
    for i, u in enumerate(backliners):
        if u["is_carry"]:
            corner = "far-LEFT corner" if has_assassins else "far-RIGHT corner"
            note = f" [CARRY — {corner}"
            if has_assassins:
                threat_p = ", ".join(f"P{p}" for p in threats['assassin'])
                note += f", away from {threat_p} assassins]"
            else:
                note += "]"
            lines.append(f"{u['unit_name']}: BACK row, {corner}{note}")
        else:
            slot = ["left", "mid-left", "middle", "mid-right", "right"][min(i, 4)]
            lines.append(f"{u['unit_name']}: BACK row, {slot}")

    # Mid row: casters/supports if too many backliners
    # (already placed above; skip)

    # Front row: tanks + divers
    frontliners = by_role["tank"] + by_role["diver"] + by_role["flex"]
    if frontliners:
        # Spread tanks across front row to absorb hits.
        slot_labels = ["far-left", "left", "mid-left", "middle", "mid-right", "right", "far-right"]
        # Place primary tank in middle, others spread out from there.
        ordered = []
        if frontliners:
            ordered.append((frontliners[0], "middle"))
            for j, u in enumerate(frontliners[1:]):
                ordered.append((u, slot_labels[j] if j < len(slot_labels) else "flex"))
        for u, slot in ordered:
            tag = " (CC anchor)" if "diver" in _classify_role(u["unit_name"], False) else ""
            lines.append(f"{u['unit_name']}: FRONT row, {slot}{tag}")

    if has_assassins:
        lines.append(f"⚠ Assassin threat: keep carries in back corner, NOT center back")
    if threats["ranged_reach"] and not has_assassins:
        lines.append(f"⚠ Ranged threat: spread backline, don't clump 3 in a corner")

    return lines


def recommend_shop(shop_unit_slugs: list[str | None], ctx: GameContext, target_comp_name: str | None = None) -> list[Recommendation]:
    """Given the 5 units currently in your shop, highlight which to buy.

    Priority: carry of target comp > 3-star reroll target you're already holding > comp units > skip.
    """
    db.init_db()
    target_comp = None
    comps = db.all_comps()
    if target_comp_name:
        for c in comps:
            if c["name"].lower() == target_comp_name.lower():
                target_comp = c
                break
    if not target_comp:
        # Use best counter pick if opponents scouted, else closest to your board
        if ctx.opponents:
            picks = _best_counter_pick(ctx.opponents, comps, your_units=ctx.your_units)
            if picks:
                target_comp = picks[0][0]
        elif ctx.your_units:
            closest = _closest_comps(ctx.your_units, comps, top_k=1)
            if closest:
                target_comp = closest[0][0]

    if not target_comp:
        return [Recommendation(
            headline="Shop scanned, but no target comp set",
            detail_lines=["Press F1 on your board + opponents first so I know what to recommend."],
            severity="warn",
        )]

    target_slugs = {_slug(u["unit_name"]): u for u in target_comp["units"]}
    recommendations: list[dict] = []
    for slot, slug in enumerate(shop_unit_slugs):
        if slug is None:
            recommendations.append({"slot": slot + 1, "slug": None, "name": "(empty/unrecognized)", "action": "skip", "reason": ""})
            continue
        s = _slug(slug)
        if s in target_slugs:
            u = target_slugs[s]
            if u["is_carry"]:
                action, reason = "BUY", f"CARRY for {target_comp['name']}"
            elif u.get("star_target", 2) >= 3:
                action, reason = "BUY", "3-star reroll target"
            else:
                action, reason = "buy", "in target comp"
        else:
            # Check if it's a carry/key unit in any S-tier comp (good pivot piece)
            for c in comps:
                if (c.get("tier") or "B") in ("S", "A"):
                    for cu in c["units"]:
                        if _slug(cu["unit_name"]) == s and cu["is_carry"]:
                            action, reason = "consider", f"carry for {c['name']} ({c.get('tier')}-tier)"
                            break
                    else:
                        continue
                    break
            else:
                action, reason = "skip", "off-comp"
        my_unit = next((u for u in target_comp["units"] if _slug(u["unit_name"]) == s), None)
        display = my_unit["unit_name"] if my_unit else _display_name(s, comps)
        recommendations.append({
            "slot": slot + 1, "slug": s, "name": display,
            "action": action, "reason": reason,
            "is_carry": bool(my_unit and my_unit["is_carry"]),
        })

    # Build single visual recommendation card
    return [Recommendation(
        headline=f"Shop (target: {target_comp['name']})",
        severity="info",
        play_view={"shop_view": True, "shop_recommendations": recommendations, "comp_name": target_comp["name"]},
    )]


def recommend_augment(choices: list[str], ctx: GameContext, recommended_comp_name: str | None = None) -> list[Recommendation]:
    """Rank a list of 3 augment choices by tier + comp synergy.

    `choices` are user-typed augment names (fuzzy matched against the DB).
    `recommended_comp_name` (optional) — if known, weights synergy with that comp.
    Falls back to deriving target comp from ctx.your_units if not provided.
    """
    db.init_db()

    # Determine the comp we're optimizing for.
    target_comp = None
    if recommended_comp_name:
        comps = db.all_comps()
        for c in comps:
            if c["name"].lower() == recommended_comp_name.lower():
                target_comp = c
                break
    if not target_comp and ctx.your_units:
        comps = db.all_comps()
        closest = _closest_comps(ctx.your_units, comps, top_k=1)
        if closest:
            target_comp = closest[0][0]
    target_name = target_comp["name"] if target_comp else None

    resolved: list[tuple[str, dict | None]] = []
    for raw in choices:
        if not raw or not raw.strip():
            continue
        aug = db.find_augment(raw)
        resolved.append((raw, aug))

    if not resolved:
        return [Recommendation(
            headline="No augments entered",
            detail_lines=["Type 3 augment names (or unique prefixes), separated by commas."],
            severity="warn",
        )]

    tier_score = {"S": 3.0, "A": 2.0, "B": 1.0, "C": 0.0}
    rarity_bonus = {"Prismatic": 0.5, "Gold": 0.2, "Silver": 0.0}

    scored: list[tuple[str, dict | None, float, list[str]]] = []
    for raw, aug in resolved:
        if aug is None:
            scored.append((raw, None, -10.0, ["NOT FOUND in augment DB — typo or new augment"]))
            continue
        notes = []
        score = tier_score.get(aug.get("general_tier") or "B", 1.0)
        score += rarity_bonus.get(aug.get("tier_rarity") or "Silver", 0.0)
        notes.append(f"Generic tier: {aug.get('general_tier') or '?'} ({aug.get('tier_rarity') or '?'})")

        # Synergy bonus if augment lists target comp.
        if target_name and target_name in aug.get("synergies", []):
            score += 2.5
            notes.append(f"✓ DIRECT synergy with {target_name}")
        elif aug.get("synergies"):
            notes.append(f"Synergizes with: {', '.join(aug['synergies'][:3])}")

        if aug.get("notes"):
            notes.append(aug["notes"])

        scored.append((raw, aug, score, notes))

    scored.sort(key=lambda x: x[2], reverse=True)

    recs: list[Recommendation] = []
    if target_name:
        recs.append(Recommendation(
            headline=f"Augment ranking (optimizing for: {target_name})",
            detail_lines=[],
            severity="info",
        ))
    else:
        recs.append(Recommendation(
            headline="Augment ranking (no target comp set — using generic tiers)",
            detail_lines=["Tip: scout opponents first or pass a comp name for synergy weighting."],
            severity="info",
        ))

    medals = ["★ PICK", "  2nd", "  3rd", "  4th"]
    for i, (raw, aug, score, notes) in enumerate(scored):
        label = medals[min(i, len(medals) - 1)]
        name = aug["name"] if aug else raw
        head = f"{label}: {name}  (score {score:.1f})"
        recs.append(Recommendation(
            headline=head,
            detail_lines=notes,
            severity="urgent" if i == 0 else "info",
        ))

    return recs


def _comp_profile(comp: dict) -> tuple[set[str], set[str]]:
    """Aggregate strengths and weaknesses for a comp by inspecting its name + units.

    Looks for known trait keywords (Set 17 traits + classes) and unions their
    profiles from COMP_PROFILE. Defaults to empty sets if nothing matches.
    """
    blob = (comp.get("name", "") + " " + " ".join(u["unit_name"] for u in comp["units"])).lower()
    strengths: set[str] = set()
    weaknesses: set[str] = set()
    for trait_key, profile in COMP_PROFILE.items():
        if trait_key in blob:
            strengths.update(profile["strengths"])
            weaknesses.update(profile["weaknesses"])
    return strengths, weaknesses


def _profile_from_raw_units(units: list[str]) -> tuple[set[str], set[str]]:
    """Infer strengths/weaknesses directly from a list of unit names — works
    even when we can't fully identify an opponent's comp. Counts unit ROLES."""
    role_count: dict[str, int] = {}
    for u in units:
        role = ROLE_HINTS.get(_slug(u), "flex")
        role_count[role] = role_count.get(role, 0) + 1

    n = max(1, len(units))
    strengths: set[str] = set()
    weaknesses: set[str] = set()

    tanks = role_count.get("tank", 0) + role_count.get("flex", 0)
    casters = role_count.get("caster", 0)
    ranged_ad = role_count.get("ranged_ad", 0)
    divers = role_count.get("diver", 0)

    # Tank-heavy comp: defensive wall, weak to shred/burn/true damage
    if tanks >= max(2, n * 0.6):
        strengths.add("tank_wall")
        weaknesses.update(["vs_burn", "vs_shred", "vs_true_dmg"])

    # AP carry comp: weak to MR, immune to physical-only counters
    if casters >= 1 and tanks <= n * 0.6:  # not also tanky
        strengths.add("ap_dmg")
        weaknesses.add("vs_mr")

    # AD ranged carry comp: classic vs_dive vulnerability
    if ranged_ad >= 1 and divers == 0:
        strengths.add("ad_dmg")
        weaknesses.update(["vs_dive", "vs_armor"])

    # Pure dive comp: weak to taunt/cc anchors
    if divers >= max(2, n * 0.5):
        strengths.add("dives_backline")
        weaknesses.add("vs_taunt")

    # Mixed comps with no clear archetype: don't tag — they shouldn't dominate scoring

    return strengths, weaknesses


def _aggregate_field(opponents: dict[int, list[str]], comps: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Tally enemy strengths and weaknesses across the field.

    For each opponent: uses identified comp profile if a comp matches strongly,
    otherwise falls back to direct unit-role inference (ensures every opponent
    contributes even with partial scout data).
    """
    str_count: dict[str, int] = {}
    weak_count: dict[str, int] = {}
    for pnum, units in opponents.items():
        # Try known-comp identification first
        ec = _identify_opponent_comp(units, comps)
        if ec:
            s, w = _comp_profile(ec)
        else:
            # Fall back to raw-unit-based profile so every opponent counts
            s, w = _profile_from_raw_units(units)
        for tag in s:
            str_count[tag] = str_count.get(tag, 0) + 1
        for tag in w:
            weak_count[tag] = weak_count.get(tag, 0) + 1
    return str_count, weak_count


def _best_counter_pick(opponents: dict[int, list[str]], comps: list[dict],
                       your_units: list[str] | None = None) -> list[tuple[dict, float, dict]]:
    """Score every comp by:
      + EXPLOIT score: my strengths × enemy weaknesses
      − VULNERABILITY score: my weaknesses × enemy strengths
      − contest penalty
      + tier bonus
      + dominance bonus
      − DOWNGRADE penalty: if comp's avg unit cost is meaningfully lower than
        the user's current avg cost, penalize (don't suggest tier-down pivots
        unless contest forces it).

    Returns top 3 with their score breakdown.
    """
    if not opponents or not comps:
        return []

    enemy_strengths_count, enemy_weaknesses_count = _aggregate_field(opponents, comps)
    n_field = len(opponents)
    my_avg_cost = avg_cost_of(your_units) if your_units else 0.0

    scored = []
    for cand in comps:
        my_strengths, my_weaknesses = _comp_profile(cand)
        cand_carries = {_slug(u["unit_name"]) for u in cand["units"] if u["is_carry"]}
        cand_avg_cost = avg_cost_of([u["unit_name"] for u in cand["units"]])

        # Exploit score
        exploit = 0
        for s in my_strengths:
            for target_weakness in EXPLOITS.get(s, []):
                exploit += enemy_weaknesses_count.get(target_weakness, 0)

        # Vulnerability score
        vulnerability = 0
        for enemy_strength, count in enemy_strengths_count.items():
            for my_weak in EXPLOITS.get(enemy_strength, []):
                if my_weak in my_weaknesses:
                    vulnerability += count

        # Contest
        contest = sum(
            1 for _, units in opponents.items()
            if cand_carries & {_slug(u) for u in units}
        )

        tier_bonus = {"S": 1.5, "A": 0.7, "B": 0.0, "C": -0.7}.get(cand.get("tier") or "B", 0.0)

        # Dominance: 3+ enemies share an exploitable weakness
        dominance = 0.0
        for s in my_strengths:
            for target in EXPLOITS.get(s, []):
                if enemy_weaknesses_count.get(target, 0) >= 3:
                    dominance += 1.0
                    break

        # Heavy contest penalty
        contest_penalty = contest * 1.5
        if contest >= 2:
            contest_penalty += 2.0

        # Downgrade penalty: punish recommending a comp meaningfully cheaper than
        # what the user is already running. Skip when contest would force a pivot.
        downgrade_penalty = 0.0
        if your_units and contest < 2:
            gap = my_avg_cost - cand_avg_cost
            if gap > 0:
                # 0.7 per cost-tier of downgrade — strong enough to flip a S-tier
                # reroll loss vs a competitive A-tier scaling comp
                downgrade_penalty = gap * 1.4

        score = (exploit * 1.0
                 - vulnerability * 1.0
                 - contest_penalty
                 + tier_bonus
                 + dominance
                 - downgrade_penalty)

        scored.append((cand, score, {
            "exploit": exploit,
            "vulnerability": vulnerability,
            "contest": contest,
            "tier_bonus": tier_bonus,
            "dominance": dominance,
            "field_size": n_field,
            "downgrade_penalty": downgrade_penalty,
            "cand_avg_cost": cand_avg_cost,
            "my_avg_cost": my_avg_cost,
        }))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:3]


def recommend(ctx: GameContext) -> list[Recommendation]:
    """Return ONE focused recommendation: 'play this comp'.

    Decision: based purely on the scouted field (we don't try to know your board).
    Scoring picks the highest-tier comp that counters the field with low contest.
    Output is intentionally minimal — units to grab, items to slam, where to put the carry.
    """
    db.init_db()
    comps = db.all_comps()
    if not comps:
        return [Recommendation(
            headline="No meta data loaded — run scripts/seed_comps.py",
            severity="warn",
        )]

    scouted = len(ctx.opponents)

    if scouted == 0:
        return [Recommendation(
            headline="Scout opponents with F1 to get a recommendation",
            detail_lines=[f"Press F1 while looking at each opponent's board ({config.OPPONENT_COUNT} total)."],
        )]

    picks = _best_counter_pick(ctx.opponents, comps, your_units=ctx.your_units)
    if not picks:
        return [Recommendation(
            headline=f"Scouted {scouted}/{config.OPPONENT_COUNT} — none identifiable yet",
            detail_lines=["Keep pressing F1 on the remaining opponents."],
        )]

    # Stage/level filter: drop comps that are wildly out of reach.
    cost_ceiling = max_obtainable_cost(ctx.stage, ctx.your_level)
    if cost_ceiling < 5:
        filtered = []
        for cand, score, br in picks:
            unobtainable = sum(
                1 for u in cand["units"]
                if UNIT_COSTS.get(_slug(u["unit_name"]), 1) > cost_ceiling
            )
            # Allow comps where <=1 unit is unreachable (you'll grow into them).
            if unobtainable <= 1:
                filtered.append((cand, score, br))
        if filtered:
            picks = filtered

    # Re-rank picks: bias toward comps the user is already partially built on.
    # transition_bonus = (units in comp the user has) / (units in comp).
    if ctx.your_units:
        my_set = {_slug(u) for u in ctx.your_units}
        rescored = []
        for cand, sc, br in picks:
            cand_units = {_slug(u["unit_name"]) for u in cand["units"]}
            transition = len(my_set & cand_units) / max(1, len(cand_units))
            rescored.append((cand, sc + transition * 1.0, {**br, "transition": transition}))
        rescored.sort(key=lambda x: x[1], reverse=True)
        picks = rescored

    # === STICKINESS OVERRIDE ===
    # If the user is currently winning AND has built into the previously
    # recommended comp, DON'T suggest a different comp. Lock in.
    confidence_state = "PLAY" if scouted >= 6 else f"BEST GUESS ({scouted}/{config.OPPONENT_COUNT})"
    if ctx.last_rec_comp_name and ctx.your_units:
        # Look up previous comp from full DB (not just top-3 picks)
        prev_cand = next((c for c in comps if c["name"] == ctx.last_rec_comp_name), None)
        if prev_cand:
            my_set = {_slug(u) for u in ctx.your_units}
            prev_units = {_slug(u["unit_name"]) for u in prev_cand["units"]}
            on_comp_pct = len(my_set & prev_units) / max(1, len(prev_units))
            prev_carries = {_slug(u["unit_name"]) for u in prev_cand["units"] if u["is_carry"]}
            prev_contest = sum(
                1 for _, opps in ctx.opponents.items()
                if prev_carries & {_slug(u) for u in opps}
            )

            # Build a synthetic picks-entry for the previous comp so downstream
            # logic (placement, items, etc.) treats it as the chosen one.
            prev_breakdown = {
                "exploit": 0, "vulnerability": 0, "contest": prev_contest,
                "tier_bonus": 0, "dominance": 0, "field_size": len(ctx.opponents),
                "downgrade_penalty": 0.0, "cand_avg_cost": avg_cost_of([u["unit_name"] for u in prev_cand["units"]]),
                "my_avg_cost": avg_cost_of(ctx.your_units), "transition": on_comp_pct,
            }
            prev_entry = (prev_cand, 0.0, prev_breakdown)

            #   (a) winning + 30%+ built + low contest → STAY THE COURSE
            #   (b) 50%+ built + neutral → KEEP BUILDING (don't pivot mid-build)
            if ctx.is_winning and on_comp_pct >= 0.30 and prev_contest < 2:
                picks = [prev_entry] + [p for p in picks if p[0]["name"] != ctx.last_rec_comp_name]
                confidence_state = f"STAY THE COURSE · {ctx.win_streak}W streak"
            elif on_comp_pct >= 0.50 and prev_contest < 2 and ctx.loss_streak < 3:
                picks = [prev_entry] + [p for p in picks if p[0]["name"] != ctx.last_rec_comp_name]
                confidence_state = f"KEEP BUILDING · {int(on_comp_pct*100)}% there"

    primary, score, breakdown = picks[0]
    # Mark confidence state on breakdown so caller can surface it
    if "STAY" in confidence_state or "KEEP" in confidence_state:
        breakdown["sticky"] = True
    elif ctx.last_rec_comp_name and primary["name"] != ctx.last_rec_comp_name and ctx.loss_streak >= 2:
        confidence_state = f"PIVOT · {ctx.loss_streak}L streak"
        breakdown["pivot_signal"] = True
    primary_units = primary["units"]
    primary_slugs = {_slug(u["unit_name"]): u for u in primary_units}
    carries = [u["unit_name"] for u in primary_units if u["is_carry"]]
    confidence = confidence_state  # set above by stickiness logic

    cost_ceiling = max_obtainable_cost(ctx.stage, ctx.your_level)
    active_costs, next_costs = active_buy_costs(ctx.your_level, primary.get("play_style"))
    my_slugs: dict[str, str] = {}
    have_units, buy_units, next_units, sell_units, locked_units = [], [], [], [], []

    def _make_entry(slug, u):
        return {
            "name": u["unit_name"], "slug": slug,
            "is_carry": bool(u["is_carry"]),
            "star_target": u.get("star_target", 2),
            "cost": UNIT_COSTS.get(slug, 1),
        }

    def _priority(entry):
        # Sort: carries first, then 3-star reroll targets, then by cost ascending
        return (
            0 if entry["is_carry"] else (1 if entry["star_target"] >= 3 else 2),
            entry["cost"],
            entry["name"],
        )

    if ctx.your_units:
        my_slugs = {_slug(u): u for u in ctx.your_units}
        for slug, u in primary_slugs.items():
            entry = _make_entry(slug, u)
            if slug in my_slugs:
                have_units.append(entry)
            elif entry["cost"] > cost_ceiling:
                locked_units.append(entry)
            elif entry["cost"] in active_costs:
                buy_units.append(entry)
            elif entry["cost"] in next_costs:
                next_units.append(entry)
            else:
                # cost > active+next but ≤ cost_ceiling — still a future target
                locked_units.append(entry)
        for slug, raw in my_slugs.items():
            if slug not in primary_slugs:
                sell_units.append({"name": _display_name(raw, comps), "slug": slug})
    else:
        for slug, u in primary_slugs.items():
            entry = _make_entry(slug, u)
            if entry["cost"] > cost_ceiling:
                locked_units.append(entry)
            elif entry["cost"] in active_costs:
                buy_units.append(entry)
            elif entry["cost"] in next_costs:
                next_units.append(entry)
            else:
                locked_units.append(entry)

    buy_units.sort(key=_priority)
    next_units.sort(key=_priority)
    locked_units.sort(key=_priority)

    placements = _assign_positions(primary, ctx.opponents, comps)
    placement_view = [
        {"name": u["unit_name"], "slug": _slug(u["unit_name"]),
         "is_carry": bool(u["is_carry"]),
         "star_target": u.get("star_target", 2),
         "have": _slug(u["unit_name"]) in my_slugs,
         "row": row, "col": col}
        for (u, row, col) in placements
    ]

    item_view = [
        {"unit": it["unit_name"], "item": it["item_name"],
         "unit_slug": _slug(it["unit_name"]), "item_slug": _slug(it["item_name"])}
        for it in primary["items"] if it["unit_name"] in carries
    ]

    threats = _field_threats(ctx.opponents, comps)
    notes: list[str] = []
    if breakdown.get("contest", 0) >= 2:
        notes.append(f"⚠ HIGH CONTEST: {breakdown['contest']} other players on this")
    if threats["assassin"]:
        notes.append(f"Assassin threat: P{','.join(map(str, threats['assassin']))}")

    # Surface why this comp won (top exploits/vulnerabilities)
    if breakdown.get("exploit", 0) > 0:
        notes.append(f"✓ Exploits {breakdown['exploit']} field weaknesses")
    if breakdown.get("vulnerability", 0) > 0:
        notes.append(f"⚠ Has {breakdown['vulnerability']} weaknesses the field can hit")

    # Pivot signal (only when user has scouted self and is far from recommended comp)
    pivot = detect_pivot_signal(ctx.your_units, primary)
    if pivot:
        notes.insert(0, pivot)

    # Stage / level / econ advice
    advice = level_advice(ctx.your_level, ctx.your_gold, ctx.your_hp, ctx.stage)
    if advice:
        notes.append(advice)

    play_view = {
        "comp_name": primary["name"],
        "tier": primary.get("tier") or "?",
        "level": primary.get("target_level") or "?",
        "play_style": primary.get("play_style") or "standard",
        "avg_place": primary.get("avg_placement"),
        "confidence": confidence,
        "placements": placement_view,
        "have_units": have_units,
        "buy_units": buy_units,         # right-now shopping list
        "next_units": next_units,        # upcoming next level
        "locked_units": locked_units,    # too high cost for current stage
        "sell_units": sell_units,
        "items": item_view,
        "carry_name": carries[0] if carries else None,
        "notes": notes,
        "have_count": len(have_units),
        "total_count": len(primary_units),
        "cost_ceiling": cost_ceiling,
        "current_level": ctx.your_level,
    }

    return [Recommendation(
        headline=f"{confidence}: {primary['name']}",
        severity="urgent",
        play_view=play_view,
    )]
