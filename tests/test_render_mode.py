from braid.ui.chat_view import ChatModel, _DocCache


def test_streaming_row_is_plain_then_finalized(qtbot):
    m = ChatModel()
    row = m.append("assistant", "", streaming=True)
    assert m.items[row].render_mode == "plain"
    m.append_text(row, "**粗体**")
    assert m.items[row].render_mode == "plain"
    m.finish(row)
    assert m.items[row].render_mode == "markdown"


def test_finalize_idempotent_and_emits_once(qtbot):
    m = ChatModel()
    row = m.append("assistant", "x", streaming=True)
    seen: list[int] = []
    m.dataChanged.connect(lambda a, b: seen.append(a.row()))
    m.finalize(row)
    m.finalize(row)
    assert seen == [row]


def test_plain_mode_skips_markdown(qtbot):
    c = _DocCache()
    assert "**" in c.get("**a**", 300, False, "plain").toPlainText()
    assert "**" not in c.get("**a**", 300, False, "markdown").toPlainText()
