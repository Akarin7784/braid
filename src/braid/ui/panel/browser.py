"""浏览器标签页（panel_spec §3）。

本模块只由 RightPanel 在首次切到浏览器标签时导入；QtWebEngine 只在
``load_webengine()`` 函数内部导入，禁止放到模块顶层。WebEngine 不可用时降级为提示。
颜色均在 paint 时从 ``braid.theme.palette.tokens`` 取。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QHideEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.browser import BrowserController
from braid.theme.menu import is_dark
from braid.theme.palette import tokens as palette
from braid.ui.panel.shell import card_shadow
from braid.ui.panel.tokens import tokens

ROW_H = 28
HIGHLIGHT_FADE_MS = 600
BREATH_MS = 1200
STATUS_INSET = 16
DEFAULT_TARGET = 28  # 只有坐标时的高亮框边长
UNAVAILABLE_TEXT = "浏览器组件不可用（未安装 QtWebEngine）\n可点击右上角 ↗ 在系统浏览器中打开"

WebFactory = Callable[[], QWidget | None]


def load_webengine() -> QWidget | None:
    """首次需要时才导入 QtWebEngine；不可用返回 None。"""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:  # ImportError / 缺系统库
        return None
    try:
        return QWebEngineView()
    except Exception:
        return None


def _c(hex_: str, alpha_mul: float = 1.0) -> QColor:
    c = QColor(hex_[:7])
    a = int(hex_[7:], 16) if len(hex_) == 9 else 255
    c.setAlpha(int(a * alpha_mul))
    return c


def browser_qss(mode: str = "light") -> str:
    t = tokens(mode)
    return f"""
QPushButton[role="navButton"] {{ min-width: {ROW_H}px; max-width: {ROW_H}px;
    min-height: {ROW_H}px; max-height: {ROW_H}px; border: none; border-radius: 10px;
    background: transparent; color: {t["text2"]}; font-size: 14px; padding: 0; }}
QPushButton[role="navButton"]:hover {{ background: {t["hover"]}; }}
QPushButton[role="navButton"]:disabled {{ color: {t["text3"]}; }}
#UrlEdit {{ background: {t["hover"]}; border: 2px solid transparent; border-radius: 10px;
    padding: 0 8px; color: {t["text"]}; font-family: monospace; font-size: 12px; }}
#UrlEdit:focus {{ border: 2px solid {t["brand"]}; }}
#WebCard {{ background: {t["surface"]}; border-radius: 14px; }}
#WebUnavailable {{ color: {t["text3"]}; font-size: 13px; }}
#AgentStatus {{ background: {t["surface"]}; border-radius: 12px; }}
#AgentStatusText {{ color: {t["text2"]}; font-size: 12px; }}
#TakeoverButton {{ background: {t["control"]}; color: {t["text"]}; border: none;
    border-radius: 8px; padding: 3px 10px; font-size: 12px; }}
"""


class BreathingDot(QWidget):
    """8px brand 圆点 + 4px sel 光晕，1.2s 呼吸。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._phase = 0.0
        self.anim = QPropertyAnimation(self, b"phase", self)
        self.anim.setDuration(BREATH_MS)
        self.anim.setStartValue(0.0)
        self.anim.setKeyValueAt(0.5, 1.0)
        self.anim.setEndValue(0.0)
        self.anim.setLoopCount(-1)

    def _get(self) -> float:
        return self._phase

    def _set(self, v: float) -> None:
        self._phase = v
        self.update()

    phase = Property(float, _get, _set)

    def paintEvent(self, e: QPaintEvent) -> None:
        t = palette(is_dark())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        c = QRectF(self.rect()).center()
        p.setBrush(_c(t["sel"], 0.5 + 0.5 * self._phase))
        p.drawEllipse(c, 8.0, 8.0)  # 4px 光晕（半径 4+4）
        p.setBrush(QColor(t["brand"]))
        p.drawEllipse(c, 4.0, 4.0)
        p.end()


