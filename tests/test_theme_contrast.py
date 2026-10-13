"""回归测试：消息正文、代码块、用户气泡的文字对比度（防止深色主题黑底黑字再次出现）。

做法：同一条消息分别用"有内容"和"空白占位"各渲染一次，逐像素比较。
有差异的像素就是文字，取其中与原底色对比度最高的那个，要求 >= 4.5:1（WCAG AA）。
"""

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.ui.main_window import MainWindow

MIN_CONTRAST = 4.5
TEXT = "对比度检查 Contrast check 0123456789 abcdefghij"
CASES = {
    "assistant_body": ("assistant", TEXT, "\u3000" * 4),
    "assistant_code": (
        "assistant",
        f"```python\nprint('{TEXT}')\n```",
        "```python\n\u3000\n```",
    ),
    "user_bubble": ("user", TEXT, "\u3000" * 4),
}


def _lum(c: QColor) -> float:
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c.redF()) + 0.7152 * ch(c.greenF()) + 0.0722 * ch(c.blueF())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _render(qtbot, dark: bool, role: str, text: str) -> QImage:
    app = QApplication.instance()
    assert app is not None
    app.setProperty("braidDark", dark)
    app.setStyleSheet(load_qss("dark" if dark else "light"))
    win = MainWindow(MockBackend())
    qtbot.addWidget(win)
    win.chat_view.set_dark(dark)
    win.resize(1200, 700)
    win.show()
    qtbot.waitExposed(win)
    view = win.chat_view
    view.chat_model.set_messages([(role, text)])
    qtbot.wait(50)
    # 视口是透明的，底色由父级画，所以要截整个窗口里视口所在的区域
    vp = view.viewport()
    rect = QRect(vp.mapTo(win, QPoint(0, 0)), vp.size())
    return win.grab(rect).toImage().convertToFormat(QImage.Format.Format_RGB32)


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("case", list(CASES))
def test_text_contrast(qtbot, dark, case):
    role, full, blank = CASES[case]
    a = _render(qtbot, dark, role, full)
    b = _render(qtbot, dark, role, blank)
    h = min(a.height(), b.height())
    best, diff = 0.0, 0
    for y in range(0, h):
        for x in range(0, a.width()):
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            if pa != pb:
                diff += 1
                best = max(best, _contrast(QColor(pa), QColor(pb)))
    assert diff > 50, f"{case}: 没检测到文字像素，渲染方式可能变了"
    assert best >= MIN_CONTRAST, (
        f"{case} ({'深色' if dark else '浅色'}): 文字对比度只有 {best:.2f}:1，"
        f"要求至少 {MIN_CONTRAST}:1"
    )
