"""九宫格阴影：给 delegate 用，代替 QGraphicsDropShadowEffect。

用法（paint 里，先画阴影再画卡片）::

    shadow = NineSliceShadow.get("e2", dark)
    shadow.paint(painter, card_rect)
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QMargins, QRect
from PySide6.QtGui import QPainter, QPixmap

# 每级的 (模糊外扩, 圆角, y 偏移)，与 design_spec.md 第 5 节一致
_LEVELS = {"e1": (12, 14, 2), "e2": (18, 14, 4), "e3": (24, 14, 4)}


class NineSliceShadow:
    def __init__(self, level: str, dark: bool) -> None:
        self.margin, self.radius, self.dy = _LEVELS[level]
        path = files("braid.assets.shadows") / f"{level}_{'dark' if dark else 'light'}.png"
        self.pix = QPixmap(str(path))

    @staticmethod
    @lru_cache(maxsize=8)
    def get(level: str, dark: bool) -> NineSliceShadow:
        return NineSliceShadow(level, dark)

    def paint(self, p: QPainter, card: QRect) -> None:
        """在 card 矩形外围画阴影；card 是卡片本身的矩形。"""
        c = self.margin + self.radius
        dst = card.marginsAdded(QMargins(self.margin, self.margin, self.margin, self.margin))
        dst.translate(0, self.dy)
        sw, sh = self.pix.width(), self.pix.height()
        xs = [(0, c), (c, sw - 2 * c), (sw - c, c)]
        ys = [(0, c), (c, sh - 2 * c), (sh - c, c)]
        dxs = [(dst.left(), c), (dst.left() + c, dst.width() - 2 * c), (dst.right() + 1 - c, c)]
        dys = [(dst.top(), c), (dst.top() + c, dst.height() - 2 * c), (dst.bottom() + 1 - c, c)]
        for (sx, swd), (dx, dwd) in zip(xs, dxs, strict=True):
            for (sy, shd), (dy, dhd) in zip(ys, dys, strict=True):
                if dwd > 0 and dhd > 0:
                    p.drawPixmap(QRect(dx, dy, dwd, dhd), self.pix, QRect(sx, sy, swd, shd))