class AgentStatusBar(QFrame):
    """浮在网页卡片底部的“Agent 正在操作 · <动作>”状态条。"""

    takeoverClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AgentStatus")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(6)
        self.dot = BreathingDot()
        lay.addWidget(self.dot)
        self.text = QLabel()
        self.text.setObjectName("AgentStatusText")
        lay.addWidget(self.text, 1)
        self.takeover_btn = QPushButton("接管")
        self.takeover_btn.setObjectName("TakeoverButton")
        self.takeover_btn.clicked.connect(self.takeoverClicked)
        lay.addWidget(self.takeover_btn)
        card_shadow(self)
        self.hide()

    def set_action(self, action: str) -> None:
        self.text.setText(f"Agent 正在操作 · {action}" if action else "Agent 正在操作")

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        self.dot.anim.start()

    def hideEvent(self, e: QHideEvent) -> None:
        super().hideEvent(e)
        self.dot.anim.stop()


class ClickHighlight(QWidget):
    """点击高亮：目标外扩 2px，brand 2px 描边 + 6px sel 外晕，圆角 12；
    下方 11px brand 标签“点击 · 选择器”。600ms 淡出。鼠标穿透。"""

    PAD = 2
    HALO = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.target = QRect()
        self.label = ""
        self._opacity = 0.0
        self.anim = QPropertyAnimation(self, b"opacity", self)
        self.anim.setDuration(HIGHLIGHT_FADE_MS)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self.anim.finished.connect(self.hide)
        self.hide()

    def _get(self) -> float:
        return self._opacity

    def _set(self, v: float) -> None:
        self._opacity = v
        self.update()

    opacity = Property(float, _get, _set)

    def flash(self, target: QRect, label: str) -> None:
        self.target, self.label = QRect(target), label
        if parent := self.parentWidget():
            self.setGeometry(parent.rect())
        self.anim.stop()
        self._opacity = 1.0
        self.show()
        self.raise_()
        self.anim.start()

    def frame_rect(self) -> QRectF:
        return QRectF(self.target).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    def paintEvent(self, e: QPaintEvent) -> None:
        if self._opacity <= 0 or self.target.isNull():
            return
        t = palette(is_dark())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        r = self.frame_rect()
        halo = QPainterPath()
        halo.addRoundedRect(r.adjusted(-self.HALO, -self.HALO, self.HALO, self.HALO), 18, 18)
        inner = QPainterPath()
        inner.addRoundedRect(r, 12, 12)
        p.fillPath(halo.subtracted(inner), _c(t["sel"]))
        p.setPen(QPen(QColor(t["brand"]), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 12, 12)
        if self.label:
            f = QFont()
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(t["brand"]))
            p.drawText(QRectF(r.left(), r.bottom() + self.HALO, 400, 16), self.label)
        p.end()


