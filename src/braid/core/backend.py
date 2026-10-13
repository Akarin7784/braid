"""AgentBackend 抽象接口：UI 只依赖这里，Agent 核心/MCP/Git 后续各自实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from PySide6.QtCore import QObject, Signal

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
    project_id: str | None = None
    parent_id: str | None = None  # 分支来源
    messages: list[Message] = field(default_factory=list)
    # 会话自己的模型与推理强度；None 表示使用设置里的默认值
    model_id: str | None = None
    reasoning: str | None = None


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str = ""
    # 支持的推理强度档位，按从低到高排列；空表示不支持推理强度
    reasoning_levels: tuple[str, ...] = ()


@dataclass
class StreamChunk:
    kind: Literal["text", "tool_call", "permission_request", "done"]
    data: str = ""


# 设置分区：与设置页左栏一一对应
CONFIG_SECTIONS: tuple[str, ...] = (
    "models",
    "permissions",
    "general",
    "agents",
    "mcp",
    "rules",
    "keybinds",
    "advanced",
)


class ConfigBus(QObject):
    """配置变更通知。AgentBackend 不是 QObject，信号挂在这个小对象上。"""

    config_changed = Signal(str)


@dataclass
class ConnectionResult:
    ok: bool
    message: str


class AgentBackend(ABC):
    _bus: ConfigBus | None = None

    @property
    def config_changed(self) -> Any:
        """``config_changed(section: str)`` 信号；set_config 成功后发出。"""
        if self._bus is None:
            self._bus = ConfigBus()
        return self._bus.config_changed

    @abstractmethod
    def get_config(self, section: str) -> dict[str, Any]:
        """返回分区配置的副本（修改它不会影响后端）。未知分区抛 KeyError。"""

    @abstractmethod
    def set_config(self, section: str, values: dict[str, Any]) -> None:
        """把 values 浅合并进分区并发出 config_changed(section)。"""

    def test_connection(self, provider_id: str, base_url: str) -> ConnectionResult:
        """测试服务商连通性。默认未实现；UI 负责异步展示结果。"""
        return ConnectionResult(False, "后端未实现")

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
