from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

from braid.backends.mock_git import MockGitSource
from braid.core.git import DiffLine
from braid.theme import palette
from braid.theme.menu import RoundedMenu
from braid.theme.palette import tokens as _pal
from braid.ui.panel import RightPanel
from braid.ui.panel.git import (
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


def test_header_and_groups(qtbot):
    _, p = _page(qtbot)
    assert p.branch_chip.text() == "⎇ feat/login ▾"
    assert p.ahead_lbl.text() == "↑1" and not p.ahead_lbl.isHidden()
    assert p.behind_lbl.isHidden()  # 落后为 0：箭头和数字一起隐藏
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
        assert r.letter.color().name().upper() == want[r.fc.status]


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
    assert p.pull_btn.text_color().name().upper() == tokens("light")["text"]
    assert p.push_btn.text_color().name().upper() == tokens("light")["brand"]


def test_behind_shown_when_nonzero(qtbot):
    src, p = _page(qtbot)
    src.behind = 3
    src.changed.emit()
    assert p.behind_lbl.text() == "↓3" and not p.behind_lbl.isHidden()


def test_diff_soft_wrap(qtbot):
    dv = DiffView()
    qtbot.addWidget(dv)
    dv.resize(200, 100)
    dv.set_lines([DiffLine("add", 7, "x" * 200), DiffLine("ctx", 8, "y")])
    srcs = [r[0] for r in dv.rows]
    assert srcs.count(0) > 1 and srcs.count(1) == 1
    assert [r[2] for r in dv.rows if r[0] == 0][1:] == [True] * (srcs.count(0) - 1)
    assert "".join(r[1] for r in dv.rows if r[0] == 0) == "+ " + "x" * 200
    assert dv.minimumHeight() == len(dv.rows) * DIFF_LINE_H
    assert CONT_MARK == "↪"


def test_palette_cached_and_paint_time(qtbot, monkeypatch):
    palette.tokens.cache_clear()
    a = palette.tokens(False)
    assert palette.tokens(False) is a and palette.tokens.cache_info().hits >= 1
    assert palette.tokens(True)["danger"] == "#E2685B"
    _, p = _page(qtbot)
    row = next(r for r in p.rows if r.fc.status == "D")
    assert row.letter.color().name().upper() == "#C0392B"
    QApplication.instance().setProperty("braidDark", True)  # 切主题：不重建控件即生效
    try:
        assert row.letter.color().name().upper() == "#E2685B"
    finally:
        QApplication.instance().setProperty("braidDark", False)


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
