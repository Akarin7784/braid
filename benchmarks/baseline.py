# ruff: noqa: E501  (子进程脚本是单个字符串，一步一行更好读)
"""发布前性能基线。

用法: python benchmarks/baseline.py [-n 7] [--platforms offscreen,xvfb] [--json out.json]

每次测量都新开子进程（冷启动），汇总中位数与 p95（ms / MB）。测量项：

- 冷启动：父进程 spawn → 主窗口 show() 返回、→ 首次 Paint 事件
- import braid（主窗口 + Mock 后端）耗时
- 打开设置页耗时，以及 8 个分区页各自首次显示耗时（show_section + 事件处理 + 同步重绘）
- 空闲 RSS：启动后静置 500ms、访问完全部设置分区后
- 主题切换：经 backend.set_config("general", theme) 走产品真实路径，含同步重绘

另外用 ``python -X importtime`` 统计导入耗时最大的模块（累计 / 自身）。
xvfb 平台需要 xvfb-run；不可用时自动跳过。所有文件读写都用 UTF-8。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r"""
import json, os, sys, time
T_SPAWN = float(os.environ["BASELINE_SPAWN"])
res = {}
t = time.perf_counter()
from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication
res["import_pyside_ms"] = (time.perf_counter() - t) * 1000
t = time.perf_counter()
from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.ui.main_window import MainWindow
res["import_braid_ms"] = (time.perf_counter() - t) * 1000
import psutil
proc = psutil.Process()

def rss():
    return proc.memory_info().rss / 1e6

class PaintWaiter(QObject):
    # 等目标控件的下一次 Paint 事件；超时计时器属于本对象
    def __init__(self, target, timeout_ms=3000):
        super().__init__(target)
        self.target, self.hit = target, None
        self.loop = QEventLoop(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.loop.quit)
        self.timeout_ms = timeout_ms
        target.installEventFilter(self)
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Paint and self.hit is None:
            self.hit = time.time()
            QTimer.singleShot(0, self, self.loop.quit)
        return False
    def wait(self):
        if self.hit is None:
            self.timer.start(self.timeout_ms)
            self.loop.exec()
        self.target.removeEventFilter(self)
        return self.hit

def settle(owner, ms):
    loop = QEventLoop(owner)
    QTimer.singleShot(ms, owner, loop.quit)
    loop.exec()

app = QApplication([])
app.setProperty("braidDark", False)
app.setStyleSheet(load_qss("light"))
backend = MockBackend()
backend.set_config("general", {"theme": "light"})
w = MainWindow(backend)
w.chat_view.set_dark(False)
w.resize(1280, 800)
waiter = PaintWaiter(w)
w.show()
res["spawn_to_shown_ms"] = (time.time() - T_SPAWN) * 1000
hit = waiter.wait()
res["spawn_to_first_paint_ms"] = ((hit or time.time()) - T_SPAWN) * 1000
res["first_paint_timeout"] = hit is None
settle(w, 500)
res["rss_idle_startup_mb"] = rss()

# 设置页
t = time.perf_counter()
w.show_settings(True)
app.processEvents()
w.repaint()
res["settings_open_ms"] = (time.perf_counter() - t) * 1000
sp = w.settings_page
from braid.ui.settings.pages import NAV
for key, _label in NAV:
    t = time.perf_counter()
    sp.show_section(key)
    app.processEvents()
    sp.stack.currentWidget().repaint()
    res[f"section_{key}_ms"] = (time.perf_counter() - t) * 1000
settle(w, 500)
res["rss_after_settings_mb"] = rss()

# 主题切换（真实路径：config_changed → apply_theme + chat_view.set_dark），各 3 次取均值
w.show_settings(False)
app.processEvents()
settle(w, 200)  # 让 deleteLater 等延迟事件真正执行（与真实事件循环一致）
res["rss_after_leave_settings_mb"] = rss()
ld, dl = [], []
for _ in range(3):
    t = time.perf_counter(); backend.set_config("general", {"theme": "dark"}); app.processEvents(); w.repaint(); ld.append((time.perf_counter() - t) * 1000)
    t = time.perf_counter(); backend.set_config("general", {"theme": "light"}); app.processEvents(); w.repaint(); dl.append((time.perf_counter() - t) * 1000)
