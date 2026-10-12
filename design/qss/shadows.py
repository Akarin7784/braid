"""阴影层级（QSS 不支持 box-shadow）。用法: apply_shadow(widget, "e3", dark=False)"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

SHADOWS = {
    "e1": (12, 2, 0x0C, 0x59),
    "e2": (18, 4, 0x0F, 0x66),
    "e3": (24, 4, 0x1A, 0x80),
    "e4": (40, 12, 0x24, 0x8C),
}


def apply_shadow(w: QWidget, level: str, dark: bool = False) -> None:
    blur, dy, a_light, a_dark = SHADOWS[level]
    fx = QGraphicsDropShadowEffect(w)
    fx.setBlurRadius(blur)
    fx.setOffset(0, dy)
    fx.setColor(QColor(0, 0, 0, a_dark if dark else a_light))
    w.setGraphicsEffect(fx)
