import sys
import time

from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.theme.fonts import apply_app_font
from braid.ui.main_window import MainWindow
from braid.ui.tray import Tray


def _qss(theme: str) -> str:
    return load_qss(theme)


def main() -> int:
    from braid import selfcheck

    if selfcheck.requested(sys.argv):
        return selfcheck.run(sys.argv)
    from braid import startup

    timing, timing_out = startup.parse(sys.argv)
    app = QApplication(sys.argv)
    t_app = time.perf_counter()
    apply_app_font(app)
    theme = "dark" if "--dark" in sys.argv else "light"
    app.setProperty("braidDark", theme == "dark")
    app.setStyleSheet(_qss(theme))
    backend = MockBackend()
    backend.set_config("general", {"theme": theme})
    w = MainWindow(backend)
    w.chat_view.set_dark(theme == "dark")
    if timing:
        startup.install(app, w, t_app, timing_out)
    w.show()
    if timing:
        w._startup_mark()  # type: ignore[attr-defined]
    tray = Tray(w)
    tray.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
