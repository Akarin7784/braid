"""模拟 Git 来源：内存中的仓库状态，不调用 git。"""

from __future__ import annotations

from braid.core.git import DiffLine, FileChange, GitSource, GitStatus

BIG_FILE = "src/data/fixtures.json"
BIG_LINES = 520


def _hunk(old: int, new: int, body: list[tuple[str, str]]) -> list[DiffLine]:
    """按 (kind, text) 序列生成一个 hunk，自动编旧/新行号并补 ``@@`` 头。"""
    n_old = sum(k != "add" for k, _ in body)
    n_new = sum(k != "del" for k, _ in body)
    out = [DiffLine("hunk", None, None, f"@@ -{old},{n_old} +{new},{n_new} @@")]
    o, n = old, new
    for kind, text in body:
        if kind == "ctx":
            out.append(DiffLine("ctx", o, n, text))
            o, n = o + 1, n + 1
        elif kind == "del":
            out.append(DiffLine("del", o, None, text))
            o += 1
        else:
            out.append(DiffLine("add", None, n, text))
            n += 1
    return out


def _whole(kind: str, lines: list[str]) -> list[DiffLine]:
    """新增/删除整个文件。"""
    n = len(lines)
    head = f"@@ -0,0 +1,{n} @@" if kind == "add" else f"@@ -1,{n} +0,0 @@"
    out = [DiffLine("hunk", None, None, head)]
    for i, t in enumerate(lines, 1):
        out.append(DiffLine("add", None, i, t) if kind == "add" else DiffLine("del", i, None, t))
    return out


_DIFFS: dict[str, list[DiffLine]] = {
    "src/pages/login.py": _hunk(
        12,
        12,
        [
            ("ctx", "from braid.widgets import LinkLabel"),
            ("add", "from braid.pages.forgot import ForgotPage"),
            ("ctx", ""),
        ],
    )
    + _hunk(
        41,
        42,
        [
            ("ctx", "self.err = QLabel()"),
            ("del", 'self.err.setStyleSheet("color:gray")'),
            ("add", 'self.err.setProperty("role", "error")'),
            ("add", 'self.forgot = LinkLabel("忘记密码")'),
            ("add", "self.forgot.clicked.connect(self.on_forgot)"),
            ("ctx", "layout.addWidget(self.err)"),
        ],
    ),
    "src/styles/login.qss": _hunk(
        3,
        3,
        [
            ("ctx", "#LoginCard {"),
            ("del", "    border-radius: 8px;"),
            ("add", "    border-radius: 14px;"),
            ("ctx", "}"),
        ],
    ),
    "src/pages/forgot.py": _whole(
        "add",
        [
            '"""忘记密码页。"""',
            "",
            "class ForgotPage(QWidget):",
            "    def __init__(self) -> None:",
            "        super().__init__()",
        ],
    ),
    "src/old_auth.py": _whole(
        "del",
        [
            "import hashlib",
            "",
            "def check(user, pwd):",
            "    h = hashlib.md5(pwd.encode()).hexdigest()",
            "    return USERS.get(user) == h",
        ],
    ),
    BIG_FILE: _whole(
        "add",
        ["["]
        + [f'  {{"id": {i}, "name": "user{i}", "active": true}},' for i in range(BIG_LINES - 2)]
        + ["]"],
    ),
}


def _stat(fc: FileChange) -> FileChange:
    lines = _DIFFS.get(fc.path, [])
    add = sum(ln.kind == "add" for ln in lines)
    rem = sum(ln.kind == "del" for ln in lines)
    return FileChange(fc.path, fc.status, add, rem)


class MockGitSource(GitSource):
    """只读示例仓库。"""

    def __init__(self) -> None:
        super().__init__()
        self.branch = "feat/login"
        self.files = [
            FileChange("src/pages/forgot.py", "A"),
            FileChange("src/pages/login.py", "M"),
            FileChange("src/styles/login.qss", "M"),
            FileChange("src/old_auth.py", "D"),
            FileChange(BIG_FILE, "A"),
        ]

    def status(self) -> GitStatus:
        return GitStatus(self.branch, [_stat(f) for f in self.files])

    def diff(self, path: str) -> list[DiffLine]:
        return list(_DIFFS.get(path, []))
