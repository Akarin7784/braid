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
    app.setStyleSheet(_qss(theme))
    w = MainWindow(MockBackend())
    w.show()
    tray = Tray(w)
    tray.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
