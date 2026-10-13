"""模拟浏览器控制器：按线框演示 agent 打开登录页并点击“登录”。不依赖 QtWebEngine。"""

from __future__ import annotations

from braid.core.browser import BrowserController


class MockBrowserController(BrowserController):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.takeovers = 0
        self.agent_active.connect(self._track)

    def _track(self, active: bool, _action: str) -> None:
        self.active = active

    def takeover(self) -> None:
        self.takeovers += 1
        super().takeover()
        self.agent_active.emit(False, "")

    def demo(self) -> None:
        self.navigate_requested.emit("http://localhost:5173/login")
        self.agent_active.emit(True, "点击“登录”")
        self.agent_click_target.emit(32, 160, 244, 30, "button#submit")
