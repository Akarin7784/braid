"""主窗口快捷键注册表、/help、/model。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from braid.backends.mock import MockBackend
from braid.core import keymap
from braid.ui.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    qtbot.waitUntil(lambda: getattr(w, "_current", None) is not None)
    return w


def _seq(w: MainWindow, aid: str) -> str:
    return w.shortcuts.shortcuts[aid].key().toString(QKeySequence.SequenceFormat.PortableText)


def test_registry_covers_actions_and_defaults(win):
    ids = {a.id for a in keymap.ACTIONS} - {"input.send", "input.newline"}
    assert set(win.shortcuts.shortcuts) == ids
    for aid in ids:
        assert _seq(win, aid) == keymap.BY_ID[aid].default
    # 输入框里的 Ctrl+Shift+I 已迁到注册表，Composer 不再自建 QShortcut
    from PySide6.QtGui import QShortcut

    assert not win.composer.findChildren(QShortcut)


def test_ctrl_tab_switches_session_not_focus(win, qtbot):
    inp = win.composer.input
    inp.setFocus()
    qtbot.waitUntil(inp.hasFocus)
    first = win._current.id
    qtbot.keyClick(inp, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: win._current.id != first)
    assert win._current.id == win._sessions[1].id
    assert inp.hasFocus()  # 没被焦点切换吞掉
    assert "\t" not in inp.toPlainText()


def test_rebind_on_config_changed(win, qtbot):
    b = win.backend
    b.replace_config("keybinds", {"session.new": "Ctrl+Shift+N", "session.search": ""})
    assert _seq(win, "session.new") == "Ctrl+Shift+N"
    assert _seq(win, "session.search") == ""
    assert not win.shortcuts.shortcuts["session.search"].isEnabled()
    b.replace_config("keybinds", {"input.send": "Ctrl+Return", "input.newline": "Return"})
    assert win.composer.input.send_key == "Ctrl+Return"
    assert win.composer.input.newline_key == "Return"
    b.reset_config()
    assert _seq(win, "session.new") == "Ctrl+N"
    assert win.shortcuts.shortcuts["session.search"].isEnabled()
    assert win.composer.input.send_key == "Return"


def test_rebound_send_key_in_composer(win, qtbot):
    win.backend.replace_config("keybinds", {"input.send": "Ctrl+Return", "input.newline": "Return"})
    sent = []
    win.composer.submitted.connect(lambda t, _a: sent.append(t))
    inp = win.composer.input
    inp.setPlainText("hi")
    qtbot.keyClick(inp, Qt.Key.Key_Return)
    assert not sent and inp.toPlainText().count("\n") == 1
    qtbot.keyClick(inp, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert sent == ["hi"]


def test_toggle_right_matches_button(win, qtbot):
    calls = []
    win.panel_toggle.clicked.connect(lambda: calls.append(1))
    assert win.panel_open()
    win.shortcuts.shortcuts["panel.toggle_right"].activated.emit()
    qtbot.waitUntil(lambda: not win.panel_open())
    assert calls == [1]  # 走的就是按钮的 clicked 入口
    win.panel_toggle.click()
    qtbot.waitUntil(win.panel_open)
    # 进设置自动收起（#49），在设置页里用快捷键打开，离开设置后恢复进设置前的状态
    win.show_settings(True)
    assert not win.panel_open()
    win.shortcuts.shortcuts["panel.toggle_right"].activated.emit()
    qtbot.waitUntil(win.panel_open)
    win.show_settings(False)
    assert win.panel_open()


def test_model_menu_shortcut(win, monkeypatch):
    hits = []
    monkeypatch.setattr(win.composer.model_chip, "showMenu", lambda: hits.append(1))
    win.shortcuts.shortcuts["input.model_menu"].activated.emit()
    assert hits == [1]


def _last(win) -> str:
    return win.chat_view.chat_model.items[-1].text


def test_help_lists_commands_and_shortcuts(win):
    win.backend.replace_config("keybinds", {"session.search": ""})
    win._command("help")
    t = _last(win)
    for c in win.composer.commands:
        assert f"/{c.name}" in t
    from braid.ui.shortcuts import display_text

    assert f"切换模型：`{display_text('Ctrl+Shift+I')}`" in t
    assert "搜索：未设置" in t


def test_help_typed_not_sent(win):
    sent = []
    win.chat.send = lambda text: sent.append(text)  # type: ignore[method-assign]
    win._submit("/help", [])
    assert not sent and "可用命令" in _last(win)


def test_model_command_show_and_switch(win):
    win._command("model")
    t = _last(win)
    assert "mock-fast" in t and "（当前）" in t and "构建" in t
    win._submit("/model mock-fast", [])
    assert win.composer.model_id == "mock-fast"
    assert "Mock Fast" in _last(win)
    win._submit("/model local 7b", [])
    assert win.composer.model_id == "local-7b"
    win._submit("/model nope", [])
    assert win.composer.model_id == "local-7b"
    assert "没有找到" in _last(win)


@pytest.mark.parametrize(
    ("platform", "mac", "model_menu", "toggle_right", "send"),
    [
        ("darwin", True, "⇧⌘I", "⇧⌘B", "↩"),
        ("linux", False, "Ctrl+Shift+I", "Ctrl+Shift+B", "Enter"),
        ("win32", False, "Ctrl+Shift+I", "Ctrl+Shift+B", "Enter"),
    ],
)
def test_help_shortcut_display_per_platform(
    win, monkeypatch, platform, mac, model_menu, toggle_right, send
):
    """模拟各平台的显示路径：macOS 用 ⌃⌥⇧⌘ 顺序的符号，存储始终是 PortableText。"""
    import sys

    from braid.ui.settings import keybinds
    from braid.ui.shortcuts import display_text

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(keybinds, "is_mac", lambda: mac)
    assert display_text("Ctrl+Shift+I") == model_menu
    win._command("help")
    t = _last(win)
    assert f"切换模型：`{model_menu}`" in t
    assert f"收起右栏：`{toggle_right}`" in t
    assert f"发送：`{send}`" in t
    # 存储与 QShortcut 绑定不随显示平台变化
    assert _seq(win, "input.model_menu") == "Ctrl+Shift+I"
    win.composer.set_key_bindings(win.shortcuts.bindings)
    assert model_menu in win.composer.model_chip.toolTip()
