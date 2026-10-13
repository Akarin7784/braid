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
