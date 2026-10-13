import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QApplication

from braid.theme.palette import tokens as _pal
from braid.ui.panel import RightPanel
from braid.ui.panel.shell import (
    MAX_WIDTH,
    MIN_WIDTH,
    TAB_H,
    TAB_NAMES,
    TAB_ROW_H,
    PanelSplitter,
    clamp_width,
)


def tokens(mode):
    return _pal(mode == "dark")


def test_tabs_switch(qtbot):
    p = RightPanel()
    qtbot.addWidget(p)
    assert [b.text() for b in p.tabs] == list(TAB_NAMES)
    assert p.current_index() == 2
    with qtbot.waitSignal(p.currentChanged) as sig:
        qtbot.mouseClick(p.tabs[1], Qt.MouseButton.LeftButton)
    assert sig.args == [1]
    assert p.stack.currentIndex() == 1 and p.tabs[1].isChecked() and not p.tabs[2].isChecked()


def test_geometry_spec(qtbot):
    p = RightPanel()
    qtbot.addWidget(p)
    assert p.width() == 420
    assert all(b.height() == TAB_H for b in p.tabs)
    assert p.tabs[0].parentWidget().height() == TAB_ROW_H


def test_width_clamp():
    assert clamp_width(100) == MIN_WIDTH
    assert clamp_width(5000) == MAX_WIDTH
    assert clamp_width(500) == 500


