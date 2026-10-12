"""AgentBackend 抽象接口：UI 只依赖这里，Agent 核心/MCP/Git 后续各自实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    text: str
    id: str = ""


@dataclass
class Session:
    id: str
    title: str
    project: str | None = None
    parent_id: str | None = None  # 分支来源
    messages: list[Message] = field(default_factory=list)


@dataclass
class ModelInfo:
    id: str
    name: str


@dataclass
class StreamChunk:
    kind: Literal["text", "tool_call", "permission_request", "done"]
    data: str = ""


class AgentBackend(ABC):
    @abstractmethod
    def list_sessions(self) -> list[Session]: ...
    @abstractmethod
    def create_session(self, title: str = "新对话") -> Session: ...
    @abstractmethod
    def branch_session(self, session_id: str, at_message: int) -> Session: ...
    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...
    @abstractmethod
    def send(
        self,
        session_id: str,
        text: str,
        model: str,
        reasoning: str = "medium",
        attachments: list[str] | None = None,
    ) -> Iterator[StreamChunk]: ...
    @abstractmethod
    def respond_permission(
        self, request_id: str, decision: Literal["once", "always", "deny"]
    ) -> None: ...
