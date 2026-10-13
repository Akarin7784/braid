"""浏览器面板与 agent 之间的抽象接口：UI 只依赖这里。

agent → UI：``navigate_requested(url)``、``agent_active(active, action)``、
``agent_click(x, y)``（网页坐标）、``agent_click_target(x, y, w, h, selector)``（可选，带元素框）。
UI → agent：用户点“接管”时调用 ``takeover()``，它发出 ``takeover_requested``，
实现方应暂停 agent 并交还鼠标，随后发 ``agent_active(False, "")``。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class BrowserController(QObject):
    navigate_requested = Signal(str)
    agent_active = Signal(bool, str)
    agent_click = Signal(int, int)
    agent_click_target = Signal(int, int, int, int, str)
    takeover_requested = Signal()

    def takeover(self) -> None:
        self.takeover_requested.emit()
