from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

from braid.backends.mock_git import MockGitSource
from braid.ui.panel import RightPanel
from braid.ui.panel.git import DIFF_FONT_PX, DIFF_LINE_H, ROW_H, GitPage
from braid.ui.panel.tokens import tokens


def _page(qtbot, op_ms=30):
    src = MockGitSource(op_ms=op_ms)
    p = GitPage(src)
    qtbot.addWidget(p)
    return src, p


def test_header_and_groups(qtbot):
    _, p = _page(qtbot)
    assert p.branch_chip.text() == "⎇ feat/login ▾"
    assert p.ahead_behind.text() == "↑1 ↓0"
    titles = [
        w.text()
        for i in range(p.files_layout.count())
        if (w := p.files_layout.itemAt(i).widget()) and w.property("role") == "groupTitle"
    ]
    assert titles == ["暂存（1）", "未暂存（3）"]
    assert [(r.fc.status, r.staged) for r in p.rows] == [
        ("A", True),
        ("M", False),
        ("M", False),
        ("D", False),
    ]
    assert all(r.height() == ROW_H for r in p.rows)


def test_status_letter_colors(qtbot):
    _, p = _page(qtbot)
    t = tokens("light")
    want = {"A": t["success"], "M": t["warning"], "D": t["danger"]}
    for r in p.rows:
        assert want[r.fc.status] in r.letter.styleSheet()


def test_diff_select_and_metrics(qtbot):
    _, p = _page(qtbot)
    assert not p.diff_placeholder.isHidden() and p.diff_scroll.isHidden()
    login = next(r for r in p.rows if r.fc.path == "src/pages/login.py")
    qtbot.mouseClick(login, Qt.MouseButton.LeftButton)
    assert login.property("selected") is True
    assert p.diff_caption.text() == "src/pages/login.py · +3 −1"
    dv = p.diff_view
    assert dv.font().pixelSize() == DIFF_FONT_PX and DIFF_LINE_H == 20
    assert dv.line_rect(2).top() == 40 and dv.line_rect(2).height() == 20
    assert [ln.kind for ln in dv.lines] == ["ctx", "del", "add", "add", "add", "ctx"]


def test_stage_toggle_hover(qtbot):
    src, p = _page(qtbot)
    row = next(r for r in p.rows if r.fc.path == "src/old_auth.py")
    assert row.toggle.isHidden()
    QApplication.sendEvent(row, QEvent(QEvent.Type.HoverEnter))
    assert not row.toggle.isHidden() and row.toggle.text() == "+"
    qtbot.mouseClick(row.toggle, Qt.MouseButton.LeftButton)
    assert [f.path for f in src.status().staged] == ["src/pages/forgot.py", "src/old_auth.py"]
    assert p.commit_btn.text() == "提交 2 个文件"


def test_commit_button_disabled_rules(qtbot):
    src, p = _page(qtbot)
    assert not p.commit_btn.isEnabled()  # 有暂存但信息为空
    p.commit_input.setPlainText("fix")
    assert p.commit_btn.isEnabled()
    src.unstage("src/pages/forgot.py")
    assert p.commit_btn.text() == "提交 0 个文件" and not p.commit_btn.isEnabled()


def test_ctrl_enter_commits(qtbot):
    src, p = _page(qtbot)
    p.commit_input.setFocus()
    qtbot.keyClicks(p.commit_input, "add forgot link")
    qtbot.keyClick(p.commit_input, Qt.Key.Key_Return)  # 普通回车只换行
    assert src.commits == []
    qtbot.keyClick(p.commit_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert src.commits == ["add forgot link"]
    assert p.commit_input.toPlainText() == "" and p.ahead_behind.text() == "↑2 ↓0"
    assert not p.commit_btn.isEnabled()


def test_commit_input_grows_max_6_lines(qtbot):
    _, p = _page(qtbot)
    ci = p.commit_input

    def h(n):
        ci.setPlainText("\n".join("x" for _ in range(n)))
        return ci.height()

    h1, h3, h6, h10 = h(1), h(3), h(6), h(10)
    assert h1 < h3 < h6 == h10


def test_push_busy_then_done(qtbot):
    src, p = _page(qtbot)
    qtbot.mouseClick(p.push_btn, Qt.MouseButton.LeftButton)
    assert not p.push_btn.isEnabled() and p.push_btn.text() != "↑ Push"
    qtbot.waitUntil(lambda: p.push_btn.isEnabled(), timeout=2000)
    assert p.push_btn.text() == "↑ Push" and p.ahead_behind.text() == "↑0 ↓0"


def test_checkout_updates_chip(qtbot):
    src, p = _page(qtbot)
    src.checkout("main")
    assert p.branch_chip.text() == "⎇ main ▾"


def test_panel_git_tab(qtbot):
    panel = RightPanel(git_source=MockGitSource())
    qtbot.addWidget(panel)
    qtbot.mouseClick(panel.tabs[1], Qt.MouseButton.LeftButton)
    assert isinstance(panel.stack.currentWidget(), GitPage)
