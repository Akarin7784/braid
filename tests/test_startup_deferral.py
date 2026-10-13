"""启动优化：首个会话推迟到首帧后打开、QSS 与 lexer 缓存、secrets 不在导入时解析 keyring。"""

import subprocess
import sys

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.ui.chat_view import _lexer
from braid.ui.main_window import MainWindow


def test_initial_session_opens_after_first_event_loop_turn(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    assert getattr(w, "_current", None) is None  # 构造时不渲染会话
    qtbot.waitUntil(lambda: getattr(w, "_current", None) is not None)
    assert w._current is w.sidebar.sessions[0]


def test_deferred_open_does_not_override_user_choice(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    target = w.sidebar.sessions[-1]
    w.sidebar.select(target.id)
    qtbot.wait(20)
    assert w._current is target


def test_deferred_open_keeps_settings_opened_before_first_frame(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.sidebar.settingsRequested.emit()  # 首帧前点齿轮
    assert w.settings_open()
    qtbot.wait(20)
    assert w.settings_open()
    assert getattr(w, "_current", None) is None


def test_blank_first_frame_shows_only_background(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    # 计时器触发前：对话区没有行、标题为空，ChatView 本身不绘制任何"无会话"占位
    assert w.chat_view.model().rowCount() == 0
    assert w.title.text() == ""
    assert not w.settings_open()
    qtbot.waitUntil(lambda: w.chat_view.model().rowCount() > 0)


def test_deferred_open_skipped_when_window_destroyed(qtbot):
    w = MainWindow(MockBackend())
    w.deleteLater()
    qtbot.wait(20)  # 计时器归窗口所有，不会对已销毁窗口回调


def test_qss_and_lexer_cached():
    assert load_qss("light") is load_qss("light")
    assert load_qss("light") != load_qss("dark")
    assert _lexer("python") is _lexer("python")
    assert type(_lexer("no-such-lang")).__name__ == "TextLexer"


def test_startup_imports_stay_light():
    code = (
        "import sys; import braid.app; "
        "mods = ('keyring', 'pygments', 'braid.ui.settings_page'); "
        "print(','.join(m for m in mods if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", check=True
    )
    assert out.stdout.strip() == ""
