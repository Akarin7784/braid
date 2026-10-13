from __future__ import annotations

import copy
import itertools
from collections.abc import Iterator
from typing import Any

from braid.core.backend import (
    CONFIG_SECTIONS,
    AgentBackend,
    ConnectionResult,
    Message,
    ModelInfo,
    Session,
    StreamChunk,
)

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


def default_config() -> dict[str, dict[str, Any]]:
    """各分区的演示数据，字段参考 opencode 的 config（model / small_model / permission …）。"""
    return {
        "models": {
            "model": "mock-large",
            "small_model": "mock-fast",
            "providers": {},  # provider_id -> {"timeout": 秒, "chunk_timeout": 秒}
        },
        "permissions": {
            "edit": "ask",
            "bash": "ask",
            "webfetch": "allow",
            "bash_rules": [
                {"pattern": "rm -rf *", "action": "deny"},
                {"pattern": "git status", "action": "allow"},
            ],
        },
        "general": {
            "theme": "light",  # system / light / dark
            "language": "zh-CN",
            "font_size": 14,
            "autoupdate": "notify",  # auto / notify / off
            "shell": "/bin/bash",
        },
        "agents": {
            "default_agent": "build",
            # 参考 opencode 的 agent 配置：model 为空表示跟随默认模型；tools 为允许的工具
            "agents": [
                {
                    "id": "build",
                    "name": "构建",
                    "builtin": True,
                    "description": "默认智能体，可读写文件、执行命令",
                    "model": "",
                    "tools": ["read", "edit", "bash", "webfetch"],
                    "prompt": "",
                },
                {
                    "id": "plan",
                    "name": "规划",
                    "builtin": True,
                    "description": "只读分析与制定计划，不改动文件",
                    "model": "",
                    "tools": ["read", "webfetch"],
                    "prompt": "",
                },
                {
                    "id": "review",
                    "name": "代码审查",
                    "builtin": False,
                    "description": "审查改动并给出修改建议",
                    "model": "mock-fast",
                    "tools": ["read"],
                    "prompt": "你是严格的代码审查者，只指出问题与改法，不直接改代码。",
                },
            ],
        },
        "mcp": {
            # name -> {type: local/remote, command|url, enabled, status, error?}
            "servers": {
                "filesystem": {
                    "type": "local",
                    "command": "npx -y @modelcontextprotocol/server-filesystem ~",
                    "enabled": True,
                    "status": "connected",
                },
                "sqlite": {
                    "type": "local",
                    "command": "uvx mcp-server-sqlite --db-path data.db",
                    "enabled": False,
                    "status": "disconnected",
                },
                "context7": {
                    "type": "remote",
                    "url": "https://mcp.context7.com/mcp",
                    "enabled": True,
                    "status": "connected",
                },
                "sentry": {
                    "type": "remote",
                    "url": "https://mcp.sentry.dev/mcp",
                    "enabled": True,
                    "status": "error",
                    "error": "HTTP 401 未授权",
                },
            },
        },
        # 参考 opencode 的 instructions：路径或 glob，相对项目根目录
        "rules": {
            "instructions": ["CONTRIBUTING.md", "docs/guidelines/*.md", ".cursor/rules/**/*.mdc"]
        },
        # 只存用户改过的项：动作 id → QKeySequence.PortableText；"" 表示清空（见 core.keymap）
        "keybinds": {},
        "advanced": {
            "auto_compact": True,  # 上下文快满时自动压缩
            "keep_tokens": 20000,  # 压缩时保留的最近 token 数
            "snapshot": True,  # 记录文件快照，用于撤销智能体的改动
            "watcher_ignore": ["dist/**", "*.log"],  # 额外的文件监听忽略规则
            "share": "manual",
            "log_level": "info",
        },
    }


class MockBackend(AgentBackend):
    def __init__(self) -> None:
        self._config = default_config()
        assert tuple(self._config) == CONFIG_SECTIONS
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
            ModelInfo(
                "mock-large",
                "Mock Large",
                "Mock AI",
                ("low", "medium", "high", "max"),
                "最强·适合复杂任务",
                "高",
            ),
            ModelInfo(
                "mock-fast", "Mock Fast", "Mock AI", ("low", "medium"), "快速·适合日常", "中"
            ),
            ModelInfo("local-7b", "Local 7B", "本地模型", (), "本机运行·离线可用", "低"),
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

    def get_config(self, section: str) -> dict[str, Any]:
        return copy.deepcopy(self._config[section])

    def set_config(self, section: str, values: dict[str, Any]) -> None:
        if section not in self._config:
            raise KeyError(section)
        self._config[section].update(copy.deepcopy(values))
        self.config_changed.emit(section)

    def replace_config(self, section: str, values: dict[str, Any]) -> None:
        if section not in self._config:
            raise KeyError(section)
        self._config[section] = copy.deepcopy(values)
        self.config_changed.emit(section)

    def reset_config(self) -> None:
        self._config = default_config()
        for section in self._config:
            self.config_changed.emit(section)

    def test_connection(self, provider_id: str, base_url: str) -> ConnectionResult:
        """演示：endpoint 以 http 开头算成功，否则失败。"""
        if base_url.strip().startswith(("http://", "https://")):
            return ConnectionResult(True, "已连接 · 320ms")
        return ConnectionResult(False, "连接失败 · 端点无效")

    def count_instruction_matches(self, pattern: str) -> int:
        """演示：按模式长度给一个稳定的匹配数。"""
        return 2 + len(pattern) % 5
