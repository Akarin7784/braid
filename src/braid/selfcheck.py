"""打包自检：``braid --self-check [输出文件]``。

检查 keyring 后端与 QtWebEngine 是否真的打进了包里，结果以 JSON 打印并写入文件
（Windows/macOS 的包是 console=False，stdout 不一定看得到），失败时退出码非 0。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 各平台必须精确选中的 keyring 后端；不接受 fail/null/chainer
EXPECTED_KEYRING = {
    "darwin": "keyring.backends.macOS.Keyring",
    "win32": "keyring.backends.Windows.WinVaultKeyring",
}
LINUX_KEYRING_MODULE = "keyring.backends.SecretService"


def _qualname(obj: object) -> str:
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


def check_keyring(
    platform: str = sys.platform,
    get_keyring: Callable[[], object] | None = None,
    import_module: Callable[[str], object] = importlib.import_module,
) -> dict[str, Any]:
    res: dict[str, Any] = {"ok": False}
    try:
        import_module("keyring")
        if platform.startswith("linux"):
            # CI 上没有 Secret Service 服务，只能确认模块在包里
            import_module(LINUX_KEYRING_MODULE)
            res.update(ok=True, module=LINUX_KEYRING_MODULE)
            return res
        if get_keyring is None:
            import keyring

            get_keyring = keyring.get_keyring
        name = _qualname(get_keyring())
        expected = EXPECTED_KEYRING.get(platform)
        res.update(backend=name, expected=expected, ok=expected is not None and name == expected)
    except Exception as e:  # noqa: BLE001 — 自检要把任何异常都记成失败
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def bundle_root() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def check_webengine_files(root: Path, platform: str = sys.platform) -> dict[str, Any]:
    """在包目录里找 QtWebEngineProcess、resources 与 locales。"""
    proc = "QtWebEngineProcess.exe" if platform == "win32" else "QtWebEngineProcess"
    found = {
        "process": any(p.name == proc for p in root.rglob(proc)),
        "resources": any(root.rglob("qtwebengine_resources.pak")),
        "locales": any(p.parent.name == "qtwebengine_locales" for p in root.rglob("*.pak")),
    }
    return {"ok": all(found.values()), **found}


def check_webengine_page(timeout_ms: int = 20000) -> dict[str, Any]:
    res: dict[str, Any] = {"ok": False}
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView

        view = QWebEngineView()
        loop = QEventLoop()
        state: dict[str, Any] = {}

        def on_loaded(ok: bool) -> None:
            state["loaded"] = ok
            view.page().runJavaScript("1 + 41", 0, on_js)

        def on_js(val: object) -> None:
            state["js"] = val
            loop.quit()

        view.loadFinished.connect(on_loaded)
        QTimer.singleShot(timeout_ms, loop.quit)
        html = "<html><head><title>braid-selfcheck</title></head><body>ok</body></html>"
        view.setHtml(html, QUrl("about:blank"))
        view.resize(320, 240)
        view.show()
        loop.exec()
        title = view.title()
        res.update(loaded=state.get("loaded"), title=title, js=state.get("js"))
        res["ok"] = (
            state.get("loaded") is True and title == "braid-selfcheck" and state.get("js") == 42
        )
        if "loaded" not in state:
            res["error"] = f"loadFinished 超时（{timeout_ms}ms）"
        view.close()
        view.deleteLater()
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def run(argv: list[str]) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # QtWebEngine 要求在 QApplication 之前设置
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(argv[:1])
    report: dict[str, Any] = {
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    report["keyring"] = check_keyring()
    root = bundle_root()
    if root is not None:
        report["webengine_files"] = check_webengine_files(root)
    report["webengine_page"] = check_webengine_page()
    report["ok"] = all(v["ok"] for v in report.values() if isinstance(v, dict))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text, flush=True)
    i = argv.index("--self-check") if "--self-check" in argv else -1
    out = argv[i + 1] if 0 <= i < len(argv) - 1 else os.environ.get("BRAID_SELF_CHECK_OUT")
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    del app
    return 0 if report["ok"] else 1


def requested(argv: list[str]) -> bool:
    return "--self-check" in argv or os.environ.get("BRAID_SELF_CHECK") == "1"
