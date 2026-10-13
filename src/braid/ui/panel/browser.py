"""浏览器标签页（panel_spec §3）。

本模块只由 RightPanel 在首次切到浏览器标签时导入；QtWebEngine 只在
``load_webengine()`` 函数内部导入，禁止放到模块顶层。WebEngine 不可用时降级为提示。
颜色均在 paint 时从 ``braid.theme.palette.tokens`` 取。
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QHideEvent,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.browser import BrowserController
from braid.theme.menu import is_dark
from braid.theme.palette import qcolor
from braid.theme.palette import tokens as palette
from braid.ui.panel.shell import card_shadow


def nav_icon_path(name: str, dark: bool) -> Traversable:
    return files("braid.assets") / "icons" / f"nav_{name}_{'dark' if dark else 'light'}.png"


def load_nav_icon(name: str, dark: bool) -> QIcon | None:
    """读 assets/icons/nav_<name>_<mode>.png（40px，按 20pt 显示）；缺失返回 None。"""
    try:
        f = nav_icon_path(name, dark)
        if not f.is_file():
            return None
        pm = QPixmap()
        if not pm.loadFromData(f.read_bytes()) or pm.isNull():
            return None
    except (FileNotFoundError, OSError, ModuleNotFoundError):
        return None
    pm.setDevicePixelRatio(pm.width() / NAV_ICON_PT)
    return QIcon(pm)


ROW_H = 28
HIGHLIGHT_FADE_MS = 600
BREATH_MS = 1200
STATUS_INSET = 16
DOT_D, RIPPLE_FROM, RIPPLE_TO = 10, 10, 36  # 只有坐标时：圆点直径、波纹起止直径
CORNER_R = 14  # 网页卡片圆角（反圆角浮层）
NAV_ICON_PT = 20  # 40px 图标按 20pt 显示
NAV_DISABLED_OPACITY = 0.35
NAV_GLYPHS = {"back": "←", "forward": "→", "reload": "↻", "stop": "✕", "external": "↗"}
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


def _sel(dark: bool, mul: float = 1.0) -> QColor:
    """sel token（自带透明度），可再按 ``mul`` 衰减。"""
    c = qcolor("sel", dark)
    c.setAlphaF(c.alphaF() * mul)
    return c


def browser_qss(mode: str = "light") -> str:
    t = palette(mode == "dark")
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
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        c = QRectF(self.rect()).center()
        p.setBrush(_sel(dark, 0.5 + 0.5 * self._phase))
        p.drawEllipse(c, 8.0, 8.0)  # 4px 光晕（半径 4+4）
        p.setBrush(qcolor("brand", dark))
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
        self.point_mode = False
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

    def flash_point(self, x: int, y: int) -> None:
        """只有坐标：brand 圆点 + 波纹 10→36px 同时淡出，共 600ms。"""
        self.flash(QRect(x, y, 0, 0), "", point=True)

    def ripple_diameter(self) -> float:
        prog = 1.0 - self._opacity
        return RIPPLE_FROM + (RIPPLE_TO - RIPPLE_FROM) * prog

    def flash(self, target: QRect, label: str, point: bool = False) -> None:
        self.point_mode = point
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
        if self._opacity <= 0:
            return
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.point_mode:
            c = QPointF(self.target.topLeft())
            p.setOpacity(self._opacity)
            p.setPen(QPen(qcolor("brand", dark), 1.5))
            p.setBrush(_sel(dark))
            rad = self.ripple_diameter() / 2
            p.drawEllipse(c, rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor("brand", dark))
            p.drawEllipse(c, DOT_D / 2, DOT_D / 2)
            p.end()
            return
        if self.target.isNull():
            p.end()
            return
        p.setOpacity(self._opacity)
        r = self.frame_rect()
        halo = QPainterPath()
        halo.addRoundedRect(r.adjusted(-self.HALO, -self.HALO, self.HALO, self.HALO), 18, 18)
        inner = QPainterPath()
        inner.addRoundedRect(r, 12, 12)
        p.fillPath(halo.subtracted(inner), _sel(dark))
        p.setPen(QPen(qcolor("brand", dark), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 12, 12)
        if self.label:
            f = QFont()
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(qcolor("brand", dark))
            p.drawText(QRectF(r.left(), r.bottom() + self.HALO, 400, 16), self.label)
        p.end()


class CornerMask(QWidget):
    """盖在网页上的透明浮层：四角各画 14px 反圆角，用面板底色填充，鼠标穿透。
    不用 setMask（会锯齿且影响 WebEngine 合成）。尺寸随目标控件变化。"""

    def __init__(self, target: QWidget, parent: QWidget) -> None:
        super().__init__(parent)
        self.target = target
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        target.installEventFilter(self)
        self.sync()

    def sync(self) -> None:
        self.setGeometry(self.target.geometry())
        self.raise_()

    def eventFilter(self, o: QObject, e: QEvent) -> bool:
        if o is self.target and e.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.sync()
        return False

    def fill_brush(self) -> QLinearGradient:
        """面板底色 pn_a→pn_b 横向渐变，按所在右栏的坐标映射。"""
        dark = is_dark()
        panel = self.parentWidget()
        while panel is not None and panel.objectName() != "RightPanel":
            panel = panel.parentWidget()
        if panel is None:
            x0, x1 = 0.0, float(max(1, self.width()))
        else:
            x0 = float(self.mapFrom(panel, QPoint(0, 0)).x())
            x1 = x0 + panel.width()
        g = QLinearGradient(x0, 0, x1, 0)
        g.setColorAt(0, qcolor("pn_a", dark))
        g.setColorAt(1, qcolor("pn_b", dark))
        return g

    def corner_path(self) -> QPainterPath:
        r = float(CORNER_R)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        rounded = QPainterPath()
        rounded.addRoundedRect(QRectF(self.rect()), r, r)
        return full.subtracted(rounded)

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(self.corner_path(), self.fill_brush())
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
        self.dark = theme == "dark"
        self.back_btn = self._nav("back", "后退")
        self.forward_btn = self._nav("forward", "前进")
        self.reload_btn = self._nav("reload", "刷新")
        for b in (self.back_btn, self.forward_btn, self.reload_btn):
            bar.addWidget(b)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("UrlEdit")
        self.url_edit.setFixedHeight(ROW_H)
        self.url_edit.setPlaceholderText("输入网址")
        self.url_edit.returnPressed.connect(lambda: self.load(self.url_edit.text()))
        bar.addWidget(self.url_edit, 1)
        self.external_btn = self._nav("external", "在系统浏览器打开")
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
        self.corners: CornerMask | None = None
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
            self.corners = CornerMask(self.view, self.card)
        card_shadow(self.card)
        lay.addWidget(self.card, 1)

        self.status = AgentStatusBar(self.card)
        self.highlight = ClickHighlight(self.card)
        self.status.takeoverClicked.connect(self.takeover)
        self.loading = False
        self._update_nav()
        for b in (self.back_btn, self.forward_btn, self.reload_btn, self.external_btn):
            self._apply_nav_opacity(b)

        if controller is not None:
            controller.navigate_requested.connect(self.load)
            controller.agent_active.connect(self.set_agent_active)
            controller.agent_click.connect(self.show_click)
            controller.agent_click_target.connect(self.show_click_target)

    # —— 地址栏 ——
    def _nav(self, name: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setProperty("role", "navButton")
        b.setToolTip(tip)
        b.setFixedSize(ROW_H, ROW_H)
        b.setIconSize(QSize(NAV_ICON_PT, NAV_ICON_PT))
        self._set_nav_icon(b, name)
        # 不可用时不隐藏，整体 0.35 不透明度（图标与字符兜底一致）
        # 只在不可用时挂 opacity effect：常驻 effect 嵌在右栏阴影 effect 里会导致按钮不绘制
        b.installEventFilter(self)
        return b

    def set_theme(self, mode: str) -> None:
        """切换深浅色：重设 QSS、导航图标与进度条（其余部件在 paint 时取色）。"""
        self.dark = mode == "dark"
        self.setStyleSheet(browser_qss(mode))
        for b in self.findChildren(QPushButton):
            name = b.property("navIcon")
            if name:
                self._set_nav_icon(b, str(name))
        self.set_progress(getattr(self, "_progress_pct", 0))
        self.update()

    def _set_nav_icon(self, b: QPushButton, name: str) -> None:
        b.setProperty("navIcon", name)
        icon = load_nav_icon(name, self.dark)
        if icon is None:
            b.setIcon(QIcon())
            b.setText(NAV_GLYPHS[name])
        else:
            b.setText("")
            b.setIcon(icon)

    @staticmethod
    def _apply_nav_opacity(b: QPushButton) -> None:
        if b.isEnabled():
            if b.graphicsEffect() is not None:
                b.setGraphicsEffect(None)  # type: ignore[arg-type]
        elif not isinstance(b.graphicsEffect(), QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(b)
            eff.setOpacity(NAV_DISABLED_OPACITY)
            b.setGraphicsEffect(eff)

    @staticmethod
    def nav_opacity(b: QPushButton) -> float:
        eff = b.graphicsEffect()
        return eff.opacity() if isinstance(eff, QGraphicsOpacityEffect) else 1.0

    def eventFilter(self, o: QObject, e: QEvent) -> bool:
        if e.type() == QEvent.Type.EnabledChange and isinstance(o, QPushButton):
            self._apply_nav_opacity(o)
        return super().eventFilter(o, e)

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
        self._set_nav_icon(self.reload_btn, "stop" if on else "reload")
        self.reload_btn.setToolTip("停止" if on else "刷新")
        self.progress.setVisible(on)
        if on:
            self.set_progress(0)
        self._update_nav()

    def set_progress(self, pct: int) -> None:
        self._progress_pct = pct
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
        y0 = self.progress.height() if self.progress.isVisible() else 0
        self.highlight.flash_point(x, y + y0)
        self.status.raise_()

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
