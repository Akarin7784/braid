import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from braid.theme.palette import tokens as _pal
from braid.ui.panel import RightPanel
from braid.ui.panel.shell import MAX_WIDTH, MIN_WIDTH, TAB_H, TAB_NAMES, TAB_ROW_H, clamp_width


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
    w = _main_window(qtbot)
    w.resize(1800, 800)
    QApplication.processEvents()
    p = w.panel
    right = p.geometry().right()
    _drag(p.grip, -100)
    QApplication.processEvents()
    assert p.width() == 520 and p.geometry().right() == right
    _drag(p.grip, -2000)
    QApplication.processEvents()
    assert p.width() == MAX_WIDTH
    _drag(p.grip, 3000)
    QApplication.processEvents()
    assert p.width() == MIN_WIDTH


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
