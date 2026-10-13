"""截设置页“MCP 服务”：mcp_{light,dark}.png（1280×800）。

用法: python benchmarks/shots_mcp.py [输出目录]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.ui.main_window import MainWindow
from braid.ui.settings_page import SettingsPage


def settle(app: QApplication, ms: int = 300) -> None:
    QTimer.singleShot(ms, app.quit)
    app.exec()


OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")


def main() -> int:
    app = QApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        app.setProperty("braidDark", theme == "dark")
        app.setStyleSheet(load_qss(theme))
        w = MainWindow(MockBackend())
        w.chat_view.set_dark(theme == "dark")
        w.resize(1280, 800)
        w.show()
        settle(app)
        w.show_settings(True)
        sp = w.settings_page
        assert isinstance(sp, SettingsPage)
        sp.show_section("mcp")
        settle(app)
        w.grab().save(str(OUT / f"mcp_{theme}.png"))
        w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
