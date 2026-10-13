"""设置分区：导航表、页面注册表，以及“权限”“通用”和占位页。

页面只经 ``AgentBackend.get_config(section)`` / ``set_config(section, values)`` 读写。
其他开发者接入新页面::

    from braid.ui.settings.pages import register_page
    register_page("mcp", lambda backend: McpPage(backend))
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend
from braid.ui.settings.widgets import (
    CloseIconButton,
    NumberField,
    PageHeader,
    SegmentedControl,
    SettingCard,
    SettingsCombo,
    number_with_unit,
)

# 左栏顺序；key 即 AgentBackend 配置分区名
NAV: tuple[tuple[str, str], ...] = (
    ("models", "模型与服务"),
    ("permissions", "权限"),
    ("general", "通用"),
    ("agents", "智能体"),
    ("mcp", "MCP 服务"),
    ("rules", "规则与指令"),
    ("keybinds", "快捷键"),
    ("advanced", "高级"),
)

PageFactory = Callable[[AgentBackend], QWidget]
PAGE_FACTORIES: dict[str, PageFactory] = {}

PAGE_PAD, PAGE_GAP, HEADER_GAP, CONTENT_MAX = 24, 12, 20, 640
PERMISSION_OPTIONS = (("allow", "允许"), ("ask", "询问"), ("deny", "拒绝"))
THEME_OPTIONS = (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色"))
UPDATE_OPTIONS = (("auto", "自动"), ("notify", "仅提醒"), ("off", "关闭"))
LANGUAGES = (("zh-CN", "简体中文"), ("en", "English"))


def register_page(key: str, factory: PageFactory) -> None:
    """注册分区页工厂；之后新建的 SettingsPage 用它替换占位页。"""
    if key not in dict(NAV):
        raise KeyError(key)
    PAGE_FACTORIES[key] = factory


class SectionPage(QWidget):
    """分区页骨架：页头 + 卡片列，统一边距。"""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumWidth(CONTENT_MAX + 2 * PAGE_PAD)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(PAGE_PAD, PAGE_PAD, PAGE_PAD, PAGE_PAD)
        self.lay.setSpacing(PAGE_GAP)
        self.header = PageHeader(title, subtitle, self)
        self.lay.addWidget(self.header)
        self.lay.addSpacing(HEADER_GAP - PAGE_GAP)

    def finish(self) -> None:
        self.lay.addStretch(1)


class PlaceholderPage(SectionPage):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, "这一页还在开发中", parent)
        self.finish()


class BashRuleRow(QWidget):
    """一条 bash 规则：模式输入框 + 允许/询问/拒绝 + 删除。"""

    def __init__(self, pattern: str, action: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self.pattern = QLineEdit(pattern, self)
        self.pattern.setObjectName("settingsField")
        self.pattern.setPlaceholderText("命令模式，如 git *")
        self.pattern.setFixedHeight(28)
        self.pattern.setMinimumWidth(60)
        self.action = SegmentedControl(PERMISSION_OPTIONS, action, self)
        self.remove = CloseIconButton(self, "删除规则")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.pattern, 1)
        lay.addWidget(self.action)
        lay.addWidget(self.remove)

    def value(self) -> dict[str, str]:
        return {"pattern": self.pattern.text().strip(), "action": self.action.value()}


class PermissionsPage(SectionPage):
    SECTION = "permissions"
    TOOLS = (("edit", "编辑文件"), ("bash", "执行命令"), ("webfetch", "抓取网页"))

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("权限", "智能体调用工具前是否需要你确认", parent)
        self.backend = backend
        conf = backend.get_config(self.SECTION)
        self.tools_card = SettingCard("", self)
        self.segments: dict[str, SegmentedControl] = {}
        for key, label in self.TOOLS:
            seg = SegmentedControl(PERMISSION_OPTIONS, conf.get(key, "ask"), self)
            seg.changed.connect(lambda v, k=key: self.backend.set_config(self.SECTION, {k: v}))
            self.tools_card.add_row(label, seg)
            self.segments[key] = seg
        self.lay.addWidget(self.tools_card)

        self.rules_card = SettingCard("命令规则（bash）", self)
        self._rows: list[BashRuleRow] = []
        self.rules_box = QVBoxLayout()
        self.rules_box.setSpacing(0)
        self.rules_card.lay.addLayout(self.rules_box)
        self.add_rule_btn = QToolButton(self)
        self.add_rule_btn.setObjectName("textButton")
        self.add_rule_btn.setText("+ 添加规则")
        self.add_rule_btn.setFixedHeight(36)
        self.add_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_rule_btn.clicked.connect(lambda: self.add_rule("", "ask"))
        self.rules_card.add_widget(self.add_rule_btn)
        self.lay.addWidget(self.rules_card)
        for r in conf.get("bash_rules", []):
            self._append(r["pattern"], r["action"])
        self.finish()

    def rules(self) -> list[BashRuleRow]:
        return list(self._rows)

    def _append(self, pattern: str, action: str) -> BashRuleRow:
        row = BashRuleRow(pattern, action, self.rules_card)
        row.pattern.editingFinished.connect(self._save_rules)
        row.action.changed.connect(lambda _v: self._save_rules())
        row.remove.clicked.connect(lambda: self.remove_rule(row))
        self.rules_box.addWidget(row)
        self._rows.append(row)
        return row

    def add_rule(self, pattern: str, action: str) -> BashRuleRow:
        row = self._append(pattern, action)
        self._save_rules()
        row.pattern.setFocus()
        return row

    def remove_rule(self, row: BashRuleRow) -> None:
        self.rules_box.removeWidget(row)
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._save_rules()

    def _save_rules(self) -> None:
        vals = [r.value() for r in self.rules()]
        self.backend.set_config(self.SECTION, {"bash_rules": vals})


class GeneralPage(SectionPage):
    SECTION = "general"

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("通用", "外观、语言与更新", parent)
        self.backend = backend
        conf = backend.get_config(self.SECTION)
        card = SettingCard("", self)
        self.theme = SegmentedControl(THEME_OPTIONS, conf.get("theme", "system"), self)
        self.theme.changed.connect(lambda v: self._set(theme=v))
        card.add_row("主题", self.theme)
        self.language = SettingsCombo(self)
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(conf.get("language"))))
        self.language.currentIndexChanged.connect(
            lambda _i: self._set(language=self.language.currentData())
        )
        card.add_row("界面语言", self.language)
        self.font_size = NumberField(int(conf.get("font_size", 14)), 11, 22, parent=self)
        self.font_size.valueChanged.connect(lambda v: self._set(font_size=v))
        card.add_row("正文字号", number_with_unit(self.font_size, "px", self))
        self.autoupdate = SegmentedControl(UPDATE_OPTIONS, conf.get("autoupdate", "notify"), self)
        self.autoupdate.changed.connect(lambda v: self._set(autoupdate=v))
        card.add_row("自动更新", self.autoupdate)
        self.shell = QLineEdit(str(conf.get("shell", "")), self)
        self.shell.setObjectName("settingsField")
        self.shell.setFixedHeight(28)
        self.shell.setFixedWidth(160)
        self.shell.setPlaceholderText("/bin/bash")
        self.shell.editingFinished.connect(lambda: self._set(shell=self.shell.text().strip()))
        card.add_row("默认 Shell", self.shell)
        self.card = card
        self.lay.addWidget(card)
        self.finish()

    def _set(self, **values: Any) -> None:
        self.backend.set_config(self.SECTION, values)


register_page("permissions", PermissionsPage)
register_page("general", GeneralPage)

# P2 分区页：模块导入时自行 register_page（放在末尾，避免循环导入）
from braid.ui.settings import agents as _agents  # noqa: E402, F401
from braid.ui.settings import rules as _rules  # noqa: E402, F401