res["theme_to_dark_ms"] = sum(ld) / len(ld)
res["theme_to_light_ms"] = sum(dl) / len(dl)
print("JSON" + json.dumps(res))
"""

IMPORT_TARGET = "import braid.ui.main_window, braid.backends.mock"


def _env(platform_name: str, cfg_dir: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "BRAID_CONFIG_DIR": cfg_dir}
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen" if platform_name == "offscreen" else "xcb"
    env.pop("QT_SCALE_FACTOR", None)
    return env


def run_once(platform_name: str) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as cfg:
        env = _env(platform_name, cfg)
        cmd = [sys.executable, "-c", CHILD]
        if platform_name == "xvfb":
            cmd = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", *cmd]
        env["BASELINE_SPAWN"] = repr(time.time())
        out = subprocess.run(
            cmd, env=env, capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
    return json.loads(out.split("JSON", 1)[1])


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(runs: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = [
        k for k, v in runs[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    return {
        k: {
            "median": statistics.median(r[k] for r in runs),
            "p95": pct([r[k] for r in runs], 0.95),
            "min": min(r[k] for r in runs),
            "max": max(r[k] for r in runs),
        }
        for k in keys
    }


def importtime(n: int = 3) -> list[tuple[str, float, float]]:
    """返回 [(模块, 累计 ms, 自身 ms)]，取 n 次中位数，按累计排序。"""
    acc: dict[str, list[tuple[float, float]]] = {}
    env = _env("offscreen", tempfile.gettempdir())
    for _ in range(n):
        err = subprocess.run(
            [sys.executable, "-X", "importtime", "-c", IMPORT_TARGET],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stderr
        for line in err.splitlines():
            if not line.startswith("import time:") or "self [us]" in line:
                continue
            parts = line[len("import time:") :].split("|")
            self_us, cum_us, name = int(parts[0]), int(parts[1]), parts[2].strip()
            acc.setdefault(name, []).append((cum_us / 1000, self_us / 1000))
    rows = [
        (name, statistics.median(c for c, _ in v), statistics.median(s for _, s in v))
        for name, v in acc.items()
    ]
    return sorted(rows, key=lambda r: -r[1])


def machine_info() -> dict[str, str]:
    info = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": str(os.cpu_count()),
    }
    try:
        import PySide6

        info["pyside6"] = PySide6.__version__
    except ImportError:
        pass
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                info["cpu"] = line.split(":", 1)[1].strip()
                break
        mem = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()[0]
        info["mem_total"] = f"{int(mem.split()[1]) / 1024 / 1024:.1f} GiB"
    except OSError:
        pass
    with contextlib.suppress(OSError, subprocess.CalledProcessError):
        info["git"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=7)
    ap.add_argument("--platforms", default="offscreen,xvfb")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    result: dict[str, object] = {"machine": machine_info(), "n": args.n, "platforms": {}}
    for plat in args.platforms.split(","):
        if plat == "xvfb" and not shutil.which("xvfb-run"):
            print("跳过 xvfb：没有 xvfb-run")
            continue
        run_once(plat)  # 预热一次（磁盘缓存 / .pyc），不计入
        runs = [run_once(plat) for _ in range(args.n)]
        summary = summarize(runs)
        result["platforms"][plat] = summary  # type: ignore[index]
        print(f"\n== {plat}（n={args.n}，中位数 / p95）")
        for k, v in summary.items():
            print(f"  {k:32s} {v['median']:9.1f} {v['p95']:9.1f}")
    rows = importtime()
    result["importtime_top"] = rows[:25]
    print("\n== -X importtime（累计 ms / 自身 ms，前 15）")
    for name, cum, self_ms in rows[:15]:
        print(f"  {cum:8.1f} {self_ms:8.1f}  {name}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
