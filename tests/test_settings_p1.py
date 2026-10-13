"""P1 设置：配置 API、Mock、通用控件、各分区页、800 高不出滚动条。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.core.backend import CONFIG_SECTIONS, AgentBackend
from braid.core.providers import Provider, ProviderStore
from braid.ui.settings.pages import (
    NAV,
    PAGE_FACTORIES,
    GeneralPage,
    PermissionsPage,
    PlaceholderPage,
    register_page,
)
from braid.ui.settings.widgets import (
    ROW_H,
    NumberField,
    SegmentedControl,
    SettingCard,
    SettingRow,
    ToggleSwitch,
)
from braid.ui.settings_page import SettingsPage

# ---- API / Mock ----


def test_sections_match_nav():
    assert tuple(k for k, _ in NAV) == CONFIG_SECTIONS
    assert [label for _, label in NAV] == [
        "模型与服务", "权限", "通用", "智能体", "MCP 服务", "规则与指令", "快捷键", "高级",
    ]  # fmt: skip


def test_abstract_api():
    for name in ("get_config", "set_config"):
        assert name in AgentBackend.__abstractmethods__


def test_mock_config_roundtrip(qtbot):
    b = MockBackend()
    for sec in CONFIG_SECTIONS:
        assert isinstance(b.get_config(sec), dict) and b.get_config(sec)
    seen: list[str] = []
    b.config_changed.connect(seen.append)
    b.set_config("general", {"font_size": 16})
    assert b.get_config("general")["font_size"] == 16
    assert b.get_config("general")["shell"]  # 浅合并，其余字段还在
    assert seen == ["general"]
    got = b.get_config("permissions")
    got["bash_rules"].clear()  # 副本，不影响后端
    assert b.get_config("permissions")["bash_rules"]
    with pytest.raises(KeyError):
        b.set_config("nope", {})
    with pytest.raises(KeyError):
        b.get_config("nope")


def test_mock_defaults_opencode_like():
    b = MockBackend()
    m = b.get_config("models")
    assert m["model"] and m["small_model"]
    p = b.get_config("permissions")
    assert {"pattern": "rm -rf *", "action": "deny"} in p["bash_rules"]
    assert b.test_connection("x", "https://a").ok
    assert not b.test_connection("x", "ftp:/bad").ok


# ---- widgets ----


def test_toggle_switch(qtbot):
    t = ToggleSwitch()
    qtbot.addWidget(t)
    assert t.size().width() == 32 and t.size().height() == 18
    off = t.track_color(False)
    t.setChecked(True)
    from braid.theme.palette import qcolor

    assert t.track_color(False) == qcolor("accent", False)
    assert t.track_color(True) == qcolor("accent", True)
    assert t.knob_color(True) == qcolor("surface", True)  # 深色开：钮用 surface
    assert off != qcolor("control", False)  # 关：control 上叠了 text3
    t.show()
    qtbot.mouseClick(t, Qt.MouseButton.LeftButton)
    assert not t.isChecked()


def test_segmented_control(qtbot):
    seg = SegmentedControl((("a", "甲"), ("b", "乙"), ("c", "丙")), "b")
    qtbot.addWidget(seg)
    seg.show()
    assert seg.value() == "b"
    with qtbot.waitSignal(seg.changed) as sig:
        qtbot.mouseClick(seg, Qt.MouseButton.LeftButton, pos=seg.segment_rect(2).center())
    assert sig.args == ["c"] and seg.value() == "c"
    seg.set_value("a")
    assert seg.value() == "a"


def test_setting_row_and_card(qtbot):
    card = SettingCard("分组")
    qtbot.addWidget(card)
    row = card.add_row("标签", ToggleSwitch())
    assert isinstance(row, SettingRow) and row.height() == ROW_H
    assert card.rows() == [row]
    card.resize(300, 120)
    card.show()
    assert card.title is not None
    # 组标题与卡内文字左对齐，都缩进 16px
    assert card.title.mapTo(card, QPoint(0, 0)).x() == 16
    assert row.label.mapTo(card, QPoint(0, 0)).x() == 16


def test_number_field(qtbot):
    f = NumberField(30, 1, 600)
    qtbot.addWidget(f)
    seen: list[int] = []
    f.valueChanged.connect(seen.append)
    f.setText("9999")
    f.editingFinished.emit()
    assert f.value() == 600  # 越界输入夹到上限
    f.setValue(45)
    assert seen == [600, 45] and f.text() == "45"
    f.setValue(0)
    assert f.value() == 1


# ---- pages ----


def _settings(qtbot, tmp_path, n: int = 0):
    store = ProviderStore(tmp_path / "p.json")
    for i in range(n):
        store.upsert(Provider(name=f"P{i}", base_url="https://x"))
    b = MockBackend()
    page = SettingsPage(store, backend=b)
    qtbot.addWidget(page)
    return page, b


def test_nav_and_placeholders(qtbot, tmp_path):
    page, _ = _settings(qtbot, tmp_path)
    assert page.nav.count() == 8
    assert isinstance(page.pages["permissions"], PermissionsPage)
    assert isinstance(page.pages["general"], GeneralPage)
    for key in ("agents", "rules", "keybinds", "advanced"):
        assert isinstance(page.pages[key], PlaceholderPage)
    page.nav.setCurrentRow(4)
    assert page.stack.currentWidget() is page.scrolls["mcp"]
    assert page.pages["mcp"].header.title.text() == "MCP 服务"


def test_register_page_hooks(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    monkeypatch.setitem(PAGE_FACTORIES, "mcp", lambda b: QLabel("mcp-real"))
    page, _ = _settings(qtbot, tmp_path)
    assert page.pages["mcp"].text() == "mcp-real"
    page.register_page("rules", QLabel("rules-real"))
    assert page.pages["rules"].text() == "rules-real"
    assert page.stack.indexOf(page.scrolls["rules"]) == 5
    with pytest.raises(KeyError):
        register_page("nope", lambda b: QLabel())


def test_models_page(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path, 1)
    m = page.models
    m.model_combo.setCurrentIndex(m.model_combo.findData("local-7b"))
    assert b.get_config("models")["model"] == "local-7b"
    m.small_combo.setCurrentIndex(m.small_combo.findData("mock-large"))
    assert b.get_config("models")["small_model"] == "mock-large"
    card = m.cards()[0]
    assert isinstance(card.enabled, ToggleSwitch)
    card.timeout.setValue(120)
    card.chunk_timeout.setValue(15)
    conf = b.get_config("models")["providers"][card.provider.id]
    assert conf == {"timeout": 120, "chunk_timeout": 15}
    card.enabled.setChecked(False)
    assert not ProviderStore(tmp_path / "p.json").list()[0].enabled


def test_models_test_connection_async(qtbot, tmp_path):
    from braid.theme.palette import qcolor

    page, _ = _settings(qtbot, tmp_path, 1)
    card = page.models.cards()[0]
    assert card._test_timer.parent() is card
    card.test_connection()
    assert card.test_result.text() == "测试中…" and not card.test_btn.isEnabled()
    qtbot.waitUntil(lambda: card.test_btn.isEnabled(), timeout=2000)
    assert card.test_result.property("tone") == "success"
    assert qcolor("success").name() in card.test_result.styleSheet()
    card.base_url.setText("bad")
    card.test_connection()
    qtbot.waitUntil(lambda: card.test_btn.isEnabled(), timeout=2000)
    assert card.test_result.property("tone") == "danger"


def test_keyring_notice_once(qtbot, tmp_path):
    import keyring
    from keyring.backends import fail
    from PySide6.QtWidgets import QLabel

    from braid.core import secrets

    keyring.set_keyring(fail.Keyring())
    page, _ = _settings(qtbot, tmp_path, 2)
    hits = [w for w in page.findChildren(QLabel) if w.text() == secrets.INSTALL_HINT]
    assert hits == [page.models.notice] and not page.models.notice.isHidden()
    lay = page.models.layout()
    idx = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert idx.index(page.models.notice) == idx.index(page.models.header) + 1


def test_permissions_page(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    p: PermissionsPage = page.pages["permissions"]
    assert set(p.segments) == {"edit", "bash", "webfetch"}
    assert p.segments["edit"].keys() == ["allow", "ask", "deny"]
    p.segments["bash"].set_value("deny", emit=True)
    assert b.get_config("permissions")["bash"] == "deny"
    rules = p.rules()
    assert rules[0].value() == {"pattern": "rm -rf *", "action": "deny"}
    row = p.add_rule("npm *", "allow")
    assert {"pattern": "npm *", "action": "allow"} in b.get_config("permissions")["bash_rules"]
    p.remove_rule(row)
    p.remove_rule(p.rules()[0])
    assert b.get_config("permissions")["bash_rules"] == [
        {"pattern": "git status", "action": "allow"}
    ]


def test_general_page(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    g: GeneralPage = page.pages["general"]
    assert g.theme.keys() == ["system", "light", "dark"]
    assert g.autoupdate.keys() == ["auto", "notify", "off"]
    g.autoupdate.set_value("off", emit=True)
    g.font_size.setValue(16)
    g.language.setCurrentIndex(g.language.findData("en"))
    g.shell.setText("/bin/zsh")
    g.shell.editingFinished.emit()
    conf = b.get_config("general")
    assert (conf["autoupdate"], conf["font_size"], conf["language"], conf["shell"]) == (
        "off", 16, "en", "/bin/zsh",
    )  # fmt: skip


def test_theme_wired_to_app(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    from braid.ui.main_window import MainWindow

    app = QApplication.instance()
    b = MockBackend()
    w = MainWindow(b)
    qtbot.addWidget(w)
    w.show_settings(True)
    g: GeneralPage = w.settings_page.pages["general"]
    try:
        g.theme.set_value("dark", emit=True)
        assert app.property("braidDark") is True
        from braid.theme import load_qss

        assert app.styleSheet() == load_qss("dark")
        g.theme.set_value("light", emit=True)
        assert app.property("braidDark") is False
    finally:
        app.setProperty("braidDark", False)
        app.setStyleSheet("")


# ---- 1280×800 不出滚动条 ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_page_fits_800(qtbot, tmp_path, monkeypatch, theme):
    import keyring
    from keyring.backends import fail

    from braid.backends.mock import MockBackend as MB
    from braid.theme import load_qss
    from braid.ui.main_window import MainWindow

    keyring.set_keyring(fail.Keyring())  # 最坏情况：页顶有钥匙串提示
    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    store = ProviderStore()
    store.upsert(Provider(name="OpenAI", base_url="https://api.openai.com/v1"))
    store.upsert(Provider(name="DeepSeek", base_url="https://api.deepseek.com/v1"))
    app = QApplication.instance()
    app.setProperty("braidDark", theme == "dark")
    w = MainWindow(MB())
    w.setStyleSheet(load_qss(theme))
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    w.set_panel_open(True, animate=False)
    w.show_settings(True)
    qtbot.waitExposed(w)
    sp = w.settings_page
    try:
        assert len(sp.models.cards()) == 2
        # #49：进设置页自动收起右栏；再手动打开右栏（中栏最窄）也要放得下
        for panel_open in (False, True):
            if panel_open:
                w.set_panel_open(True, animate=False)
            assert w.panel_open() == panel_open
            for key, _ in NAV:
                sp.show_section(key)
                qtbot.wait(20)
                sc = sp.scrolls[key]
                assert sc.verticalScrollBar().maximum() == 0, (key, panel_open)
                assert sc.overlay_bar.isHidden(), key
                assert sc.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    finally:
        app.setProperty("braidDark", False)


# ---- 设计走查 5 项 ----


def test_number_field_unit(qtbot):
    from braid.theme import load_qss
    from braid.ui.settings.widgets import number_with_unit

    f = NumberField(30, 1, 600)
    box = number_with_unit(f, "秒")
    qtbot.addWidget(box)
    box.setStyleSheet(load_qss("light"))
    box.show()
    assert f.width() == 64
    assert f.alignment() & Qt.AlignmentFlag.AlignRight
    assert box.unit.text() == "秒" and box.unit.objectName() == "fieldUnit"
    assert box.unit.mapTo(box, QPoint(0, 0)).x() > f.mapTo(box, QPoint(0, 0)).x()
    line = next(x for x in load_qss("light").splitlines() if x.startswith("#fieldUnit"))
    from braid.theme.palette import tokens

    assert tokens(False)["text3"] in line


def test_provider_card_units_and_result_left(qtbot, tmp_path):
    page, _ = _settings(qtbot, tmp_path, 1)
    page.resize(900, 760)
    page.show()
    qtbot.waitExposed(page)
    card = page.models.cards()[0]
    for f in (card.timeout, card.chunk_timeout):
        assert f.width() == 64
        assert f.parentWidget().unit.text() == "秒"
    card.test_connection()
    qtbot.waitUntil(lambda: card.test_btn.isEnabled(), timeout=2000)
    assert card.test_result.text() == "已连接 · 320ms"
    rx = card.test_result.mapTo(card, QPoint(0, 0)).x() + card.test_result.width()
    assert rx <= card.test_btn.mapTo(card, QPoint(0, 0)).x()


def test_settings_combo_popup(qtbot, tmp_path):
    from braid.theme.menu import RoundedMenu
    from braid.ui.settings.widgets import SettingsCombo

    page, _ = _settings(qtbot, tmp_path)
    cb = page.models.model_combo
    assert isinstance(cb, SettingsCombo)
    assert cb.arrow_rect().width() == 12
    assert cb.arrow_rect().right() < cb.width()
    menu = cb.build_popup()
    assert isinstance(menu, RoundedMenu) and menu.radius == 10
    assert menu.property("role") == "comboPopup"
    acts = menu.actions()
    assert [a.text() for a in acts] == [cb.itemText(i) for i in range(cb.count())]
    assert [a.isChecked() for a in acts].index(True) == cb.currentIndex()
    acts[2].trigger()
    assert cb.currentIndex() == 2
    from braid.theme import load_qss
    from braid.theme.palette import tokens

    for theme, dark in (("light", False), ("dark", True)):
        qss = load_qss(theme)
        line = next(x for x in qss.splitlines() if 'comboPopup"]::item:checked' in x)
        assert tokens(dark)["row_sel"] in line


def test_segmented_block_per_theme():
    from braid.theme.palette import qcolor

    assert SegmentedControl.block_color(False) == qcolor("surface", False)
    assert SegmentedControl.block_color(True) == qcolor("active", True)


def test_bash_rule_delete_icon(qtbot, tmp_path):
    from braid.theme.palette import qcolor
    from braid.ui.settings.widgets import CloseIconButton

    page, b = _settings(qtbot, tmp_path)
    row = page.pages["permissions"].rules()[0]
    assert isinstance(row.remove, CloseIconButton) and row.remove.size().width() == 16
    assert row.remove.icon_color() == qcolor("text3")
    row.remove.hovered = True
    assert row.remove.icon_color() == qcolor("danger")
    row.remove.click()
    assert len(b.get_config("permissions")["bash_rules"]) == 1


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_row_labels_regular_weight(qtbot, tmp_path, theme):
    from PySide6.QtGui import QFont

    from braid.theme import load_qss
    from braid.theme.palette import qcolor

    page, _ = _settings(qtbot, tmp_path, 1)
    page.setStyleSheet(load_qss(theme))
    page.show()
    qtbot.waitExposed(page)
    rows = [r for p in page.pages.values() for c in p.findChildren(SettingCard) for r in c.rows()]
    assert len(rows) >= 10
    for r in rows:
        r.label.ensurePolished()
        assert r.label.font().weight() == QFont.Weight.Normal, r.label.text()
        assert not r.label.font().bold()
    line = next(x for x in load_qss(theme).splitlines() if x.startswith("#settingLabel"))
    assert "font-weight: normal" in line
    assert qcolor("text", theme == "dark").name().upper() in line.upper()
    # 页标题才加粗（有真实粗字面时）
    from braid.ui.settings.widgets import title_weight

    t = page.models.header.title.font()
    assert t.weight() == title_weight(t)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_descriptions_use_text2(qtbot, tmp_path, theme):
    """页头副标题与卡片组标题这类说明文字一律 text2。"""
    from braid.theme import load_qss
    from braid.theme.palette import qcolor

    dark = theme == "dark"
    app = QApplication.instance()
    app.setProperty("braidDark", dark)
    try:
        page, _ = _settings(qtbot, tmp_path, 1)
        page.setStyleSheet(load_qss(theme))
        page.show()
        qtbot.waitExposed(page)
        want = qcolor("text2", dark).name()
        labels = []
        for key in ("models", "permissions", "general"):
            sub = page.pages[key].header.subtitle
            assert sub.text()
            labels.append(sub)
            labels += [c.title for c in page.pages[key].findChildren(SettingCard) if c.title]
        assert any("确认" in lab.text() for lab in labels)
        assert any("bash" in lab.text() for lab in labels)
        for lab in labels:
            lab.ensurePolished()
            assert lab.palette().color(lab.foregroundRole()).name() == want, lab.text()
    finally:
        app.setProperty("braidDark", False)
