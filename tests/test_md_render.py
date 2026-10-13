from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QTextFormat, QTextTable

from braid.ui import chat_view
from braid.ui.chat_view import ChatView, _DocCache, parse_code_fences

LONG = "看代码：\n\n```python\n" + "\n".join(f"x{i} = {i}" for i in range(30)) + "\n```\n"


def _tables(doc):
    return [f for f in doc.rootFrame().childFrames() if isinstance(f, QTextTable)]


def test_table_styled(qtbot):
    doc = _DocCache().get("| a | b |\n|---|---|\n| 1 | 2 |\n", 400, False)
    (t,) = _tables(doc)
    assert t.format().border() == 0
    assert t.format().cellPadding() >= 4
    assert t.cellAt(0, 0).format().background().style() != 0


def test_blockquote_text2_no_border(qtbot):
    doc = _DocCache().get("> 引用内容\n", 400, True)
    b = doc.begin()
    while b.isValid() and not b.blockFormat().hasProperty(QTextFormat.Property.BlockQuoteLevel):
        b = b.next()
    assert b.isValid()
    assert b.blockFormat().leftMargin() > 0
    color = b.begin().fragment().charFormat().foreground().color().name().upper()
    assert color == chat_view.THEME[True]["text2"].upper()


def test_inline_code_bg(qtbot):
    doc = _DocCache().get("用 `foo()` 调用\n", 400, False)
    it = doc.begin().begin()
    found = False
    while not it.atEnd():
        f = it.fragment()
        if f.text() == "foo()":
            found = f.charFormat().background().style() != 0
        it += 1
    assert found


def test_collapse_and_toggle(qtbot):
    v = ChatView()
    qtbot.addWidget(v)
    v.resize(700, 900)
    v.chat_model.set_messages([("assistant", LONG)])
    v.show()
    d = v.delegate
    item = v.chat_model.items[0]
    doc = d._doc(item, 600)
    (info,) = d.cache.code_blocks(doc)
    assert info.collapsed and info.total_lines == 30
    assert "x25" not in doc.toPlainText()
    h0 = doc.size().height()
    v.trigger(0, "code_toggle:0")
    doc2 = d._doc(item, 600)
    assert "x25" in doc2.toPlainText() and doc2.size().height() > h0
    v.trigger(0, "code_toggle:0")
    assert "x25" not in d._doc(item, 600).toPlainText()


def test_code_copy_via_hit(qtbot):
    v = ChatView()
    qtbot.addWidget(v)
    v.resize(700, 900)
    v.chat_model.set_messages([("assistant", "a\n\n```\nprint(1)\n```\n\n```\nsecond()\n```\n")])
    v.show()
    qtbot.waitExposed(v)
    item = v.chat_model.items[0]
    rect = v.visualRect(v.chat_model.index(0))
    col = v.delegate._column(rect.adjusted(0, chat_view.PAD // 2, 0, 0))
    doc = v.delegate._doc(item, max(80, v.delegate._text_width(item, col.width())))
    codes = v.delegate._code_rects(item, v.delegate._bubble_rect(item, col, doc), doc)
    assert len(codes) == 2
    action = v.delegate.hit(rect, item, codes[1][2].center())
    assert action == "code_copy:1"
    v.trigger(0, action)
    assert QGuiApplication.clipboard().text() == "second()"


def test_parse_fences():
    assert [c for _s, _e, c in parse_code_fences("```\na\nb\n```\nx\n~~~\nc\n~~~")] == ["a\nb", "c"]


def test_user_bubble_paints_shadow(qtbot, monkeypatch):
    calls: list[tuple[str, bool]] = []

    class Fake:
        def paint(self, p, r):
            calls.append(("paint", isinstance(r, QRect)))

    monkeypatch.setattr(
        chat_view.NineSliceShadow,
        "get",
        staticmethod(lambda lv, dk: calls.append((lv, dk)) or Fake()),
    )
    v = ChatView()
    qtbot.addWidget(v)
    v.resize(600, 400)
    v.chat_model.set_messages([("user", "你好"), ("assistant", "回答")])
    v.show()
    img = QImage(600, 400, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    v.render(p, QPoint())
    p.end()
    assert ("e2", False) in calls and ("paint", True) in calls
    assert calls.count(("e2", False)) == 1  # 只给用户气泡画
