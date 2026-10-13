"""设置分区“MCP 服务”：本地 / 远程两张卡，每行 状态点 + 名称 + 命令或 URL + 开关。

只经 ``AgentBackend`` 的 ``get_config("mcp")`` / ``set_config("mcp", ...)`` 读写，
收到 ``config_changed("mcp")`` 后重建。数据形状::

    {"servers": {name: {"type": "local"|"remote", "command"|"url": str,
                        "enabled": bool, "status": ..., "error"?: str}}}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from braid.core.backend import AgentBackend
from braid.theme.menu import is_dark
from braid.theme.palette import qcolor
from braid.ui.settings.pages import SectionPage, register_page
from braid.ui.settings.widgets import (
    ADD_CARD_H,
    AddCard,
    SettingCard,
    SettingRow,
    ToggleSwitch,
)

SECTION = "mcp"
ADD_H = ADD_CARD_H  # 兼容旧名
ERROR_TEXT = "连接失败"
NAME_W = 120  # 名称列定宽，命令/URL 列在所有行同一 x 起
McpKind = Literal["local", "remote"]
McpStatus = Literal["connected", "error", "disconnected"]
STATUS_TOKEN: dict[str, str] = {
    "connected": "success",
    "error": "danger",
    "disconnected": "text3",
}
STATUS_TEXT = {"connected": "已连接", "error": "连接失败", "disconnected": "未连接"}


@dataclass(frozen=True)
class McpServerConfig:
    """配置 dict 与界面之间的转换助手。"""

    name: str
    kind: McpKind
    target: str  # local: 命令；remote: URL
    enabled: bool = True
    status: McpStatus = "disconnected"
    error: str | None = None

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> McpServerConfig:
        kind = cast(McpKind, d.get("type", "local"))
        return cls(
            name,
            kind,
            str(d.get("command" if kind == "local" else "url", "")),
            bool(d.get("enabled", True)),
            cast(McpStatus, d.get("status", "disconnected")),
            d.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.kind,
            ("command" if self.kind == "local" else "url"): self.target,
            "enabled": self.enabled,
            "status": self.status,
        }
        if self.error:
            d["error"] = self.error
        return d


def servers_from_config(cfg: dict[str, Any]) -> list[McpServerConfig]:
    return [McpServerConfig.from_dict(n, d) for n, d in cfg.get("servers", {}).items()]


class StatusDot(QWidget):
    def __init__(self, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.status = status
        self.setFixedSize(8, 8)
        self.setToolTip(STATUS_TEXT.get(status, status))

    def color_token(self) -> str:
        return STATUS_TOKEN.get(self.status, "text3")

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(self.color_token(), is_dark()))
        p.drawEllipse(self.rect())


class _Tail(QWidget):
    """行右侧：命令/URL（中间省略）+ 开关。"""

    def __init__(self, cfg: McpServerConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.target = QLabel(self)
        self.target.setObjectName("mcpTarget")
        self.target.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.switch = ToggleSwitch(self, checked=cfg.enabled)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self.target, 1)
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, e: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(e)
        text = ERROR_TEXT if self.cfg.status == "error" else self.cfg.target
        fm = self.target.fontMetrics()
        w = max(0, self.target.width())
        self.target.setText(fm.elidedText(text, Qt.TextElideMode.ElideMiddle, w))


class McpRow(SettingRow):
    """SettingRow（44px，标签左、控件右），标签前插状态点，控件区放命令/URL + 开关。"""

    toggled = Signal(str, bool)

    def __init__(self, cfg: McpServerConfig, parent: QWidget | None = None) -> None:
        tail = _Tail(cfg)
        super().__init__(cfg.name, tail, parent)
        self.cfg = cfg
        self.target, self.switch = tail.target, tail.switch
        self.dot = StatusDot(cfg.status, self)
        self.label.setFixedWidth(NAME_W)
        self.label.setToolTip(cfg.name)
        fm = self.label.fontMetrics()
        self.label.setText(fm.elidedText(cfg.name, Qt.TextElideMode.ElideRight, NAME_W))
        lay = cast(QHBoxLayout, self.layout())
        lay.insertWidget(0, self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.setSpacing(10)
        lay.setStretchFactor(self.label, 0)
        lay.setStretchFactor(tail, 1)
        if cfg.status == "error":
            self.target.setProperty("error", True)
            tip = f"连接失败：{cfg.error or '未知错误'}"
            self.dot.setToolTip(tip)
            self.setToolTip(tip)
        else:
            self.target.setToolTip(cfg.target)
        self.switch.toggled.connect(lambda on: self.toggled.emit(cfg.name, on))


class McpPage(SectionPage):
    GROUPS = (("local", "本地"), ("remote", "远程"))

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("MCP 服务", "连接本地或远程的 MCP 服务，为智能体提供更多工具", parent)
        self.backend = backend
        self.cards: dict[str, SettingCard] = {}
        for kind, label in self.GROUPS:
            card = SettingCard(label, self)
            self.cards[kind] = card
            self.lay.addWidget(card)
        self.add_card = AddCard("+ 添加 MCP 服务", self)
        self.lay.addWidget(self.add_card)
        self.finish()
        backend.config_changed.connect(self._on_config_changed)
        self.reload()

    def rows(self) -> list[McpRow]:
        return [r for c in self.cards.values() for r in c.findChildren(McpRow)]

    def card_rows(self, kind: str) -> list[McpRow]:
        return self.cards[kind].findChildren(McpRow)

    def reload(self) -> None:
        for r in self.rows():
            r.setParent(None)
            r.deleteLater()
        for cfg in servers_from_config(self.backend.get_config(SECTION)):
            card = self.cards[cfg.kind]
            row = McpRow(cfg, card)
            row.toggled.connect(self.set_enabled)
            card.add_widget(row)

    def _on_config_changed(self, section: str) -> None:
        if section == SECTION:
            self.reload()

    def set_enabled(self, name: str, enabled: bool) -> None:
        servers = self.backend.get_config(SECTION).get("servers", {})
        if name in servers:
            servers[name]["enabled"] = enabled
            self.backend.set_config(SECTION, {"servers": servers})


register_page(SECTION, McpPage)
