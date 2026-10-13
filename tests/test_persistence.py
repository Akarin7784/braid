from keyring.backends import fail

from braid.core import secrets
from braid.core.providers import Provider, ProviderStore
from braid.core.session_store import SessionStore


def test_provider_roundtrip_without_key(tmp_path):
    store = ProviderStore(tmp_path / "p.json")
    p = Provider(name="OpenAI", kind="openai", models=["gpt-x"])
    store.upsert(p)
    assert secrets.set_key(p.id, "sk-123") is True
    reloaded = ProviderStore(tmp_path / "p.json")
    assert reloaded.get(p.id) == p
    assert "sk-123" not in (tmp_path / "p.json").read_text()
    assert secrets.get_key(p.id) == "sk-123"


def test_remove_provider_deletes_key(tmp_path, memory_keyring):
    store = ProviderStore(tmp_path / "p.json")
    p = Provider(name="X")
    store.upsert(p)
    secrets.set_key(p.id, "k")
    store.remove(p.id)
    assert secrets.get_key(p.id) is None and memory_keyring.store == {}


def test_fail_backend_keeps_key_in_memory_only(tmp_path):
    import keyring

    keyring.set_keyring(fail.Keyring())
    assert secrets.keyring_available() is False
    assert secrets.set_key("p1", "secret") is False
    assert secrets.get_key("p1") == "secret"
    assert not any("secret" in f.read_text() for f in tmp_path.rglob("*") if f.is_file())


def test_sessions_pin_order_and_delete(tmp_path):
    s = SessionStore(tmp_path / "s.json")
    s.upsert("a", "A", updated_at=1)
    s.upsert("b", "B", updated_at=2)
    s.upsert("c", "C", updated_at=3)
    s.set_pinned("a", True)
    s.delete_session("c")
    ids = [r.id for r in SessionStore(tmp_path / "s.json").list_sessions()]
    assert ids == ["a", "b"]
    assert SessionStore(tmp_path / "s.json").list_sessions()[0].pinned is True
