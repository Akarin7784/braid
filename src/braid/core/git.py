"""Git 只读接口：右栏 Git 页只通过 GitSource 读取仓库状态与 diff，不做任何写操作。"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from PySide6.QtCore import QObject, Signal

FileStatus = Literal["A", "M", "D"]
LineKind = Literal["ctx", "add", "del", "hunk"]


@dataclass(frozen=True)
class FileChange:
    path: str
    status: FileStatus
    additions: int = 0  # 增行数
    deletions: int = 0  # 删行数

    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class DiffLine:
    """一行 diff。``hunk`` 行的 text 是 ``@@ -a,b +c,d @@`` 范围，行号为 None；
    增行只有新行号，删行只有旧行号，上下文行两者都有。"""

    kind: LineKind
    old: int | None
    new: int | None
    text: str


@dataclass
class GitStatus:
    branch: str
    files: list[FileChange] = field(default_factory=list)  # 工作区相对 HEAD 的改动


class GitSource(QObject):
    """只读的仓库状态来源。状态变化时发 ``changed``。"""

    changed = Signal()

    @abstractmethod
    def status(self) -> GitStatus: ...

    @abstractmethod
    def diff(self, path: str) -> list[DiffLine]: ...
