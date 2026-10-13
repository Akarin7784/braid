from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QStyleOptionViewItem

from braid.ui.chat_view import ChatView


def _hint(v: ChatView, row: int, width: int = 800) -> int:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, width, 100)
    return v.delegate.sizeHint(opt, v.chat_model.index(row, 0)).height()


def _view(qtbot) -> ChatView:  # type: ignore[no-untyped-def]
    v = ChatView()
    qtbot.addWidget(v)
    v.set_dark(False)
    v.chat_model.set_messages([("assistant", "第一段\n\n" + "很长的一段文字 " * 60)])
    return v


def test_finished_row_height_cache_hit(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = _view(qtbot)
    h1 = _hint(v, 0)
    hits = v.delegate.height_hits
    assert _hint(v, 0) == h1
    assert v.delegate.height_hits == hits + 1


def test_cache_invalidates_on_width_change(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = _view(qtbot)
    wide = _hint(v, 0, 800)
    hits = v.delegate.height_hits
    narrow = _hint(v, 0, 400)
    assert v.delegate.height_hits == hits
    assert narrow > wide


def test_cache_invalidates_on_dark_toggle(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = _view(qtbot)
    _hint(v, 0)
    hits = v.delegate.height_hits
    v.set_dark(True)
    _hint(v, 0)
    assert v.delegate.height_hits == hits
    _hint(v, 0)
    assert v.delegate.height_hits == hits + 1


def test_cache_invalidates_on_text_change(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = _view(qtbot)
    h1 = _hint(v, 0)
    v.chat_model.items[0].variants[0] += "\n\n" + "追加 " * 200
    hits = v.delegate.height_hits
    assert _hint(v, 0) > h1
    assert v.delegate.height_hits == hits


def test_streaming_row_not_cached(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = _view(qtbot)
    row = v.chat_model.append("assistant", "流式中", streaming=True)
    _hint(v, row)
    hits = v.delegate.height_hits
    _hint(v, row)
    assert v.delegate.height_hits == hits
    assert id(v.chat_model.items[row]) not in v.delegate._heights
