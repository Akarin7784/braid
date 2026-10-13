from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from braid.backends.mock_git import BIG_FILE, MockGitSource
from braid.core.git import DiffLine
from braid.theme import palette
from braid.theme.menu import RoundedMenu
from braid.theme.palette import tokens as _pal
from braid.ui.panel import RightPanel
from braid.ui.panel.git import (
    BIG_DIFF_LINES,
    BIG_HINT,
    CONT_MARK,
    DIFF_FONT_PX,
    DIFF_LINE_H,
    ROW_H,
    SPIN_PERIOD_MS,
    SPIN_SIZE,
    SPIN_TICK_MS,
    DiffView,
    GitPage,
)


def tokens(mode):
    return _pal(mode == "dark")


def _page(qtbot, op_ms=30):
    src = MockGitSource(op_ms=op_ms)
    p = GitPage(src)
    qtbot.addWidget(p)
    return src, p


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
    assert p.commit_input.toPlainText() == "" and p.ahead_lbl.text() == "↑2"
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
    p.show()
    w0 = p.push_btn.width()
    assert p.push_btn.property("emphasis") is True  # 领先 > 0
    qtbot.mouseClick(p.push_btn, Qt.MouseButton.LeftButton)
    b = p.push_btn
    assert not b.isEnabled() and b.spinner.isVisible() and b.spinner.timer.isActive()
    assert b.spinner.timer.interval() == SPIN_TICK_MS and b.width() == w0 and b.text() == "Push"
    assert b.spinner.size().width() == SPIN_SIZE
    assert b.spinner.color().name().upper() == tokens("light")["text2"]  # 禁用时保持原色
    sp = b.spinner.geometry()
    assert sp.right() < b.width() // 2  # 在文字左侧
    qtbot.waitUntil(lambda: p.push_btn.isEnabled(), timeout=2000)
    assert not b.spinner.isVisible() and b.width() == w0
    assert p.ahead_lbl.isHidden() and b.property("emphasis") is False


def test_checkout_updates_chip(qtbot):
    src, p = _page(qtbot)
    src.checkout("main")
    assert p.branch_chip.text() == "⎇ main ▾"


def test_panel_git_tab(qtbot):
    panel = RightPanel(git_source=MockGitSource())
    qtbot.addWidget(panel)
    qtbot.mouseClick(panel.tabs[1], Qt.MouseButton.LeftButton)
    assert isinstance(panel.stack.currentWidget(), GitPage)


def test_spinner_period():
    assert SPIN_TICK_MS == 16 and SPIN_PERIOD_MS == 800


def test_branch_menu_rounded_checked(qtbot):
    _, p = _page(qtbot)
    p._branch_menu()
    m = p._menu
    assert isinstance(m, RoundedMenu)
    checked = [a.text() for a in m.actions() if a.isCheckable() and a.isChecked()]
    assert checked == ["feat/login"] and all(a.isCheckable() for a in m.actions())
    m.close()


def test_pull_push_arrow_icons(qtbot):
    _, p = _page(qtbot)
    for b in (p.pull_btn, p.push_btn):
        assert not b.icon().isNull() and b.iconSize().width() == 12
    assert p.pull_btn.text() == "Pull" and p.push_btn.text() == "Push"
    assert p.pull_btn.text_color().name().upper() == tokens("light")["text2"]
    assert p.push_btn.text_color().name().upper() == tokens("light")["brand"]


def test_behind_shown_when_nonzero(qtbot):
    src, p = _page(qtbot)
    src.behind = 3
    src.changed.emit()
    assert p.behind_lbl.text() == "↓3" and not p.behind_lbl.isHidden()


