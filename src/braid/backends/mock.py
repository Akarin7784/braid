from __future__ import annotations

import itertools
from collections.abc import Iterator

from braid.core.backend import AgentBackend, Message, ModelInfo, Session, StreamChunk

DEMO_REPLY = """好的，先看一下现在的实现。**主要问题**有两点：

1. 校验逻辑和界面耦合在一起
2. 没有超时处理

可以这样拆：

```python
def login(user: str, pwd: str, timeout: float = 5.0) -> bool:
    if not user:
        raise ValueError("empty user")
    return auth.check(user, pwd, timeout=timeout)
```
"""


class MockBackend(AgentBackend):
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._sessions: dict[str, Session] = {}
        for t, proj in [
            ("重构登录模块", "Braid"),
            ("写周报", None),
            ("调研 PySide6 打包", "Braid"),
        ]:
            s = self.create_session(t)
            s.project_id = proj
            s.messages += [
                Message("user", f"帮我{t}"),
                Message("assistant", DEMO_REPLY),
            ]

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def create_session(self, title: str = "新对话") -> Session:
        s = Session(id=f"s{next(self._ids)}", title=title)
        self._sessions[s.id] = s
        return s

    def branch_session(self, session_id: str, at_message: int) -> Session:
        src = self._sessions[session_id]
        s = self.create_session(src.title + "（分支）")
        s.parent_id, s.messages = src.id, list(src.messages[: at_message + 1])
        return s

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo("mock-large", "Mock Large", "Mock AI", ("low", "medium", "high", "max")),
            ModelInfo("mock-fast", "Mock Fast", "Mock AI", ("low", "medium")),
            ModelInfo("local-7b", "Local 7B", "本地模型"),
        ]

    def send(
        self, session_id, text, model, reasoning="medium", attachments=None
    ) -> Iterator[StreamChunk]:
        s = self._sessions[session_id]
        s.messages.append(Message("user", text))
        reply = f"（{model}）收到：{text}"
        for ch in reply:
            yield StreamChunk("text", ch)
        s.messages.append(Message("assistant", reply))
        yield StreamChunk("done")

    def respond_permission(self, request_id, decision) -> None:
        pass
