"""流式行增量排版：高度/文本与整篇排版一致，绕开 _DocCache，finalize 仍切 Markdown。"""

from __future__ import annotations

from PySide6.QtGui import QTextDocument

from braid.ui.chat_view import ChatView

CHUNKS = [
    "第一段：流式",
    "输出的文本，",
    "很长很长" * 30,
    "\n\n第二段",
    " **加粗** ",
    "\n- 列表项",
    "末尾",
]


def _plain_height(text: str, width: int) -> int:
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setPlainText(text)
    doc.setTextWidth(width)
    return int(doc.size().height())


def _stream(qtbot, chunks: list[str]) -> tuple[ChatView, int]:
    v = ChatView()
    qtbot.addWidget(v)
    v.resize(900, 600)
    v.show()
    m = v.chat_model
    m.set_messages([("user", "你好")])
    row = m.append("assistant", "", streaming=True)
    v.stream.start(row)
    for c in chunks:
        v.stream.push(c)
        v.stream.flush()
        qtbot.wait(1)
    return v, row


def test_incremental_matches_full_layout(qtbot):
    v, row = _stream(qtbot, CHUNKS)
    item = v.chat_model.items[row]
    d = v.delegate
    tw = 680
    doc = d._doc(item, tw)
    assert doc.toPlainText() == "".join(CHUNKS)
    assert int(doc.size().height()) == _plain_height("".join(CHUNKS), tw)
    # 同一份文档被复用（增量），没有进 _DocCache
    assert d._doc(item, tw) is doc
    assert all(k[3] != "plain" or k[0] != item.text for k in d.cache._d)
    # 宽度变化后仍与整篇排版一致
    assert int(d._doc(item, 400).size().height()) == _plain_height(item.text, 400)
    v.stream.stop()


def test_non_prefix_change_rebuilds(qtbot):
    v, row = _stream(qtbot, ["abc\n", "def"])
    item = v.chat_model.items[row]
    v.chat_model.new_variant(row, "xyz")
    assert v.delegate._doc(item, 500).toPlainText() == "xyz"
    v.stream.stop()


def test_finalize_switches_to_markdown(qtbot):
    v, row = _stream(qtbot, CHUNKS)
    item = v.chat_model.items[row]
    v.stream.stop()
    assert not item.streaming and item.render_mode == "markdown"
    doc = v.delegate._doc(item, 680)
    assert "**" not in doc.toPlainText()  # Markdown 已渲染
    assert v.delegate._streams == {}  # 结束后释放增量文档
