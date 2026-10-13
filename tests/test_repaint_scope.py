from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from braid.ui.chat_view import ChatDelegate, ChatView


@pytest.fixture
def painted(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    rows: list[int] = []
    orig = ChatDelegate.paint

    def spy(
        self: ChatDelegate,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        rows.append(index.row())
        orig(self, painter, option, index)

    monkeypatch.setattr(ChatDelegate, "paint", spy)
    yield rows


def _settle(qtbot) -> None:  # type: ignore[no-untyped-def]
    for _ in range(3):
        qtbot.wait(5)


def _streaming_view(qtbot) -> tuple[ChatView, int]:  # type: ignore[no-untyped-def]
    v = ChatView()
    qtbot.addWidget(v)
    v.set_dark(False)
    v.resize(900, 700)
    v.show()
    qtbot.waitExposed(v)
    m = v.chat_model
    m.set_messages([("user", f"历史 {i}") for i in range(200)])
    row = m.append("assistant", "", streaming=True)
    m.append_text(row, "流式")
    _settle(qtbot)
    m.append_text(row, "流")  # 第一次更新记录行高
    _settle(qtbot)
    return v, row


def test_same_height_update_paints_only_streaming_row(qtbot, painted) -> None:  # type: ignore[no-untyped-def]
    v, row = _streaming_view(qtbot)
    for _ in range(3):
        painted.clear()
        v.chat_model.append_text(row, "式")
        _settle(qtbot)
        assert painted and set(painted) == {row}


def test_height_change_relayouts(qtbot, painted) -> None:  # type: ignore[no-untyped-def]
    v, row = _streaming_view(qtbot)
    idx = v.chat_model.index(row)
    before = v.visualRect(idx).height()
    painted.clear()
    v.chat_model.append_text(row, "\n新的一段")
    _settle(qtbot)
    assert v.visualRect(idx).height() > before
    assert len(set(painted)) > 1  # 高度变化仍整表重排
    sb = v.verticalScrollBar()
    assert sb.value() == sb.maximum()


def test_mid_list_stream_height_change_moves_rows_below(qtbot) -> None:  # type: ignore[no-untyped-def]
    v = ChatView()
    qtbot.addWidget(v)
    v.resize(900, 700)
    v.show()
    m = v.chat_model
    m.set_messages([("user", f"历史 {i}") for i in range(5)])
    m.new_variant(1, "开始", streaming=True)
    m.append_text(1, "x")
    _settle(qtbot)
    y_below = v.visualRect(m.index(2)).y()
    m.append_text(1, "\n第二段\n第三段")
    _settle(qtbot)
    assert v.visualRect(m.index(2)).y() > y_below
