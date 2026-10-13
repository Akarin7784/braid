import sys

from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.ui.main_window import MainWindow
from braid.ui.tray import Tray


def _qss(theme: str) -> str:
    return load_qss(theme)


def main() -> int:
    app = QApplication(sys.argv)
    theme = "dark" if "--dark" in sys.argv else "light"
    app.setProperty("braidDark", theme == "dark")
    app.setStyleSheet(_qss(theme))
    backend = MockBackend()
    backend.set_config("general", {"theme": theme})
    w = MainWindow(backend)
    w.chat_view.set_dark(theme == "dark")
    w.show()
    tray = Tray(w)
    tray.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
