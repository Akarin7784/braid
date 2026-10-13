import subprocess
import sys

import pytest
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from braid.backends.mock_browser import MockBrowserController
from braid.theme.palette import tokens
from braid.ui.panel import browser as bmod
from braid.ui.panel.browser import (
    HIGHLIGHT_FADE_MS,
    ROW_H,
    STATUS_INSET,
    UNAVAILABLE_TEXT,
    BrowserPage,
)


class _History:
    def __init__(self):
        self.back = self.fwd = False

    def canGoBack(self):  # noqa: N802
        return self.back

    def canGoForward(self):  # noqa: N802
        return self.fwd


class FakeView(QWidget):
    """与 QWebEngineView 同名接口的替身，不依赖 WebEngine。"""

    urlChanged = Signal(QUrl)
    loadStarted = Signal()
    loadProgress = Signal(int)
    loadFinished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.h = _History()
        self.calls: list[str] = []
        self.url = QUrl()

    def history(self):
        return self.h

    def setUrl(self, u):  # noqa: N802
        self.url = u
        self.calls.append("setUrl")
        self.urlChanged.emit(u)

    def back(self):
        self.calls.append("back")

    def forward(self):
        self.calls.append("forward")

    def reload(self):
        self.calls.append("reload")

    def stop(self):
        self.calls.append("stop")


def _render(w, img):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QRegion

    w.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)


def _page(qtbot, view=True, ctrl=None):
    p = BrowserPage(ctrl, web_factory=(FakeView if view else lambda: None))
    qtbot.addWidget(p)
    p.resize(420, 700)
    p.show()
    return p


