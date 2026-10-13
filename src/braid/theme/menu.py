"""无边框圆角菜单：QSS 画不出 QMenu 的阴影，这里用九宫格阴影画在 margin 区域里。

用法::

    menu = RoundedMenu(parent)
    menu.addGroupHeader("Anthropic")      # 服务商分组标题
    sub = menu.addMenu("Claude Sonnet")  # 子菜单自动也是 RoundedMenu
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import Property, QMargins, QRect, Qt
from PySide6.QtGui import QAction, QColor, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QToolButton, QWidget

from braid.theme.nine_slice import NineSliceShadow

SHADOW_MARGIN = 18  # 阴影外扩；QSS 里 padding 24 = 阴影 18 + 内边距 6
RADIUS = 12


def is_dark() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("braidDark"))


class RoundedMenu(QMenu):
    _surface = "#FFFFFF"

    def _get_surface(self) -> str:
        return self._surface

    def _set_surface(self, c: str) -> None:
        self._surface = c
        self.update()

    surfaceColor = Property(str, _get_surface, _set_surface)  # 由 QSS qproperty-surfaceColor 设置

    def __init__(self, title: str | QWidget | None = None, parent: QWidget | None = None) -> None:
        if isinstance(title, QWidget):
            super().__init__(title)
        elif title is None:
            super().__init__(parent)
        else:
            super().__init__(title, parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setProperty("rounded", True)
        self.style().unpolish(self)
        self.style().polish(self)

    def addGroupHeader(self, text: str) -> QAction:
        """分组标题（如服务商名）：不可点击，显示为三级文字色。"""
        a = self.addAction(text)
        a.setEnabled(False)
        return a

    def addMenu(self, *args, **kwargs):
        if len(args) == 1 and isinstance(args[0], str):
            sub = RoundedMenu(args[0], self)
            super().addMenu(sub)
            return sub
        return super().addMenu(*args, **kwargs)

    def paintEvent(self, e: QPaintEvent) -> None:
        m = SHADOW_MARGIN
        card = self.rect().marginsRemoved(QMargins(m, m, m, m))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        NineSliceShadow.get("e2", is_dark()).paint(p, card)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._surface))
        p.drawRoundedRect(card, RADIUS, RADIUS)
        p.end()
        super().paintEvent(e)


class ChipButton(QToolButton):
    """模型 chip：QSS 的 ::menu-indicator 对 InstantPopup 不生效，下拉箭头在这里自绘。"""

    ARROW = 10
    ARROW_RIGHT = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "modelChip")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        name = "dark" if is_dark() else "light"
        pm = QPixmap(str(files("braid.assets") / "icons" / f"chevron_down_{name}.png"))
        if pm.isNull():
            return
        s = self.ARROW
        r = QRect(self.width() - self.ARROW_RIGHT - s, (self.height() - s) // 2, s, s)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(r, pm)
        p.end()
