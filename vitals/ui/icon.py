"""App icon drawn in code: a dark rounded square with a pulse line. No image assets needed."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF


def make_image(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    p.setBrush(QColor("#26282c"))
    p.setPen(QPen(QColor("#3a3d43"), s * 0.02))
    p.drawRoundedRect(QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94), s * 0.2, s * 0.2)
    pts = [(0.14, 0.54), (0.34, 0.54), (0.43, 0.30), (0.54, 0.74), (0.63, 0.46), (0.68, 0.54), (0.86, 0.54)]
    pen = QPen(QColor("#5b8bc9"), s * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
    p.end()
    return img


def make_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(make_image(sz)))
    return ic