def test_module_import_has_no_webengine():
    code = (
        "import sys, braid.ui.panel.browser;assert not any('WebEngine' in m for m in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_address_bar_layout(qtbot):
    p = _page(qtbot)
    for b in (p.back_btn, p.forward_btn, p.reload_btn, p.external_btn):
        assert b.size().width() == ROW_H and b.size().height() == ROW_H
    assert p.url_edit.height() == ROW_H
    assert [b.toolTip() for b in (p.back_btn, p.forward_btn, p.reload_btn, p.external_btn)] == [
        "后退",
        "前进",
        "刷新",
        "在系统浏览器打开",
    ]
    assert not p.back_btn.isEnabled() and not p.forward_btn.isEnabled()


def test_navigation_and_history(qtbot):
    p = _page(qtbot)
    v = p.view
    p.url_edit.setText("localhost:5173/login")
    p.url_edit.returnPressed.emit()
    assert v.url.toString() == "https://localhost:5173/login"
    v.h.back = True
    v.urlChanged.emit(QUrl("http://a/b"))
    assert p.url_edit.text() == "http://a/b" and p.back_btn.isEnabled()
    p.back_btn.click()
    assert "back" in v.calls


def test_loading_reload_becomes_stop(qtbot):
    p = _page(qtbot)
    p.view.loadStarted.emit()
    assert p.reload_btn.property("navIcon") == "stop" and p.progress.isVisible()
    p.view.loadProgress.emit(40)
    assert tokens(False)["brand"] in p.progress.styleSheet()
    p.reload_btn.click()
    assert p.view.calls[-1] == "stop"
    p.view.loadFinished.emit(True)
    assert p.reload_btn.property("navIcon") == "reload" and not p.progress.isVisible()
    p.reload_btn.click()
    assert p.view.calls[-1] == "reload"


def test_unavailable_fallback(qtbot):
    p = _page(qtbot, view=False)
    assert not p.web_available
    labels = [w.text() for w in p.card.findChildren(QLabel)]
    assert UNAVAILABLE_TEXT in labels
    assert not p.reload_btn.isEnabled()
    p.load("example.com")  # 不崩溃，只更新地址栏
    assert p.url_edit.text() == "https://example.com"


def test_load_webengine_degrades_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", None)  # 模拟未安装
    assert bmod.load_webengine() is None


def test_agent_status_and_takeover(qtbot):
    ctrl = MockBrowserController()
    p = _page(qtbot, ctrl=ctrl)
    assert not p.status.isVisible()
    ctrl.demo()
    assert p.status.isVisible() and p.status.text.text() == "Agent 正在操作 · 点击“登录”"
    assert p.view.url.toString() == "http://localhost:5173/login"
    g = p.status.geometry()
    assert g.left() == STATUS_INSET and p.card.width() - g.right() - 1 == STATUS_INSET
    assert p.card.height() - g.bottom() - 1 == STATUS_INSET
    assert p.status.dot.anim.state() == p.status.dot.anim.State.Running
    with qtbot.waitSignal(ctrl.takeover_requested):
        p.status.takeover_btn.click()
    assert ctrl.takeovers == 1 and not ctrl.active
    assert not p.status.isVisible() and not p.highlight.isVisible()


def test_click_highlight_fades_600ms(qtbot):
    ctrl = MockBrowserController()
    p = _page(qtbot, ctrl=ctrl)
    ctrl.agent_click_target.emit(32, 160, 244, 30, "button#submit")
    h = p.highlight
    assert h.isVisible() and h.label == "点击 · button#submit"
    assert h.anim.duration() == HIGHLIGHT_FADE_MS == 600
    fr = h.frame_rect()
    assert (fr.left(), fr.width()) == (30, 248)  # 外扩 2px
    img = QImage(h.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    h.render(img)
    edge = img.pixelColor(int(fr.left()) + 40, int(fr.top()))
    assert edge.red() > 150 and edge.blue() < 120  # brand 描边
    qtbot.waitUntil(lambda: not h.isVisible(), timeout=2000)


def test_click_point_dot_and_ripple(qtbot):
    ctrl = MockBrowserController()
    p = _page(qtbot, ctrl=ctrl)
    ctrl.agent_click.emit(100, 100)
    h = p.highlight
    assert h.point_mode and h.isVisible() and h.label == ""
    assert (bmod.DOT_D, bmod.RIPPLE_FROM, bmod.RIPPLE_TO) == (10, 10, 36)
    assert h.anim.duration() == 600
    h.anim.stop()
    h.opacity = 1.0
    assert h.ripple_diameter() == 10
    h.opacity = 0.5
    assert h.ripple_diameter() == 23
    h.opacity = 0.0
    assert h.ripple_diameter() == 36
    h.opacity = 1.0
    img = QImage(h.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    _render(h, img)
    c = img.pixelColor(100, 100)
    assert c.name().upper() == tokens(False)["brand"]  # 圆点中心为 brand
    assert img.pixelColor(100 + 12, 100).alpha() == 0  # 初始无方框/波纹仅 10px
    h.flash(h.target, "x")  # 有元素框时恢复方框模式
    assert not h.point_mode


def test_corner_mask(qtbot):
    from PySide6.QtCore import Qt

    p = _page(qtbot)
    m = p.corners
    assert m is not None
    assert m.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert m.geometry() == p.view.geometry()
    p.resize(520, 600)
    QApplication.processEvents()
    assert m.geometry() == p.view.geometry()
    img = QImage(m.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    _render(m, img)
    corner = img.pixelColor(0, 0)
    assert corner.alpha() == 255
    assert corner.name().upper() in (tokens(False)["pn_a"], tokens(False)["pn_b"])
    assert img.pixelColor(m.width() // 2, m.height() // 2).alpha() == 0
    assert img.pixelColor(bmod.CORNER_R, bmod.CORNER_R).alpha() == 0


def test_corner_mask_absent_when_unavailable(qtbot):
    assert _page(qtbot, view=False).corners is None


def test_nav_icons_fallback_glyphs(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(bmod, "nav_icon_path", lambda n, d: tmp_path / f"nav_{n}.png")
    p = _page(qtbot)
    assert p.back_btn.text() == "←" and p.back_btn.icon().isNull()
    assert p.external_btn.text() == "↗" and p.reload_btn.text() == "↻"
    p.set_loading(True)
    assert p.reload_btn.text() == "✕"


def test_nav_icons_loaded(qtbot, monkeypatch, tmp_path):
    for n in ("back", "forward", "reload", "stop", "external"):
        pm = QPixmap(40, 40)
        pm.fill(QColor("#123456"))
        pm.save(str(tmp_path / f"nav_{n}_light.png"))
    monkeypatch.setattr(
        bmod, "nav_icon_path", lambda n, d: tmp_path / f"nav_{n}_{'dark' if d else 'light'}.png"
    )
    p = _page(qtbot)
    for b in (p.back_btn, p.forward_btn, p.reload_btn, p.external_btn):
        assert b.text() == "" and not b.icon().isNull()
        assert b.iconSize().width() == bmod.NAV_ICON_PT == 20
    icon = bmod.load_nav_icon("back", False)
    assert icon is not None
    assert icon.availableSizes()[0].width() == 40  # 40px 源图，按 iconSize 20pt 显示
    p.set_loading(True)
    assert p.reload_btn.property("navIcon") == "stop" and p.reload_btn.text() == ""
    p.set_loading(False)
    assert p.reload_btn.property("navIcon") == "reload"


@pytest.mark.parametrize("dark", [False, True])
def test_packaged_nav_icons_load(qtbot, dark):
    for n in ("back", "forward", "reload", "stop", "external"):
        assert bmod.load_nav_icon(n, dark) is not None, n
    p = BrowserPage(web_factory=FakeView, theme="dark" if dark else "light")
    qtbot.addWidget(p)
    for b in (p.back_btn, p.forward_btn, p.reload_btn, p.external_btn):
        assert b.text() == "" and not b.icon().isNull()


def test_disabled_nav_opacity(qtbot):
    p = _page(qtbot)
    for b in (p.back_btn, p.forward_btn):
        assert not b.isEnabled() and not b.isHidden()
        assert BrowserPage.nav_opacity(b) == pytest.approx(0.35)
    p.view.h.back = True
    p.view.urlChanged.emit(QUrl("http://a"))
    assert BrowserPage.nav_opacity(p.back_btn) == 1.0
    assert BrowserPage.nav_opacity(p.forward_btn) == pytest.approx(0.35)
    assert BrowserPage.nav_opacity(p.external_btn) == 1.0


@pytest.mark.webengine
def test_real_webengine_page(qtbot):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    p = BrowserPage()
    qtbot.addWidget(p)
    assert p.web_available
    assert "PySide6.QtWebEngineWidgets" in sys.modules
