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
    assert "sk-123" not in (tmp_path / "p.json").read_text(encoding="utf-8")
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
    assert not any(
        "secret" in f.read_text(encoding="utf-8") for f in tmp_path.rglob("*") if f.is_file()
    )


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


def test_project_id_grouping_and_legacy_file(tmp_path):
    import json

    path = tmp_path / "s.json"
    path.write_text(
        json.dumps({"sessions": [{"id": "old", "title": "旧", "updated_at": 5}]}), encoding="utf-8"
    )
    s = SessionStore(path)
    s.upsert("a", "A", updated_at=1, project_id="p1")
    s.upsert("b", "B", updated_at=2, project_id="p1")
    s.set_pinned("a", True)
    s.set_project("old", None)
    groups = SessionStore(path).grouped()
    assert [(k, [r.id for r in v]) for k, v in groups] == [("p1", ["a", "b"]), (None, ["old"])]


def test_qcolor_converts_rrggbbaa():
    from braid.theme.palette import qcolor, tokens

    c = qcolor("sel")
    assert tokens(False)["sel"].upper() == "#C9643233"
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (0xC9, 0x64, 0x32, 0x33)
    assert qcolor("text").alpha() == 255
