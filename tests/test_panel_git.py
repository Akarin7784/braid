import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from braid.backends.mock_git import BIG_FILE, MockGitSource
from braid.core.git import DiffLine
from braid.theme import palette
from braid.theme.palette import tokens as _pal
from braid.ui.panel import RightPanel
from braid.ui.panel.git import (
    BIG_DIFF_LINES,
    BIG_HINT,
    CONT_MARK,
    DIFF_FONT_PX,
    DIFF_LINE_H,
    ROW_H,
    DiffView,
    GitPage,
)


def tokens(mode):
    return _pal(mode == "dark")


def _page(qtbot):
    src = MockGitSource()
    p = GitPage(src)
    qtbot.addWidget(p)
    return src, p


def test_panel_git_tab(qtbot):
    panel = RightPanel(git_source=MockGitSource())
    qtbot.addWidget(panel)
    qtbot.mouseClick(panel.tabs[1], Qt.MouseButton.LeftButton)
    assert isinstance(panel.stack.currentWidget(), GitPage)


def _hex(c):
    return c.name().upper()


def test_read_only_sorted_list(qtbot):
    from PySide6.QtWidgets import QAbstractButton, QPlainTextEdit

    _, p = _page(qtbot)
    assert p.branch_label.text() == "⎇ feat/login"
    # 只读：页面里没有任何按钮或输入框（无暂存、提交、Pull/Push、切换分支）
    assert p.findChildren(QAbstractButton) == [] and p.findChildren(QPlainTextEdit) == []
    paths = [r.fc.path for r in p.rows]
    assert paths == sorted(paths) and BIG_FILE in paths and len(paths) == 5
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
    login = p.entry("src/pages/login.py")
    gone = p.entry("src/old_auth.py")
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
    p.toggle_file(p.entry("src/pages/login.py").fc)
    src.changed.emit()
    assert p.entry("src/pages/login.py").expanded


def test_big_file_folded_until_load(qtbot, monkeypatch):
    src, p = _page(qtbot)
    calls = []
    orig = src.diff
    monkeypatch.setattr(src, "diff", lambda *a: calls.append(a) or orig(*a))
    big = p.entry(BIG_FILE)
    assert big.fc.changed_lines > BIG_DIFF_LINES and big.big
    p.toggle_file(big.fc)
    assert big.expanded and big.diff.placeholder == BIG_HINT and calls == []
    qtbot.mouseClick(big.diff, Qt.MouseButton.LeftButton)
    assert big.diff.placeholder is None and len(big.diff.lines) > BIG_DIFF_LINES
    assert calls == [(BIG_FILE,)]


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
    gone = p.entry("src/old_auth.py")
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


def test_big_tag_only_on_big_files(qtbot):
    from braid.ui.panel.git import BIG_TAG

    _, p = _page(qtbot)
    assert BIG_TAG == "较大"
    assert [r.fc.path for r in p.rows if r.big] == [BIG_FILE]


def test_hunk_separator_uses_border_subtle(qtbot):
    dv = DiffView()
    qtbot.addWidget(dv)
    dv.resize(400, 60)
    dv.set_lines([DiffLine("hunk", None, None, "@@ -1,1 +1,1 @@")])
    img = QImage(dv.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    dv.render(img)
    r = dv.line_rect(0)
    y = r.y() + r.height() // 2
    assert _hex(img.pixelColor(dv.width() - 10, y)) == tokens("light")["border_subtle"]
    assert tokens("dark")["border_subtle"] == "#333332"


def test_diff_font_cjk_fallback_regular(qtbot):
    """只查回退规则：等宽西文族（剔除 CJK 族）+ 标题字体链解析出的中文族，Regular。
    不写死字体名，各平台落到的具体字体不同。"""
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from braid.ui.panel.git import diff_families, mono_font
    from braid.ui.settings.widgets import CJK_FALLBACK, mono_families, resolved_cjk_family

    cjk_db = set(QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese))
    cjk = resolved_cjk_family(QApplication.font())
    if not cjk_db or not cjk:
        pytest.skip("本平台没有可用的中文字体")
    latin = [x for x in mono_families() if x not in cjk_db and x not in CJK_FALLBACK]
    expected = latin + ([cjk] if cjk not in latin else [])
    fams = diff_families()
    assert fams == expected
    f = mono_font()
    assert f.families() == fams and f.weight() == QFont.Weight.Normal


def test_diff_cjk_glyphs_resolve_to_regular(qtbot):
    """中文字形实际落到的字体必须是 Regular（数字字重 400），不检查字体名。"""
    from PySide6.QtGui import QFontDatabase, QTextLayout

    from braid.ui.panel.git import mono_font

    if not QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese):
        pytest.skip("本平台没有可用的中文字体")
    lay = QTextLayout("忘记密码", mono_font())
    lay.beginLayout()
    lay.createLine()
    lay.endLayout()
    runs = lay.glyphRuns()
    assert runs
    for run in runs:
        assert run.rawFont().weight() == 400


def test_branch_label_plain_text2_aligned_with_path(qtbot):
    from PySide6.QtCore import QPoint

    _, p = _page(qtbot)
    p.resize(480, 400)
    p.show()
    qtbot.waitExposed(p)
    lb = p.branch_label
    assert "⎇" in lb.text()
    img = QImage(lb.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    lb.render(img)
    assert img.pixelColor(lb.width() - 1, 1).alpha() == 0  # 无底色
    assert _hex(lb.palette().color(lb.foregroundRole())) == tokens("light")["text2"]
    row = p.rows[0]
    win = p.window()
    lx = lb.mapTo(win, QPoint(lb.contentsRect().left(), 0)).x()
    px = row.mapTo(win, QPoint(row.path_x(), 0)).x()
    assert lx == px
