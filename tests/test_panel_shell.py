import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from braid.ui.panel import RightPanel
from braid.ui.panel.shell import MAX_WIDTH, MIN_WIDTH, TAB_H, TAB_NAMES, TAB_ROW_H, clamp_width
from braid.ui.panel.tokens import tokens


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
