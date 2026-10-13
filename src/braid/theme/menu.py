"""无边框圆角菜单：QSS 画不出 QMenu 的阴影，这里用九宫格阴影画在 margin 区域里。

用法::

    menu = RoundedMenu(parent)
    menu.addGroupHeader("Anthropic")      # 服务商分组标题
    sub = menu.addMenu("Claude Sonnet")  # 子菜单自动也是 RoundedMenu
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import Property, QEvent, QMargins, QRect, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QStyleOptionToolButton,
    QToolButton,
    QWidget,
)

from braid.theme.nine_slice import NineSliceShadow

SHADOW_MARGIN = 18  # 阴影外扩；QSS 里 padding 24 = 阴影 18 + 内边距 6
RADIUS = 12


def is_dark() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("braidDark"))


class RoundedMenu(QMenu):
    radius: int = RADIUS  # 实例可覆盖（下拉框弹层用 10）
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
            sub = type(self)(args[0], self)
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
        p.drawRoundedRect(card, self.radius, self.radius)
        p.end()
        super().paintEvent(e)


DESC_PROP = "braidDesc"  # 菜单项第二行说明
TAG_PROP = "braidTag"  # 菜单项右侧小标签（高 / 中 / 低）


class ModelMenu(RoundedMenu):
    """模型菜单：每项两行，第一行名称（QSS 留出下方 padding），第二行 text3 12px 说明；
    右侧可选一个小标签。选中只靠打勾（QSS 去掉 :checked 底色），子菜单同样是 ModelMenu。"""

    DESC_PX = 12
    TEXT_X = 48  # 与第一行名称左缘对齐（QSS padding-left 32 + 勾选列 16）
    TAG_PX = 11

    def __init__(self, title: str | QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setProperty("role", "modelMenu")
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def describe(action: QAction, desc: str, tag: str = "") -> None:
        action.setProperty(DESC_PROP, desc)
        action.setProperty(TAG_PROP, tag)

    def paintEvent(self, e: QPaintEvent) -> None:
        super().paintEvent(e)
        from braid.theme.palette import qcolor

        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(self.DESC_PX)
        f.setWeight(QFont.Weight.Normal)
        tf = QFont(f)
        tf.setPixelSize(self.TAG_PX)
        for a in self.actions():
            desc = a.property(DESC_PROP)
            tag = a.property(TAG_PROP)
            if not desc and not tag:
                continue
            r = self.actionGeometry(a)
            right = r.right() - (30 if a.menu() else 12)
            if tag:
                p.setFont(tf)
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(str(tag))
                tr = QRect(right - tw, r.top() + 7, tw, fm.height() + 4)
                # 纯文字小标签：无底色，text3
                p.setPen(qcolor("text3", dark))
                p.drawText(tr, int(Qt.AlignmentFlag.AlignCenter), str(tag))
                right = tr.left() - 8
            if desc:
                p.setFont(f)
                p.setPen(qcolor("text3", dark))
                x = r.left() + self.TEXT_X
                dr = QRect(x, r.bottom() - 22, right - x, 18)
                txt = p.fontMetrics().elidedText(str(desc), Qt.TextElideMode.ElideRight, dr.width())
                p.drawText(dr, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), txt)
        p.end()


class ChipButton(QToolButton):
    """模型 chip：QSS 的 ::menu-indicator 对 InstantPopup 不生效，下拉箭头在这里自绘。"""

    ARROW = 10
    ARROW_RIGHT = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "modelChip")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

    PAD_LEFT = 12
    GAP = 12

    def _reserved(self) -> int:
        return self.GAP + self.ARROW + self.ARROW_RIGHT

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        # +2：horizontalAdvance 取整后可能比实际排版窄 1px，导致文字被省略成“…”
        w = self.PAD_LEFT + fm.horizontalAdvance(self.text()) + 2 + self._reserved()
        return QSize(w, max(super().sizeHint().height(), fm.height() + 8))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.updateGeometry()

    def changeEvent(self, e: QEvent) -> None:  # noqa: N802
        # QSS 的 font-size 在 polish 时才生效：字体变了要重算宽度，否则文字被省略成“…”
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            self.updateGeometry()

    def paintEvent(self, event: QPaintEvent) -> None:
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        text = opt.text
        opt.text = ""
        p = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt, p, self)
        tr = QRect(self.PAD_LEFT, 0, self.width() - self.PAD_LEFT - self._reserved(), self.height())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        elided = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, tr.width())
        p.drawText(tr, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)
        name = "dark" if is_dark() else "light"
        pm = QPixmap(str(files("braid.assets") / "icons" / f"chevron_down_{name}.png"))
        if not pm.isNull():
            s = self.ARROW
            r = QRect(self.width() - self.ARROW_RIGHT - s, (self.height() - s) // 2, s, s)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(r, pm)
        p.end()
