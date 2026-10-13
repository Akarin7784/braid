"""右栏页面延迟构建：启动不导入 QtWebEngine、不查询 git；首次显示才构建，之后复用。"""

import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication

from braid.backends.mock_git import MockGitSource
from braid.ui.panel.shell import ARTIFACTS_TAB, BROWSER_TAB, GIT_TAB


@pytest.fixture
def git_calls(monkeypatch):
    """统计对仓库的查询（真实实现里即 git 子进程调用）。"""
    calls: list[str] = []
    for name in ("status", "diff", "branches"):
        orig = getattr(MockGitSource, name)

        def wrapped(self, *a, _orig=orig, _n=name, **k):
            calls.append(_n)
            return _orig(self, *a, **k)

        monkeypatch.setattr(MockGitSource, name, wrapped)
    return calls


def _window(qtbot, *, collapsed=False):
    from braid.backends.mock import MockBackend
    from braid.ui.main_window import MainWindow

    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1280, 800)
    if collapsed:
        w.panel.hide()
    w.show()
    qtbot.waitExposed(w)
    QApplication.processEvents()
    return w


def test_startup_imports_no_webengine_and_no_panel_pages():
    code = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from braid.backends.mock import MockBackend\n"
        "from braid.ui.main_window import MainWindow\n"
        "w = MainWindow(MockBackend()); w.show(); app.processEvents()\n"
        "assert not any('WebEngine' in m for m in sys.modules), 'webengine imported'\n"
        "assert 'braid.ui.panel.browser' not in sys.modules\n"
        "assert 'braid.ui.panel.git' not in sys.modules\n"
        "assert not w.panel.page_created(0) and not w.panel.page_created(1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_open_panel_builds_only_current_tab(qtbot, git_calls):
    w = _window(qtbot)
    p = w.panel
    assert p.page_created(ARTIFACTS_TAB)
    assert not p.page_created(BROWSER_TAB) and not p.page_created(GIT_TAB)
    assert git_calls == []


def test_git_queried_only_when_tab_shown_and_reused(qtbot, git_calls):
    w = _window(qtbot)
    p = w.panel
    assert git_calls == []
    p.set_current(GIT_TAB)
    QApplication.processEvents()
    assert p.page_created(GIT_TAB) and "status" in git_calls
    page = p.stack.widget(GIT_TAB)
    p.set_current(ARTIFACTS_TAB)
    n = len(git_calls)
    # Git 页隐藏时仓库变化不触发查询，切回时再刷新一次
    p.git_source.changed.emit()
    assert len(git_calls) == n
    p.set_current(GIT_TAB)
    QApplication.processEvents()
    assert p.stack.widget(GIT_TAB) is page  # 复用，不重建
    assert git_calls[n:] == ["status"]


def test_browser_built_on_first_show_and_reused(qtbot):
    w = _window(qtbot)
    p = w.panel
    placeholder = p.stack.widget(BROWSER_TAB)
    assert not p.browser_loaded and type(placeholder).__name__ == "QWidget"
    p.set_current(BROWSER_TAB)
    QApplication.processEvents()
    assert p.browser_loaded
    page = p.stack.widget(BROWSER_TAB)
    assert type(page).__name__ == "BrowserPage"
    p.set_current(ARTIFACTS_TAB)
    p.set_current(BROWSER_TAB)
    assert p.stack.widget(BROWSER_TAB) is page


def test_collapsed_at_startup_builds_nothing(qtbot, git_calls):
    w = _window(qtbot, collapsed=True)
    p = w.panel
    assert not p.isVisible()
    assert not any(p.page_created(i) for i in (BROWSER_TAB, GIT_TAB, ARTIFACTS_TAB))
    p.set_current(GIT_TAB)  # 收起时切标签也不构建
    assert not p.page_created(GIT_TAB) and git_calls == []
    w.set_panel_open(True, animate=False)
    QApplication.processEvents()
    assert p.page_created(GIT_TAB) and "status" in git_calls
    assert not p.page_created(BROWSER_TAB)
