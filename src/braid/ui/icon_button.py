"""标题行图标按钮：28×28 点击区，16×16 图形自绘居中。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QPushButton, QWidget

HIT = 28
GLYPH = 16


class IconButton(QPushButton):
    """kind: "sidebar"（三横线）、"panel"（右半实心的面板框）或 "gear"（齿轮）。"""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.kind = kind
        self.setProperty("variant", "ghost")
        self.setFixedSize(HIT, HIT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(HIT, HIT)

    def paintEvent(self, e: QPaintEvent) -> None:
        super().paintEvent(e)  # QSS 画底色与悬停
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().buttonText().color()
        pen = QPen(color, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        o = (HIT - GLYPH) / 2
        r = QRectF(o, o, GLYPH, GLYPH)
        if self.kind == "sidebar":
            for dy in (-4.0, 0.0, 4.0):
                y = r.center().y() + dy
                p.drawLine(QPointF(r.left() + 2, y), QPointF(r.right() - 2, y))
        elif self.kind == "gear":
            c = r.center()
            p.drawEllipse(c, 2.5, 2.5)
            p.drawEllipse(c, 5.5, 5.5)
            for i in range(8):
                a = math.pi / 4 * i
                dx, dy = math.cos(a), math.sin(a)
                p.drawLine(
                    QPointF(c.x() + dx * 5.5, c.y() + dy * 5.5),
                    QPointF(c.x() + dx * 7.5, c.y() + dy * 7.5),
                )
        else:
            box = r.adjusted(1.5, 2.5, -1.5, -2.5)
            p.drawRoundedRect(box, 2, 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            half = QRectF(
                box.center().x() + 1, box.top() + 2, box.width() / 2 - 3, box.height() - 4
            )
            p.drawRoundedRect(half, 1, 1)
