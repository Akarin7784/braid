"""模拟 Git 来源：内存中的仓库状态，不调用 git。数据同线框 panel_git_*.png。"""

from __future__ import annotations

from PySide6.QtCore import QTimer

from braid.core.git import DiffLine, FileChange, GitSource, GitStatus

_LOGIN_DIFF = [
    DiffLine("ctx", 41, "self.err = QLabel()"),
    DiffLine("del", 42, 'self.err.setStyleSheet("color:gray")'),
    DiffLine("add", 42, 'self.err.setProperty("role", "error")'),
    DiffLine("add", 43, 'self.forgot = LinkLabel("忘记密码")'),
    DiffLine("add", 44, "self.forgot.clicked.connect(self.on_forgot)"),
    DiffLine("ctx", 45, "layout.addWidget(self.err)"),
]


class MockGitSource(GitSource):
    def __init__(self, op_ms: int = 400) -> None:
        super().__init__()
        self.op_ms = op_ms
        self._branch = "feat/login"
        self._branches = ["main", "feat/login", "design/menu-style"]
        self.ahead, self.behind = 1, 0
        self._staged = [FileChange("src/pages/forgot.py", "A")]
        self._unstaged = [
            FileChange("src/pages/login.py", "M"),
            FileChange("src/styles/login.qss", "M"),
            FileChange("src/old_auth.py", "D"),
        ]
        self.commits: list[str] = []
        self._busy: set[str] = set()

    def status(self) -> GitStatus:
        return GitStatus(
            self._branch, self.ahead, self.behind, list(self._staged), list(self._unstaged)
        )

    def diff(self, path: str, staged: bool) -> list[DiffLine]:
        if path == "src/pages/login.py":
            return list(_LOGIN_DIFF)
        fc = next((f for f in self._staged + self._unstaged if f.path == path), None)
        if fc is None:
            return []
        kind = {"A": "add", "D": "del"}.get(fc.status, "ctx")
        return [DiffLine(kind, i + 1, f"# {path} 第 {i + 1} 行") for i in range(3)]  # type: ignore[arg-type]

    def branches(self) -> list[str]:
        return list(self._branches)

    def checkout(self, branch: str) -> None:
        if branch in self._branches and branch != self._branch:
            self._branch = branch
            self.changed.emit()

    def _move(self, path: str, src: list[FileChange], dst: list[FileChange]) -> None:
        for f in src:
            if f.path == path:
                src.remove(f)
                dst.append(f)
                self.changed.emit()
                return

    def stage(self, path: str) -> None:
        self._move(path, self._unstaged, self._staged)

    def unstage(self, path: str) -> None:
        self._move(path, self._staged, self._unstaged)

    def commit(self, message: str) -> None:
        if not message.strip() or not self._staged:
            self.error.emit("没有可提交的内容")
            return
        self.commits.append(message.strip())
        self._staged.clear()
        self.ahead += 1
        self.changed.emit()

    def _run(self, op: str, done: object) -> None:
        if op in self._busy:
            return
        self._busy.add(op)
        self.busyChanged.emit(op, True)

        def finish() -> None:
            self._busy.discard(op)
            done()  # type: ignore[operator]
            self.busyChanged.emit(op, False)
            self.changed.emit()

        QTimer.singleShot(self.op_ms, finish)

    def pull(self) -> None:
        def done() -> None:
            self.behind = 0

        self._run("pull", done)

    def push(self) -> None:
        def done() -> None:
            self.ahead = 0

        self._run("push", done)
