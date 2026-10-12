"""消息列表：流式节流、停止、重试生成新版本、分支切换。"""

from braid.backends.mock import MockBackend
from braid.ui.chat_controller import ChatController
from braid.ui.chat_view import ChatView


def _setup(qtbot):
    be = MockBackend()
    view = ChatView()
    qtbot.addWidget(view)
    ctl = ChatController(be, view, "mock-fast")
    ctl.open_session(be.list_sessions()[0].id)
    return be, view, ctl


def test_stream_throttled_and_finishes(qtbot):
    _, view, ctl = _setup(qtbot)
    changes = []
    view.chat_model.dataChanged.connect(lambda *_: changes.append(1))
    ctl.send("你好")
    qtbot.waitUntil(lambda: not ctl.busy, timeout=3000)
    last = view.chat_model.items[-1]
    assert last.text.endswith("你好") and not last.streaming
    assert len(changes) < len(last.text)  # 50ms 节流：刷新次数少于字符数


def test_stop(qtbot):
    _, view, ctl = _setup(qtbot)
    ctl.send("停一下")
    ctl.stop()
    assert not ctl.busy and not view.chat_model.items[-1].streaming


def test_retry_and_branch_switch(qtbot):
    _, view, ctl = _setup(qtbot)
    ctl.send("q")
    qtbot.waitUntil(lambda: not ctl.busy, timeout=3000)
    row = len(view.chat_model.items) - 1
    view.trigger(row, "retry")
    qtbot.waitUntil(lambda: not ctl.busy, timeout=3000)
    item = view.chat_model.items[row]
    assert len(item.variants) == 2 and item.current == 1
    view.trigger(row, "prev")
    assert item.current == 0
    view.trigger(row, "next")
    assert item.current == 1


def test_edit_emits_text(qtbot):
    _, view, ctl = _setup(qtbot)
    with qtbot.waitSignal(ctl.editRequested) as sig:
        view.trigger(0, "edit")
    assert sig.args == [view.chat_model.items[0].text]
