"""设置页性能：分区按需构建、钥匙串延后检查、离开即销毁、MCP 用共享等宽字体。"""

from __future__ import annotations

import subprocess
import sys

import pytest
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.core.providers import Provider, ProviderStore
from braid.ui.settings.pages import NAV, PAGE_FACTORIES
from braid.ui.settings_page import (
    KEYRING_CHECKING,
    KEYRING_FAIL,
    KEYRING_OK,
    SettingsPage,
)


def _settings(qtbot, tmp_path):
    page = SettingsPage(ProviderStore(tmp_path / "p.json"), backend=MockBackend())
    qtbot.addWidget(page)
    return page


def test_unvisited_pages_not_constructed(qtbot, tmp_path, monkeypatch):
    built: list[str] = []
    for key in list(PAGE_FACTORIES):
        orig = PAGE_FACTORIES[key]

        def spy(backend, _k=key, _f=orig):
            built.append(_k)
            return _f(backend)

        monkeypatch.setitem(PAGE_FACTORIES, key, spy)
    page = _settings(qtbot, tmp_path)
    assert page.built() == ["models"] and built == []
    page.show_section("keybinds")
    assert built == ["keybinds"] and page.built() == ["models", "keybinds"]
    page.show_section("models")
    page.show_section("keybinds")  # 再访问不重建
    assert built == ["keybinds"]
    page.ensure_page("advanced")
    assert built == ["keybinds", "advanced"]


def test_header_visible_right_after_nav_click(qtbot, tmp_path):
    page = _settings(qtbot, tmp_path)
    page.resize(1100, 760)
    page.show()
    qtbot.waitExposed(page)
    for row, (key, label) in enumerate(NAV):
        if key == "models":
            continue
        page.nav.setCurrentRow(row)  # 不跑事件循环，立即检查
        w = page.pages[key]
        assert page.stack.currentWidget() is page.scrolls[key]
        header = w.header
        assert header.isVisible() and header.title.isVisible(), key
        assert header.title.text() == label


def test_reset_reloads_only_built_pages(qtbot, tmp_path):
    page = _settings(qtbot, tmp_path)
    page.show_section("advanced")
    old = page.pages["advanced"]
    page.reload_pages()
    qtbot.waitUntil(lambda: page.pages["advanced"] is not old)
    assert page.built() == ["models", "advanced"]


def test_keyring_status_width_fixed(qtbot, tmp_path):
    import keyring
    from keyring.backends import fail

    for backend_ok in (True, False):
        if not backend_ok:
            keyring.set_keyring(fail.Keyring())
        page = _settings(qtbot, tmp_path)
        page.resize(1100, 760)
        page.show()
        qtbot.waitExposed(page)
        st = page.models.keyring_status
        if page.models.keyring_ok is None:
            assert st.text() == KEYRING_CHECKING and st.property("state") == "checking"
        w0, x0 = st.width(), st.mapTo(page, st.rect().topLeft()).x()
        fm = st.fontMetrics()
        final = KEYRING_OK if backend_ok else KEYRING_FAIL
        assert w0 >= fm.horizontalAdvance(final)
        qtbot.waitUntil(
            lambda p=page: p.models.keyring_ok is not None, timeout=5000
        )  # 首帧后自动检查
        assert st.text() == final
        assert st.width() == w0 and st.mapTo(page, st.rect().topLeft()).x() == x0
        assert page.models.notice.isHidden() is backend_ok


def test_checking_text3_qss():
    from braid.theme import load_qss
    from braid.theme.palette import tokens

    for theme in ("light", "dark"):
        t = tokens(theme == "dark")
        line = next(
            x for x in load_qss(theme).splitlines() if x.startswith("QLabel#keyringStatus {")
        )
        assert t["text3"] in line


def test_keyring_not_imported_until_deferred_check(tmp_path):
    code = r"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDeadlineTimer, QEventLoop, QTimer
from braid.core.providers import Provider, ProviderStore
from braid.backends.mock import MockBackend
from braid.ui.settings_page import SettingsPage
app = QApplication([])
store = ProviderStore()
store.upsert(Provider(name="X"))
page = SettingsPage(store, backend=MockBackend())
a = "keyring" in sys.modules
page.resize(1000, 700); page.show()
# 等结果而不是固定等待：CI 上钥匙串后端可能很慢（同 qtbot.waitUntil(..., timeout=5000)）
deadline = QDeadlineTimer(5000)
while page.models.keyring_ok is None and not deadline.hasExpired():
    loop = QEventLoop(page); QTimer.singleShot(10, page, loop.quit); loop.exec()
