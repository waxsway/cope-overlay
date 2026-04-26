"""PyQt6 overlay window. Frameless, transparent, always on top, draggable.

Design system in src/ui_design.py — colors, typography, spacing tokens.
Keep visual decisions there, not inlined here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config
from src.recommender import Recommendation
from src.ui_design import COLOR, FONT, SPACE, PORTRAIT_LG, PORTRAIT_MD, PORTRAIT_SM, ITEM_LG, ITEM_MD, RADIUS_SM, RADIUS_MD, RADIUS_LG, font_qss, tier_gradient


# Module-level hover label (set by OverlayWindow on init)
_HOVER_LABEL: QLabel | None = None


class HoverFilter(QObject):
    def __init__(self, info_text: str):
        super().__init__()
        self.info = info_text

    def eventFilter(self, obj, event):
        if _HOVER_LABEL is None:
            return False
        if event.type() == QEvent.Type.Enter:
            _HOVER_LABEL.setText(self.info)
        elif event.type() == QEvent.Type.Leave:
            _HOVER_LABEL.setText("")
        return False


# -------------------- portrait / item primitives --------------------

def _portrait(slug: str, size: int = PORTRAIT_MD, dim: bool = False,
              display_name: str | None = None, extra_tooltip: str = "",
              border_color: str | None = None, glow_color: str | None = None) -> QLabel:
    """Champion portrait. Optional border + glow effect for highlights."""
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sprite_path = config.SPRITES_DIR / f"{slug}.png"
    if sprite_path.exists():
        pix = QPixmap(str(sprite_path)).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        if pix.width() > size or pix.height() > size:
            x = max(0, (pix.width() - size) // 2)
            y = max(0, (pix.height() - size) // 2)
            pix = pix.copy(x, y, size, size)
        lbl.setPixmap(pix)

    bg_alpha = "0" if sprite_path.exists() else "180"
    border = border_color or (COLOR["border_strong"] if not dim else COLOR["border"])
    border_style = "dashed" if dim else "solid"
    radius = RADIUS_MD
    lbl.setStyleSheet(f"""
        QLabel {{
            background: rgba(28, 32, 42, {bg_alpha});
            border: 2px {border_style} {border};
            border-radius: {radius}px;
            color: {COLOR['text_2']};
            {font_qss('caption')}
        }}
    """)
    if not sprite_path.exists():
        lbl.setText(slug[:5])

    # Glow effect for carries/highlighted
    if glow_color:
        eff = QGraphicsDropShadowEffect()
        eff.setBlurRadius(20)
        eff.setColor(QColor(glow_color))
        eff.setOffset(0, 0)
        lbl.setGraphicsEffect(eff)

    name = display_name or slug
    tip = name + (f" — {extra_tooltip}" if extra_tooltip else "")
    lbl.setToolTip(tip)
    hf = HoverFilter(tip)
    lbl.installEventFilter(hf)
    lbl._hover_filter = hf
    return lbl


def _item_icon(slug: str, size: int = ITEM_MD, display_name: str | None = None) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    item_path = config.ITEMS_DIR / f"{slug}.png"
    if item_path.exists():
        pix = QPixmap(str(item_path)).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        if pix.width() > size or pix.height() > size:
            x = max(0, (pix.width() - size) // 2)
            y = max(0, (pix.height() - size) // 2)
            pix = pix.copy(x, y, size, size)
        lbl.setPixmap(pix)
    else:
        lbl.setText("?")
    lbl.setStyleSheet(f"""
        QLabel {{
            background: {COLOR['surface_3']};
            border: 1px solid {COLOR['border']};
            border-radius: {RADIUS_SM}px;
            color: {COLOR['text_2']};
        }}
    """)
    name = display_name or slug
    lbl.setToolTip(name)
    hf = HoverFilter(name)
    lbl.installEventFilter(hf)
    lbl._hover_filter = hf
    return lbl


# -------------------- composite components --------------------

def _tier_badge(tier: str) -> QLabel:
    """Gradient pill showing tier letter."""
    badge = QLabel(tier)
    badge.setFixedSize(28, 22)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(f"""
        QLabel {{
            background: {tier_gradient(tier)};
            color: #1a1d24;
            border-radius: 11px;
            {font_qss('caption')}
            padding-bottom: 1px;
        }}
    """)
    return badge


def _cost_badge(cost: int) -> QLabel:
    """Tiny gold-coin-ish badge showing unit cost."""
    cost_color = ["#9ba1ac", "#c4d2d8", "#7be0c8", "#bc8cff", "#ffd66b", "#ff9966"][min(cost, 5)]
    badge = QLabel(f"{cost}g")
    badge.setFixedHeight(14)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(f"""
        QLabel {{
            background: rgba(0, 0, 0, 100);
            color: {cost_color};
            border: 1px solid {cost_color};
            border-radius: 7px;
            padding: 0 4px;
            {font_qss('caption')}
        }}
    """)
    return badge


def _scout_progress_dots(scouted: int, total: int = 7) -> QWidget:
    """Row of N dots, filled = scouted."""
    container = QWidget()
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    for i in range(total):
        dot = QLabel()
        dot.setFixedSize(8, 8)
        if i < scouted:
            color = COLOR["accent"]
        else:
            color = COLOR["surface_3"]
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        h.addWidget(dot)
    h.addStretch(1)
    return container


import math


class HexBoardWidget(QWidget):
    """True-hex-shaped TFT board visualizer.

    Pointy-top hexes arranged in 4 rows × 7 cols = 28 cells total. Odd-indexed
    rows are offset right by half a hex width (matches TFT's actual board).
    Each placed unit's portrait is clipped to the hex shape and drawn inside.
    """
    HEX_SIDE = 30   # side length in pixels
    PADDING = 8

    def __init__(self, placements: list[dict], parent=None):
        super().__init__(parent)
        self.placements = {(p["row"], p["col"]): p for p in placements}

        s = self.HEX_SIDE
        # Pointy-top hex dimensions
        self.hex_w = math.sqrt(3) * s
        self.hex_h = 2 * s
        # Row vertical spacing (centers): 1.5 * s for nesting
        self.row_v = 1.5 * s
        # Total board pixel size:
        #   width  = 7 cols × hex_w + 0.5 hex_w (for offset row)
        #   height = (4 - 1) × row_v + hex_h
        total_w = int(7 * self.hex_w + 0.5 * self.hex_w + 2 * self.PADDING)
        total_h = int(3 * self.row_v + self.hex_h + 2 * self.PADDING)
        self.setFixedSize(total_w, total_h)
        self.setMouseTracking(True)
        self._cell_centers: dict[tuple[int, int], tuple[float, float]] = {}
        # Cache portrait pixmaps clipped to hex.
        self._clipped_pix: dict[str, QPixmap] = {}
        self._compute_centers()

    def _compute_centers(self):
        s = self.HEX_SIDE
        for board_row in range(4):
            # FRONT row (board_row 0) renders at TOP visually.
            visual_row = board_row
            offset_x = (self.hex_w / 2) if visual_row % 2 == 1 else 0
            for col in range(7):
                cx = self.PADDING + offset_x + col * self.hex_w + self.hex_w / 2
                cy = self.PADDING + visual_row * self.row_v + s
                self._cell_centers[(board_row, col)] = (cx, cy)

    def _hex_polygon(self, cx: float, cy: float) -> QPolygonF:
        """Pointy-top hex centered at (cx, cy)."""
        s = self.HEX_SIDE
        pts = []
        for i in range(6):
            angle = math.pi / 180 * (60 * i - 30)  # rotate so flats are L/R
            pts.append(QPointF(cx + s * math.cos(angle), cy + s * math.sin(angle)))
        return QPolygonF(pts)

    def _clipped_portrait(self, slug: str) -> QPixmap | None:
        if slug in self._clipped_pix:
            return self._clipped_pix[slug]
        sprite_path = config.SPRITES_DIR / f"{slug}.png"
        if not sprite_path.exists():
            return None
        side = int(2 * self.HEX_SIDE)
        src = QPixmap(str(sprite_path)).scaled(
            side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        if src.width() > side or src.height() > side:
            x = max(0, (src.width() - side) // 2)
            y = max(0, (src.height() - side) // 2)
            src = src.copy(x, y, side, side)
        # Clip to hex shape using a transparent canvas.
        canvas = QPixmap(side, side)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        # Hex aligned to canvas center
        cx, cy = side / 2, side / 2
        s = self.HEX_SIDE
        pts = []
        for i in range(6):
            angle = math.pi / 180 * (60 * i - 30)
            pts.append(QPointF(cx + s * math.cos(angle), cy + s * math.sin(angle)))
        path.addPolygon(QPolygonF(pts))
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, src)
        painter.end()
        self._clipped_pix[slug] = canvas
        return canvas

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for (row, col), (cx, cy) in self._cell_centers.items():
            poly = self._hex_polygon(cx, cy)
            placement = self.placements.get((row, col))
            if placement is None:
                # Empty hex
                painter.setBrush(QBrush(QColor(COLOR["surface_3"])))
                painter.setPen(QPen(QColor(COLOR["border"]), 1))
                painter.drawPolygon(poly)
                continue
            # Filled cell — draw clipped portrait then border
            pix = self._clipped_portrait(placement["slug"])
            if pix is not None:
                side = int(2 * self.HEX_SIDE)
                painter.drawPixmap(int(cx - side / 2), int(cy - side / 2), pix)
            else:
                painter.setBrush(QBrush(QColor(COLOR["surface_2"])))
                painter.setPen(QPen(QColor(COLOR["border_strong"]), 1))
                painter.drawPolygon(poly)
            # Border / highlight
            border_color = COLOR["border_strong"]
            border_width = 2
            if placement["is_carry"]:
                border_color = COLOR["carry"]
                border_width = 3
            elif placement.get("star_target", 2) >= 3:
                border_color = COLOR["three_star"]
            elif placement["have"]:
                border_color = COLOR["owned"]
            elif not placement["have"]:
                border_color = COLOR["text_muted"]
                # Dashed for buy targets
                pen = QPen(QColor(border_color), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(poly)
                continue
            painter.setPen(QPen(QColor(border_color), border_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(poly)
        painter.end()

    def mouseMoveEvent(self, event):
        # Update hover label when cursor enters a placed hex
        if _HOVER_LABEL is None:
            return
        x, y = event.position().x(), event.position().y()
        for (row, col), (cx, cy) in self._cell_centers.items():
            if math.hypot(x - cx, y - cy) <= self.HEX_SIDE * 0.95:
                placement = self.placements.get((row, col))
                if placement:
                    extras = []
                    if placement["is_carry"]:
                        extras.append("CARRY")
                    if placement.get("star_target", 2) >= 3:
                        extras.append("3-star target")
                    extras.append("HAVE" if placement["have"] else "BUY")
                    _HOVER_LABEL.setText(f"{placement['name']} — {' · '.join(extras)}")
                    return
                else:
                    _HOVER_LABEL.setText("")
                    return
        _HOVER_LABEL.setText("")

    def leaveEvent(self, event):
        if _HOVER_LABEL:
            _HOVER_LABEL.setText("")


def build_board_visualizer(placements: list[dict]) -> QWidget:
    """Card-wrapped hex board: FRONT row at top, BACK row at bottom.
    Uses true hex shapes (28 cells: 4 rows × 7 cols)."""
    wrapper = QFrame()
    wrapper.setStyleSheet(f"""
        QFrame {{
            background: {COLOR['surface_2']};
            border: 1px solid {COLOR['border']};
            border-radius: {RADIUS_LG}px;
        }}
    """)
    wv = QVBoxLayout(wrapper)
    wv.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
    wv.setSpacing(SPACE["xs"])

    front_label = QLabel("FRONT  ▲  fights enemy first")
    front_label.setStyleSheet(f"color: {COLOR['text_muted']}; {font_qss('caption')}")
    front_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    wv.addWidget(front_label)

    hex_widget = HexBoardWidget(placements)
    wv.addWidget(hex_widget, alignment=Qt.AlignmentFlag.AlignHCenter)

    back_label = QLabel("BACK  ▼  your carries")
    back_label.setStyleSheet(f"color: {COLOR['text_muted']}; {font_qss('caption')}")
    back_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    wv.addWidget(back_label)
    return wrapper


def build_unit_row(units: list[dict], action: str = "BUY", action_color: str | None = None) -> QWidget:
    """Compact unit cards in a horizontal row. Action label printed once at left."""
    container = QFrame()
    container.setStyleSheet(f"""
        QFrame {{
            background: {COLOR['surface_2']};
            border: 1px solid {COLOR['border']};
            border-radius: {RADIUS_MD}px;
        }}
    """)
    h = QHBoxLayout(container)
    h.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
    h.setSpacing(SPACE["sm"])

    color = action_color or COLOR["text_2"]
    action_lbl = QLabel(action)
    action_lbl.setStyleSheet(f"color: {color}; {font_qss('caption')}")
    action_lbl.setMinimumWidth(60)
    h.addWidget(action_lbl)

    for u in units:
        cell = QWidget()
        v = QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        tip = []
        if u.get("is_carry"):
            tip.append("CARRY")
        if u.get("star_target", 2) >= 3:
            tip.append("3-star target")
        if "cost" in u:
            tip.append(f"{u['cost']}-cost")
        border_col = None
        glow = None
        if u.get("is_carry"):
            border_col = COLOR["carry"]
            glow = COLOR["carry"]
        elif u.get("star_target", 2) >= 3:
            border_col = COLOR["three_star"]
        portrait = _portrait(
            u["slug"], size=PORTRAIT_SM, dim=False,
            display_name=u.get("name"), extra_tooltip=" · ".join(tip),
            border_color=border_col, glow_color=glow,
        )
        v.addWidget(portrait, alignment=Qt.AlignmentFlag.AlignCenter)
        if "cost" in u:
            badge = _cost_badge(u["cost"])
            v.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)
        h.addWidget(cell)
    h.addStretch(1)
    return container


def build_item_row(items: list[dict], carry_name: str | None) -> QWidget:
    container = QFrame()
    container.setStyleSheet(f"""
        QFrame {{
            background: {COLOR['surface_2']};
            border: 1px solid {COLOR['border']};
            border-radius: {RADIUS_MD}px;
        }}
    """)
    h = QHBoxLayout(container)
    h.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
    h.setSpacing(SPACE["sm"])
    label = QLabel(f"ITEMS · {carry_name or 'carry'}")
    label.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('caption')}")
    label.setMinimumWidth(120)
    h.addWidget(label)
    for i, it in enumerate(items, 1):
        cell = QWidget()
        v = QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(_item_icon(it["item_slug"], size=ITEM_LG, display_name=it.get("item")))
        n = QLabel(f"#{i}")
        n.setStyleSheet(f"color: {COLOR['text_muted']}; {font_qss('caption')}")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(n)
        h.addWidget(cell)
    h.addStretch(1)
    return container


def _banner(text: str, severity: str) -> QWidget:
    icon = {"info": "•", "warn": "⚠", "danger": "✕", "success": "✓"}.get(severity, "•")
    color = {"info": COLOR["accent"], "warn": COLOR["warn"], "danger": COLOR["danger"], "success": COLOR["owned"]}.get(severity, COLOR["accent"])
    bg_alpha = "44"
    container = QFrame()
    container.setStyleSheet(f"""
        QFrame {{
            background: rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.10);
            border-left: 3px solid {color};
            border-radius: {RADIUS_SM}px;
        }}
    """)
    h = QHBoxLayout(container)
    h.setContentsMargins(SPACE["md"], SPACE["xs"], SPACE["md"], SPACE["xs"])
    h.setSpacing(SPACE["sm"])
    icon_lbl = QLabel(icon)
    icon_lbl.setStyleSheet(f"color: {color}; {font_qss('subhead')}")
    h.addWidget(icon_lbl)
    text_lbl = QLabel(text)
    text_lbl.setStyleSheet(f"color: {COLOR['text']}; {font_qss('body')}")
    text_lbl.setWordWrap(True)
    h.addWidget(text_lbl, 1)
    return container


# -------------------- main overlay window --------------------

class OverlayWindow(QMainWindow):
    refresh_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(config.OVERLAY_OPACITY)

        pos = self._load_position()
        self.setGeometry(
            pos.get("x", config.OVERLAY_DEFAULT_X),
            pos.get("y", config.OVERLAY_DEFAULT_Y),
            pos.get("w", config.OVERLAY_WIDTH),
            pos.get("h", config.OVERLAY_HEIGHT),
        )

        # Outer frame with shadow
        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet(f"""
            QFrame#container {{
                background: rgba(13, 17, 23, 230);
                border: 1px solid {COLOR['border_strong']};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 4)
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        wrapper = QWidget()
        wrapper.setLayout(outer)
        self.setCentralWidget(wrapper)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["md"])

        # Title bar with brand + version-ish text
        title_row = QHBoxLayout()
        brand = QLabel("⬢  TFT")
        brand.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('headline')}")
        title_row.addWidget(brand)
        sub = QLabel("intelligence overlay")
        sub.setStyleSheet(f"color: {COLOR['text_muted']}; {font_qss('caption')}")
        title_row.addWidget(sub)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        # Recommendations container
        self.recs_container = QWidget()
        self.recs_layout = QVBoxLayout(self.recs_container)
        self.recs_layout.setSpacing(SPACE["md"])
        self.recs_layout.setContentsMargins(0, 0, 0, 0)
        self.recs_layout.addStretch(1)
        layout.addWidget(self.recs_container, 1)

        # Hover label (gold-bar at bottom that updates with portrait names)
        self.hover_label = QLabel("")
        self.hover_label.setStyleSheet(f"""
            color: {COLOR['carry']};
            background: {COLOR['surface_2']};
            border: 1px solid {COLOR['border']};
            border-radius: {RADIUS_SM}px;
            padding: 4px 10px;
            {font_qss('body_strong')}
        """)
        self.hover_label.setMinimumHeight(28)
        self.hover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hover_label)

        global _HOVER_LABEL
        _HOVER_LABEL = self.hover_label

        # Footer hotkey hints — compact
        self.footer = QLabel(
            "F1 scout  ·  F2 reset  ·  F3 hide  ·  F5 augment  ·  F6 state  ·  F7 shop  ·  F9 compact  ·  F10 auto  ·  F11 mute  ·  F8 quit"
        )
        self.footer.setStyleSheet(f"color: {COLOR['text_muted']}; {font_qss('caption')}")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.footer)

        self.set_recommendations([Recommendation(
            headline="Ready",
            detail_lines=["Press F1 while scouting an opponent's board"],
        )])

        self._drag_pos: QPoint | None = None
        self._compact = False
        self._normal_size = (self.width(), self.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._save_position()

    def set_recommendations(self, recs: Iterable[Recommendation]) -> None:
        for i in reversed(range(self.recs_layout.count() - 1)):
            item = self.recs_layout.itemAt(i)
            w = item.widget()
            if w:
                w.setParent(None)
        for rec in recs:
            self.recs_layout.insertWidget(self.recs_layout.count() - 1, self._build_card(rec))

    def _build_card(self, rec: Recommendation) -> QWidget:
        # If this is a play_view or shop_view, render the structured form;
        # otherwise plain card with headline + detail lines.
        if rec.play_view:
            if rec.play_view.get("shop_view"):
                return self._build_shop_card(rec)
            return self._build_play_card(rec)
        return self._build_simple_card(rec)

    def _build_simple_card(self, rec: Recommendation) -> QWidget:
        sev = rec.severity
        return _banner(rec.headline + (" — " + " · ".join(rec.detail_lines) if rec.detail_lines else ""), sev)

    def _build_play_card(self, rec: Recommendation) -> QWidget:
        pv = rec.play_view
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {COLOR['surface']};
                border: 1px solid {COLOR['border_strong']};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        v.setSpacing(SPACE["md"])

        # ---- Hero header: tier badge + comp name + scout progress ----
        head_row = QHBoxLayout()
        head_row.setSpacing(SPACE["sm"])
        head_row.addWidget(_tier_badge(pv.get("tier", "B")))
        title = QLabel(pv["comp_name"])
        title.setStyleSheet(f"color: {COLOR['text']}; {font_qss('display')}")
        head_row.addWidget(title)
        head_row.addStretch(1)
        confidence_text = pv.get("confidence", "PLAY")
        conf_lbl = QLabel(confidence_text)
        conf_color = COLOR["owned"] if confidence_text.startswith("PLAY") else COLOR["accent"]
        conf_lbl.setStyleSheet(f"color: {conf_color}; {font_qss('caption')}")
        head_row.addWidget(conf_lbl)
        v.addLayout(head_row)

        # ---- Subheader: stats + progress dots ----
        meta_row = QHBoxLayout()
        meta_text = (f"Lv {pv['level']}  ·  {pv.get('play_style', 'standard')}  ·  "
                     f"avg place {pv.get('avg_place') or '?'}  ·  "
                     f"have {pv['have_count']}/{pv['total_count']}")
        meta_lbl = QLabel(meta_text)
        meta_lbl.setStyleSheet(f"color: {COLOR['text_2']}; {font_qss('body')}")
        meta_row.addWidget(meta_lbl)
        meta_row.addStretch(1)
        v.addLayout(meta_row)

        # ---- Notes (banners) ----
        for note in pv.get("notes", []):
            sev = "warn"
            if "PIVOT" in note or "CONTEST" in note:
                sev = "danger"
            elif "✓" in note:
                sev = "success"
            v.addWidget(_banner(note, sev))

        # ---- Board visualizer ----
        v.addWidget(build_board_visualizer(pv["placements"]))

        # ---- Items strip ----
        if pv.get("items"):
            v.addWidget(build_item_row(pv["items"], pv.get("carry_name")))

        # ---- Buy / Next / Later / Sell rows (level-progressive) ----
        cur_lvl = pv.get("current_level")
        if pv.get("buy_units"):
            label = f"BUY NOW (L{cur_lvl})" if cur_lvl else "BUY NOW"
            v.addWidget(build_unit_row(pv["buy_units"], action=label, action_color=COLOR["owned"]))
        if pv.get("next_units"):
            next_lvl = (cur_lvl + 1) if cur_lvl else None
            label = f"NEXT (L{next_lvl})" if next_lvl else "NEXT"
            v.addWidget(build_unit_row(pv["next_units"], action=label, action_color=COLOR["accent"]))
        if pv.get("locked_units"):
            v.addWidget(build_unit_row(pv["locked_units"],
                                        action="LATER", action_color=COLOR["text_muted"]))
        if pv.get("sell_units"):
            v.addWidget(build_unit_row(pv["sell_units"],
                                        action="SELL", action_color=COLOR["danger"]))

        return card

    def _build_shop_card(self, rec: Recommendation) -> QWidget:
        pv = rec.play_view
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {COLOR['surface']};
                border: 1px solid {COLOR['border_strong']};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        v.setSpacing(SPACE["md"])

        head = QLabel(f"SHOP  →  {pv.get('comp_name', '?')}")
        head.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('headline')}")
        v.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])
        action_colors = {
            "BUY": COLOR["owned"], "buy": COLOR["accent"],
            "consider": COLOR["warn"], "skip": COLOR["text_muted"],
        }
        for slot in pv.get("shop_recommendations", []):
            cell = QFrame()
            cell.setStyleSheet(f"""
                QFrame {{
                    background: {COLOR['surface_2']};
                    border: 1px solid {COLOR['border']};
                    border-radius: {RADIUS_MD}px;
                }}
            """)
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
            cv.setSpacing(SPACE["xs"])
            border_col = COLOR["carry"] if slot.get("is_carry") else None
            glow = COLOR["carry"] if slot.get("is_carry") else None
            icon = _portrait(slot.get("slug") or "training_dummy", size=PORTRAIT_LG,
                             dim=slot.get("action") not in ("BUY", "buy"),
                             display_name=slot.get("name"),
                             extra_tooltip=slot.get("reason", ""),
                             border_color=border_col, glow_color=glow)
            cv.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
            name_lbl = QLabel(slot.get("name", "?"))
            name_lbl.setStyleSheet(f"color: {COLOR['text']}; {font_qss('body_strong')}")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cv.addWidget(name_lbl)
            ac = action_colors.get(slot.get("action", ""), COLOR["text_muted"])
            action_lbl = QLabel(slot.get("action", "—").upper())
            action_lbl.setStyleSheet(f"color: {ac}; {font_qss('caption')}")
            action_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cv.addWidget(action_lbl)
            row.addWidget(cell)
        v.addLayout(row)
        return card

    def toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def toggle_compact(self) -> None:
        self._compact = not self._compact
        if self._compact:
            self._normal_size = (self.width(), self.height())
            self.resize(320, 100)
            self.recs_container.setVisible(False)
            self.footer.setVisible(False)
        else:
            self.resize(*self._normal_size)
            self.recs_container.setVisible(True)
            self.footer.setVisible(True)

    def _save_position(self) -> None:
        try:
            path = config.CALIBRATION_PATH
            data = {}
            if path.exists():
                data = json.loads(path.read_text())
            data["overlay_position"] = {
                "x": self.x(), "y": self.y(), "w": self.width(), "h": self.height(),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_position(self) -> dict:
        try:
            if config.CALIBRATION_PATH.exists():
                data = json.loads(config.CALIBRATION_PATH.read_text())
                return data.get("overlay_position", {})
        except Exception:
            pass
        return {}


# -------------------- dialogs --------------------

_DIALOG_QSS = f"""
    QDialog {{ background: {COLOR['bg']}; }}
    QLabel {{ color: {COLOR['text']}; {font_qss('body')} }}
    QLineEdit {{
        background: {COLOR['surface_2']};
        color: {COLOR['text']};
        border: 1px solid {COLOR['border']};
        padding: 8px 10px;
        border-radius: {RADIUS_SM}px;
        {font_qss('body')}
    }}
    QLineEdit:focus {{ border: 1px solid {COLOR['accent']}; }}
    QPushButton {{
        background: {COLOR['surface_2']};
        color: {COLOR['text']};
        border: 1px solid {COLOR['border_strong']};
        padding: 6px 14px;
        border-radius: {RADIUS_SM}px;
        {font_qss('body_strong')}
    }}
    QPushButton:hover {{ background: {COLOR['surface_3']}; border: 1px solid {COLOR['accent']}; }}
"""


class FirstRunDialog(QDialog):
    """Shown on first launch — asks for the user's TFT in-game name (used by OCR
    self-detection). Saved to data/user_config.json."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TFT Overlay · First-Run Setup")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(_DIALOG_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        v.setSpacing(SPACE["sm"])

        title = QLabel("WELCOME")
        title.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('caption')}")
        v.addWidget(title)
        intro = QLabel(
            "Set your TFT in-game name (the one shown above your portrait).\n"
            "This lets the overlay automatically detect when you're scouting yourself.\n"
            "You can change it later in data/user_config.json."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("e.g. Dr Fart MD#NA1")
        v.addWidget(self.name_field)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.name_field.setFocus()
        self.resize(420, 200)

    def get_name(self) -> str:
        return self.name_field.text().strip()


class GameStateDialog(QDialog):
    def __init__(self, current: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Game State")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(_DIALOG_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        v.setSpacing(SPACE["sm"])

        title = QLabel("GAME STATE")
        title.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('caption')}")
        v.addWidget(title)
        v.addWidget(QLabel("All fields optional. Updates the recommender context."))

        self.fields: dict[str, QLineEdit] = {}
        for key, placeholder, default_val in [
            ("stage", "Stage (e.g. 3-2)", current.get("stage", "") if current else ""),
            ("level", "Level (1-10)", str(current.get("level", "")) if current else ""),
            ("gold", "Gold", str(current.get("gold", "")) if current else ""),
            ("hp", "HP", str(current.get("hp", "")) if current else ""),
            ("dead", "Eliminated players (e.g. 3,5)", str(current.get("dead", "")) if current else ""),
        ]:
            f = QLineEdit()
            f.setPlaceholderText(placeholder)
            if default_val:
                f.setText(default_val)
            v.addWidget(f)
            self.fields[key] = f

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.fields["stage"].setFocus()
        self.resize(380, 320)

    def get_state(self) -> dict:
        out: dict = {}
        s = self.fields["stage"].text().strip()
        if s:
            out["stage"] = s
        for key in ("level", "gold", "hp"):
            val = self.fields[key].text().strip()
            if val.isdigit():
                out[key] = int(val)
        dead_raw = self.fields["dead"].text().strip()
        if dead_raw is not None:
            parts = [p.strip() for p in dead_raw.split(",") if p.strip()]
            out["dead"] = {int(p) for p in parts if p.isdigit()}
        return out


class AugmentInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Augment Pick")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(_DIALOG_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        v.setSpacing(SPACE["sm"])

        title = QLabel("AUGMENT PICK")
        title.setStyleSheet(f"color: {COLOR['carry']}; {font_qss('caption')}")
        v.addWidget(title)
        v.addWidget(QLabel("Type the 3 augment names (partial OK — fuzzy matched)"))

        self.fields = []
        for i in range(3):
            f = QLineEdit()
            f.setPlaceholderText(f"Augment {i+1}")
            v.addWidget(f)
            self.fields.append(f)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.fields[0].setFocus()
        self.resize(380, 240)

    def get_choices(self) -> list[str]:
        return [f.text().strip() for f in self.fields if f.text().strip()]


def make_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    return app
