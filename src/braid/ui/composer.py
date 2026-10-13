"""主输入框：Enter 发送 / Shift+Enter 换行、附件（按钮/粘贴图片/拖拽）、
底栏模型 / 权限 / 推理强度三个 chip、生成中可停止、`/` 命令菜单。"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import ModelInfo
from braid.core.settings import settings
from braid.theme.menu import ChipButton, RoundedMenu


@dataclass(frozen=True)
class SlashCommand:
    name: str
    hint: str


DEFAULT_COMMANDS = [
    SlashCommand("clear", "清空当前会话"),
    SlashCommand("new", "新建会话"),
    SlashCommand("branch", "从这里开分支"),
    SlashCommand("model", "切换模型"),
    SlashCommand("help", "查看可用命令"),
]
PERMISSIONS = [("ask", "每次询问"), ("auto-edit", "自动编辑"), ("full", "完全自主")]
REASONING_LABELS = {"low": "低", "medium": "中", "high": "高", "max": "最高"}


class _Input(QTextEdit):
    submit = Signal()
    slashChanged = Signal(str)  # 当前 `/xxx` 前缀；空串表示不在命令模式
    navigate = Signal(int)  # 命令菜单上下移动
    accept = Signal()  # 命令菜单回车选中
    escape = Signal()
    filesAdded = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ComposerInput")
        self.setAcceptRichText(False)
        self.setPlaceholderText("输入消息，/ 唤起命令…")
        self.menu_open = False
        self.textChanged.connect(self._check_slash)

    def _check_slash(self) -> None:
        t = self.toPlainText()
        self.slashChanged.emit(
            t[1:] if t.startswith("/") and " " not in t and "\n" not in t else "\0"
        )

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k, mods = e.key(), e.modifiers()
        if self.menu_open and k in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.navigate.emit(-1 if k == Qt.Key.Key_Up else 1)
            return
        if self.menu_open and k == Qt.Key.Key_Escape:
            self.escape.emit()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText("\n")
            elif self.menu_open:
                self.accept.emit()
            else:
                self.submit.emit()
            return
        super().keyPressEvent(e)

    # 粘贴图片 / 文件
    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasImage():
            img = QImage(source.imageData())
            path = Path(tempfile.gettempdir()) / f"braid-paste-{uuid.uuid4().hex[:8]}.png"
            img.save(str(path))
            self.filesAdded.emit([str(path)])
        elif source.hasUrls():
            self.filesAdded.emit([u.toLocalFile() for u in source.urls() if u.isLocalFile()])
        else:
            super().insertFromMimeData(source)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e: QDropEvent) -> None:
        if e.mimeData().hasUrls():
            self.insertFromMimeData(e.mimeData())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


def _chip(text: str) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setProperty("role", "chip")
    b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    return b


class Composer(QFrame):
    """发出 `submitted(text, attachments)`、`stopRequested()`、`commandTriggered(name)`。"""

    submitted = Signal(str, list)
    selectionChanged = Signal(str, str)  # model_id, reasoning（不支持时为空串）
    stopRequested = Signal()
    commandTriggered = Signal(str)

    def __init__(
        self,
        models: list[ModelInfo],
        commands: list[SlashCommand] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Composer")
        self.commands = commands or DEFAULT_COMMANDS
        self.attachments: list[str] = []
        self.busy = False
        self.models = {m.id: m for m in models}
        self.model_id = ""
        self.reasoning = ""
        self.permission = "ask"

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 10, 10)
        self.att_row = QHBoxLayout()
        self.att_row.setSpacing(6)
        self.att_row.addStretch(1)
        col.addLayout(self.att_row)
        self.input = _Input()
        self.input.setMinimumHeight(48)
        self.input.setMaximumHeight(200)
        self.input.textChanged.connect(self._autosize)
        self.input.setFixedHeight(48)
        col.addWidget(self.input)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.attach_btn = QPushButton("\U0001f4ce")
        self.attach_btn.setProperty("variant", "ghost")
        self.attach_btn.setToolTip("添加附件")
        self.attach_btn.clicked.connect(self._pick_files)
        bar.addWidget(self.attach_btn)
        self.model_chip = ChipButton()
        self.model_chip.setObjectName("ModelChip")
        self.model_chip.setToolTip("模型与推理强度（Ctrl+Shift+I）")
        self.model_menu = self._build_model_menu(models)
        self.model_chip.setMenu(self.model_menu)
        QShortcut(QKeySequence("Ctrl+Shift+I"), self, self.open_model_menu)
        self.perm_chip = self._menu_chip(PERMISSIONS, self.permission, "permission")
        for c in (self.model_chip, self.perm_chip):
            bar.addWidget(c)
        self.set_selection(settings.default_model, settings.default_reasoning)
        bar.addStretch(1)
        self.send_btn = QPushButton("\u2191")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setProperty("variant", "primary")
        self.send_btn.setFixedSize(34, 34)
        self.send_btn.setToolTip("发送（Enter）")
        self.send_btn.clicked.connect(self._send_or_stop)
        bar.addWidget(self.send_btn)
        col.addLayout(bar)

        self.cmd_menu = QListWidget(self)
        self.cmd_menu.setObjectName("SlashMenu")
        self.cmd_menu.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.cmd_menu.itemClicked.connect(lambda _: self._run_command())
        self.cmd_menu.hide()

        self.input.submit.connect(self._send_or_stop)
        self.input.slashChanged.connect(self._update_menu)
        self.input.navigate.connect(self._move_sel)
        self.input.accept.connect(self._run_command)
        self.input.escape.connect(self._hide_menu)
        self.input.filesAdded.connect(self.add_attachments)

    # 底栏 chip
    def _menu_chip(self, opts: list[tuple[str, str]], cur: str, attr: str) -> QToolButton:
        chip = _chip(dict(opts).get(cur, cur))
        menu = RoundedMenu(chip)
        for key, label in opts:
            act = QAction(label, menu, checkable=True, checked=key == cur)

            def pick(_: bool = False, k: str = key, lbl: str = label) -> None:
                setattr(self, attr, k)
                chip.setText(lbl)
                for a in menu.actions():
                    a.setChecked(a.text() == lbl)

            act.triggered.connect(pick)
            menu.addAction(act)
        chip.setMenu(menu)
        return chip

    # 模型 × 推理强度 两级菜单
    def _build_model_menu(self, models: list[ModelInfo]) -> RoundedMenu:
        menu = RoundedMenu(self)
        self._model_actions: dict[str, QAction] = {}
        self._level_actions: dict[tuple[str, str], QAction] = {}
        group = QActionGroup(menu)
        providers: dict[str, list[ModelInfo]] = {}
        for m in models:
            providers.setdefault(m.provider or "其他", []).append(m)
        for provider, items in providers.items():
            menu.addGroupHeader(provider)
            for m in items:
                if m.reasoning_levels:
                    sub = menu.addMenu(m.name)
                    act = sub.menuAction()
                    for lv in m.reasoning_levels:
                        la = QAction(REASONING_LABELS.get(lv, lv), sub, checkable=True)
                        la.triggered.connect(
                            lambda _=False, mid=m.id, lv=lv: self.set_selection(mid, lv)
                        )
                        group.addAction(la)
                        sub.addAction(la)
                        self._level_actions[(m.id, lv)] = la
                else:
                    act = QAction(m.name, menu)
                    act.triggered.connect(lambda _=False, mid=m.id: self.set_selection(mid, ""))
                    menu.addAction(act)
                act.setCheckable(True)
                self._model_actions[m.id] = act
        return menu

    def set_selection(self, model_id: str, reasoning: str | None = None) -> None:
        m = self.models.get(model_id) or next(iter(self.models.values()), None)
        if m is None:
            return
        levels = m.reasoning_levels
        if not levels:
            lv = ""
        elif reasoning in levels:
            lv = reasoning or ""
        elif settings.default_reasoning in levels:
            lv = settings.default_reasoning
        else:
            lv = levels[len(levels) // 2]
        self.model_id, self.reasoning = m.id, lv
        for mid, a in self._model_actions.items():
            a.setChecked(mid == m.id)
            f = a.font()
            f.setBold(mid == m.id)
            a.setFont(f)
        for (mid, l2), a in self._level_actions.items():
            a.setChecked(mid == m.id and l2 == lv)
        self.model_chip.setText(m.name + (f" · {REASONING_LABELS.get(lv, lv)}" if lv else ""))
        self.selectionChanged.emit(self.model_id, self.reasoning)

    def open_model_menu(self) -> None:
        self.model_chip.showMenu()

    def _autosize(self) -> None:
        h = int(self.input.document().size().height()) + 12
        self.input.setFixedHeight(max(48, min(200, h)))

    # 附件
    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "添加附件")
        self.add_attachments(files)

    def add_attachments(self, paths: list[str]) -> None:
        for p in paths:
            if p and p not in self.attachments:
                self.attachments.append(p)
                chip = _chip(Path(p).name + "  \u2715")
                chip.setToolTip(p)
                chip.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
                chip.clicked.connect(lambda _=False, p=p, c=chip: self._remove(p, c))
                self.att_row.insertWidget(self.att_row.count() - 1, chip)

    def _remove(self, path: str, chip: QToolButton) -> None:
        self.attachments.remove(path)
        chip.deleteLater()

    def _clear_attachments(self) -> None:
        self.attachments.clear()
        while self.att_row.count() > 1:
            item = self.att_row.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

    # 发送 / 停止
    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_btn.setText("\u25a0" if busy else "\u2191")
        self.send_btn.setToolTip("停止生成" if busy else "发送（Enter）")

    def _send_or_stop(self) -> None:
        if self.busy:
            self.stopRequested.emit()
            return
        text = self.input.toPlainText().strip()
        if not text and not self.attachments:
            return
        self.submitted.emit(text, list(self.attachments))
        self.input.clear()
        self._clear_attachments()

    def set_text(self, text: str) -> None:
        self.input.setPlainText(text)
        self.input.setFocus()

    # `/` 命令菜单
    def _update_menu(self, prefix: str) -> None:
        if prefix == "\0":
            self._hide_menu()
            return
        self.cmd_menu.clear()
        for c in self.commands:
            if c.name.startswith(prefix):
                it = QListWidgetItem(f"/{c.name}    {c.hint}")
                it.setData(Qt.ItemDataRole.UserRole, c.name)
                self.cmd_menu.addItem(it)
        if not self.cmd_menu.count():
            self._hide_menu()
            return
        self.cmd_menu.setCurrentRow(0)
        h = min(6, self.cmd_menu.count()) * 30 + 8
        self.cmd_menu.setFixedSize(min(360, self.width()), h)
        self.cmd_menu.move(self.mapToGlobal(QPoint(0, -h - 6)))
        self.cmd_menu.show()
        self.input.menu_open = True

    def _hide_menu(self) -> None:
        self.cmd_menu.hide()
        self.input.menu_open = False

    def _move_sel(self, d: int) -> None:
        n = self.cmd_menu.count()
        self.cmd_menu.setCurrentRow((self.cmd_menu.currentRow() + d) % n)

    def _run_command(self) -> None:
        it = self.cmd_menu.currentItem()
        self._hide_menu()
        if it:
            self.input.clear()
            self.commandTriggered.emit(it.data(Qt.ItemDataRole.UserRole))
