"""“智能体”设置页（分区 ``agents``）。

布局：默认智能体一行 → 智能体列表卡（每行 52px，点击就地展开编辑器）→ “+ 新建智能体”。
页面本身从不滚动；展开后放不下时只有列表卡内部用浮层细滚动条滚动。
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QEasingCurve, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend
from braid.theme.menu import RoundedMenu
from braid.ui.settings.pages import SectionPage, register_page
from braid.ui.settings.widgets import (
    CARD_PAD_H,
    AddCard,
    ChipMultiSelect,
    GrowHandle,
    SettingCard,
    SettingRow,
    SettingsCombo,
    make_scroll,
    mono_font,
)

SECTION = "agents"
AGENT_ROW_H = 52
PROMPT_MIN_H = 120
EXPAND_MS = 150
SAVE_DELAY_MS = 400
EDITOR_BOTTOM_PAD = 16
EDITOR_ROW_H = 36
FIELD_W = 240
LIST_MIN_H = 2 * AGENT_ROW_H
TOOLS = (("read", "读取"), ("edit", "编辑"), ("bash", "命令"), ("webfetch", "网页"), ("mcp", "MCP"))
INHERIT = ""  # model 为空 = 跟随默认模型


class AgentEditor(QWidget):
    """展开后的编辑器：模型、允许的工具（胶囊多选）、提示词（等宽，可拖高）。"""

    changed = Signal(dict)  # 改动的字段

    def __init__(self, agent: dict[str, Any], backend: AgentBackend, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("agentEditor")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        # 名称 / 描述：自定义为单行输入（预填），内置为只读文字
        self.name_edit: QLineEdit | None = None
        self.desc_edit: QLineEdit | None = None
        for key, label in (("name", "名称"), ("description", "描述")):
            value = str(agent.get(key, ""))
            w: QWidget
            if agent.get("builtin"):
                w = QLabel(value, self)
                w.setObjectName("agentFieldValue")
            else:
                edit = QLineEdit(value, self)
                edit.setObjectName("settingsInput")
                edit.setFixedWidth(FIELD_W)
                edit.editingFinished.connect(lambda k=key, e=edit: self._field_done(k, e))
                w = edit
                if key == "name":
                    self.name_edit = edit
                else:
                    self.desc_edit = edit
            lay.addWidget(self._row(label, w))
        self.model = SettingsCombo(self)
        self.model.addItem("跟随默认模型", INHERIT)
        for m in backend.list_models():
            self.model.addItem(m.name, m.id)
        self.model.setCurrentIndex(max(0, self.model.findData(agent.get("model", INHERIT))))
        self.model.currentIndexChanged.connect(
            lambda _i: self.changed.emit({"model": self.model.currentData()})
        )
        lay.addWidget(self._row("模型", self.model))
        self.tools = ChipMultiSelect(TOOLS, agent.get("tools", []), self)
        self.tools.changed.connect(lambda keys: self.changed.emit({"tools": keys}))
        lay.addWidget(self._row("允许的工具", self.tools))
        cap = QLabel("提示词", self)
        cap.setObjectName("settingLabel")
        lay.addWidget(cap)
        self.prompt = QPlainTextEdit(agent.get("prompt", ""), self)
        self.prompt.setObjectName("promptEdit")
        self.prompt.setFont(mono_font(px=12))
        self.prompt.setPlaceholderText("留空则使用内置提示词")
        self.prompt.setFixedHeight(PROMPT_MIN_H)
        lay.addWidget(self.prompt)
        # 底部 16px 留白；拖动把手（10px）放在这 16px 内部
        self.grow = GrowHandle(self.prompt, PROMPT_MIN_H, self)
        self.bottom = QWidget(self)
        self.bottom.setFixedHeight(EDITOR_BOTTOM_PAD)
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(0, 0, 0, EDITOR_BOTTOM_PAD - self.grow.height())
        bl.addWidget(self.grow)
        lay.addWidget(self.bottom)
        self._save = QTimer(self)
        self._save.setSingleShot(True)
        self._save.setInterval(SAVE_DELAY_MS)
        self._save.timeout.connect(lambda: self.changed.emit({"prompt": self.prompt.toPlainText()}))
        self.prompt.textChanged.connect(self._save.start)
        self._last = {k: str(agent.get(k, "")) for k in ("name", "description")}

    def _row(self, label: str, w: QWidget) -> SettingRow:
        """编辑器内的紧凑行：只从外部设定行高，不改 SettingRow 内部布局。"""
        row = SettingRow(label, w, self)
        row.setFixedHeight(EDITOR_ROW_H)
        return row

    def _field_done(self, key: str, edit: QLineEdit) -> None:
        text = edit.text().strip()
        if key == "name" and not text:  # 名称不能为空：还原
            edit.setText(self._last.get(key, ""))
            return
        if text != self._last.get(key):
            self._last[key] = text
            self.changed.emit({key: text})


class AgentRow(QWidget):
    """一行：左名称（内置带“内置”标签）+ 12px 描述；右模型名（text3）+ ⋯ 菜单。点击展开。"""

    toggled = Signal(object)  # self
    edited = Signal(str, dict)  # id, 改动
    remove_requested = Signal(str)
    resized = Signal()  # 高度变化（动画每帧、动画结束）

    def __init__(self, agent: dict[str, Any], backend: AgentBackend, parent: QWidget | None = None):
        super().__init__(parent)
        self.agent, self.backend = agent, backend
        self.setObjectName("agentRow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.head = QWidget(self)
        self.head.setFixedHeight(AGENT_ROW_H)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self.head)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addStretch(1)  # 名称 + 描述整体垂直居中
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = QLabel(agent["name"], self.head)
        self.name.setObjectName("agentName")
        top.addWidget(self.name)
        self.tag: QLabel | None = None
        if agent.get("builtin"):
            self.tag = QLabel("内置", self.head)
            self.tag.setObjectName("agentTag")
            top.addWidget(self.tag)
        top.addStretch(1)
        left.addLayout(top)
        self.desc = QLabel(agent.get("description", ""), self.head)
        self.desc.setObjectName("agentDesc")
        self.desc.setMinimumWidth(40)
        self.desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        left.addWidget(self.desc)
        left.addStretch(1)
        h.addLayout(left, 1)
        self.model_label = QLabel(self._model_text(), self.head)
        self.model_label.setObjectName("agentModel")
        h.addWidget(self.model_label)
        self.more = QToolButton(self.head)
        self.more.setObjectName("providerMore")
        self.more.setText("⋯")
        self.more.clicked.connect(self._open_menu)
        h.addWidget(self.more)
        outer.addWidget(self.head)
        self.editor = AgentEditor(agent, backend, self)
        self.editor.changed.connect(self._on_edit)
        self.editor.setMaximumHeight(0)
        self.editor.hide()
        outer.addWidget(self.editor)
        self.expanded = False
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(EXPAND_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self._anim_done)

    @property
    def agent_id(self) -> str:
        return str(self.agent["id"])

    def _model_text(self) -> str:
        mid = self.agent.get("model") or INHERIT
        if not mid:
            return "跟随默认"
        names = {m.id: m.name for m in self.backend.list_models()}
        return names.get(mid, mid)

    def _on_edit(self, change: dict[str, Any]) -> None:
        self.agent.update(change)
        self.model_label.setText(self._model_text())
        self.name.setText(str(self.agent["name"]))
        self.desc.setText(str(self.agent.get("description", "")))
        self.edited.emit(self.agent_id, change)

    def build_menu(self) -> RoundedMenu:
        menu = RoundedMenu(self)
        menu.addAction("收起编辑" if self.expanded else "编辑").triggered.connect(
            lambda: self.toggled.emit(self)
        )
        if not self.agent.get("builtin"):
            act = menu.addAction("删除智能体")
            act.triggered.connect(lambda: self.remove_requested.emit(self.agent_id))
        return menu

    def _open_menu(self) -> None:
        self.build_menu().exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.head.geometry().contains(e.position().toPoint()):
            self.toggled.emit(self)
        super().mousePressEvent(e)

    def set_expanded(self, on: bool, animate: bool = True) -> None:
        if on == self.expanded:
            return
        self.expanded = on
        full = self.editor.sizeHint().height()
        if on:
            self.editor.show()
        self.anim.stop()
        start = self.editor.maximumHeight() if self.editor.isVisible() else 0
        end = full if on else 0
        if not animate:
            self.editor.setMaximumHeight(end)
            self._anim_done()
            return
        self.anim.setStartValue(min(start, full))
        self.anim.setEndValue(end)
        self.anim.start()

    def _step(self, v: int) -> None:
        self.editor.setMaximumHeight(int(v))
        self.resized.emit()

    def _anim_done(self) -> None:
        if self.expanded:
            self.editor.setMaximumHeight(16777215)  # 展开后可再拖高提示词
        else:
            self.editor.hide()
        self.resized.emit()


class AgentList(SettingCard):
    """智能体列表卡；内容超出可用高度时只在卡内滚动（浮层细滚动条）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.body = QWidget(self)
        self.body.setObjectName("agentListBody")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(0)
        self.list_scroll: QScrollArea = make_scroll(self.body, self)
        self.list_scroll.setMinimumHeight(LIST_MIN_H)
        self.lay.setContentsMargins(CARD_PAD_H, 4, 0, 4)  # 右侧不留白，滚动条贴卡边
        self.body_lay.setContentsMargins(0, 0, CARD_PAD_H, 0)
        self.add_widget(self.list_scroll)
        # 纵向 Expanding + 滚动区最大高度=内容高：有空间就贴合内容，没空间就被压缩、卡内滚动
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.list_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._fit = QTimer(self)
        self._fit.setSingleShot(True)
        self._fit.setInterval(0)
        self._fit.timeout.connect(self.fit_height)

    def agent_rows(self) -> list[AgentRow]:
        return [
            w
            for i in range(self.body_lay.count())
            if (it := self.body_lay.itemAt(i)) is not None
            and isinstance(w := it.widget(), AgentRow)
        ]

    def content_height(self) -> int:
        """按行直接算（布局的 sizeHint 有缓存，动画中途不可靠）。"""
        total = 0
        for r in self.agent_rows():
            total += AGENT_ROW_H
            if r.editor.isVisibleTo(r):
                total += min(r.editor.sizeHint().height(), r.editor.maximumHeight())
        return total

    def fit_height(self) -> None:
        """滚动区最大高度 = 内容高度：放得下时卡片贴合内容，放不下时由页面布局压缩、卡内滚动。"""
        h = max(LIST_MIN_H, self.content_height())
        self.list_scroll.setMaximumHeight(h)
        m = self.lay.contentsMargins()
        self.setMaximumHeight(h + m.top() + m.bottom())

    def schedule_fit(self) -> None:
        self.fit_height()
        self._fit.start()


