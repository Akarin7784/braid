# ruff: noqa: E501  (子进程脚本是单个字符串，按阶段一行一项更好读)
"""冷启动分阶段计时：python benchmarks/startup_phases.py [-n 5]。

每次新开进程，输出各阶段中位数（ms）。

注意：首次 show() 约有 55–60ms 的固定开销，来自 Qt 对整个窗口的首次样式套用与布局，
并非右栏页面构建（ArtifactsPage 自身约 2ms）。推迟默认页或改变占位页替换方式只会把这笔
开销在 show() 与 first paint 之间挪动，"TOTAL to first paint" 不变；要降低它，应减少首帧的
控件数量与样式表复杂度。
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys

CHILD = r"""
import json, time
T0 = time.perf_counter()
ph = {}
def mark(name, t):
    ph[name] = ph.get(name, 0.0) + (time.perf_counter() - t) * 1000
t = time.perf_counter()
from PySide6.QtWidgets import QApplication
mark("import PySide6.QtWidgets", t)
t = time.perf_counter()
from braid.ui import main_window as mw
from braid.backends.mock import MockBackend
from braid.theme import load_qss
mark("import braid", t)
t = time.perf_counter(); app = QApplication([]); mark("QApplication()", t)
t = time.perf_counter(); qss = load_qss("light"); mark("QSS load", t)
t = time.perf_counter(); app.setStyleSheet(qss); mark("setStyleSheet", t)
t = time.perf_counter(); app.font(); from PySide6.QtGui import QFontDatabase; QFontDatabase.families(); mark("fonts", t)

def wrap(owner, attr, label):
    obj = getattr(owner, attr)
    owner, attr = obj, "__init__"
    orig = obj.__init__
    def f(*a, **k):
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            mark(label, t)
    setattr(owner, attr, f)
wrap(mw, "SessionStore", "MW: session store")
wrap(mw, "Sidebar", "MW: sidebar (incl. store.load)")
wrap(mw, "ChatView", "MW: chat view")
wrap(mw, "Composer", "MW: composer")
wrap(mw, "ChatController", "MW: chat controller")
wrap(mw, "RightPanel", "MW: right panel [RIGHT PANEL]")
wrap(mw, "WindowControls", "MW: window controls")
t = time.perf_counter(); w = mw.MainWindow(MockBackend()); mark("MainWindow() total", t)
t = time.perf_counter(); w.show(); mark("show()", t)
t = time.perf_counter(); w.grab(); mark("first paint", t)
t = time.perf_counter()
if hasattr(w, "open_initial_session"):
    app.processEvents(); w.open_initial_session()
mark("initial session render (after first paint)", t)
T_SESSION = ph["initial session render (after first paint)"]
t = time.perf_counter(); w.show_settings(True); app.processEvents(); mark("settings page (on demand)", t)
ph["TOTAL to first paint"] = ph.pop("_", 0) + (time.perf_counter() - T0) * 1000 - ph["settings page (on demand)"] - T_SESSION
print("JSON" + json.dumps(ph))
"""


def main() -> None:
    n = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 5
    env = {**os.environ, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    runs: list[dict[str, float]] = []
    for _ in range(n):
        out = subprocess.run(
            [sys.executable, "-c", CHILD],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        runs.append(json.loads(out.split("JSON", 1)[1]))
    med = {k: statistics.median(r[k] for r in runs) for k in runs[0]}
    for k, v in sorted(med.items(), key=lambda kv: -kv[1]):
        print(f"{v:8.1f} ms  {k}")


if __name__ == "__main__":
    main()
