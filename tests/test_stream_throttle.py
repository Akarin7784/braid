"""流式输出节流：增量合并、结束时写完、finalize 只调用一次。"""

from __future__ import annotations

from braid.ui.chat_view import THROTTLE_MS, ChatModel, ChatView, StreamBuffer


def _view(qtbot) -> ChatView:
    v = ChatView()
    qtbot.addWidget(v)
    return v


def test_coalescing_reduces_update_count(qtbot):
    v = _view(qtbot)
    m = v.chat_model
    row = m.append("assistant", "", streaming=True)
    updates: list[int] = []
    m.dataChanged.connect(lambda a, b, *_: updates.append(a.row()))
    v.stream.start(row)
    tokens = ["字"] * 200
    for t in tokens:
        v.stream.push(t)
    assert updates == []  # 未到一帧不写模型
    qtbot.waitUntil(lambda: m.items[row].text == "字" * 200, timeout=1000)
    assert 1 <= len(updates) < len(tokens) // 10
    v.stream.stop()


def test_timer_idle_when_nothing_pending(qtbot):
    v = _view(qtbot)
    row = v.chat_model.append("assistant", "", streaming=True)
    v.stream.start(row)
    assert not v.stream._timer.isActive()
    v.stream.push("a")
    assert v.stream._timer.isActive()
    assert v.stream._timer.parent() is v.stream
    qtbot.wait(THROTTLE_MS * 3)
    assert not v.stream._timer.isActive()
    v.stream.stop()


def test_finish_flushes_all_text(qtbot):
    v = _view(qtbot)
    m = v.chat_model
    row = m.append("assistant", "", streaming=True)
    v.stream.start(row)
    chunks = [f"块{i} " for i in range(50)]
    for c in chunks:
        v.stream.push(c)
    v.stream.stop()  # 不等定时器
    it = m.items[row]
    assert it.text == "".join(chunks)
    assert not it.streaming
    assert it.render_mode == "markdown"
    assert not v.stream._timer.isActive()


def test_finalize_called_exactly_once(qtbot, monkeypatch):
    m = ChatModel()
    buf = StreamBuffer(m)
    calls: list[int] = []
    orig = m.finalize
    monkeypatch.setattr(m, "finalize", lambda r: (calls.append(r), orig(r)))
    finish_calls: list[int] = []
    orig_finish = m.finish
    monkeypatch.setattr(m, "finish", lambda r: (finish_calls.append(r), orig_finish(r)))
    row = m.append("assistant", "", streaming=True)
    buf.start(row)
    buf.push("**粗体**")
    buf.stop()
    buf.stop()  # 重复 stop 不会再次 finalize
    assert calls == [row]
    assert finish_calls == [row]
    assert m.items[row].render_mode == "markdown"


def test_finish_alone_does_not_finalize(qtbot):
    m = ChatModel()
    row = m.append("assistant", "x", streaming=True)
    m.finish(row)
    assert m.items[row].render_mode == "plain"
