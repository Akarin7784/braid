"""产物（Artifact）抽象接口：右栏产物页只依赖这里。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath

from PySide6.QtCore import QObject, Signal


@dataclass
class Artifact:
    id: str
    name: str
    content: str
    path: str = ""  # 磁盘路径；空表示仅在内存中
    kind: str = ""  # markdown / html / code / image；空则按扩展名推断
    previous: str | None = None  # 上一版本内容，用于 Diff；None 表示无前版本
    created: datetime = field(default_factory=datetime.now)

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def resolved_kind(self) -> str:
        if self.kind:
            return self.kind
        ext = PurePath(self.name).suffix.lower()
        if ext in (".md", ".markdown"):
            return "markdown"
        if ext in (".html", ".htm"):
            return "html"
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
            return "image"
        return "code"


class ArtifactSource(QObject):
    """产物来源。Agent 核心实现它并在生成产物时发 ``artifact_added``。"""

    artifact_added = Signal(object)  # Artifact

    def list_artifacts(self) -> list[Artifact]:
        return []
