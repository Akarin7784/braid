"""冷启动基准：新进程里从 import 到主窗口显示，目标不超过 1.5 秒。"""

import os
import subprocess
import sys
import time

import pytest

LIMIT_S = float(os.environ.get("BRAID_STARTUP_LIMIT", "1.5"))

SCRIPT = """
import time
t0 = time.perf_counter()
from PySide6.QtWidgets import QApplication
app = QApplication([])
from braid.ui import main_window
cls = next(v for k, v in vars(main_window).items() if isinstance(v, type) and k.endswith("Window"))
try:
    w = cls()
except TypeError:
    from braid.backends import mock
    from braid.core.backend import AgentBackend
    b = next(v for v in vars(mock).values()
             if isinstance(v, type) and issubclass(v, AgentBackend) and v is not AgentBackend)
    w = cls(b())
w.show()
app.processEvents()
print(time.perf_counter() - t0)
"""


@pytest.mark.benchmark
def test_cold_start_under_limit():
    env = {**os.environ, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    runs = []
    for _ in range(3):
        t0 = time.perf_counter()
        out = subprocess.run(
            [sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, check=True
        )
        runs.append((float(out.stdout.strip().splitlines()[-1]), time.perf_counter() - t0))
    best_inproc = min(r[0] for r in runs)
    best_total = min(r[1] for r in runs)
    print(f"startup: in-process {best_inproc:.3f}s, process total {best_total:.3f}s")
    assert best_total <= LIMIT_S, f"冷启动 {best_total:.2f}s 超过 {LIMIT_S}s"
