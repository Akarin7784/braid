"""右栏跟随深浅色切换、提交输入框高度、GL 预热。"""

import sys

from PySide6.QtWidgets import QWidget

from braid.backends.mock_artifacts import MockArtifactSource
from braid.backends.mock_browser import MockBrowserController
from braid.backends.mock_git import MockGitSource
from braid.ui.gl_prewarm import prewarm_gl_surface
from braid.ui.panel import RightPanel
from braid.ui.panel.shell import ARTIFACTS_TAB, GIT_TAB


def _panel(qtbot):
    p = RightPanel(
        artifact_source=MockArtifactSource(),
        git_source=MockGitSource(),
        browser_controller=MockBrowserController(),
        lazy_pages=True,
    )
    qtbot.addWidget(p)
    return p


def test_panel_and_built_pages_follow_theme(qtbot):
    p = _panel(qtbot)
    git = p.ensure_page(GIT_TAB)
    art = p.ensure_page(ARTIFACTS_TAB)
    light_qss = (p.styleSheet(), git.styleSheet(), art.styleSheet())
    p.set_theme("dark")
    assert p.theme_mode == "dark"
    assert git.theme == "dark" and art.theme == "dark" and art.preview.theme == "dark"
    assert (p.styleSheet(), git.styleSheet(), art.styleSheet()) != light_qss
    p.set_theme("light")
    assert (p.styleSheet(), git.styleSheet(), art.styleSheet()) == light_qss


def test_browser_page_set_theme_reloads_icons(qtbot):
    from braid.ui.panel.browser import BrowserPage

    b = BrowserPage(web_factory=lambda: None, theme="light")
    qtbot.addWidget(b)
    before = b.styleSheet()
    b.set_theme("dark")
    assert b.dark and b.styleSheet() != before


def test_commit_input_padding_and_height(qtbot):
    p = _panel(qtbot)
    git = p.ensure_page(GIT_TAB)
    c = git.commit_input
    c.ensurePolished()
    c._fit()
    m = c.contentsMargins()
    assert m.top() >= 10 and m.bottom() >= 10
    assert c.height() == c.fontMetrics().lineSpacing() + m.top() + m.bottom()


def test_prewarm_only_on_windows(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    if sys.platform != "win32":
        assert prewarm_gl_surface(w) is None


def test_sync_icons_and_commit_scrollbar_follow_theme(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    p = _panel(qtbot)
    git = p.ensure_page(GIT_TAB)
    light = git.pull_btn.icon().pixmap(12, 12).toImage()
    app.setProperty("braidDark", True)
    try:
        p.set_theme("dark")
        dark = git.pull_btn.icon().pixmap(12, 12).toImage()
        assert light != dark
    finally:
        app.setProperty("braidDark", False)
        p.set_theme("light")
    c = git.commit_input
    assert c.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    c.setPlainText("\n".join("x" * 8))
    assert c.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