class AgentsPage(SectionPage):
    SECTION = SECTION

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("智能体", "按任务选用不同的模型、工具和提示词", parent)
        self.backend = backend
        self.default_card = SettingCard("", self)
        self.default_combo = SettingsCombo(self)
        self.default_card.add_row("默认智能体", self.default_combo)
        self.lay.addWidget(self.default_card)
        self.list = AgentList(self)
        self.lay.addWidget(self.list, 1)
        self.add_card = AddCard("+ 新建智能体", self)
        self.add_card.clicked.connect(self.add_agent)
        self.lay.addWidget(self.add_card)
        # 末尾弹簧 stretch=0：列表（stretch=1）优先占空间，贴合内容后剩余才给弹簧
        self.lay.addStretch(0)
        self.default_combo.currentIndexChanged.connect(self._on_default)
        self.rebuild()

    # ---- 数据 ----
    def _conf(self) -> dict[str, Any]:
        return self.backend.get_config(SECTION)

    def agents(self) -> list[dict[str, Any]]:
        return list(self._conf().get("agents", []))

    def _save_agents(self, agents: list[dict[str, Any]]) -> None:
        self.backend.set_config(SECTION, {"agents": copy.deepcopy(agents)})

    # ---- 界面 ----
    def rebuild(self) -> None:
        for r in self.list.agent_rows():
            self.list.body_lay.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        conf = self._conf()
        agents = conf.get("agents", [])
        for a in agents:
            row = AgentRow(dict(a), self.backend, self.list.body)
            row.toggled.connect(self.toggle)
            row.edited.connect(self._on_row_edit)
            row.remove_requested.connect(self.remove_agent)
            row.resized.connect(self.list.schedule_fit)
            row.editor.prompt.installEventFilter(self)
            row.editor.grow.installEventFilter(self)
            self.list.body_lay.addWidget(row)
        self.default_combo.blockSignals(True)
        self.default_combo.clear()
        for a in agents:
            self.default_combo.addItem(a["name"], a["id"])
        self.default_combo.setCurrentIndex(
            max(0, self.default_combo.findData(conf.get("default_agent")))
        )
        self.default_combo.blockSignals(False)
        self.list.schedule_fit()

    def eventFilter(self, obj: Any, e: Any) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.Resize:
            self.list.schedule_fit()  # 拖高提示词后重新贴合
        return False

    def expanded_row(self) -> AgentRow | None:
        return next((r for r in self.list.agent_rows() if r.expanded), None)

    def toggle(self, row: AgentRow, animate: bool = True) -> None:
        """同一时间只展开一个。"""
        for r in self.list.agent_rows():
            if r is not row and r.expanded:
                r.set_expanded(False, animate)
        row.set_expanded(not row.expanded, animate)
        self.list.schedule_fit()

    def _on_default(self, _i: int) -> None:
        self.backend.set_config(SECTION, {"default_agent": self.default_combo.currentData()})

    def _on_row_edit(self, agent_id: str, change: dict[str, Any]) -> None:
        agents = self.agents()
        for a in agents:
            if a["id"] == agent_id:
                a.update(change)
        self._save_agents(agents)

    def add_agent(self) -> dict[str, Any]:
        agents = self.agents()
        ids = {a["id"] for a in agents}
        n = 1
        while f"custom{n}" in ids:
            n += 1
        new = {
            "id": f"custom{n}",
            "name": f"新智能体 {n}",
            "builtin": False,
            "description": "自定义智能体",
            "model": INHERIT,
            "tools": ["read"],
            "prompt": "",
        }
        agents.append(new)
        self._save_agents(agents)
        self.rebuild()
        last = self.list.agent_rows()[-1]
        self.toggle(last, animate=False)
        return new

    def remove_agent(self, agent_id: str) -> None:
        agents = self.agents()
        target = next((a for a in agents if a["id"] == agent_id), None)
        if target is None or target.get("builtin"):
            return  # 内置不可删
        agents.remove(target)
        values: dict[str, Any] = {"agents": copy.deepcopy(agents)}
        if self._conf().get("default_agent") == agent_id:
            values["default_agent"] = agents[0]["id"] if agents else ""
        self.backend.set_config(SECTION, values)
        QTimer.singleShot(0, self, self.rebuild)


register_page(SECTION, AgentsPage)
