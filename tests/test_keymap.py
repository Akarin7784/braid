from PySide6.QtGui import QKeySequence

from braid.core import keymap


def test_ids_unique_and_groups_known():
    ids = [a.id for a in keymap.ACTIONS]
    assert len(ids) == len(set(ids))
    groups = {g for g, _ in keymap.GROUPS}
    assert all(a.group in groups for a in keymap.ACTIONS)


def test_input_group_order():
    names = [a.name for a in keymap.ACTIONS if a.group == "input"]
    assert names == ["发送", "换行", "命令面板", "切换模型"]


def test_defaults_portable_roundtrip_and_distinct():
    seqs = [a.default for a in keymap.ACTIONS]
    assert len(seqs) == len(set(seqs))
    for s in seqs:
        ks = QKeySequence(s)
        assert not ks.isEmpty()
        assert ks.toString(QKeySequence.SequenceFormat.PortableText) == s


def test_toggle_right_avoids_altgr():
    assert "Alt" not in keymap.BY_ID["panel.toggle_right"].default


def test_send_and_newline_not_clearable():
    assert not keymap.BY_ID["input.send"].clearable
    assert not keymap.BY_ID["input.newline"].clearable


def test_effective_merges_and_guards():
    eff = keymap.effective(
        {"session.new": "Ctrl+Shift+N", "input.send": "", "session.search": "", "x.y": "A"}
    )
    assert eff["session.new"] == "Ctrl+Shift+N"
    assert eff["input.send"] == "Return"
    assert eff["session.search"] == ""
    assert "x.y" not in eff
