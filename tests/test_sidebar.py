"""侧边栏与浮层窗口控制按钮。"""

import pytest
from PySide6.QtWidgets import QApplication

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


def test_grouping_by_project_and_pin(bar):
    g = bar.groups()
    assert list(g) == ["Braid", "未分配"]
    assert g["Braid"] == ["重构登录模块", "调研 PySide6 打包"]
    assert g["未分配"] == ["写周报"]
    sid = bar.sessions[2].id  # 调研 PySide6 打包
    bar.toggle_pin(sid)
    assert bar.groups()["Braid"][0] == "调研 PySide6 打包"
    bar.toggle_pin(sid)
    assert bar.groups()["Braid"][0] == "重构登录模块"


def test_group_collapse(bar):
    bar.toggle_group("Braid")
    assert bar.groups()["Braid"] == []
    bar.toggle_group("Braid")
    assert len(bar.groups()["Braid"]) == 2


def test_header_spacing_and_row_height(bar):
    from braid.ui.sidebar import HEADER

    heads = [bar.list.item(i) for i in range(bar.list.count()) if bar.list.item(i).data(HEADER)]
    assert heads[0].sizeHint().height() == 8 + 14 + 8
    assert heads[1].sizeHint().height() == 20 + 14 + 8
    row = next(
        bar.list.item(i) for i in range(bar.list.count()) if not bar.list.item(i).data(HEADER)
    )
    assert row.sizeHint().height() == 34


def test_new_session(bar, qtbot):
    with qtbot.waitSignal(bar.sessionSelected) as sig:
        s = bar.new_session()
    assert sig.args[0] is s
    assert bar.groups()["未分配"][0] == "新对话"


def test_rename(bar):
    sid = bar.sessions[0].id
    bar.rename_session(sid, "  新名字 ")
    assert "新名字" in bar.groups()["Braid"]


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
    assert sum(map(len, bar.groups().values())) == 2
    assert bar.list.currentItem() is not None


def test_search(bar):
    bar.search.setText("周报")
    assert bar.groups() == {"未分配": ["写周报"]}
    bar.search.setText("不存在")
    assert bar.groups() == {}
    bar.search.clear()
    assert sum(map(len, bar.groups().values())) == 3


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
    win.set_panel_open(False, animate=False)
    chat = win.chat_view.parentWidget()

    def filled() -> bool:
        return chat.mapTo(win, chat.rect().topRight()).x() >= win.width() - 1

    # macOS 上分割器/布局可能晚一拍才调整完，等稳定后再断言
    qtbot.waitUntil(lambda: not win.panel.isVisible() and filled(), timeout=3000)
    win.set_panel_open(True, animate=False)
    assert win.panel.width() >= 240


def test_selected_bg_uses_row_sel_token():
    from braid.ui.sidebar import SELECTED_BG

    assert SELECTED_BG == {False: "#EDEDEC", True: "#2B2B2A"}


def test_window_control_properties_and_qss_hover(win, qtbot):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QColor, QEnterEvent
    from PySide6.QtWidgets import QApplication

    from braid.theme import load_qss

    QApplication.instance().setStyleSheet(load_qss("light"))
    try:
        c = win.controls
        for b in c.buttons.values():
            assert b.property("role") == "windowControl"
        close = c.buttons["close"]
        assert close.property("kind") == "close"
        assert c.buttons["min"].property("kind") is None
        close._repolish()
        normal = close.palette().buttonText().color()
        assert normal == QColor("#6B6B69")
        QApplication.sendEvent(close, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        assert close.property("hovered") is True
        assert close.palette().buttonText().color() == QColor("#FFFFFF")  # 来自 QSS :hover
        mn = c.buttons["min"]
        mn.set_hovered(True)
        assert mn.icon_color() == normal
        img = close.grab().toImage()
        assert img.pixelColor(2, 14) == QColor("#E5484D")  # QSS 画的 hover 底
        QApplication.sendEvent(close, QEvent(QEvent.Type.Leave))
        assert close.property("hovered") is False
        assert close.palette().buttonText().color() == normal
    finally:
        QApplication.instance().setStyleSheet("")


def test_panel_toggle_aligns_right(qtbot) -> None:
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1200, 760)
    w.show()
    t = w.panel_toggle
    chat = w.chat_view.parentWidget()
    w.set_panel_open(True, animate=False)
    QApplication.processEvents()
    right = t.mapTo(w, t.rect().topLeft()).x() + t.width()
    assert chat.mapTo(w, chat.rect().topLeft()).x() + chat.width() - right == 16
    w.set_panel_open(False, animate=False)
    QApplication.processEvents()
    right = t.mapTo(w, t.rect().topLeft()).x() + t.width()
    assert w.controls.x() - right == 8


def test_title_bar_single_center_line(qtbot) -> None:
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1200, 760)
    w.show()
    for open_ in (False, True):
        w.set_panel_open(open_, animate=False)
        QApplication.processEvents()
        bar = w.title_bar
        assert bar.height() == 44
        for c in (w.sidebar_toggle, w.title, w.panel_toggle):
            assert abs(c.geometry().center().y() + 0.5 - 22) <= 0.5, c.objectName()
        if not open_:
            top = w.controls.y() - bar.mapTo(w, bar.rect().topLeft()).y()
            assert abs(top + w.controls.height() / 2 - 22) <= 0.5
    for b in (w.sidebar_toggle, w.panel_toggle):
        assert (b.width(), b.height()) == (28, 28)


def test_sidebar_persists_pin_and_delete(qtbot, tmp_path):
    from braid.backends.mock import MockBackend
    from braid.core.session_store import SessionStore
    from braid.ui.sidebar import Sidebar

    path = tmp_path / "s.json"
    sb = Sidebar(MockBackend(), store=SessionStore(path))
    qtbot.addWidget(sb)
    sid = sb.sessions[-1].id
    sb.toggle_pin(sid)
    sb2 = Sidebar(MockBackend(), store=SessionStore(path))
    qtbot.addWidget(sb2)
    assert sid in sb2.pinned
    groups = SessionStore(path).grouped()
    assert sum(len(r) for _, r in groups) == len(sb2.sessions)
