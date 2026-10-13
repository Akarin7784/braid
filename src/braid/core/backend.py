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


@dataclass(frozen=True)
class EffortOption:
    """一个推理强度档位：id 存进会话与设置，label / description 原样显示在模型菜单里。"""

    id: str
    label: str
    description: str = ""


# 旧接口只给 reasoning_levels（档位 id）时的兜底文案；新后端应直接给 efforts
LEGACY_EFFORTS: dict[str, EffortOption] = {
    "low": EffortOption("low", "低", "思考更少，回复更快"),
    "medium": EffortOption("medium", "中", "速度与质量兼顾"),
    "high": EffortOption("high", "高", "思考更多，适合难题"),
    "max": EffortOption("max", "最高", "思考最充分，耗时最长"),
}


@dataclass
class ModelInfo:
    """模型菜单的全部数据都来自这里，界面不写死任何模型或档位文案。

    - group：菜单分组标题（如服务商名），空则回退到 provider，再空不分组标题；
    - tier：右侧小标签（如 高 / 中 / 低），空则不显示；
    - description：第二行一句话说明，空则不显示；
    - efforts：推理强度档位（从低到高），空表示不支持，菜单不出子菜单、按钮只显示模型名。

    兼容旧调用：位置参数顺序不变；只给 reasoning_levels 时按 LEGACY_EFFORTS 补齐 efforts，
    只给 efforts 时 reasoning_levels 自动等于各档 id。
    """

    id: str
    name: str
    provider: str = ""
    reasoning_levels: tuple[str, ...] = ()
    description: str = ""
    tier: str = ""
    group: str = ""
    efforts: tuple[EffortOption, ...] = ()

    def __post_init__(self) -> None:
        if self.efforts:
            self.efforts = tuple(self.efforts)
            self.reasoning_levels = tuple(e.id for e in self.efforts)
        elif self.reasoning_levels:
            self.efforts = tuple(
                LEGACY_EFFORTS.get(lv, EffortOption(lv, lv)) for lv in self.reasoning_levels
            )
        if not self.group:
            self.group = self.provider

    def effort(self, effort_id: str) -> EffortOption | None:
        return next((e for e in self.efforts if e.id == effort_id), None)


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
    """界面只通过这个接口和 Agent 核心打交道。

    推理强度（effort）约定：类型是 ``str | None``。
    - 字符串：``ModelInfo.efforts`` 里某一档的 ``id``，如 ``"medium"``；
    - ``None``：不指定，由后端按该模型的默认行为处理（模型不支持推理强度时界面总是传 None）。
    不再使用空串表示“没有档位”。
    """

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

    def replace_config(self, section: str, values: dict[str, Any]) -> None:
        """整体替换分区（用于需要删除键的分区，如 ``keybinds``）并发出 config_changed。"""
        raise NotImplementedError

    def reset_config(self) -> None:
        """所有分区恢复默认值，逐个发出 config_changed。不触碰钥匙串。"""
        raise NotImplementedError

    def count_instruction_matches(self, pattern: str) -> int:
        """glob 形式的指令文件模式在项目里匹配到几个文件。默认 0。"""
        return 0

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
        reasoning: str | None = None,
        attachments: list[str] | None = None,
    ) -> Iterator[StreamChunk]:
        """发送一条消息并流式返回。``reasoning`` 是推理强度档位 id；None 表示用模型默认。"""
        ...

    @abstractmethod
    def respond_permission(
        self, request_id: str, decision: Literal["once", "always", "deny"]
    ) -> None: ...
