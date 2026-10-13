"""--startup-time 参数解析与输出。"""

import json
from pathlib import Path

from braid import startup


def test_parse_flag_and_env() -> None:
    assert startup.parse(["braid"], {}) == (False, None)
    assert startup.parse(["braid", "--startup-time"], {}) == (True, None)
    assert startup.parse(["braid", "--startup-time", "o.txt"], {}) == (True, "o.txt")
    assert startup.parse(["braid", "--startup-time", "--dark"], {}) == (True, None)
    assert startup.parse(["braid"], {"BRAID_STARTUP_TIME": "1"}) == (True, None)
    assert startup.parse(["braid"], {"BRAID_STARTUP_TIME": "x.json"}) == (True, "x.json")


def test_report_and_write(tmp_path: Path) -> None:
    data = startup.report(10.0, 10.1, 10.25, 10.3)
    assert (
        data["qapp_ms"] == 100.0 and data["shown_ms"] == 250.0 and data["first_paint_ms"] == 300.0
    )
    out = tmp_path / "s.txt"
    startup.write(data, str(out))
    assert json.loads(out.read_text(encoding="utf-8"))["first_paint_ms"] == 300.0


def test_first_paint_quits(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    w = QWidget()
    qtbot.addWidget(w)
    out = tmp_path / "s.txt"
    quits: list[int] = []
    app.aboutToQuit.connect(lambda: quits.append(1))
    orig = app.quit
    app.quit = lambda: quits.append(1)  # type: ignore[method-assign]
    try:
        startup.install(app, w, startup.T0, str(out))
        w.show()
        qtbot.waitUntil(out.exists, timeout=5000)
    finally:
        app.quit = orig  # type: ignore[method-assign]
    assert json.loads(out.read_text(encoding="utf-8"))["first_paint_ms"] >= 0
    assert quits
