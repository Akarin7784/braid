"""侧边栏与浮层窗口控制按钮。"""

import pytest

from braid.backends.mock import MockBackend
from braid.ui.main_window import MainWindow
from braid.ui.sidebar import Sidebar
from braid.ui.window_controls import RIGHT_MARGIN, WindowControls


@pytest.fixture
def win(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def _check_top_right(w):
    ctl = w.findChildren(WindowControls)
    assert len(ctl) == 1
    c = ctl[0]
    assert c.isVisible() and c.parent() is w
    g = c.geometry()
    assert g.right() + 1 == w.width() - RIGHT_MARGIN
    assert g.top() < 60
    assert c.size().height() == 28 and all(b.size().width() == 28 for b in c.buttons.values())
    return c


def test_controls_panel_open(win):
    c = _check_top_right(win)
    tb = win.panel_tabs
    cy = tb.mapTo(win, tb.rect().center()).y()
    assert abs(c.geometry().center().y() - cy) <= 1
    last = tb.tabRect(tb.count() - 1)
    last_right = tb.mapTo(win, last.topRight()).x()
    assert c.geometry().left() - last_right >= 16


def test_controls_panel_closed_and_animation(win, qtbot):
    win.set_panel_open(False)
    qtbot.waitUntil(lambda: not win.panel.isVisible(), timeout=2000)
    c = _check_top_right(win)
    t = win.title
    assert abs(c.geometry().center().y() - t.mapTo(win, t.rect().center()).y()) <= 1
    win.set_panel_open(True)
    qtbot.waitUntil(lambda: win.panel.width() > 300, timeout=2000)
    _check_top_right(win)


def test_controls_follow_resize(win):
    win.resize(1100, 700)
    _check_top_right(win)


def test_no_titlebar_buttons_left(win):
    from PySide6.QtWidgets import QPushButton

    texts = {b.text() for b in win.findChildren(QPushButton)}
    assert not texts & {"\u2212", "\u25a1", "\u2715"}


@pytest.fixture
def bar(qtbot):
    s = Sidebar(MockBackend())
    qtbot.addWidget(s)
    return s


def test_grouping_and_pin(bar):
    assert list(bar.groups()) == ["最近"]
    sid = bar.sessions[1].id
    bar.toggle_pin(sid)
    g = bar.groups()
    assert list(g) == ["置顶", "最近"] and g["置顶"] == ["写周报"]
    bar.toggle_pin(sid)
    assert list(bar.groups()) == ["最近"]


def test_new_session(bar, qtbot):
    with qtbot.waitSignal(bar.sessionSelected) as sig:
        s = bar.new_session()
    assert sig.args[0] is s
    assert bar.groups()["最近"][0] == "新对话"


def test_rename(bar):
    sid = bar.sessions[0].id
    bar.rename_session(sid, "  新名字 ")
    assert "新名字" in bar.groups()["最近"]


def test_rename_via_edit(bar):
    sid = bar.sessions[0].id
    bar.select(sid)
    bar.list.currentItem().setText("编辑后")
    assert bar.session(sid).title == "编辑后"


def test_delete(bar):
    bar.select(bar.sessions[0].id)
    sid = bar.sessions[0].id
    bar.delete_session(sid)
    assert bar.session(sid) is None
    assert len(bar.groups()["最近"]) == 2
    assert bar.list.currentItem() is not None


def test_search(bar):
    bar.search.setText("周报")
    assert bar.groups() == {"最近": ["写周报"]}
    bar.search.setText("不存在")
    assert bar.groups() == {}
    bar.search.clear()
    assert len(bar.groups()["最近"]) == 3


def test_entries(bar, qtbot):
    assert [b.text() for b in bar.entries.values()] == ["项目", "产物", "定时任务"]
    with qtbot.waitSignal(bar.entryTriggered) as sig:
        bar.entries["artifacts"].click()
    assert sig.args == ["artifacts"]


def test_selected_has_background(bar, qtbot):
    from PySide6.QtGui import QColor

    from braid.ui.sidebar import SELECTED_BG

    bar.resize(260, 400)
    bar.show()
    qtbot.waitExposed(bar)
    bar.select(bar.sessions[0].id)
    r = bar.list.visualItemRect(bar.list.currentItem())
    img = bar.list.viewport().grab().toImage()
    px = img.pixelColor(r.left() + 5, r.center().y())
    assert px == QColor(SELECTED_BG[False])


def test_center_fills_when_panel_collapsed(win, qtbot):
    win.set_panel_open(False)
    qtbot.waitUntil(lambda: not win.panel.isVisible(), timeout=2000)
    chat = win.chat_view.parentWidget()
    assert chat.mapTo(win, chat.rect().topRight()).x() >= win.width() - 1
    win.set_panel_open(True, animate=False)
    assert win.panel.width() >= 240
