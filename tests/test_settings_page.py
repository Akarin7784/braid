import pytest
from PySide6.QtCore import Qt

from braid.core import secrets
from braid.core.providers import Provider, ProviderStore
from braid.ui.settings_page import SAVED_TEXT, SettingsPage, mask_key


def _page(qtbot, tmp_path):
    store = ProviderStore(tmp_path / "p.json")
    page = SettingsPage(store)
    qtbot.addWidget(page)
    return page, store


def test_mask_key():
    assert mask_key("sk-abcdef1234") == "••••1234"
    assert mask_key(None) == ""


def test_add_provider_and_persist(qtbot, tmp_path):
    page, store = _page(qtbot, tmp_path)
    assert page.models.cards() == []
    page.models.add_card.click()
    assert len(page.models.cards()) == 1
    assert len(ProviderStore(tmp_path / "p.json").list()) == 1


def test_key_saved_masked_and_hint(qtbot, tmp_path):
    page, store = _page(qtbot, tmp_path)
    prov = page.models.add_provider()
    card = page.models.cards()[0]
    card.key.edit.setText("sk-secret9876")
    card.key.edit.editingFinished.emit()
    assert secrets.get_key(prov.id) == "sk-secret9876"
    assert card.key.edit.text() == "••••9876"
    assert card.key.hint.text() == SAVED_TEXT
    card.key.toggle_reveal()
    assert card.key.edit.text() == "sk-secret9876"
    assert "sk-secret" not in (tmp_path / "p.json").read_text(encoding="utf-8")


def test_fail_backend_shows_warning(qtbot, tmp_path):
    import keyring
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())
    store = ProviderStore(tmp_path / "p.json")
    store.upsert(Provider(name="X"))
    page = SettingsPage(store)
    qtbot.addWidget(page)
    card = page.models.cards()[0]
    assert not card.warning.isHidden()
    assert card.warning.text() == secrets.INSTALL_HINT


def test_remove_via_confirm(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page, store = _page(qtbot, tmp_path)
    prov = page.models.add_provider()
    secrets.set_key(prov.id, "k")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    card = page.models.cards()[0]
    assert [a.text() for a in card.build_menu().actions()] == ["删除服务商"]
    card.confirm_remove()
    qtbot.waitUntil(lambda: page.models.cards() == [])
    assert store.list() == [] and secrets.get_key(prov.id) is None


def test_eye_icon_follows_state(qtbot, tmp_path):
    page, store = _page(qtbot, tmp_path)
    page.models.add_provider()
    key = page.models.cards()[0].key
    assert key.eye.property("eyeState") == "closed" and not key.eye.icon().isNull()
    key.toggle_reveal()
    assert key.eye.property("eyeState") == "open" and not key.eye.icon().isNull()


@pytest.mark.parametrize("width", [1280, 900, 640])
def test_settings_no_horizontal_scrollbar_or_size_grip(
    qtbot, tmp_path, monkeypatch, width: int
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QScrollBar, QSizeGrip

    from braid.backends.mock import MockBackend
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    ProviderStore(tmp_path / "providers.json").upsert(
        Provider(name="OpenAI", base_url="https://api.example.com/v1/chat/completions")
    )
    from braid.theme import load_qss

    w = MainWindow(MockBackend())
    w.setStyleSheet(load_qss("light"))  # 带上真实内边距，否则量不出裁切
    qtbot.addWidget(w)
    w.resize(width, 800)
    w.show()
    w.show_settings(True)
    qtbot.wait(50)
    page = w.findChild(SettingsPage)
    assert page is not None
    assert page.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    bars = [
        b
        for b in page.findChildren(QScrollBar)
        if b.orientation() == Qt.Orientation.Horizontal and b.isVisible()
    ]
    assert bars == []
    assert [g for g in w.findChildren(QSizeGrip) if g.isVisible()] == []
    card = page.models.cards()[0]
    vp = page.scroll_area.viewport()
    for wid in (card, card.base_url, card.key.edit, card.key.eye):
        assert wid.isVisible()
        left = wid.mapTo(vp, QPoint(0, 0)).x()
        assert left >= 0
        assert left + wid.width() <= vp.width(), (type(wid).__name__, width)
    # 输入框随宽度伸缩但不被压成 0
    assert card.key.edit.width() > 40
    # 中栏不能比自身下限窄（否则整列被分割器裁掉）
    center = w.chat_view.parentWidget()
    assert center.width() >= center.minimumSizeHint().width()


def test_header_texts(qtbot, tmp_path):
    from braid.ui.settings_page import PAGE_SUBTITLE, PAGE_TITLE

    page, _ = _page(qtbot, tmp_path)
    assert page.models.title.text() == PAGE_TITLE == "模型与服务"
    assert page.models.subtitle.text() == PAGE_SUBTITLE
    assert page.models.title.objectName() == "settingsTitle"
    assert page.models.subtitle.objectName() == "settingsSubtitle"


def test_add_card_size_and_empty_state(qtbot, tmp_path):
    page, _ = _page(qtbot, tmp_path)
    page.resize(900, 700)
    page.show()
    qtbot.waitExposed(page)
    m = page.models
    assert not m.empty.isHidden()
    m.add_provider()
    qtbot.wait(10)
    assert m.empty.isHidden()
    card = m.cards()[0]
    assert m.add_card.height() == 64
    assert m.add_card.width() == card.width()
    card.store.remove(card.provider.id)
    m.rebuild()
    assert not m.empty.isHidden()


def test_overlay_scrollbar_hidden_when_idle(qtbot, tmp_path):
    from PySide6.QtWidgets import QSizeGrip  # noqa: F401

    store = ProviderStore(tmp_path / "p.json")
    for i in range(8):
        store.upsert(Provider(name=f"P{i}"))
    page = SettingsPage(store)
    qtbot.addWidget(page)
    page.resize(900, 400)
    page.show()
    qtbot.waitExposed(page)
    area = page.scroll_area
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    bar = page.vbar
    assert bar.width() == 6
    assert bar.idle_timer.parent() is bar
    assert bar.isHidden()
    assert bar.maximum() > 0
    area.verticalScrollBar().setValue(50)
    assert bar.isVisible()
    assert bar.value() == 50
    bar.idle_timer.setInterval(20)
    bar.idle_timer.start()
    qtbot.waitUntil(bar.isHidden, timeout=1000)


def test_nav_selection_uses_row_sel():
    from braid.theme import load_qss
    from braid.theme.palette import tokens

    for theme, dark in (("light", False), ("dark", True)):
        qss = load_qss(theme)
        line = next(x for x in qss.splitlines() if x.startswith("#settingsNav::item:selected"))
        assert tokens(dark)["row_sel"] in line
        assert tokens(dark)["active"] not in line


def test_title_weight_needs_real_cjk_face(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QFont, QFontDatabase

    from braid.ui import settings_page as sp

    page, _ = _page(qtbot, tmp_path)
    f = page.models.title.font()
    assert f.pixelSize() == 18
    assert f.weight() == sp.title_weight(f)
    monkeypatch.setattr(sp, "resolved_cjk_family", lambda _f: "X")
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular"]))
    assert sp.title_weight(f) == QFont.Weight.Normal
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular", "Bold"]))
    assert sp.title_weight(f) == QFont.Weight.DemiBold
    monkeypatch.setattr(sp, "resolved_cjk_family", lambda _f: None)
    assert sp.title_weight(f) == QFont.Weight.Normal