class BrowserPage(QWidget):
    """地址栏 + 网页卡片（含状态条、点击高亮浮层）。"""

    def __init__(
        self,
        controller: BrowserController | None = None,
        parent: QWidget | None = None,
        theme: str = "light",
        web_factory: WebFactory = load_webengine,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(browser_qss(theme))
        self.controller = controller
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.back_btn = self._nav("←", "后退")
        self.forward_btn = self._nav("→", "前进")
        self.reload_btn = self._nav("↻", "刷新")
        for b in (self.back_btn, self.forward_btn, self.reload_btn):
            bar.addWidget(b)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("UrlEdit")
        self.url_edit.setFixedHeight(ROW_H)
        self.url_edit.setPlaceholderText("输入网址")
        self.url_edit.returnPressed.connect(lambda: self.load(self.url_edit.text()))
        bar.addWidget(self.url_edit, 1)
        self.external_btn = self._nav("↗", "在系统浏览器打开")
        self.external_btn.clicked.connect(self.open_external)
        bar.addWidget(self.external_btn)
        lay.addLayout(bar)

        self.card = QFrame()
        self.card.setObjectName("WebCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.progress = QFrame()  # 地址栏下方 2px brand 进度条（宽度按进度）
        self.progress.setFixedHeight(2)
        self.progress.hide()
        cl.addWidget(self.progress)
        self.view: Any = web_factory()
        if self.view is None:
            self.web_available = False
            msg = QLabel(UNAVAILABLE_TEXT, alignment=Qt.AlignmentFlag.AlignCenter)
            msg.setObjectName("WebUnavailable")
            msg.setWordWrap(True)
            cl.addWidget(msg, 1)
        else:
            self.web_available = True
            cl.addWidget(self.view, 1)
            self._wire_view(self.view)
        card_shadow(self.card)
        lay.addWidget(self.card, 1)

        self.status = AgentStatusBar(self.card)
        self.highlight = ClickHighlight(self.card)
        self.status.takeoverClicked.connect(self.takeover)
        self.loading = False
        self._update_nav()

        if controller is not None:
            controller.navigate_requested.connect(self.load)
            controller.agent_active.connect(self.set_agent_active)
            controller.agent_click.connect(self.show_click)
            controller.agent_click_target.connect(self.show_click_target)

    # —— 地址栏 ——
    def _nav(self, glyph: str, tip: str) -> QPushButton:
        b = QPushButton(glyph)
        b.setProperty("role", "navButton")
        b.setToolTip(tip)
        b.setFixedSize(ROW_H, ROW_H)
        return b

    def _wire_view(self, v: Any) -> None:
        # 只用 QWebEngineView 的公开 API，不在顶层引用其类型
        self.back_btn.clicked.connect(v.back)
        self.forward_btn.clicked.connect(v.forward)
        v.urlChanged.connect(self._on_url_changed)
        v.loadStarted.connect(lambda: self.set_loading(True))
        v.loadProgress.connect(self.set_progress)
        v.loadFinished.connect(lambda _ok: self.set_loading(False))
        self.reload_btn.clicked.connect(self._reload_or_stop)

    def _on_url_changed(self, u: QUrl) -> None:
        self.url_edit.setText(u.toString())
        self._update_nav()

    def _reload_or_stop(self) -> None:
        if self.view is None:
            return
        (self.view.stop if self.loading else self.view.reload)()

    def _update_nav(self) -> None:
        h = self.view.history() if self.view is not None else None
        self.back_btn.setEnabled(bool(h and h.canGoBack()))
        self.forward_btn.setEnabled(bool(h and h.canGoForward()))
        self.reload_btn.setEnabled(self.view is not None)

    def load(self, url: str) -> None:
        url = url.strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        self.url_edit.setText(url)
        if self.view is not None:
            self.view.setUrl(QUrl(url))

    def open_external(self) -> None:
        if self.url_edit.text().strip():
            QDesktopServices.openUrl(QUrl(self.url_edit.text().strip()))

    def set_loading(self, on: bool) -> None:
        self.loading = on
        self.reload_btn.setText("✕" if on else "↻")
        self.reload_btn.setToolTip("停止" if on else "刷新")
        self.progress.setVisible(on)
        if on:
            self.set_progress(0)
        self._update_nav()

    def set_progress(self, pct: int) -> None:
        t = palette(is_dark())
        stop = max(0.0, min(1.0, pct / 100))
        s2 = min(1.0, stop + 0.001)
        self.progress.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 {t['brand']}, stop:{stop:.3f} {t['brand']}, "
            f"stop:{s2:.3f} transparent, stop:1 transparent);"
        )

    # —— agent ——
    def set_agent_active(self, active: bool, action: str = "") -> None:
        if active:
            self.status.set_action(action)
            self._place_status()
            self.status.show()
            self.status.raise_()
        else:
            self.status.hide()
            self.highlight.anim.stop()
            self.highlight.hide()

    def _place_status(self) -> None:
        r = self.card.rect()
        h = self.status.sizeHint().height()
        self.status.setGeometry(
            STATUS_INSET, r.height() - STATUS_INSET - h, r.width() - 2 * STATUS_INSET, h
        )

    def show_click(self, x: int, y: int) -> None:
        d = DEFAULT_TARGET
        self.show_click_target(x - d // 2, y - d // 2, d, d, "")

    def show_click_target(self, x: int, y: int, w: int, h: int, selector: str) -> None:
        y0 = self.progress.height() if self.progress.isVisible() else 0
        self.highlight.flash(QRect(x, y + y0, w, h), f"点击 · {selector}" if selector else "点击")
        self.status.raise_()

    def takeover(self) -> None:
        if self.controller is not None:
            self.controller.takeover()
        else:
            self.set_agent_active(False)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        if self.status.isVisible():
            self._place_status()
        if self.highlight.isVisible():
            self.highlight.setGeometry(self.card.rect())
