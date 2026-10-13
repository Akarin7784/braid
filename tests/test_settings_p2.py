"""P2 设置：智能体、规则与指令两页。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.core.providers import ProviderStore
from braid.theme import load_qss
from braid.theme.palette import qcolor, tokens
from braid.ui.settings.agents import (
    AGENT_ROW_H,
    EXPAND_MS,
    PROMPT_MIN_H,
    AgentsPage,
)
from braid.ui.settings.pages import NAV
from braid.ui.settings.rules import EMPTY_TEXT, RulesPage, is_glob
from braid.ui.settings.widgets import (
    ADD_CARD_H,
    AddCard,
    ChipMultiSelect,
    CloseIconButton,
    ElidedLabel,
    GrowHandle,
    SettingsCombo,
)
from braid.ui.settings_page import AddProviderCard, SettingsPage


def _settings(qtbot, tmp_path, backend=None):
    b = backend or MockBackend()
    page = SettingsPage(ProviderStore(tmp_path / "p.json"), backend=b)
    qtbot.addWidget(page)
    return page, b


def _line(theme: str, start: str) -> str:
    return next(x for x in load_qss(theme).splitlines() if x.startswith(start))


# ---- 注册与数据 ----


def test_pages_registered(qtbot, tmp_path):
    page, _ = _settings(qtbot, tmp_path)
    assert isinstance(page.pages["agents"], AgentsPage)
    assert isinstance(page.pages["rules"], RulesPage)
    assert [k for k, _ in NAV].index("agents") == page.stack.indexOf(page.scrolls["agents"])


def test_mock_agents_rules_data():
    b = MockBackend()
    a = b.get_config("agents")
    assert a["default_agent"] == "build"
    ids = [x["id"] for x in a["agents"]]
    assert ids == ["build", "plan", "review"]
    assert [x["builtin"] for x in a["agents"]] == [True, True, False]
    assert all({"name", "description", "model", "tools", "prompt"} <= set(x) for x in a["agents"])
    r = b.get_config("rules")["instructions"]
    assert any(is_glob(p) for p in r) and any(not is_glob(p) for p in r)
    assert b.count_instruction_matches("docs/*.md") > 0


# ---- AddCard ----


def test_add_card_public(qtbot):
    c = AddCard("+ 新建")
    qtbot.addWidget(c)
    assert c.height() == ADD_CARD_H == 64 and c.text() == "+ 新建"
    with qtbot.waitSignal(c.clicked):
        c.click()
    old = AddProviderCard()
    qtbot.addWidget(old)
    assert isinstance(old, AddCard) and old.text() == "+ 添加服务商"


# ---- 智能体 ----


def test_agent_rows_layout(qtbot, tmp_path):
    page, _ = _settings(qtbot, tmp_path)
    ap: AgentsPage = page.pages["agents"]
    rows = ap.list.agent_rows()
    assert [r.name.text() for r in rows] == ["构建", "规划", "代码审查"]
    assert all(r.head.height() == AGENT_ROW_H == 52 for r in rows)
    assert [r.tag is not None for r in rows] == [True, True, False]
    assert rows[0].tag.text() == "内置"
    assert rows[0].model_label.text() == "跟随默认"
    assert rows[2].model_label.text() == "Mock Fast"
    assert rows[0].desc.objectName() == "agentDesc"
    assert isinstance(ap.add_card, AddCard) and ap.add_card.text() == "+ 新建智能体"
    assert isinstance(ap.default_combo, SettingsCombo)
    assert ap.default_combo.currentData() == "build"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_agent_row_colors_qss(theme):
    dark = theme == "dark"
    t = tokens(dark)
    assert t["text"] in _line(theme, "#agentName") and "normal" in _line(theme, "#agentName")
    desc = _line(theme, "#agentDesc")
    assert t["text2"] in desc and "12px" in desc
    assert t["text3"] in _line(theme, "#agentModel")
    tag = _line(theme, "#agentTag")
    assert t["control"] in tag and "11px" in tag and "border-radius: 6px" in tag
    assert t["active"] in _line(theme, "QToolButton#toolChip:checked")


def test_default_agent_combo(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    ap: AgentsPage = page.pages["agents"]
    ap.default_combo.setCurrentIndex(ap.default_combo.findData("plan"))
    assert b.get_config("agents")["default_agent"] == "plan"


def test_expand_only_one_animated(qtbot, tmp_path):
    page, _ = _settings(qtbot, tmp_path)
    page.resize(1000, 760)
    page.show()
    page.show_section("agents")
    qtbot.waitExposed(page)
    ap: AgentsPage = page.pages["agents"]
    r0, r1 = ap.list.agent_rows()[:2]
    assert r0.anim.parent() is r0 and r0.anim.duration() == EXPAND_MS == 150
    qtbot.mouseClick(r0, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert r0.expanded and r0.anim.state() == r0.anim.State.Running
    qtbot.waitUntil(lambda: r0.anim.state() == r0.anim.State.Stopped, timeout=1000)
    assert r0.editor.isVisible() and r0.editor.height() > PROMPT_MIN_H
    ap.toggle(r1)
    assert r1.expanded and not r0.expanded
    assert ap.expanded_row() is r1
    qtbot.waitUntil(lambda: not r0.editor.isVisible(), timeout=1000)


def test_editor_fields_save(qtbot, tmp_path):
    from PySide6.QtGui import QFontInfo

    page, b = _settings(qtbot, tmp_path)
    ap: AgentsPage = page.pages["agents"]
    row = ap.list.agent_rows()[2]
    ed = row.editor
    assert ed.model.currentData() == "mock-fast"
    ed.model.setCurrentIndex(ed.model.findData(""))
    assert b.get_config("agents")["agents"][2]["model"] == ""
    assert row.model_label.text() == "跟随默认"
    assert isinstance(ed.tools, ChipMultiSelect) and ed.tools.selected() == ["read"]
    ed.tools.chips["bash"].click()
    assert b.get_config("agents")["agents"][2]["tools"] == ["read", "bash"]
    assert ed.prompt.height() == PROMPT_MIN_H == 120
    assert QFontInfo(ed.prompt.font()).fixedPitch()
    assert ed._save.parent() is ed
    ed.prompt.setPlainText("新的提示词")
    qtbot.waitUntil(lambda: b.get_config("agents")["agents"][2]["prompt"] == "新的提示词")
    assert isinstance(ed.grow, GrowHandle)
    ed.grow.grow_to(200)
    assert ed.prompt.height() == 200
    ed.grow.grow_to(50)
    assert ed.prompt.height() == PROMPT_MIN_H


def test_menu_and_delete(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    ap: AgentsPage = page.pages["agents"]
    builtin, custom = ap.list.agent_rows()[0], ap.list.agent_rows()[2]
    assert [a.text() for a in builtin.build_menu().actions()] == ["编辑"]
    acts = custom.build_menu().actions()
    assert [a.text() for a in acts] == ["编辑", "删除智能体"]
    ap.remove_agent("build")  # 内置不可删
    assert len(b.get_config("agents")["agents"]) == 3
    ap.default_combo.setCurrentIndex(2)
    acts[1].trigger()
    conf = b.get_config("agents")
    assert [a["id"] for a in conf["agents"]] == ["build", "plan"]
    assert conf["default_agent"] == "build"
    qtbot.waitUntil(lambda: len(ap.list.agent_rows()) == 2)


def test_add_agent(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    ap: AgentsPage = page.pages["agents"]
    ap.add_card.click()
    agents = b.get_config("agents")["agents"]
    assert len(agents) == 4 and agents[-1]["builtin"] is False
    assert ap.list.agent_rows()[-1].expanded
    assert ap.default_combo.count() == 4


# ---- 规则与指令 ----


def test_rules_rows(qtbot, tmp_path):
    from PySide6.QtGui import QFontInfo

    page, _ = _settings(qtbot, tmp_path)
    rp: RulesPage = page.pages["rules"]
    rows = rp.rows()
    assert [r.path for r in rows] == rp.paths()
    for r in rows:
        assert isinstance(r.label, ElidedLabel) and QFontInfo(r.label.font()).fixedPitch()
        assert isinstance(r.remove, CloseIconButton)
        assert (r.count is not None) == is_glob(r.path)
    glob_row = next(r for r in rows if r.count)
    assert glob_row.count.text().startswith("匹配 ") and glob_row.count.text().endswith(" 个文件")
    assert rp.empty.isHidden()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_rules_colors_qss(theme):
    t = tokens(theme == "dark")
    assert t["text3"] in _line(theme, "#matchCount")
    assert t["text3"] in _line(theme, "#settingsEmpty")


def test_elided_middle(qtbot):
    lab = ElidedLabel("very/long/" * 20 + "AGENTS.md")
    qtbot.addWidget(lab)
    lab.resize(120, 20)
    lab.show()
    t = lab.text()
    assert "…" in t and t.startswith("very") and t.endswith(".md")  # 中间省略
    assert lab.full_text().startswith("very/long/") and lab.toolTip() == lab.full_text()


def test_rules_add_remove_empty(qtbot, tmp_path):
    page, b = _settings(qtbot, tmp_path)
    rp: RulesPage = page.pages["rules"]
    page.show()
    page.show_section("rules")
    assert rp.add_row.isHidden()
    rp.add_btn.click()
    assert rp.add_row.isVisible() and rp.add_btn.isHidden()
    qtbot.keyClicks(rp.input, "docs/*.md")
    qtbot.keyClick(rp.input, Qt.Key.Key_Return)
    assert "docs/*.md" in b.get_config("rules")["instructions"]
    assert rp.add_row.isHidden() and rp.add_btn.isVisible()
    assert not rp.add_path("docs/*.md")  # 去重
    for p in list(rp.paths()):
        next(r for r in rp.rows() if r.path == p).remove.click()
    assert b.get_config("rules")["instructions"] == []
    assert not rp.empty.isHidden() and rp.empty.text() == EMPTY_TEXT


def test_rules_pick_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    page, b = _settings(qtbot, tmp_path)
    rp: RulesPage = page.pages["rules"]
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("/p/README.md", ""))
    )
    rp.start_add()
    rp.pick_btn.click()
    assert b.get_config("rules")["instructions"][-1] == "/p/README.md"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    rp.pick_file()  # 取消不加
    assert b.get_config("rules")["instructions"][-1] == "/p/README.md"


# ---- 1280×800：页面不滚，只有列表卡内部滚 ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_p2_pages_fit_800(qtbot, tmp_path, monkeypatch, theme):
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    app = QApplication.instance()
    app.setProperty("braidDark", theme == "dark")
    b = MockBackend()
    w = MainWindow(b)
    w.setStyleSheet(load_qss(theme))
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    w.show_settings(True)
    qtbot.waitExposed(w)
    sp = w.settings_page
    ap: AgentsPage = sp.pages["agents"]
    try:
        for panel_open in (False, True):
            if panel_open:
                w.set_panel_open(True, animate=False)
            assert w.panel_open() == panel_open
            for key in ("agents", "rules"):
                sp.show_section(key)
                qtbot.wait(30)
                assert sp.scrolls[key].verticalScrollBar().maximum() == 0, (key, panel_open)
            sp.show_section("agents")
            ap.toggle(ap.list.agent_rows()[0], animate=False)
            qtbot.wait(30)
            assert sp.scrolls["agents"].verticalScrollBar().maximum() == 0
            # 默认数据展开后也放得下，列表不必滚
            assert ap.list.list_scroll.verticalScrollBar().maximum() == 0
            ap.toggle(ap.list.agent_rows()[0], animate=False)
            qtbot.wait(30)
    finally:
        app.setProperty("braidDark", False)


def test_overflow_scrolls_inside_list_only(qtbot, tmp_path, monkeypatch):
    from braid.ui.main_window import MainWindow

    monkeypatch.setenv("BRAID_CONFIG_DIR", str(tmp_path))
    b = MockBackend()
    w = MainWindow(b)
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    w.show_settings(True)
    sp = w.settings_page
    sp.show_section("agents")
    qtbot.waitExposed(w)
    ap: AgentsPage = sp.pages["agents"]
    for _ in range(4):
        ap.add_agent()  # 新建会自动展开最后一个
    ed = ap.list.agent_rows()[-1].editor
    ed.grow.grow_to(400)
    qtbot.wait(50)
    assert sp.scrolls["agents"].verticalScrollBar().maximum() == 0  # 页面不滚
    inner = ap.list.list_scroll
    assert inner.verticalScrollBar().maximum() > 0  # 只有列表卡内部滚
    assert inner.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    bar = inner.overlay_bar
    inner.verticalScrollBar().setValue(30)
    assert bar.isVisible() and bar.width() == 6
    assert ap.add_card.isVisible()
    vp = sp.scrolls["agents"].viewport()
    bottom = ap.add_card.mapTo(vp, QPoint(0, ap.add_card.height())).y()
    assert bottom <= vp.height()
    assert qcolor("text3")  # 颜色仍走 token
