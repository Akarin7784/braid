"""打包冷启动测量：``braid --startup-time [输出文件]`` 或 ``BRAID_STARTUP_TIME=<输出文件|1>``。

从入口脚本最早记下的时间点（``T0``）到主窗口第一次 Paint，记录毫秒数并退出。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

# 打包入口会覆盖；直接 python -m 运行时退化为导入本模块的时间
T0: float = time.perf_counter()

FLAG = "--startup-time"
ENV = "BRAID_STARTUP_TIME"


def parse(argv: list[str], environ: dict[str, str] | None = None) -> tuple[bool, str | None]:
    """返回 (是否启用, 输出文件)。"""
    env = os.environ if environ is None else environ
    if FLAG in argv:
        i = argv.index(FLAG)
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        return True, nxt if nxt and not nxt.startswith("-") else None
    val = env.get(ENV)
    if val:
        return True, None if val == "1" else val
    return False, None


def report(t0: float, t_app: float, t_shown: float, t_paint: float) -> dict[str, Any]:
    ms = lambda t: round((t - t0) * 1000, 1)  # noqa: E731
    return {
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "qapp_ms": ms(t_app),
        "shown_ms": ms(t_shown),
        "first_paint_ms": ms(t_paint),
    }


def write(data: dict[str, Any], out: str | None) -> str:
    text = json.dumps(data, ensure_ascii=False)
    print(text, flush=True)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    return text


class _FirstPaint(QObject):
    def __init__(self, on_paint: Any) -> None:
        super().__init__()
        self._cb = on_paint
        self._done = False

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        if not self._done and ev.type() == QEvent.Type.Paint:
            self._done = True
            self._cb()
        return False


def install(app: QApplication, window: QWidget, t_app: float, out: str | None) -> None:
    """在 window.show() 之前调用；第一次 Paint 后写结果并退出。"""
    marks: dict[str, float] = {}

    def on_paint() -> None:
        marks["paint"] = time.perf_counter()
        QTimer.singleShot(0, finish)

    def finish() -> None:
        guard.stop()
        write(report(T0, t_app, marks.get("shown", marks["paint"]), marks["paint"]), out)
        app.quit()

    flt = _FirstPaint(on_paint)
    flt.setParent(window)
    window.installEventFilter(flt)
    window._startup_mark = lambda: marks.setdefault("shown", time.perf_counter())  # type: ignore[attr-defined]
    # 30 秒没画出来也退出，避免 CI 卡住；挂在窗口上，窗口销毁即作废
    guard = QTimer(flt)
    guard.setSingleShot(True)
    guard.timeout.connect(lambda: (write({"error": "30s 内没有 Paint"}, out), app.exit(2)))
    guard.start(30000)
