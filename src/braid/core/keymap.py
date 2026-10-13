"""快捷键动作表：主窗口注册表和设置页「快捷键」共用的唯一来源。

配置分区 ``keybinds`` 只存用户改过的项，形如 ``{"session.new": "Ctrl+N"}``，
值为 ``QKeySequence.PortableText`` 字符串；空字符串表示用户清空了该快捷键
（仅 ``clearable`` 为真的动作允许）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

GROUPS: tuple[tuple[str, str], ...] = (
    ("session", "会话"),
    ("input", "输入"),
    ("panel", "面板"),
    ("app", "应用"),
)


@dataclass(frozen=True)
class Action:
    id: str
    group: str
    name: str
    default: str
    clearable: bool = True


ACTIONS: tuple[Action, ...] = (
    Action("session.new", "session", "新对话", "Ctrl+N"),
    Action("session.switch", "session", "切换会话", "Ctrl+Tab"),
    Action("session.search", "session", "搜索", "Ctrl+F"),
    Action("input.send", "input", "发送", "Return", clearable=False),
    Action("input.newline", "input", "换行", "Shift+Return", clearable=False),
    Action("input.command_palette", "input", "命令面板", "Ctrl+K"),
    Action("input.model_menu", "input", "切换模型", "Ctrl+Shift+I"),
    Action("panel.toggle_sidebar", "panel", "收起侧栏", "Ctrl+B"),
    Action("panel.toggle_right", "panel", "收起右栏", "Ctrl+Shift+B"),
    Action("panel.next_tab", "panel", "切换 tab", "Ctrl+Shift+]"),
    Action("app.settings", "app", "打开设置", "Ctrl+,"),
    Action("app.toggle_theme", "app", "切换主题", "Ctrl+Shift+L"),
)

BY_ID: dict[str, Action] = {a.id: a for a in ACTIONS}


def effective(overrides: Mapping[str, str] | None) -> dict[str, str]:
    """合并默认值与用户覆盖；未知 id 和不可清空动作的空值被忽略。"""
    result = {a.id: a.default for a in ACTIONS}
    for aid, seq in (overrides or {}).items():
        action = BY_ID.get(aid)
        if action is None or not isinstance(seq, str):
            continue
        if seq == "" and not action.clearable:
            continue
        result[aid] = seq
    return result
