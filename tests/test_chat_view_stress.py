"""消息列表压力测试：1000 条消息、流式只刷新最后一行。"""

import time

from braid.ui.chat_view import ChatView


def _fill(view, n=1000):
    code = "```python\nfor i in range(10):\n    print(i)\n```"
    msgs = [("user" if i % 2 == 0 else "assistant", f"消息 {i}\n\n{code}") for i in range(n)]
    view.chat_model.set_messages(msgs)


def test_1000_messages_scroll(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    t0 = time.perf_counter()
    _fill(view)
    view.scrollToBottom()
    qtbot.wait(10)
    load = time.perf_counter() - t0
    sb = view.verticalScrollBar()
    steps = 60
    t0 = time.perf_counter()
    for i in range(steps):
        sb.setValue(sb.maximum() * i // steps)
        view.viewport().repaint()
    per_frame = (time.perf_counter() - t0) / steps
    print(f"load {load:.3f}s, scroll {per_frame * 1000:.1f}ms/frame")
    assert view.chat_model.rowCount() == 1000
    assert load < 5.0
    assert per_frame < 0.1  # 宽松上限，精确帧率留给基准测试


def test_streaming_only_touches_last_row(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    _fill(view, 200)
    m = view.chat_model
    row = m.append("assistant", "", streaming=True)
    touched = []
    m.dataChanged.connect(lambda a, b, *_: touched.append((a.row(), b.row())))
    resets = []
    m.modelReset.connect(lambda: resets.append(1))
    for ch in "流式输出测试" * 20:
        m.append_text(row, ch)
    m.finish(row)
    assert touched and all(a == b == row for a, b in touched)
    assert not resets
