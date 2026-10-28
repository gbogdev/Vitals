"""Custom widgets (plain line chart, stat tile) and the neutral dark theme."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

# Muted palette: neutral greys with a single restrained blue accent.
BG, SURFACE, SURFACE2, BORDER = "#1e1f22", "#26282c", "#2f3237", "#3a3d43"
TEXT, MUTED, ACCENT = "#dcdde0", "#8b8f97", "#5b8bc9"

DARK_QSS = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 9.5pt; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#tileValue {{ font-size: 16pt; font-weight: 600; }}
QTabWidget::pane {{ border: 0; border-top: 1px solid {BORDER}; }}
QTabBar {{ background: {BG}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; border: 0;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ background: #383b41; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 4px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QCheckBox {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #5a5e66; border-radius: 3px;
    background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTableWidget, QPlainTextEdit {{ background: {SURFACE}; alternate-background-color: #2a2c30;
    border: 1px solid {BORDER}; border-radius: 4px; gridline-color: transparent;
    selection-background-color: #34507a; selection-color: {TEXT}; }}
QPlainTextEdit {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt; }}
QTableWidget::item {{ padding: 3px 6px; border: 0; }}
QHeaderView::section {{ background: {SURFACE2}; color: {MUTED}; border: 0; border-bottom: 1px solid {BORDER};
    padding: 5px 8px; font-weight: 600; }}
QSplitter::handle {{ background: {BG}; height: 6px; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QFrame#tile {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #4a4d54; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #4a4d54; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


class StatTile(QFrame):
    """Compact label + current value + secondary line."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)
        t = QLabel(title)
        t.setProperty("muted", True)
        self.value = QLabel("n/a")
        self.value.setObjectName("tileValue")
        self.sub = QLabel("")
        self.sub.setProperty("muted", True)
        for w in (t, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = ""):
        self.value.setText(value)
        self.sub.setText(sub)


class LineChart(QWidget):
    """Single-series chart with light grid and subtle fill. None values leave a gap.
    y_max=None autoscales."""

    def __init__(self, title: str, unit: str = "%", y_max: float | None = 100.0, color: str = ACCENT):
        super().__init__()
        self.title, self.unit, self.y_max, self.color = title, unit, y_max, QColor(color)
        self.values: list = []
        self.setMinimumHeight(110)

    def set_values(self, values: list):
        self.values = values
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, top = self.width(), self.height(), 24
        box = QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(SURFACE))
        p.drawRoundedRect(box, 6, 6)
        ok = [v for v in self.values if v is not None]
        ymax = self.y_max or max(ok + [1.0]) * 1.15
        p.setPen(QColor(TEXT))
        p.drawText(10, 17, self.title)
        last = f"{ok[-1]:.1f}{self.unit}" if ok else "n/a"
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, 4, w - 10, 18), Qt.AlignRight | Qt.AlignVCenter, f"{last}  (max {ymax:.0f}{self.unit})")
        px0, px1, py0, py1 = 8, w - 8, top, h - 8
        p.setPen(QPen(QColor("#33363b"), 1))
        for i in range(1, 4):
            y = py0 + (py1 - py0) * i / 4
            p.drawLine(px0, int(y), px1, int(y))
        n = len(self.values)
        if n < 2:
            return
        seg: list = []
        pen = QPen(self.color, 1.6)
        fill = QColor(self.color)
        fill.setAlpha(34)

        def flush():
            if len(seg) > 1:
                path = QPainterPath(seg[0])
                for pt in seg[1:]:
                    path.lineTo(pt)
                area = QPainterPath(path)
                area.lineTo(seg[-1].x(), py1)
                area.lineTo(seg[0].x(), py1)
                area.closeSubpath()
                p.fillPath(area, fill)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            seg.clear()

        for i, v in enumerate(self.values):
            if v is None:
                flush()
                continue
            x = px0 + i * (px1 - px0) / (n - 1)
            seg.append(QPointF(x, py1 - (py1 - py0) * min(v, ymax) / ymax))
        flush()