def _drag(grip, dx):
    def ev(t, x):
        g = QPointF(grip.mapToGlobal(QPoint(2, 10))) + QPointF(x, 0)
        return QMouseEvent(
            t,
            QPointF(2, 10),
            g,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    QApplication.sendEvent(grip, ev(QMouseEvent.Type.MouseButtonPress, 0))
    QApplication.sendEvent(grip, ev(QMouseEvent.Type.MouseMove, dx))
    QApplication.sendEvent(grip, ev(QMouseEvent.Type.MouseButtonRelease, dx))


def test_drag_grip_clamps(qtbot):
    p = RightPanel()
    qtbot.addWidget(p)
    p.show()
    _drag(p.grip, -100)  # 向左拖变宽
    assert p.width() == 520
    _drag(p.grip, -1000)
    assert p.width() == MAX_WIDTH
    _drag(p.grip, 2000)
    assert p.width() == MIN_WIDTH


def test_tokens_have_active():
    assert tokens("light")["active"] == "#E9E9E8"
    assert tokens("dark")["active"] == "#3A3A39"


def test_no_webengine_at_import():
    code = (
        "import sys; import braid.ui.main_window, braid.ui.panel;"
        "assert not any('WebEngine' in m for m in sys.modules), 'webengine';"
        "assert 'braid.ui.panel.browser' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.webengine
def test_browser_lazy(qtbot):
    import sys as _s

    p = RightPanel()
    qtbot.addWidget(p)
    assert not p.browser_loaded
    qtbot.mouseClick(p.tabs[0], Qt.MouseButton.LeftButton)
    assert p.browser_loaded and "braid.ui.panel.browser" in _s.modules
    assert p.stack.currentIndex() == 0


def test_panel_follows_app_dark(qtbot):
    app = QApplication.instance()
    app.setProperty("braidDark", True)
    try:
        p = RightPanel()
        qtbot.addWidget(p)
        assert tokens("dark")["pn_a"] in p.styleSheet()
    finally:
        app.setProperty("braidDark", False)


def _main_window(qtbot):
    from braid.backends.mock import MockBackend
    from braid.ui.main_window import MainWindow

    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    qtbot.waitExposed(w)
    # 真实平台（Windows）上 show/resize 是异步的，等分割器完成布局再断言
    qtbot.waitUntil(lambda: sum(w.splitter.sizes()) > 0 and w.panel.width() > 0)
    QApplication.processEvents()
    return w


def test_no_divider_between_chat_and_panel(qtbot):
    w = _main_window(qtbot)
    split = w.centralWidget()
    h = split.handle(split.indexOf(w.panel))
    assert h.width() == 0 or not h.isVisible()
    assert not h.isEnabled()
    chat = split.widget(split.indexOf(w.panel) - 1)
    assert w.panel.geometry().left() == chat.geometry().right() + 1  # 紧贴，无缝
    assert split.handle(1).width() > 0  # 左栏分割条不受影响


def test_main_window_grip_drag_clamped(qtbot):
    """不写死像素：期望值由实际分割器尺寸、中栏最小宽度和 320–720 推出。"""
    from braid.ui.panel.shell import splitter_min_width

    w = _main_window(qtbot)
    w.resize(1800, 800)  # 屏幕更小时窗口达不到也没关系
    QApplication.processEvents()
    p, split = w.panel, w.splitter
    chat = split.widget(split.indexOf(p) - 1)
    total = sum(split.sizes())

    def settle():
        QApplication.processEvents()
        assert sum(split.sizes()) == total  # 只在中栏与右栏之间互换
        assert chat.width() >= splitter_min_width(chat)  # 中栏不被挤破

    start, right = p.width(), p.geometry().right()
    lo, hi = p.width_range()
    assert (lo, hi) == (MIN_WIDTH, min(MAX_WIDTH, start + chat.width() - splitter_min_width(chat)))
    _drag(p.grip, -100)
    settle()
    assert p.width() == min(start + 100, hi) and p.geometry().right() == right
    _drag(p.grip, -5000)
    settle()
    assert p.width() == hi <= MAX_WIDTH
    _drag(p.grip, 5000)
    settle()
    assert p.width() == MIN_WIDTH


def _col_mins(w):
    from braid.ui.panel.shell import splitter_min_width

    split = w.splitter
    widgets = [split.widget(i) for i in range(split.count())]
    handles = sum(split.handle(i).width() for i in range(1, split.count()))
    return sum(splitter_min_width(x) for x in widgets) + handles


def test_narrow_window_clamps_to_chat_min(qtbot):
    """窄窗口：宽度由各栏实际最小宽度推出，不写死像素，也不假设窗口能精确到请求值。"""
    from braid.ui.panel.shell import splitter_min_width

    w = _main_window(qtbot)
    split, p = w.splitter, w.panel
    chat = split.widget(split.indexOf(p) - 1)
    chat_min = splitter_min_width(chat)
    # 分割器之外的窗口开销（中心控件边距等）：窗口宽 - 分割器宽
    overhead = w.width() - split.width()
    target = max(w.minimumWidth(), _col_mins(w) + overhead)
    w.resize(target, 700)
    qtbot.waitUntil(lambda: abs(split.width() + overhead - w.width()) <= 1)
    QApplication.processEvents()

    p.set_panel_width(MAX_WIDTH)
    QApplication.processEvents()
    assert MIN_WIDTH <= p.width() == p.width_range()[1] <= MAX_WIDTH
    if split.width() >= _col_mins(w):  # 空间够时：中栏绝不被挤到最小宽度以下
        assert chat.width() >= chat_min
    else:  # 空间本身不够（窗口最小宽度 < 各栏最小宽度之和）：右栏至少不多占
        assert p.width() == MIN_WIDTH
    p.set_panel_width(MIN_WIDTH)
    QApplication.processEvents()
    assert p.width() == MIN_WIDTH
    if split.width() >= _col_mins(w):
        assert chat.width() >= chat_min


def test_set_width_before_layout_is_applied_later(qtbot):
    from PySide6.QtWidgets import QWidget

    split = PanelSplitter()
    qtbot.addWidget(split)
    split.addWidget(QWidget())
    p = RightPanel()
    split.addWidget(p)
    assert sum(split.sizes()) == 0
    p.set_panel_width(500)  # 尚未布局：记下待应用
    split.resize(1400, 600)
    split.show()
    qtbot.waitExposed(split)
    qtbot.waitUntil(lambda: p.width() == 500)


def test_trailing_widget(qtbot):
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QWidget

    class Box(QWidget):
        def sizeHint(self):
            return QSize(90, 28)

    p = RightPanel()
    qtbot.addWidget(p)
    p.show()
    row = p.tabs[0].parentWidget()
    assert p.trailing.isHidden() and p.trailing_widget() is None
    stretch_before = row.layout().itemAt(len(p.tabs)).geometry().width()
    box = Box()
    p.set_trailing_widget(box)
    QApplication.processEvents()
    assert p.trailing_widget() is box and box.isVisible()
    g = box.geometry().translated(p.trailing.pos())
    assert g.right() == row.contentsRect().right()  # 最右侧
    assert box.height() == 28 and abs(g.center().y() - row.height() / 2) <= 1  # 垂直居中
    assert g.left() > p.tabs[-1].geometry().right()
    p.set_trailing_widget(None)
    QApplication.processEvents()
    assert p.trailing.isHidden() and box.parent() is None
    assert row.layout().itemAt(len(p.tabs)).geometry().width() == stretch_before


def test_trailing_reserve_width(qtbot):
    from braid.ui.window_controls import WindowControls

    w = _main_window(qtbot)
    p = w.panel
    want = WindowControls.reserved_width() + 16
    assert p.trailing_reserve() == want
    row = p.tab_row
    stretch = row.layout().itemAt(len(p.tabs))
    # 留空 = 标签行右侧到面板右边缘：留空条 + 面板 18px 内边距
    space_from_right = p.width() - row.mapTo(p, stretch.geometry().topRight()).x() - 1
    assert space_from_right == want


def _gap(w):
    c = w.controls
    last = w.panel.tabs[-1]
    last_right = last.mapTo(w, last.rect().topRight()).x()
    return c.geometry().left() - last_right


def test_controls_never_cover_last_tab(qtbot):
    w = _main_window(qtbot)
    assert _gap(w) >= 16
    w.panel.set_panel_width(MIN_WIDTH)
    QApplication.processEvents()
    w._place_controls()
    assert w.panel.width() == MIN_WIDTH and _gap(w) >= 16
    # 最窄面板时：标签宽 + 两侧留空必须放得下（与平台字体/缩放无关）
    from braid.ui.window_controls import WindowControls

    last = w.panel.tabs[-1]
    used = last.mapTo(w.panel, last.rect().topRight()).x() + 1
    assert used + WindowControls.reserved_width() + 16 <= w.panel.width()
    w.set_panel_open(False, animate=False)
    w.set_panel_open(True, animate=False)
    QApplication.processEvents()
    assert _gap(w) >= 16


def test_main_window_panel_dark_from_app_property_only(qtbot):
    app = QApplication.instance()
    app.setProperty("braidDark", True)
    try:
        w = _main_window(qtbot)
        assert tokens("dark")["pn_a"] in w.panel.styleSheet()
        assert tokens("light")["pn_a"] not in w.panel.styleSheet()
    finally:
        app.setProperty("braidDark", False)


def test_tab_row_aligned_with_title_row(qtbot):
    w = _main_window(qtbot)
    assert w.panel_open()
    p = w.panel
    row = p.tab_row
    assert row.height() == TAB_ROW_H == 44
    assert row.mapTo(w, row.rect().topLeft()).y() == 0
    for b in p.tabs:
        top = b.mapTo(w, b.rect().topLeft()).y()
        assert abs(top + b.height() / 2 - 22) <= 0.5
    w._place_controls()
    g = w.controls.geometry()
    assert abs(g.top() + g.height() / 2 - 22) <= 0.5


@pytest.fixture
def big_font_window(qtbot):
    """模拟 Windows 上更宽的 UI 字体（Segoe UI / 微软雅黑）：窗口字体放大 1.4 倍。"""
    from braid.backends.mock import MockBackend
    from braid.ui.main_window import MainWindow

    w = MainWindow(MockBackend())
    f = QFont(w.font())
    f.setPointSizeF(f.pointSizeF() * 1.4)
    w.setFont(f)
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    qtbot.waitExposed(w)
    qtbot.waitUntil(lambda: sum(w.splitter.sizes()) > 0)
    QApplication.processEvents()
    return w


def test_big_font_panel_min_is_320(big_font_window):
    from braid.ui.panel.shell import splitter_min_width
    from braid.ui.window_controls import WindowControls

    w = big_font_window
    p = w.panel
    # 字体变大不应抬高面板最小宽度（Windows CI 上曾被抬到 448）
    assert splitter_min_width(p) == MIN_WIDTH
    assert p.minimumSizeHint().width() <= MIN_WIDTH
    p.set_panel_width(MIN_WIDTH)
    QApplication.processEvents()
    w._place_controls()
    assert p.width() == MIN_WIDTH
    assert _gap(w) >= 16  # 浮层按钮不压最后一个标签
    last = p.tabs[-1]
    assert last.mapTo(p, last.rect().topRight()).x() + 1 + WindowControls.reserved_width() + 16 <= (
        p.width()
    )
    assert all(t.width() >= 28 for t in p.tabs)
    _assert_no_tab_scrolling(p)
    # 放大字体并压缩可用空间：标签必须右侧省略（…），全名不变，且不出现滚动条/滚动箭头
    p.tab_row.setStyleSheet('QPushButton[role="panelTab"] { font-size: 22px; }')
    p.set_trailing_reserve(WindowControls.reserved_width() + 16 + 60)
    QApplication.processEvents()
    assert p.width() == MIN_WIDTH
    assert any(t.is_elided() for t in p.tabs)
    for t in p.tabs:
        if t.is_elided():
            shown = t.elided_text()
            assert shown.endswith("…") and shown != t.text()
        assert t.text() in TAB_NAMES
        assert t.geometry().right() < p.tab_row.width()  # 不溢出标签行
    _assert_no_tab_scrolling(p)
    w._place_controls()
    assert _gap(w) >= 16


def _assert_no_tab_scrolling(p):
    from PySide6.QtWidgets import QAbstractScrollArea, QScrollBar, QTabBar, QToolButton

    row = p.tab_row
    assert not row.findChildren(QScrollBar)
    assert not row.findChildren(QAbstractScrollArea)
    assert not row.findChildren(QTabBar)  # 无 QTabBar 自带的滚动箭头
    assert not [b for b in row.findChildren(QToolButton) if b.isVisible()]


def test_big_font_narrow_window_keeps_chat_min(big_font_window):
    from braid.ui.panel.shell import splitter_min_width

    w = big_font_window
    p, split = w.panel, w.splitter
    chat = split.widget(split.indexOf(p) - 1)
    chat_min = splitter_min_width(chat)
    # 把中栏和右栏的富余都去掉：右栏应先缩到 320，中栏不低于其最小宽度
    slack = (chat.width() - chat_min) + (p.width() - MIN_WIDTH)
    w.resize(max(w.minimumWidth(), w.width() - slack), 700)
    QApplication.processEvents()
    assert chat.width() >= chat_min
    assert p.width() >= MIN_WIDTH
    p.set_panel_width(MAX_WIDTH)
    QApplication.processEvents()
    assert chat.width() >= chat_min and MIN_WIDTH <= p.width() <= MAX_WIDTH
    p.set_panel_width(MIN_WIDTH)
    QApplication.processEvents()
    assert p.width() == MIN_WIDTH and chat.width() >= chat_min


def test_tab_elides_when_squeezed(qtbot):
    from braid.ui.panel.shell import TAB_MIN_W, PanelTab

    t = PanelTab("很长很长的标签名字")
    qtbot.addWidget(t)
    assert t.minimumSizeHint().width() == TAB_MIN_W
    t.resize(40, 28)
    assert t.is_elided() and t.text() == "很长很长的标签名字"
