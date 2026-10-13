import subprocess
import sys

import pytest
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QLabel, QWidget

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
    assert p.reload_btn.text() == "✕" and p.progress.isVisible()
    p.view.loadProgress.emit(40)
    assert tokens(False)["brand"] in p.progress.styleSheet()
    p.reload_btn.click()
    assert p.view.calls[-1] == "stop"
    p.view.loadFinished.emit(True)
    assert p.reload_btn.text() == "↻" and not p.progress.isVisible()
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
    edge = QColor(img.pixel(int(fr.left()) + 40, int(fr.top())))
    assert edge.red() > 150 and edge.blue() < 120  # brand 描边
    qtbot.waitUntil(lambda: not h.isVisible(), timeout=2000)


def test_click_point_only(qtbot):
    ctrl = MockBrowserController()
    p = _page(qtbot, ctrl=ctrl)
    ctrl.agent_click.emit(100, 100)
    assert p.highlight.target.center().x() in (99, 100) and p.highlight.label == "点击"


@pytest.mark.webengine
def test_real_webengine_page(qtbot):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    p = BrowserPage()
    qtbot.addWidget(p)
    assert p.web_available
    assert "PySide6.QtWebEngineWidgets" in sys.modules
