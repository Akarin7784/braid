"""窗口控制按钮（最小化/最大化/关闭）：全窗口唯一一份，浮层定位在窗口右上角。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

BTN = 28
ICON = 10
SPACING = 2
RIGHT_MARGIN = 10


class ControlButton(QToolButton):
    """样式（底色、hover、圆角）全部交给 QSS；图标用 palette().buttonText() 自绘。"""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setObjectName(f"WinCtl_{kind}")
        self.setProperty("role", "windowControl")
        if kind == "close":
            self.setProperty("kind", "close")
        self.setFixedSize(BTN, BTN)
        self.setAutoRaise(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip({"min": "最小化", "max": "最大化", "close": "关闭"}[kind])

    def sizeHint(self) -> QSize:
        return QSize(BTN, BTN)

    def _repolish(self) -> None:
        # QSS 的 [hovered="true"] 颜色在 polish 时写进 palette
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def set_hovered(self, on: bool) -> None:
        self.setProperty("hovered", on)
        self._repolish()

    def enterEvent(self, e: QEnterEvent) -> None:
        super().enterEvent(e)
        self.set_hovered(True)

    def leaveEvent(self, e: QEvent) -> None:
        super().leaveEvent(e)
        self.set_hovered(False)

    def icon_color(self) -> QColor:
        return self.palette().buttonText().color()

    def paintEvent(self, e: QPaintEvent) -> None:
        super().paintEvent(e)  # QSS 画底色
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.icon_color(), 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        o = (BTN - ICON) / 2
        r = QRectF(o, o, ICON, ICON)
        if self.kind == "min":
            p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
        elif self.kind == "max":
            if self.window().isMaximized():
                p.drawRect(r.adjusted(0, 2, -2, 0))
                p.drawPolyline(
                    [
                        QPointF(r.left() + 2, r.top() + 2),
                        QPointF(r.left() + 2, r.top()),
                        QPointF(r.right(), r.top()),
                        QPointF(r.right(), r.bottom() - 2),
                        QPointF(r.right() - 2, r.bottom() - 2),
                    ]
                )
            else:
                p.drawRoundedRect(r, 1.5, 1.5)
        else:
            p.drawLine(r.topLeft(), r.bottomRight())
            p.drawLine(r.topRight(), r.bottomLeft())


class WindowControls(QWidget):
    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WindowControls")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING)
        self.buttons: dict[str, ControlButton] = {}
        for kind, sig in (
            ("min", self.minimizeRequested),
            ("max", self.maximizeRequested),
            ("close", self.closeRequested),
        ):
            b = ControlButton(kind, self)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
            self.buttons[kind] = b
        self.setFixedSize(self.total_width(), BTN)

    @staticmethod
    def total_width() -> int:
        return BTN * 3 + SPACING * 2

    @staticmethod
    def reserved_width() -> int:
        """标签行/中栏顶栏右侧需要留出的宽度（不含 16px 间隔）。"""
        return WindowControls.total_width() + RIGHT_MARGIN
