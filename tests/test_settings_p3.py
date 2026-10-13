"""P3：快捷键、高级两页。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.core import keymap
from braid.core.providers import ProviderStore
from braid.theme import load_qss
from braid.theme.palette import tokens
from braid.ui.settings.advanced import (
    DIALOG_W,
    IGNORE_HINT,
    SNAPSHOT_NOTE,
    AdvancedPage,
    ResetDialog,
)
from braid.ui.settings.keybinds import (
    CHIP_GAP,
    CHIP_H,
    NOTE_MS,
    RECORD_TEXT,
    SEARCH_H,
    UNCLEARABLE_TEXT,
    KeybindsPage,
    display_parts,
    split_portable,
)
from braid.ui.settings.rules import InstructionRow
from braid.ui.settings.widgets import ROW_H, SettingCard
from braid.ui.settings_page import SettingsPage


def _settings(qtbot, tmp_path, backend=None):
    b = backend or MockBackend()
    page = SettingsPage(ProviderStore(tmp_path / "p.json"), backend=b)
    qtbot.addWidget(page)
    return page, b


def _kb(qtbot, mac=False):
    b = MockBackend()
    page = KeybindsPage(b, mac=mac)
    qtbot.addWidget(page)
    page.resize(760, 700)
    page.show()
    qtbot.waitExposed(page)
    return page, b


def _line(theme: str, start: str) -> str:
    return next(x for x in load_qss(theme).splitlines() if x.startswith(start))


def _press(qtbot, row, key, mods=Qt.KeyboardModifier.NoModifier):
    qtbot.keyClick(row, key, mods)


# ---- 注册、数据、占位页 ----


def test_pages_registered_and_mock(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    assert isinstance(page.pages["keybinds"], KeybindsPage)
    assert isinstance(page.pages["advanced"], AdvancedPage)
    assert b.get_config("keybinds") == {}
    adv = b.get_config("advanced")
    assert adv["auto_compact"] is True and adv["keep_tokens"] == 20000
    assert adv["snapshot"] is True and adv["watcher_ignore"] == ["dist/**", "*.log"]


def test_backend_replace_and_reset():
    b = MockBackend()
    seen: list[str] = []
    b.config_changed.connect(seen.append)
    b.replace_config("keybinds", {"session.new": "Ctrl+M"})
    assert b.get_config("keybinds") == {"session.new": "Ctrl+M"}
    b.replace_config("keybinds", {})
    assert b.get_config("keybinds") == {}
    b.set_config("advanced", {"snapshot": False})
    seen.clear()
    b.reset_config()
    assert b.get_config("advanced")["snapshot"] is True
    assert "keybinds" in seen and "advanced" in seen
    with pytest.raises(KeyError):
        b.replace_config("nope", {})


# ---- 键帽显示 ----


def test_split_and_mac_symbols():
    assert split_portable("Ctrl+Shift+]") == (["Ctrl", "Shift"], "]")
    assert split_portable("Ctrl++") == (["Ctrl"], "+")
    assert split_portable("") == ([], "")
    assert display_parts("Ctrl+Shift+B", mac=True) == ["⇧", "⌘", "B"]
    assert display_parts("Ctrl+Alt+Shift+Meta+K", mac=True) == ["⌃", "⌥", "⇧", "⌘", "K"]
    assert display_parts("Shift+Return", mac=True) == ["⇧", "↩"]
    assert display_parts("Ctrl+Shift+B", mac=False) == ["Ctrl", "Shift", "B"]
    assert display_parts("Alt+Meta+X", mac=False) == ["Alt", "Win", "X"]
    assert display_parts("Return", mac=False) == ["Enter"]
    assert "+" not in display_parts("Ctrl+Shift+B", mac=False)


def test_chips_style_and_mac_page(qtbot):
    page, _b = _kb(qtbot, mac=True)
    row = page.rows["panel.toggle_right"]
    assert row.chips.texts() == ["⇧", "⌘", "B"]
    chip = row.chips.chips[0]
    assert chip.height() == CHIP_H == 22
    assert row.chips.lay.spacing() == CHIP_GAP == 4
    assert QFontInfo(chip.font()).pixelSize() == 12
    pc, _ = _kb(qtbot, mac=False)
    assert pc.rows["panel.toggle_right"].chips.texts() == ["Ctrl", "Shift", "B"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_keybinds_qss(theme):
    t = tokens(theme == "dark")
    chip = _line(theme, "QLabel#keyChip")
    assert t["control"] in chip and "border-radius: 6px" in chip
    g = _line(theme, "#keyGroupTitle")
    assert t["text3"] in g and "11px" in g
    assert t["text3"] in _line(theme, "QLabel#keyRecord")
    assert t["text3"] in _line(theme, "#keyNote")
    c = _line(theme, "#keyConflict")
    assert t["warning"] in c and "12px" in c
    assert t["text3"] in _line(theme, "QToolButton#keyReset {")
    assert t["text"] in _line(theme, "QToolButton#keyReset:hover")


# ---- 布局 ----


def test_keybinds_layout(qtbot):
    page, _b = _kb(qtbot)
    assert page.search.height() == SEARCH_H == 36
    assert list(page.cards) == [g for g, _ in keymap.GROUPS]
    for gid, gname in keymap.GROUPS:
        card = page.cards[gid]
        assert isinstance(card, SettingCard) and card.title is not None
        assert card.title.text() == gname and card.title.objectName() == "keyGroupTitle"
    assert set(page.rows) == set(keymap.BY_ID)
    assert all(r.main.height() == ROW_H == 44 for r in page.rows.values())
    assert page.reset_all_btn.text() == "全部恢复默认"
    # 只有卡片列表区在滚动区里，搜索框和标题在外面
    assert page.list_scroll.widget().isAncestorOf(page.cards["session"])
    assert not page.list_scroll.isAncestorOf(page.search)
    assert not page.list_scroll.isAncestorOf(page.reset_all_btn)


def test_search_filters(qtbot):
    page, _b = _kb(qtbot)
    page.search.setText("模型")
    vis = [aid for aid, r in page.rows.items() if r.isVisibleTo(page)]
    assert vis == ["input.model_menu"]
    assert not page.cards["session"].isVisibleTo(page)
    page.search.setText("ctrl shift b")
    vis = {aid for aid, r in page.rows.items() if r.isVisibleTo(page)}
    assert vis == {"panel.toggle_right"}
    page.search.setText("zzzz")
    assert page.empty.isVisibleTo(page)
    page.search.setText("")
    assert all(r.isVisibleTo(page) for r in page.rows.values())


# ---- 录制 ----


def test_record_set_cancel(qtbot):
    page, b = _kb(qtbot)
    row = page.rows["session.new"]
    qtbot.mouseClick(row, Qt.MouseButton.LeftButton, pos=row.main.geometry().center())
    assert row.recording and row.record_box.isVisible() and not row.chips.isVisible()
    assert row.record_box.text() == RECORD_TEXT
    _press(qtbot, row, Qt.Key.Key_Escape)
    assert not row.recording and row.chips.isVisible()
    assert b.get_config("keybinds") == {}
    page.toggle_record(row)
    _press(
        qtbot, row, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier
    )  # 只按修饰键：继续等
    assert row.recording
    _press(
        qtbot,
        row,
        Qt.Key.Key_M,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert b.get_config("keybinds") == {"session.new": "Ctrl+Alt+M"}
    assert row.chips.texts() == ["Ctrl", "Alt", "M"]
    assert row.reset.isVisible()
    # 只有一行在录制
    page.toggle_record(row)
    page.toggle_record(page.rows["session.search"])
    assert not row.recording and page.recording_row() is page.rows["session.search"]


def test_backspace_clears(qtbot):
    page, b = _kb(qtbot)
    row = page.rows["session.switch"]
    page.toggle_record(row)
    _press(qtbot, row, Qt.Key.Key_Backspace)
    assert b.get_config("keybinds") == {"session.switch": ""}
    assert row.chips.texts() == [] and row.reset.isVisible()


def test_unclearable(qtbot):
    page, b = _kb(qtbot)
    row = page.rows["input.send"]
    assert not keymap.BY_ID["input.send"].clearable
    page.toggle_record(row)
    _press(qtbot, row, Qt.Key.Key_Backspace)
    assert b.get_config("keybinds") == {}
    assert row.chips.texts() == ["Enter"]
    assert row.note.isVisible() and row.note.text() == UNCLEARABLE_TEXT
    assert row.note_timer.parent() is row and row.note_timer.interval() == NOTE_MS == 1500
    assert t3_line("light", "#keyNote")
    qtbot.waitUntil(lambda: not row.note.isVisible(), timeout=NOTE_MS + 1000)
    assert row.findChildren(type(row.reset), "keyLock") == []  # 不显示锁图标


def t3_line(theme: str, sel: str) -> bool:
    return tokens(theme == "dark")["text3"] in _line(theme, sel)


def test_conflict_and_replace(qtbot):
    page, b = _kb(qtbot)
    row = page.rows["session.search"]
    page.toggle_record(row)
    _press(qtbot, row, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)  # 收起侧栏的键
    assert b.get_config("keybinds") == {}  # 冲突时不保存
    assert row.conflict.isVisible()
    assert row.conflict_label.text() == "与「收起侧栏」冲突"
    assert row.replace_btn.isVisible()
    row.replace_btn.click()
    assert b.get_config("keybinds") == {"session.search": "Ctrl+B", "panel.toggle_sidebar": ""}
    assert not row.conflict.isVisible()
    assert page.rows["panel.toggle_sidebar"].chips.texts() == []
    assert page.rows["panel.toggle_sidebar"].reset.isVisible()


def test_conflict_with_unclearable_no_replace(qtbot):
    page, b = _kb(qtbot)
    row = page.rows["session.new"]
    page.toggle_record(row)
    _press(qtbot, row, Qt.Key.Key_Return)  # 发送（不可清空）
    assert row.conflict.isVisible() and row.conflict_label.text() == "与「发送」冲突"
    assert not row.replace_btn.isVisible()
    page.replace("session.new", "Return", "input.send")  # 直接调用也不生效
    assert b.get_config("keybinds") == {}


def test_reset_one_and_all(qtbot):
    page, b = _kb(qtbot)
    b.replace_config("keybinds", {"session.new": "Ctrl+M", "app.settings": "Ctrl+;"})
    r = page.rows["session.new"]
    assert r.reset.isVisible() and r.reset.width() == 16 and r.reset.text() == "↺"
    assert not page.rows["session.switch"].reset.isVisible()
    r.reset.click()
    assert b.get_config("keybinds") == {"app.settings": "Ctrl+;"}
    assert not r.reset.isVisible() and r.chips.texts() == ["Ctrl", "N"]
    assert page.reset_all_btn.isEnabled()
    page.reset_all_btn.click()
    assert b.get_config("keybinds") == {}
    assert not page.reset_all_btn.isEnabled()
    # 录回默认值不算改动
    page.toggle_record(r)
    _press(qtbot, r, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert b.get_config("keybinds") == {}


# ---- 高级 ----


def _adv(qtbot, backend=None):
    b = backend or MockBackend()
    page = AdvancedPage(b)
    qtbot.addWidget(page)
    page.resize(760, 760)
    page.show()
    qtbot.waitExposed(page)
    return page, b


def test_advanced_context(qtbot):
    page, b = _adv(qtbot)
    assert page.keep_tokens.value() == 20000 and page.keep_box.unit.text() == "tokens"
    assert page.keep_row.isEnabled()
    page.keep_tokens.setValue(32000)
    assert b.get_config("advanced")["keep_tokens"] == 32000
    page.auto_compact.click()
    assert b.get_config("advanced")["auto_compact"] is False
    assert not page.keep_row.isEnabled() and not page.keep_tokens.isEnabled()
    assert page.keep_row.property("dim") is True
    t3 = tokens(False)["text3"]
    assert t3 in _line("light", '#settingRow[dim="true"] QLabel#settingLabel')
    page.auto_compact.click()
    assert page.keep_row.isEnabled()


def test_advanced_snapshot_and_watch(qtbot):
    page, b = _adv(qtbot)
    assert page.snap_note.text() == SNAPSHOT_NOTE
    t = tokens(False)
    note = _line("light", "#settingDesc, #snapshotNote")
    assert t["text2"] in note and "12px" in note
    page.snapshot.click()
    assert b.get_config("advanced")["snapshot"] is False
    assert (
        page.ignore_hint.text() == IGNORE_HINT and page.ignore_hint.objectName() == "settingsEmpty"
    )
    rows = page.ignore_rows()
    assert [r.path for r in rows] == ["dist/**", "*.log"]
    assert all(
        isinstance(r, InstructionRow) and QFontInfo(r.label.font()).fixedPitch() for r in rows
    )
    page.add_btn.click()
    assert page.add_row.isVisible()
    qtbot.keyClicks(page.input, "coverage/")
    qtbot.keyClick(page.input, Qt.Key.Key_Return)
    assert b.get_config("advanced")["watcher_ignore"] == ["dist/**", "*.log", "coverage/"]
    assert not page.add_row.isVisible()
    assert not page.add_ignore("coverage/")
    page.ignore_rows()[0].remove.click()
    qtbot.waitUntil(lambda: [r.path for r in page.ignore_rows()] == ["*.log", "coverage/"])


def test_reset_card(qtbot):
    page, _b = _adv(qtbot)
    gap = page.reset_card.geometry().top() - page.watch_card.geometry().bottom() - 1
    assert gap == 32
    assert (
        page.reset_label.text() == "重置全部设置" and page.reset_desc.objectName() == "settingDesc"
    )
    assert page.reset_btn.text() == "重置…" and page.reset_btn.objectName() == "dangerTextButton"
    t = tokens(False)
    assert t["danger"] in _line("light", "QToolButton#dangerTextButton {")
    hover = _line("light", "QToolButton#dangerTextButton:hover")
    r, g, bb = (int(t["danger"][i : i + 2], 16) for i in (1, 3, 5))
    assert f"rgba({r}, {g}, {bb}, 31)" in hover  # 12% danger


def test_reset_dialog_ui(qtbot):
    page, _b = _adv(qtbot)
    dlg = page.open_reset_dialog()
    qtbot.addWidget(dlg)
    assert isinstance(dlg, ResetDialog) and dlg.isVisible()
    assert dlg.card_rect().width() == DIALOG_W == 400
    assert dlg.title.text() == "重置全部设置？"
    assert not dlg.delete_keys.isChecked()
    assert dlg.delete_keys.text() == "同时删除钥匙串里的 API Key"
    assert dlg.cancel_btn.text() == "取消" and dlg.ok_btn.text() == "重置"
    assert dlg.ok_btn.geometry().left() > dlg.cancel_btn.geometry().left()
    dlg.delete_keys.setChecked(True)
    assert dlg.ok_btn.text() == "重置并删除 Key"
    dlg.delete_keys.setChecked(False)
    assert dlg.ok_btn.text() == "重置"
    for theme in ("light", "dark"):
        t = tokens(theme == "dark")
        ok = _line(theme, "QToolButton#dangerButton")
        assert t["danger"] in ok and "#FFFFFF" in ok.upper()
    dlg.cancel_btn.click()
    assert not dlg.isVisible()


def _spy_secrets(monkeypatch):
    from braid.core import secrets

    deleted: list[str] = []
    monkeypatch.setattr(secrets, "delete_key", deleted.append)
    return deleted


def test_reset_keeps_keychain_by_default(qtbot, monkeypatch):
    deleted = _spy_secrets(monkeypatch)
    page, b = _adv(qtbot)
    page.provider_ids = lambda: ["openai", "anthropic"]
    b.set_config("advanced", {"snapshot": False})
    b.replace_config("keybinds", {"session.new": "Ctrl+M"})
    dlg = page.open_reset_dialog()
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(page.reset_done):
        dlg.ok_btn.click()
    assert b.get_config("advanced")["snapshot"] is True
    assert b.get_config("keybinds") == {}
    assert deleted == []


def test_reset_with_delete_keys(qtbot, monkeypatch):
    deleted = _spy_secrets(monkeypatch)
    page, _b = _adv(qtbot)
    page.provider_ids = lambda: ["openai", "anthropic"]
    dlg = page.open_reset_dialog()
    qtbot.addWidget(dlg)
    dlg.delete_keys.setChecked(True)
    dlg.ok_btn.click()
    assert deleted == ["openai", "anthropic"]


def test_reset_cancel_changes_nothing(qtbot, monkeypatch):
    deleted = _spy_secrets(monkeypatch)
    page, b = _adv(qtbot)
    b.set_config("advanced", {"snapshot": False})
    dlg = page.open_reset_dialog()
    qtbot.addWidget(dlg)
    dlg.delete_keys.setChecked(True)
    dlg.cancel_btn.click()
    assert b.get_config("advanced")["snapshot"] is False and deleted == []


def test_secrets_import_does_not_touch_keyring():
    import subprocess
    import sys

    code = "import sys; import braid.core.secrets; sys.exit(1 if 'keyring' in sys.modules else 0)"
    r = subprocess.run([sys.executable, "-c", code], check=False, env=None)
    assert r.returncode == 0


def test_reset_rebuilds_settings_pages(qtbot, tmp_path, monkeypatch):
    deleted = _spy_secrets(monkeypatch)
    page, b = _settings(qtbot, tmp_path)
    old = page.pages["advanced"]
    old.snapshot.click()
    assert b.get_config("advanced")["snapshot"] is False
    old.reset_all()
    qtbot.waitUntil(lambda: page.pages["advanced"] is not old)
    assert page.pages["advanced"].snapshot.isChecked()
    assert isinstance(page.pages["keybinds"], KeybindsPage)
    assert deleted == []


# ---- 1280×800 不出现滚动条 ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_p3_pages_fit_800(qtbot, tmp_path, monkeypatch, theme):
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    app = QApplication.instance()
    app.setProperty("braidDark", theme == "dark")
    w = MainWindow(MockBackend())
    w.setStyleSheet(load_qss(theme))
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    w.show_settings(True)
    qtbot.waitExposed(w)
    sp = w.settings_page
    try:
        for panel_open in (False, True):
            if panel_open:
                w.set_panel_open(True, animate=False)
            assert w.panel_open() == panel_open
            for key in ("keybinds", "advanced"):
                sp.show_section(key)
                qtbot.wait(30)
                assert sp.scrolls[key].verticalScrollBar().maximum() == 0, (key, panel_open)
            kp: KeybindsPage = sp.pages["keybinds"]
            sp.show_section("keybinds")
            qtbot.wait(30)
            # 12 个动作放不下时只有卡片列表区滚动（浮层细滚动条）
            inner = kp.list_scroll.verticalScrollBar()
            assert inner.maximum() > 0
            assert kp.list_scroll.overlay_bar.width() == 6
            assert kp.search.mapTo(kp, kp.search.rect().topLeft()).y() >= 0
    finally:
        app.setProperty("braidDark", False)
