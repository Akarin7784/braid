from __future__ import annotations

import itertools
from collections.abc import Iterator

from braid.core.backend import AgentBackend, Message, ModelInfo, Session, StreamChunk


class MockBackend(AgentBackend):
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._sessions: dict[str, Session] = {}
        for t in ["重构登录模块", "写周报", "调研 PySide6 打包"]:
            s = self.create_session(t)
            s.messages += [
                Message("user", f"帮我{t}"),
                Message("assistant", "好的，这是模拟回复。"),
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
        return [ModelInfo("mock-large", "Mock Large"), ModelInfo("mock-fast", "Mock Fast")]

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