b = "keyring" in sys.modules
print(f"RESULT {a} {b} {page.models.keyring_ok is not None}")
"""
    import os

    env = {**os.environ, "BRAID_CONFIG_DIR": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    ).stdout
    assert "RESULT False True True" in out, out


def test_settings_destroyed_on_leave(qtbot, tmp_path, monkeypatch):
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    qtbot.waitExposed(w)
    app = QApplication.instance()
    base = len(app.allWidgets())
    w.show_settings(True)
    sp = w.settings_page
    for key, _ in NAV:
        sp.show_section(key)
    during = len(app.allWidgets())
    assert during > base + 100
    destroyed: list[bool] = []
    sp.destroyed.connect(lambda: destroyed.append(True))
    w.show_settings(False)
    assert w.settings_page is None and not w.settings_open()
    qtbot.waitUntil(lambda: bool(destroyed))
    QApplication.processEvents()
    after = len(app.allWidgets())
    assert after <= base + 5, (base, during, after)
    # 再进入时重新构建，只建默认分区
    w.show_settings(True)
    assert w.settings_page is not None and w.settings_page is not sp
    assert w.settings_page.built() == ["models"]


def test_leave_restores_panel_and_reenter(qtbot, tmp_path, monkeypatch):
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    qtbot.waitExposed(w)
    w.set_panel_open(True, animate=False)
    for _ in range(2):
        w.show_settings(True)
        assert not w.panel_open()
        w.show_settings(False)
        assert w.panel_open() and w.chat_view.isVisible()


def test_mcp_uses_mono_font(qtbot, tmp_path):
    from braid.theme import load_qss
    from braid.ui.settings.mcp import McpRow
    from braid.ui.settings.widgets import mono_families

    page = _settings(qtbot, tmp_path)
    mcp = page.ensure_page("mcp")
    rows = mcp.findChildren(McpRow)
    assert rows
    for r in rows:
        f: QFont = r.target.font()
        assert f.families() == mono_families() and f.pixelSize() == 12
        assert QFontInfo(f).fixedPitch()
    line = next(x for x in load_qss("light").splitlines() if x.startswith("#mcpTarget {"))
    assert "font-family" not in line and "font-size" not in line


def test_store_with_providers_keys_load_after_check(qtbot, tmp_path):
    store = ProviderStore(tmp_path / "p.json")
    store.upsert(Provider(name="A"))
    page = SettingsPage(store, backend=MockBackend())
    qtbot.addWidget(page)
    card = page.models.cards()[0]
    assert not card.key.loaded
    page.show()
    qtbot.waitUntil(lambda: card.key.loaded)
    assert card.key.edit.isEnabled()


def test_keyring_check_runs_off_ui_thread(qtbot, tmp_path, monkeypatch):
    import threading

    from braid.core import secrets

    seen: list[str] = []

    def fake() -> bool:
        seen.append(threading.current_thread().name)
        return True

    monkeypatch.setattr(secrets, "keyring_available", fake)
    page = _settings(qtbot, tmp_path)
    page.resize(1100, 760)
    page.show()
    qtbot.waitExposed(page)
    qtbot.waitUntil(lambda: page.models.keyring_ok is not None, timeout=5000)
    assert seen == ["braid-keyring-check"]
    assert page.models.keyring_status.text() == KEYRING_OK
    assert (
        page.models._poll_timer.parent() is page.models and not page.models._poll_timer.isActive()
    )


def test_mono_families_memoized(monkeypatch):
    from PySide6.QtGui import QFontDatabase

    from braid.ui.settings import widgets

    widgets.mono_families()  # 确保已缓存
    calls: list[int] = []
    orig = QFontDatabase.families
    monkeypatch.setattr(QFontDatabase, "families", lambda *a: calls.append(1) or orig(*a))
    a = widgets.mono_families()
    a.append("被调用方改动")
    assert calls == [] and "被调用方改动" not in widgets.mono_families()


def test_mono_font_warmed_after_first_show(qtbot, tmp_path, monkeypatch):
    from braid.ui import settings_page as sp_mod

    hosts: list[object] = []
    monkeypatch.setattr(sp_mod, "warm_mono_font", lambda host=None: hosts.append(host))
    page = _settings(qtbot, tmp_path)
    assert page._warm_timer.parent() is page and not page._warm_timer.isActive()
    page.show()
    qtbot.waitExposed(page)
    qtbot.waitUntil(lambda: hosts == [page], timeout=2000)
    page.hide()
    page.show()  # 只预热一次
    qtbot.wait(sp_mod.WARM_DELAY_MS + 50)
    assert hosts == [page]


def test_first_visit_no_blank_frame(qtbot, tmp_path):
    """首次进入智能体/快捷键：切换时页面已建好，占位页从不绘制，首帧即含页头。"""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget

    page = _settings(qtbot, tmp_path)
    page.resize(1100, 760)
    page.show()
    qtbot.waitExposed(page)
    keys = [k for k, _ in NAV]
    placeholders = {page.stack.widget(i) for i in range(page.stack.count())} - {
        page.scrolls["models"]
    }
    switched: list[tuple[str, bool]] = []
    page.stack.currentChanged.connect(
        lambda i: switched.append(
            (keys[i], dict.__contains__(page.pages, keys[i]))
            if page.stack.widget(i) not in placeholders
            else (keys[i], False)
        )
    )

    class PaintSpy(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.painted: list[QObject] = []

        def eventFilter(self, obj: QObject, e: QEvent) -> bool:  # noqa: N802
            if e.type() == QEvent.Type.Paint:
                self.painted.append(obj)
            return False

    spy = PaintSpy()
    for ph in placeholders:
        ph.installEventFilter(spy)
    for key in ("agents", "keybinds"):
        page.show_section(key)  # 同步构建并切换，此时还没跑事件循环
        header = page.pages[key].header
        header.title.installEventFilter(spy)
        spy.painted.clear()
        qtbot.waitUntil(lambda h=header: h.title in spy.painted, timeout=1000)  # 下一帧
        assert not set(spy.painted) & placeholders
        # 下一帧里出现的就是完整页面：截一帧，页头区域不是纯背景色
        img = page.stack.grab().toImage()
        title_pos = header.title.mapTo(page.stack, header.title.rect().center())
        bg = img.pixelColor(2, 2)
        y = int(title_pos.y() * img.devicePixelRatio())  # grab 是设备像素
        row = [img.pixelColor(x, y) for x in range(img.width())]
        assert any(c != bg for c in row)
    assert switched == [("agents", True), ("keybinds", True)]
    assert all(isinstance(w, QWidget) for w in placeholders)


def test_slow_keyring_check_does_not_block_ui(qtbot, tmp_path, monkeypatch):
    """后台检查很慢（模拟 CI 上的慢后端）时，界面线程照常跑事件循环，状态位一直是“检查中…”。"""
    import threading
    import time

    from PySide6.QtCore import QTimer

    from braid.core import secrets

    release = threading.Event()

    def slow() -> bool:
        # 工作线程里至少拖 500ms，并一直等到断言做完才放行（慢 CI 上也不会提前返回）
        time.sleep(0.5)
        release.wait(5)
        return True

    monkeypatch.setattr(secrets, "keyring_available", slow)
    page = _settings(qtbot, tmp_path)
    page.resize(1100, 760)
    page.show()
    qtbot.waitExposed(page)
    m = page.models
    st = m.keyring_status
    ticks: list[float] = []
    ticker = QTimer(page)  # 归页面所有
    ticker.setInterval(10)
    ticker.timeout.connect(lambda: ticks.append(time.monotonic()))
    ticker.start()
    qtbot.waitUntil(lambda: m._check_thread is not None, timeout=5000)
    assert m.keyring_ok is None and st.text() == KEYRING_CHECKING
    qtbot.waitUntil(lambda: len(ticks) >= 10, timeout=5000)
    # 结果还没到，事件循环已经转了 10 次以上，且相邻两次之间没有长时间卡顿
    assert m.keyring_ok is None and st.text() == KEYRING_CHECKING
    gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
    assert max(gaps) < 0.25, gaps
    release.set()
    qtbot.waitUntil(lambda: m.keyring_ok is not None, timeout=5000)
    ticker.stop()
    assert st.text() == KEYRING_OK


@pytest.mark.parametrize("exc", [ImportError("no keyring backend"), RuntimeError("boom")])
def test_keyring_check_exception_resolves_unavailable(qtbot, tmp_path, monkeypatch, exc):
    """后台检查抛异常（如 PyInstaller 漏了 hiddenimports）时按不可用处理，不会卡在“检查中…”。"""
    import threading

    from braid.core import secrets

    def broken() -> bool:
        raise exc

    escaped: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda a: escaped.append(a.exc_value))
    monkeypatch.setattr(secrets, "keyring_available", broken)
    page = _settings(qtbot, tmp_path)
    page.resize(1100, 760)
    page.show()
    qtbot.waitExposed(page)
    m = page.models
    qtbot.waitUntil(lambda: m.keyring_ok is not None, timeout=5000)
    assert m.keyring_ok is False
    assert m.keyring_status.text() == KEYRING_FAIL
    assert m.keyring_status.property("state") == "fail"
    assert not m.notice.isHidden()
    assert m._check_thread is not None
    m._check_thread.join(timeout=5)
    assert escaped == []
    assert m.run_keyring_check() is False  # 同步路径同样不抛
