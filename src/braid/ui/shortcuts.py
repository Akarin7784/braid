"""主窗口快捷键注册表：按 ``keymap.ACTIONS`` 给每个动作建一个 QShortcut。

绑定始终是 ``keymap.effective(backend.get_config("keybinds"))``；收到
``config_changed("keybinds")``（单项修改、``replace_config`` 整段替换、``reset_config``
都会发）就整体重算，不区分改了哪一项。空串表示未绑定。存储始终是 PortableText，
只有显示时才转成平台写法（macOS 用 ⌘ 等符号）。

``input.send`` / ``input.newline`` 不建 QShortcut：它们只在输入框内生效，由输入框按键
处理读取这里算出的绑定。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from braid.core import keymap
from braid.core.backend import AgentBackend

SECTION = "keybinds"
COMPOSER_ACTIONS = frozenset({"input.send", "input.newline"})


def display_text(seq: str, mac: bool | None = None, win: bool | None = None) -> str:
    """PortableText → 界面显示。

    macOS 按 ⌃⌥⇧⌘ 顺序连写符号（Ctrl+Shift+I → ⇧⌘I），其他平台用 + 连接
    （Ctrl+Shift+I）。``mac`` / ``win`` 为 None 时按当前平台，与设置页键帽同一套规则。
    """
    from braid.ui.settings import keybinds

    mac = keybinds.is_mac() if mac is None else mac
    return ("" if mac else "+").join(keybinds.display_parts(seq, mac=mac, win=win))


class ShortcutRegistry(QObject):
    """``bindingsChanged(dict)`` 在每次重算后发出，值为完整的 id → PortableText。"""

    bindingsChanged = Signal(dict)

    def __init__(
        self,
        window: QWidget,
        backend: AgentBackend,
        handlers: dict[str, Callable[[], None]],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._backend = backend
        self._handlers = handlers
        self.shortcuts: dict[str, QShortcut] = {}
        self.bindings: dict[str, str] = {}
        for a in keymap.ACTIONS:
            if a.id in COMPOSER_ACTIONS or a.id not in handlers:
                continue
            sc = QShortcut(window)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(handlers[a.id])
            self.shortcuts[a.id] = sc
        backend.config_changed.connect(self._on_config_changed)
        self.reload()

    def _on_config_changed(self, section: str) -> None:
        if section == SECTION:
            self.reload()

    def reload(self) -> None:
        try:
            overrides = self._backend.get_config(SECTION)
        except (KeyError, NotImplementedError):
            overrides = {}
        self.bindings = keymap.effective(overrides)
        for aid, sc in self.shortcuts.items():
            seq = self.bindings.get(aid, "")
            sc.setKey(QKeySequence.fromString(seq, QKeySequence.SequenceFormat.PortableText))
            sc.setEnabled(bool(seq))
        self.bindingsChanged.emit(dict(self.bindings))

    def key(self, action_id: str) -> str:
        return self.bindings.get(action_id, "")

    def display(self, action_id: str) -> str:
        seq = self.key(action_id)
        return display_text(seq) if seq else ""
