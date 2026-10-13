import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import braid  # noqa: E402

_SRC = (Path(__file__).resolve().parent.parent / "src").resolve()
_PKG = Path(braid.__file__).resolve().parent
assert _PKG.is_relative_to(_SRC), (
    f"导入的 braid 来自 {_PKG}，不是当前 worktree 的 {_SRC}。"
    "借用别人的 venv 时请加 PYTHONPATH=src。"
)
