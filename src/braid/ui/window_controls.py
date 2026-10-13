"""窗口控制按钮（最小化/最大化/关闭）：全窗口唯一一份，浮层定位在窗口右上角。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QWidget

BTN = 28
ICON = 10
SPACING = 2
RIGHT_MARGIN = 10

COLORS = {
    False: {"text2": "#6B6B69", "hover": "#E6E6E4"},
    True: {"text2": "#A3A3A0", "hover": "#353533"},
}
CLOSE_HOVER = "#E5484D"


def _dark() -> bool:
    app = QApplication.instance()
    return bool(app.property("braidDark")) if app else False


class ControlButton(QAbstractButton):
    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setObjectName(f"WinCtl_{kind}")
        self.setFixedSize(BTN, BTN)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip({"min": "最小化", "max": "最大化", "close": "关闭"}[kind])

    def sizeHint(self) -> QSize:
        return QSize(BTN, BTN)

    def paintEvent(self, e: QPaintEvent) -> None:
        c = COLORS[_dark()]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse() or self.isDown()
        icon = QColor(c["text2"])
        if hover:
            bg = QColor(CLOSE_HOVER if self.kind == "close" else c["hover"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)
            if self.kind == "close":
                icon = QColor("#FFFFFF")
        pen = QPen(icon, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        o = (BTN - ICON) / 2
        r = QRectF(o, o, ICON, ICON)
        if self.kind == "min":
            p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
        elif self.kind == "max":
            win = self.window()
            if win.isMaximized():
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
