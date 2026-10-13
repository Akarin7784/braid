import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Windows 上 offscreen 平台用 FreeType 字体库，只扫描 QT_QPA_FONTDIR（默认是 Qt 安装目录
# 下的 lib/fonts，PySide6 的 wheel 里没有），字体库几乎为空，任何字体都解析不到。
# 测试时指向系统字体目录，让 offscreen 和真实 windows 平台看到同一批字体。
if (
    sys.platform == "win32"
    and os.environ["QT_QPA_PLATFORM"].startswith("offscreen")
    and "QT_QPA_FONTDIR" not in os.environ
):
    _fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if _fonts.is_dir():
        os.environ["QT_QPA_FONTDIR"] = str(_fonts)

import braid  # noqa: E402

_SRC = (Path(__file__).resolve().parent.parent / "src").resolve()
_PKG = Path(braid.__file__).resolve().parent
assert _PKG.is_relative_to(_SRC), (
    f"导入的 braid 来自 {_PKG}，不是当前 worktree 的 {_SRC}。"
    "借用别人的 venv 时请加 PYTHONPATH=src。"
)

import pytest  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring(tmp_path, monkeypatch):
    import keyring

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path / "config"))
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    from braid.core import secrets

    secrets._memory.clear()
    yield kr
