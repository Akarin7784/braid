import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme.palette import qcolor
from braid.ui.settings.mcp import (
    ADD_H,
    ERROR_TEXT,
    McpPage,
    McpRow,
    McpServerConfig,
    servers_from_config,
)
from braid.ui.settings.pages import PAGE_FACTORIES
from braid.ui.settings.widgets import CARD_PAD_H, ROW_H, ToggleSwitch


def _page(qtbot, backend=None):
    page = McpPage(backend or MockBackend())
    qtbot.addWidget(page)
    page.resize(640, 700)
    page.show()
    qtbot.waitExposed(page)
    return page


def test_registered():
    assert PAGE_FACTORIES["mcp"] is McpPage


def test_settings_page_uses_mcp(qtbot):
    from braid.ui.settings_page import SettingsPage

    sp = SettingsPage(backend=MockBackend())
    qtbot.addWidget(sp)
    assert isinstance(sp.pages["mcp"], McpPage)


def test_groups_render(qtbot):
    page = _page(qtbot)
    assert [r.cfg.name for r in page.card_rows("local")] == ["filesystem", "sqlite"]
    assert [r.cfg.name for r in page.card_rows("remote")] == ["context7", "sentry"]
    for r in page.rows():
        assert isinstance(r, McpRow) and r.height() == ROW_H
        assert isinstance(r.switch, ToggleSwitch)
        if r.cfg.status != "error":
            assert r.target.toolTip() == r.cfg.target
    assert page.card_rows("local")[0].cfg.target.startswith("npx")
    assert page.card_rows("remote")[0].cfg.target.startswith("https://")


def test_toggle_writes_config(qtbot):
    be = MockBackend()
    page = _page(qtbot, be)
    row = page.card_rows("local")[1]
    assert not row.switch.isChecked()
    with qtbot.waitSignal(be.config_changed) as blk:
        qtbot.mouseClick(row.switch, Qt.MouseButton.LeftButton)
    assert blk.args == ["mcp"]
    assert be.get_config("mcp")["servers"]["sqlite"]["enabled"] is True


def test_refresh_on_config_changed(qtbot):
    be = MockBackend()
    page = _page(qtbot, be)
    servers = be.get_config("mcp")["servers"]
    servers["new"] = {"type": "remote", "url": "https://x.dev/mcp"}
    be.set_config("mcp", {"servers": servers})
    qtbot.wait(10)
    assert [r.cfg.name for r in page.card_rows("remote")][-1] == "new"


def test_config_roundtrip():
    servers = MockBackend().get_config("mcp")["servers"]
    for cfg in servers_from_config({"servers": servers}):
        assert cfg.to_dict() == servers[cfg.name]
    assert McpServerConfig("a", "local", "x").to_dict().get("error") is None


@pytest.mark.parametrize(
    "status,token", [("connected", "success"), ("error", "danger"), ("disconnected", "text3")]
)
def test_status_dot_color(qtbot, status, token):
    be = MockBackend()
    be.set_config("mcp", {"servers": {"x": {"type": "local", "command": "c", "status": status}}})
    page = _page(qtbot, be)
    dot = page.rows()[0].dot
    assert dot.color_token() == token
    img = dot.grab().toImage()
    assert img.pixelColor(QPoint(img.width() // 2, img.height() // 2)).rgb() == qcolor(token).rgb()


def test_error_row(qtbot):
    page = _page(qtbot)
    sentry = next(r for r in page.rows() if r.cfg.name == "sentry")
    assert sentry.target.text() == ERROR_TEXT
    assert sentry.target.property("error") is True
    assert "HTTP 401 未授权" in sentry.dot.toolTip()
    assert "HTTP 401 未授权" in sentry.toolTip()


def test_alignment_16px(qtbot):
    page = _page(qtbot)
    for kind in ("local", "remote"):
        card = page.cards[kind]
        cx = card.mapTo(page, QPoint(0, 0)).x()
        title = card.title
        assert title is not None
        tx = title.mapTo(page, QPoint(title.contentsRect().left(), 0)).x()
        dx = page.card_rows(kind)[0].dot.mapTo(page, QPoint(0, 0)).x()
        assert tx == dx == cx + CARD_PAD_H == cx + 16


def test_add_card(qtbot):
    page = _page(qtbot)
    assert page.add_card.text() == "+ 添加 MCP 服务"
    assert page.add_card.height() == ADD_H
    assert page.add_card.width() == page.cards["local"].width()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_scrollbar_panel_collapsed_and_open(qtbot, theme):
    from braid.theme import load_qss
    from braid.ui.main_window import MainWindow

    app = QApplication.instance()
    app.setProperty("braidDark", theme == "dark")
    try:
        w = MainWindow(MockBackend())
        w.setStyleSheet(load_qss(theme))
        qtbot.addWidget(w)
        w.resize(1280, 800)
        w.show()
        w.set_panel_open(True, animate=False)
        w.show_settings(True)
        qtbot.waitExposed(w)
        sp = w.settings_page
        sp.show_section("mcp")
        for panel_open in (False, True):  # #49：进设置页自动收起；再手动打开
            if panel_open:
                w.set_panel_open(True, animate=False)
            assert w.panel_open() == panel_open
            qtbot.wait(20)
            sc = sp.scrolls["mcp"]
            assert sc.verticalScrollBar().maximum() == 0, panel_open
            assert sc.overlay_bar.isHidden()
            vp = sc.viewport().rect()
            page = sp.pages["mcp"]
            for wid in [*page.cards.values(), page.add_card, *(r.switch for r in page.rows())]:
                r = wid.rect().translated(wid.mapTo(sc.viewport(), QPoint(0, 0)))
                assert vp.contains(r), (wid, r, vp, panel_open)
    finally:
        app.setProperty("braidDark", False)
