"""打包自检逻辑与 spec 里的 keyring/WebEngine 断言。"""

from pathlib import Path

import pytest

from braid import selfcheck

ROOT = Path(__file__).resolve().parents[1]


def _backend(qual: str) -> object:
    mod, _, name = qual.rpartition(".")
    return type(name, (), {"__module__": mod})()


@pytest.mark.parametrize(
    ("platform", "backend", "ok"),
    [
        ("darwin", "keyring.backends.macOS.Keyring", True),
        ("win32", "keyring.backends.Windows.WinVaultKeyring", True),
        ("darwin", "keyring.backends.fail.Keyring", False),
        ("win32", "keyring.backends.fail.Keyring", False),
        ("win32", "keyring.backends.null.Keyring", False),
        ("darwin", "keyring.backends.chainer.ChainerBackend", False),
        ("win32", "keyring.backends.macOS.Keyring", False),
    ],
)
def test_keyring_backend_must_match_exactly(platform: str, backend: str, ok: bool) -> None:
    res = selfcheck.check_keyring(platform, get_keyring=lambda: _backend(backend))
    assert res["ok"] is ok, res
    assert res["backend"] == backend


def test_keyring_get_keyring_raising_is_failure() -> None:
    def boom() -> object:
        raise RuntimeError("no backend")

    res = selfcheck.check_keyring("darwin", get_keyring=boom)
    assert res["ok"] is False and "RuntimeError" in res["error"]


def test_linux_only_needs_secretservice_module() -> None:
    seen: list[str] = []
    res = selfcheck.check_keyring("linux", import_module=lambda m: seen.append(m))
    assert res["ok"] is True and seen == ["keyring", "keyring.backends.SecretService"]

    def missing(m: str) -> object:
        if m == "keyring.backends.SecretService":
            raise ImportError(m)
        return None

    assert selfcheck.check_keyring("linux", import_module=missing)["ok"] is False


def test_webengine_files(tmp_path: Path) -> None:
    assert selfcheck.check_webengine_files(tmp_path, "linux")["ok"] is False
    (tmp_path / "libexec").mkdir()
    (tmp_path / "libexec" / "QtWebEngineProcess").touch()
    res_dir = tmp_path / "resources"
    res_dir.mkdir()
    (res_dir / "qtwebengine_resources.pak").touch()
    (tmp_path / "qtwebengine_locales").mkdir()
    (tmp_path / "qtwebengine_locales" / "zh-CN.pak").touch()
    assert selfcheck.check_webengine_files(tmp_path, "linux")["ok"] is True
    assert selfcheck.check_webengine_files(tmp_path, "win32")["process"] is False


def test_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAID_SELF_CHECK", raising=False)
    assert selfcheck.requested(["braid", "--self-check"])
    assert not selfcheck.requested(["braid"])
    monkeypatch.setenv("BRAID_SELF_CHECK", "1")
    assert selfcheck.requested(["braid"])


def test_spec_declares_keyring_and_webengine() -> None:
    spec = (ROOT / "packaging" / "braid.spec").read_text(encoding="utf-8")
    assert 'collect_submodules("keyring.backends")' in spec
    assert 'copy_metadata("keyring")' in spec
    for m in ("macOS", "Windows", "SecretService", "kwallet", "chainer", "fail", "null"):
        assert f'"keyring.backends.{m}"' in spec, m
    for m in (
        "jaraco.classes",
        "jaraco.functools",
        "jaraco.context",
        "secretstorage",
        "jeepney",
        "win32ctypes",
        "PySide6.QtWebEngineWidgets",
        "braid.selfcheck",
    ):
        assert m in spec, m
    assert "hiddenimports=hiddenimports" in spec
