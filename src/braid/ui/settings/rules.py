"""“规则与指令”设置页（分区 ``rules``）。

一张卡列出指令文件（opencode 的 ``instructions``：路径或 glob）。每行：等宽路径（过长中间省略）、
glob 在右侧显示 text3 “匹配 N 个文件”、× 删除。卡末“+ 添加指令文件”展开行内输入框，回车确认，
旁边“选择文件”打开文件对话框。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend
from braid.ui.settings.pages import SectionPage, register_page
from braid.ui.settings.widgets import (
    ROW_H,
    CloseIconButton,
    ElidedLabel,
    SettingCard,
    mono_font,
)

SECTION = "rules"
EMPTY_TEXT = "还没有指令文件，项目根目录的 AGENTS.md 会自动读取"
GLOB_CHARS = set("*?[")


def is_glob(path: str) -> bool:
    return any(c in GLOB_CHARS for c in path)


class InstructionRow(QWidget):
    removed = Signal(str)

    def __init__(self, path: str, matches: int | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setFixedHeight(ROW_H)
        self.label = ElidedLabel(path, self)
        self.label.setObjectName("instructionPath")
        self.label.setFont(mono_font(px=12))
        self.count: QLabel | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.label, 1)
        if matches is not None:
            self.count = QLabel(f"匹配 {matches} 个文件", self)
            self.count.setObjectName("matchCount")
            lay.addWidget(self.count)
        self.remove = CloseIconButton(self, "移除")
        self.remove.clicked.connect(lambda: self.removed.emit(self.path))
        lay.addWidget(self.remove)


class RulesPage(SectionPage):
    SECTION = SECTION

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("规则与指令", "智能体每次对话前读取的指令文件，支持通配符", parent)
        self.backend = backend
        self.card = SettingCard("指令文件", self)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(0)
        self.card.lay.addLayout(self.rows_box)
        self.empty = QLabel(EMPTY_TEXT, self.card)
        self.empty.setObjectName("settingsEmpty")
        self.empty.setWordWrap(True)
        self.card.add_widget(self.empty)
        # 行内添加：点“+ 添加指令文件”在卡末展开输入框（位于按钮行之上）
        self.add_btn = QToolButton(self.card)
        self.add_btn.setObjectName("textButton")
        self.add_btn.setText("+ 添加指令文件")
        self.add_btn.setFixedHeight(36)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self.start_add)
        # “+ 添加指令文件”与右侧“选择文件”同一行，始终可见
        self.action_bar = QWidget(self.card)
        self.action_bar.setFixedHeight(36)
        al = QHBoxLayout(self.action_bar)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(self.add_btn)
        al.addStretch(1)
        self.add_row = QWidget(self.card)
        self.add_row.setFixedHeight(ROW_H)
        ar = QHBoxLayout(self.add_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(8)
        self.input = QLineEdit(self.add_row)
        self.input.setObjectName("settingsField")
        self.input.setFont(mono_font(px=12))
        self.input.setFixedHeight(30)
        self.input.setPlaceholderText("路径或通配符，如 docs/*.md，回车确认")
        self.input.returnPressed.connect(self._confirm_input)
        self.pick_btn = QToolButton(self.action_bar)
        self.pick_btn.setObjectName("textButton")
        self.pick_btn.setText("选择文件")
        self.pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_btn.clicked.connect(self.pick_file)
        ar.addWidget(self.input, 1)
        al.addWidget(self.pick_btn)
        self.add_row.hide()
        self.card.add_widget(self.add_row)
        self.card.add_widget(self.action_bar)
        self.lay.addWidget(self.card)
        self.finish()
        self.rebuild()

    def paths(self) -> list[str]:
        return list(self.backend.get_config(SECTION).get("instructions", []))

    def rows(self) -> list[InstructionRow]:
        return [
            w
            for i in range(self.rows_box.count())
            if (it := self.rows_box.itemAt(i)) is not None
            and isinstance(w := it.widget(), InstructionRow)
        ]

    def rebuild(self) -> None:
        for r in self.rows():
            self.rows_box.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        paths = self.paths()
        for p in paths:
            n = self.backend.count_instruction_matches(p) if is_glob(p) else None
            row = InstructionRow(p, n, self.card)
            row.removed.connect(self.remove_path)
            self.rows_box.addWidget(row)
        self.empty.setVisible(not paths)

    def _save(self, paths: list[str]) -> None:
        self.backend.set_config(SECTION, {"instructions": paths})
        self.rebuild()

    def add_path(self, path: str) -> bool:
        path = path.strip()
        paths = self.paths()
        if not path or path in paths:
            return False
        self._save([*paths, path])
        return True

    def remove_path(self, path: str) -> None:
        self._save([p for p in self.paths() if p != path])

    def start_add(self) -> None:
        self.add_row.show()
        self.input.setFocus()

    def _finish_add(self) -> None:
        self.input.clear()
        self.add_row.hide()

    def _confirm_input(self) -> None:
        self.add_path(self.input.text())
        self._finish_add()

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择指令文件", "", "Markdown (*.md *.mdc);;所有文件 (*)"
        )
        if path:
            self.add_path(path)
            self._finish_add()


register_page(SECTION, RulesPage)
