"""Small custom widgets: a plain line chart (no extra dependencies) and the dark theme."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

DARK_QSS = """
* { font-size: 9pt; }
QWidget { background: #2b2b2b; color: #d4d4d4; }
QMainWindow, QTabWidget::pane { border: 1px solid #3c3c3c; }
QTabBar::tab { background: #333; padding: 4px 12px; border: 1px solid #3c3c3c; }
QTabBar::tab:selected { background: #444; }
QPushButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
    background: #3a3a3a; border: 1px solid #555; padding: 2px 6px; }
QPushButton:hover { background: #454545; }
QTableView, QTableWidget, QPlainTextEdit, QListWidget { background: #252525; alternate-background-color: #2a2a2a;
    gridline-color: #333; selection-background-color: #3d5a80; }
QHeaderView::section { background: #333; border: 0; border-right: 1px solid #444; padding: 3px; }
QStatusBar { background: #232323; }
QGroupBox { border: 1px solid #444; margin-top: 8px; } QGroupBox::title { left: 8px; padding: 0 3px; }
"""


class LineChart(QWidget):
    """Single-series chart. Missing values (None) leave a gap. y_max=None autoscales."""

    def __init__(self, title: str, unit: str = "%", y_max: float | None = 100.0, color: str = "#6a9fd8"):
        super().__init__()
        self.title, self.unit, self.y_max, self.color = title, unit, y_max, QColor(color)
        self.values: list = []
        self.setMinimumHeight(90)

    def set_values(self, values: list):
        self.values = values
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#252525"))
        w, h = self.width(), self.height()
        top, left = 18, 4
        ok = [v for v in self.values if v is not None]
        ymax = self.y_max or max(ok + [1.0]) * 1.1
        p.setPen(QColor("#555"))
        p.drawRect(0, top, w - 1, h - top - 1)
        last = f"{ok[-1]:.1f}{self.unit}" if ok else "n/a"
        p.setPen(QColor("#d4d4d4"))
        p.drawText(left, 13, f"{self.title}: {last}   (axis 0-{ymax:.0f}{self.unit})")
        n = len(self.values)
        if n < 2:
            return
        p.setPen(QPen(self.color, 1.4))
        seg: list = []

        def flush():
            if len(seg) > 1:
                p.drawPolyline(QPolygonF(seg))
            seg.clear()

        for i, v in enumerate(self.values):
            if v is None:
                flush()
                continue
            x = i * (w - 1) / (n - 1)
            y = top + (h - top - 2) * (1 - min(v, ymax) / ymax)
            seg.append(QPointF(x, y))
        flush()
