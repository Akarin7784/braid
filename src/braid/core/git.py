"""Git 抽象接口：右栏 Git 页只通过 GitSource 读写仓库状态。"""

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
    ahead: int = 0
    behind: int = 0
    staged: list[FileChange] = field(default_factory=list)
    unstaged: list[FileChange] = field(default_factory=list)


class GitSource(QObject):
    """仓库状态来源。实现方在状态变化时发 ``changed``；
    Pull/Push 是异步操作，开始/结束时发 ``busyChanged(op, busy)``，失败发 ``error``。"""

    changed = Signal()
    busyChanged = Signal(str, bool)  # op: "pull" | "push"
    error = Signal(str)

    @abstractmethod
    def status(self) -> GitStatus: ...

    @abstractmethod
    def diff(self, path: str, staged: bool) -> list[DiffLine]: ...

    @abstractmethod
    def branches(self) -> list[str]: ...

    @abstractmethod
    def checkout(self, branch: str) -> None: ...

    @abstractmethod
    def stage(self, path: str) -> None: ...

    @abstractmethod
    def unstage(self, path: str) -> None: ...

    @abstractmethod
    def commit(self, message: str) -> None: ...

    @abstractmethod
    def pull(self) -> None: ...

    @abstractmethod
    def push(self) -> None: ...
