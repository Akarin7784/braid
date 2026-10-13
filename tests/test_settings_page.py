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
