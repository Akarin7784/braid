from __future__ import annotations

from braid.ui.chat_view import ChatView


def test_chat_view_follows_app_braid_dark(qtbot, qapp) -> None:
    v = ChatView()
    qtbot.addWidget(v)
    old = qapp.property("braidDark")
    try:
        qapp.setProperty("braidDark", True)
        assert v.delegate.dark is True
        qapp.setProperty("braidDark", False)
        assert v.delegate.dark is False
        v.set_dark(True)  # 手动覆盖
        qapp.setProperty("braidDark", False)
        assert v.delegate.dark is True
        v.set_dark(None)  # 恢复跟随
        assert v.delegate.dark is False
    finally:
        qapp.setProperty("braidDark", old)
