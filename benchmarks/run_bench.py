"""性能基准：滚动帧耗时、流式吞吐、空闲内存。

用法: python benchmarks/run_bench.py --out bench.json [--baseline base.json] [--tolerance 0.2]
对比基线时，任一指标变差超过容差会打印警告；加 --strict 时以非零退出码失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

# 指标名 -> 越小越好(True) / 越大越好(False)
LOWER_IS_BETTER = {
    "scroll_ms_per_frame": True,
    "stream_chars_per_s": False,
    "idle_rss_mb": True,
    "buffered_stream_chars_per_s": False,
    "buffered_frame_ms_avg": True,
    "multipara_stream_chars_per_s": False,
    "multipara_frame_ms_avg": True,
    "multipara_frame_ms_p95": True,
}


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except ImportError:
        import resource

        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1e6 if sys.platform == "darwin" else r / 1e3


def bench_scroll(app: QApplication) -> float:
    from braid.ui.chat_view import ChatView

    v = ChatView()
    v.resize(900, 700)
    v.show()
    code = "```python\nfor i in range(10):\n    print(i)\n```"
    v.chat_model.set_messages([("assistant", f"消息 {i}\n\n{code}") for i in range(1000)])
    app.processEvents()
    sb = v.verticalScrollBar()
    steps = 120
    t0 = time.perf_counter()
    for i in range(steps):
        sb.setValue(sb.maximum() * i // steps)
        v.viewport().repaint()
    ms = (time.perf_counter() - t0) / steps * 1000
    v.close()
    return ms


def bench_stream(app: QApplication) -> float:
    from braid.ui.chat_view import ChatView

    v = ChatView()
    v.resize(900, 700)
    v.show()
    m = v.chat_model
    m.set_messages([("user", f"历史 {i}") for i in range(200)])
    row = m.append("assistant", "", streaming=True)
    chunk = "流式输出的一段文本 `code` "
    n = 500
    t0 = time.perf_counter()
    for i in range(n):
        m.append_text(row, chunk)
        if i % 10 == 0:
            app.processEvents()
    m.finish(row)
    m.finalize(row)
    app.processEvents()
    rate = n * len(chunk) / (time.perf_counter() - t0)
    v.close()
    return rate


def bench_stream_buffered(
    app: QApplication, prefix: str = "buffered", para_every: int = 0
) -> dict[str, float]:
    """模拟后端逐 token 推送，经 ChatView.stream 节流后写入模型；统计吞吐、模型更新次数与帧耗时。"""
    from braid.ui.chat_view import ChatView

    v = ChatView()
    v.resize(900, 700)
    v.show()
    m = v.chat_model
    m.set_messages([("user", f"历史 {i}") for i in range(200)])
    row = m.append("assistant", "", streaming=True)
    updates = [0]
    m.dataChanged.connect(lambda *_: updates.__setitem__(0, updates[0] + 1))
    token = "流式"
    n = 3000
    frames: list[float] = []
    v.stream.start(row)
    t0 = time.perf_counter()
    sent = 0
    for i in range(n):
        tok = token + "\n" if para_every and i % para_every == para_every - 1 else token
        sent += len(tok)
        v.stream.push(tok)
        if i % 8 == 7:  # 与 ChatController 每轮取 8 块一致
            f0 = time.perf_counter()
            app.processEvents()
            v.viewport().repaint()
            frames.append((time.perf_counter() - f0) * 1000)
            time.sleep(0.001)
    v.stream.stop()
    app.processEvents()
    dt = time.perf_counter() - t0
    v.close()
    frames.sort()
    return {
        f"{prefix}_stream_chars_per_s": sent / dt,
        f"{prefix}_stream_updates": float(updates[0]),
        f"{prefix}_frame_ms_avg": sum(frames) / len(frames),
        f"{prefix}_frame_ms_p95": frames[int(len(frames) * 0.95)],
    }


def bench_stream_multipara(app: QApplication) -> dict[str, float]:
    """多段落流式：每 40 块插入换行（约 6000 字、75 段），增量排版只需重排末段。"""
    return bench_stream_buffered(app, prefix="multipara", para_every=40)


def bench_idle_mem(app: QApplication) -> float:
    from braid.ui import main_window

    cls = next(
        v for k, v in vars(main_window).items() if isinstance(v, type) and k.endswith("Window")
    )
    try:
        w = cls()
    except TypeError:
        from braid.backends.mock import MockBackend

        w = cls(MockBackend())
    w.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    return _rss_mb()


def compare(cur: dict, base: dict, tol: float) -> list[str]:
    bad = []
    for k, lower in LOWER_IS_BETTER.items():
        if k not in base or not base[k]:
            continue
        ratio = cur[k] / base[k]
        worse = ratio > 1 + tol if lower else ratio < 1 - tol
        if worse:
            bad.append(f"{k}: {base[k]:.2f} -> {cur[k]:.2f} ({(ratio - 1) * 100:+.0f}%)")
    return bad


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="bench.json")
    p.add_argument("--baseline")
    p.add_argument("--tolerance", type=float, default=0.2)
    p.add_argument("--strict", action="store_true")
    a = p.parse_args()
    app = QApplication.instance() or QApplication([])
    res = {
        "idle_rss_mb": bench_idle_mem(app),
        "scroll_ms_per_frame": bench_scroll(app),
        "stream_chars_per_s": bench_stream(app),
        **bench_stream_buffered(app),
        **bench_stream_multipara(app),
        "platform": sys.platform,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
    if a.baseline and os.path.exists(a.baseline):
        with open(a.baseline, encoding="utf-8") as f:
            bad = compare(res, json.load(f), a.tolerance)
        for b in bad:
            print(f"::warning title=性能回退::{b}")
        if bad and a.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