def test_branch_menu_check_qss(qtbot):
    from PySide6.QtGui import QImage

    from braid.theme import load_qss

    app = QApplication.instance()
    old = app.styleSheet()
    qss = load_qss("light")
    assert "QMenu::indicator:checked" in qss and "check_light.png" in qss
    app.setStyleSheet(qss)
    try:
        _, p = _page(qtbot)
        p._branch_menu()
        m = p._menu
        m.ensurePolished()
        m.adjustSize()
        img = QImage(m.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        m.render(img)
        acts = m.actions()
        cur = next(a for a in acts if a.isChecked())
        other = next(a for a in acts if not a.isChecked())

        def ink(a):
            g = m.actionGeometry(a)
            n = 0
            for x in range(g.left(), g.left() + 40):
                for y in range(g.top(), g.bottom()):
                    c = img.pixelColor(x, y)
                    if c.alpha() and c.lightness() < 200:
                        n += 1
            return n

        assert ink(cur) > ink(other) + 5  # 当前分支左侧画出了对勾
        m.close()
    finally:
        app.setStyleSheet(old)


def _hex(c):
    return c.name().upper()


def test_single_list_no_groups(qtbot):
    _, p = _page(qtbot)
    assert p.branch_chip.text() == "⎇ feat/login ▾"
    assert p.ahead_lbl.text() == "↑1" and not p.ahead_lbl.isHidden()
    assert p.behind_lbl.isHidden()
    labels = [w for w in p.file_list.findChildren(type(p.ahead_lbl)) if w.text()]
    assert labels == []  # 不再有暂存/未暂存分组标题
    assert [r.fc.path for r in p.rows] == [
        "src/pages/forgot.py",
        "src/pages/login.py",
        "src/styles/login.qss",
        "src/old_auth.py",
        BIG_FILE,
    ]
    assert all(r.height() == ROW_H for r in p.rows)
    assert not any(e.expanded for e in p.entries)


def test_row_stats_and_name_colors(qtbot):
    _, p = _page(qtbot)
    t = tokens("light")
    by = {r.fc.path: r for r in p.rows}
    assert by["src/pages/login.py"].stats_text() == ("+4", "−1")
    assert by["src/old_auth.py"].stats_text() == ("+0", "−5")
    assert by["src/pages/login.py"].dir_and_name() == ("src/pages/", "login.py")
    assert _hex(by["src/pages/forgot.py"].name_color()) == t["success"]
    assert _hex(by["src/old_auth.py"].name_color()) == t["danger"]
    assert _hex(by["src/pages/login.py"].name_color()) == t["text"]


def test_expand_multiple_inline(qtbot):
    _, p = _page(qtbot)
    p.resize(480, 700)
    p.show()
    login = p.entry("src/pages/login.py", False)
    gone = p.entry("src/old_auth.py", False)
    qtbot.mouseClick(login.row, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(gone.row, Qt.MouseButton.LeftButton)
    assert login.expanded and gone.expanded and login.diff.isVisible() and gone.diff.isVisible()
    dv = login.diff
    assert dv.font().pixelSize() == DIFF_FONT_PX and DIFF_LINE_H == 20
    assert [ln.kind for ln in dv.lines].count("hunk") == 2
    assert dv.lines[0].text == "@@ -12,2 +12,3 @@"
    dl = next(ln for ln in dv.lines if ln.kind == "del")
    assert dl.old == 42 and dl.new is None
    assert all(ln.kind == "del" for ln in gone.diff.lines[1:])
    # 再点收起，其他保持展开
    qtbot.mouseClick(login.row, Qt.MouseButton.LeftButton)
    assert not login.expanded and login.diff.isHidden() and gone.expanded


def test_expand_survives_refresh(qtbot):
    src, p = _page(qtbot)
    p.toggle_file(p.entry("src/pages/login.py", False).fc, False)
    src.checkout("main")
    assert p.entry("src/pages/login.py", False).expanded


def test_big_file_folded_until_load(qtbot, monkeypatch):
    src, p = _page(qtbot)
    calls = []
    orig = src.diff
    monkeypatch.setattr(src, "diff", lambda *a: calls.append(a) or orig(*a))
    big = p.entry(BIG_FILE, False)
    assert big.fc.changed_lines > BIG_DIFF_LINES and big.big
    p.toggle_file(big.fc, False)
    assert big.expanded and big.diff.placeholder == BIG_HINT and calls == []
    qtbot.mouseClick(big.diff, Qt.MouseButton.LeftButton)
    assert big.diff.placeholder is None and len(big.diff.lines) > BIG_DIFF_LINES
    assert calls == [(BIG_FILE, False)]


def test_stage_all_in_top_row(qtbot):
    src, p = _page(qtbot)
    assert p.stage_btn.text() == "全部暂存"
    p.toggle_file(p.entry("src/old_auth.py", False).fc, False)
    qtbot.mouseClick(p.stage_btn, Qt.MouseButton.LeftButton)
    assert len(src.status().unstaged) == 0 and p.commit_btn.text() == "提交 5 个文件"
    assert p.stage_btn.text() == "取消暂存"
    assert p.entry("src/old_auth.py", True).expanded  # 展开状态跟着文件走
    qtbot.mouseClick(p.stage_btn, Qt.MouseButton.LeftButton)
    assert len(src.status().staged) == 0


def test_hover_background(qtbot):
    _, p = _page(qtbot)
    row = p.rows[1]
    row.resize(300, ROW_H)

    def px():
        img = QImage(row.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        row.render(img)
        return img.pixelColor(150, 2)

    hover = tokens("light")["hover"]
    assert _hex(px()) != hover
    QApplication.sendEvent(row, QEvent(QEvent.Type.HoverEnter))
    assert _hex(px()) == hover
    QApplication.sendEvent(row, QEvent(QEvent.Type.HoverLeave))
    assert _hex(px()) != hover


def test_diff_colors_follow_theme(qtbot):
    from braid.ui.panel.git import diff_bg

    app = QApplication.instance()
    _, p = _page(qtbot)
    assert diff_bg("ctx", False) is None and diff_bg("hunk", True) is None
    gone = p.entry("src/old_auth.py", False)
    assert _hex(gone.row.name_color()) == tokens("light")["danger"]
    app.setProperty("braidDark", True)
    try:
        p.set_theme("dark")
        assert p.theme == "dark"
        assert _hex(gone.row.name_color()) == tokens("dark")["danger"]
        bg = diff_bg("del", True)
        assert bg.alpha() == 0x26 and bg.rgb() == palette.qcolor("danger", True).rgb()
        assert diff_bg("add", True).alpha() == 0x26
    finally:
        app.setProperty("braidDark", False)
        p.set_theme("light")


def test_diff_soft_wrap(qtbot):
    dv = DiffView()
    qtbot.addWidget(dv)
    dv.resize(240, 100)
    dv.set_lines([DiffLine("add", None, 7, "x" * 200), DiffLine("ctx", 8, 8, "y")])
    srcs = [r[0] for r in dv.rows]
    assert srcs.count(0) > 1 and srcs.count(1) == 1
    assert [r[2] for r in dv.rows if r[0] == 0][1:] == [True] * (srcs.count(0) - 1)
    assert "".join(r[1] for r in dv.rows if r[0] == 0) == "+ " + "x" * 200
    assert CONT_MARK == "↪"
