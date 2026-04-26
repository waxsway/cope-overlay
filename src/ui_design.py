"""Design tokens for the overlay UI. Colors, typography, spacing — referenced
everywhere instead of inlining hex values throughout overlay.py."""
from __future__ import annotations


# Color palette — deep dark theme with gold/blue accents.
COLOR = {
    # Backgrounds
    "bg":           "#0d1117",     # window base
    "surface":      "#161b22",     # primary cards
    "surface_2":    "#1f2730",     # elevated cards / hover
    "surface_3":    "#252c36",     # nested elements
    # Borders
    "border":       "#30363d",
    "border_strong":"#484f58",
    # Text
    "text":         "#e6edf3",     # primary
    "text_2":       "#9ba1ac",     # secondary
    "text_muted":   "#6e7681",     # captions
    # Accents
    "accent":       "#58a6ff",     # info/blue
    "carry":        "#ffd66b",     # gold for carries / S-tier
    "owned":        "#3fb950",     # green for have/owned
    "buy":          "#79c0ff",     # cyan for buy actions
    "warn":         "#d29922",     # amber
    "danger":       "#f85149",     # red
    "three_star":   "#d2a8ff",     # purple for 3-star target
    "tier_s":       "#ffb347",     # S tier (orange-gold gradient start)
    "tier_a":       "#a0c4ff",     # A tier (silver-blue)
    "tier_b":       "#9ba1ac",
    "tier_c":       "#6e7681",
}

# Typography — px sizes.
FONT = {
    "display":      ("Segoe UI", 22, 700),
    "headline":     ("Segoe UI", 16, 700),
    "subhead":      ("Segoe UI", 13, 600),
    "body":         ("Segoe UI", 12, 400),
    "body_strong":  ("Segoe UI", 12, 600),
    "caption":      ("Segoe UI", 10, 600),
    "mono":         ("Consolas", 11, 400),
}

# Spacing scale — 4/8 grid.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

# Sizing
PORTRAIT_LG = 56
PORTRAIT_MD = 44
PORTRAIT_SM = 36
ITEM_LG = 40
ITEM_MD = 28
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 10


def font_qss(token: str) -> str:
    """Return a CSS font-family / size / weight rule for a font token."""
    family, size, weight = FONT[token]
    return f"font-family: '{family}'; font-size: {size}px; font-weight: {weight};"


def tier_gradient(tier: str) -> str:
    """CSS qlineargradient for tier badge."""
    if tier == "S":
        return "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffb347, stop:1 #ffd66b)"
    if tier == "A":
        return "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #a0c4ff, stop:1 #d4dfff)"
    if tier == "B":
        return "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6e7681, stop:1 #9ba1ac)"
    return COLOR["text_muted"]
