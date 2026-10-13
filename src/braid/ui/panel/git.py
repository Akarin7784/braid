"""Git 页（panel_spec §4）：分支行 + 文件列表卡片 + Diff 卡片 + 提交区。只依赖 GitSource。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from braid.core.git import DiffLine, FileChange, GitSource
from braid.theme.menu import RoundedMenu
from braid.ui.panel.shell import card_shadow
from braid.ui.panel.tokens import tokens

ROW_H = 28  # 文件行高
DIFF_FONT_PX, DIFF_LINE_H, LINENO_W = 12, 20, 26
COMMIT_MAX_LINES = 6
STATUS_TOKEN = {"A": "success", "M": "warning", "D": "danger"}
SPINNER = "◐◓◑◒"


def qcolor(hex_: str) -> QColor:
    """tokens 的 #RRGGBBAA → QColor。"""
    if len(hex_) == 9:
        c = QColor(hex_[:7])
        c.setAlpha(int(hex_[7:], 16))
        return c
    return QColor(hex_)


def mono_font(px: int = DIFF_FONT_PX) -> QFont:
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    return f


def git_qss(mode: str = "light") -> str:
    t = tokens(mode)
    return f"""
#GitFilesCard, #GitDiffCard, #GitCommitCard {{ background: {t["surface"]}; border-radius: 14px; }}
#BranchChip {{ background: {t["control"]}; color: {t["text"]}; border: none;
    border-radius: 12px; padding: 4px 10px; font-size: 12px; }}
#AheadBehind, QLabel[role="groupTitle"], #DiffCaption {{ color: {t["text3"]}; font-size: 12px; }}
QPushButton[variant="secondary"] {{ background: {t["control"]}; color: {t["text"]};
    border: none; border-radius: 10px; padding: 4px 12px; }}
QPushButton[variant="secondary"]:disabled {{ color: {t["text3"]}; }}
QFrame[role="fileRow"] {{ border-radius: 10px; background: transparent; }}
QFrame[role="fileRow"]:hover {{ background: {t["hover"]}; }}
QFrame[role="fileRow"][selected="true"] {{ background: {t["active"]}; }}
QFrame[role="fileRow"] QLabel[role="path"] {{ color: {t["text2"]}; }}
QFrame[role="fileRow"][selected="true"] QLabel[role="path"] {{ color: {t["text"]}; }}
QPushButton[role="stageToggle"] {{ border: none; background: transparent; color: {t["text2"]};
    font-weight: 600; }}
#CommitInput {{ background: transparent; border: none; color: {t["text"]}; font-size: 13px; }}
#CommitButton {{ background: {t["accent"]}; color: {t["accent_text"]}; border: none;
    border-radius: 10px; padding: 4px 12px; font-weight: 600; }}
#CommitButton:hover {{ background: {t["accent_hover"]}; }}
#CommitButton:disabled {{ background: {t["control"]}; color: {t["text3"]}; }}
#DiffPlaceholder {{ color: {t["text3"]}; font-size: 13px; }}
"""


def _repolish(w: QWidget) -> None:
    if st := w.style():
        st.unpolish(w)
        st.polish(w)


class FileRow(QFrame):
    """文件行：路径（等宽 12 text2）+ hover 时的 +/− + 状态字母。"""

    clicked = Signal(object, bool)  # FileChange, staged
    toggleStage = Signal(object, bool)

    def __init__(self, fc: FileChange, staged: bool, mode: str = "light") -> None:
        super().__init__()
        self.fc, self.staged = fc, staged
        self.setProperty("role", "fileRow")
        self.setProperty("selected", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        self.path = QLabel(fc.path)
        self.path.setProperty("role", "path")
        self.path.setFont(mono_font(12))
        lay.addWidget(self.path, 1)
        self.toggle = QPushButton("−" if staged else "+")
        self.toggle.setProperty("role", "stageToggle")
        self.toggle.setFixedSize(20, 20)
        self.toggle.setToolTip("取消暂存" if staged else "暂存")
        self.toggle.hide()
        self.toggle.clicked.connect(lambda: self.toggleStage.emit(self.fc, self.staged))
        lay.addWidget(self.toggle)
        self.letter = QLabel(fc.status)
        f = QFont()
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        self.letter.setFont(f)
        self.letter.setStyleSheet(f"color: {tokens(mode)[STATUS_TOKEN[fc.status]]};")
        lay.addWidget(self.letter)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        _repolish(self)

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.HoverEnter:
            self.toggle.show()
        elif e.type() == QEvent.Type.HoverLeave:
            self.toggle.hide()
        return super().event(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.fc, self.staged)


class DiffView(QWidget):
    """自绘 diff：等宽 12px、行高 20，行号 26 宽 text3，加/删行着色底。"""

    def __init__(self, mode: str = "light") -> None:
        super().__init__()
        self.mode = mode
        self.lines: list[DiffLine] = []
        self.setFont(mono_font())

    def set_lines(self, lines: list[DiffLine]) -> None:
        self.lines = list(lines)
        self.setMinimumHeight(len(self.lines) * DIFF_LINE_H)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(200, len(self.lines) * DIFF_LINE_H)

    def line_rect(self, i: int) -> QRect:
        return QRect(0, i * DIFF_LINE_H, self.width(), DIFF_LINE_H)

    def paintEvent(self, e: QPaintEvent) -> None:
        t = tokens(self.mode)
        dark = self.mode == "dark"
        bg = {
            "add": qcolor("#5CC28A26" if dark else "#2E8B571F"),
            "del": qcolor("#E2685B26" if dark else "#C0392B1A"),
        }
        sign = {"add": "+", "del": "-", "ctx": " "}
        p = QPainter(self)
        p.setFont(self.font())
        for i, ln in enumerate(self.lines):
            r = self.line_rect(i)
            if ln.kind in bg:
                p.fillRect(r, bg[ln.kind])
            p.setPen(QColor(t["text3"]))
            p.drawText(
                QRect(4, r.y(), LINENO_W, DIFF_LINE_H),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                str(ln.lineno),
            )
            p.setPen(QColor(t["text"]))
            p.drawText(
                QRect(4 + LINENO_W + 4, r.y(), r.width(), DIFF_LINE_H),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                f"{sign[ln.kind]} {ln.text}",
            )
        p.end()


class CommitInput(QPlainTextEdit):
    """单行起步、最多 6 行；Ctrl+Enter 提交。"""

    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CommitInput")
        self.setPlaceholderText("提交信息（Ctrl+Enter 提交）")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._fit)
        self._fit()

    def _line_h(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _fit(self) -> None:
        doc = self.document()
        n = max(1, min(COMMIT_MAX_LINES, doc.lineCount() if doc else 1))
        m = self.contentsMargins()
        self.setFixedHeight(n * self._line_h() + 8 + m.top() + m.bottom())

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class GitPage(QWidget):
    def __init__(
        self, source: GitSource, parent: QWidget | None = None, theme: str = "light"
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.theme = theme
        self.setStyleSheet(git_qss(theme))
        self.rows: list[FileRow] = []
        self.selected: tuple[str, bool] | None = None  # (path, staged)
        self._busy: dict[str, int] = {}
        self._spin = QTimer(self, interval=120)
        self._spin.timeout.connect(self._tick)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # 顶行
        top = QHBoxLayout()
        top.setSpacing(8)
        self.branch_chip = QPushButton()
        self.branch_chip.setObjectName("BranchChip")
        self.branch_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.branch_chip.clicked.connect(self._branch_menu)
        top.addWidget(self.branch_chip)
        self.ahead_behind = QLabel()
        self.ahead_behind.setObjectName("AheadBehind")
        top.addWidget(self.ahead_behind)
        top.addStretch(1)
        self.pull_btn = QPushButton("↓ Pull")
        self.push_btn = QPushButton("↑ Push")
        for b, op in ((self.pull_btn, "pull"), (self.push_btn, "push")):
            b.setProperty("variant", "secondary")
            b.setProperty("label", b.text())
            b.clicked.connect(getattr(source, op))
            top.addWidget(b)
        lay.addLayout(top)

        # 文件列表卡片
        self.files_card = QFrame()
        self.files_card.setObjectName("GitFilesCard")
        self.files_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.files_layout = QVBoxLayout(self.files_card)
        self.files_layout.setContentsMargins(6, 10, 6, 10)
        self.files_layout.setSpacing(0)
        card_shadow(self.files_card)
        lay.addWidget(self.files_card)

        # Diff 卡片
        diff_card = QFrame()
        diff_card.setObjectName("GitDiffCard")
        diff_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dl = QVBoxLayout(diff_card)
        dl.setContentsMargins(12, 12, 12, 12)
        dl.setSpacing(6)
        self.diff_caption = QLabel()
        self.diff_caption.setObjectName("DiffCaption")
        self.diff_caption.setFont(mono_font(12))
        dl.addWidget(self.diff_caption)
        self.diff_view = DiffView(theme)
        self.diff_scroll = QScrollArea()
        self.diff_scroll.setWidgetResizable(True)
        self.diff_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.diff_scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget {background: transparent;}"
        )
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.diff_view)
        hl.addStretch(1)
        self.diff_scroll.setWidget(holder)
        dl.addWidget(self.diff_scroll, 1)
        self.diff_placeholder = QLabel("选择文件查看改动", alignment=Qt.AlignmentFlag.AlignCenter)
        self.diff_placeholder.setObjectName("DiffPlaceholder")
        dl.addWidget(self.diff_placeholder, 1)
        card_shadow(diff_card)
        lay.addWidget(diff_card, 1)

        # 提交区
        commit_card = QFrame()
        commit_card.setObjectName("GitCommitCard")
        commit_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cl = QHBoxLayout(commit_card)
        cl.setContentsMargins(10, 8, 8, 8)
        cl.setSpacing(8)
        self.commit_input = CommitInput()
        cl.addWidget(self.commit_input, 1)
        self.commit_btn = QPushButton()
        self.commit_btn.setObjectName("CommitButton")
        cl.addWidget(self.commit_btn, 0, Qt.AlignmentFlag.AlignBottom)
        card_shadow(commit_card)
        lay.addWidget(commit_card)

        self.commit_btn.clicked.connect(self.commit)
        self.commit_input.submitted.connect(self.commit)
        self.commit_input.textChanged.connect(self._update_commit_btn)
        source.changed.connect(self.refresh)
        source.busyChanged.connect(self._on_busy)
        self.refresh()

    # —— 数据 ——
    def refresh(self) -> None:
        st = self.source.status()
        self.status = st
        self.branch_chip.setText(f"⎇ {st.branch} ▾")
        self.ahead_behind.setText(f"↑{st.ahead} ↓{st.behind}")
        while (item := self.files_layout.takeAt(0)) is not None:
            if w := item.widget():
                w.deleteLater()
        self.rows = []
        for title, files, staged in (("暂存", st.staged, True), ("未暂存", st.unstaged, False)):
            g = QLabel(f"{title}（{len(files)}）")
            g.setProperty("role", "groupTitle")
            g.setContentsMargins(8, 4, 8, 4)
            self.files_layout.addWidget(g)
            for fc in files:
                row = FileRow(fc, staged, self.theme)
                row.clicked.connect(self.select)
                row.toggleStage.connect(self._toggle_stage)
                self.files_layout.addWidget(row)
                self.rows.append(row)
        sel = self.selected
        if sel and any((r.fc.path, r.staged) == sel for r in self.rows):
            self.select_path(*sel)
        else:
            self.selected = None
            self._show_diff(None, [])
        self._update_commit_btn()

    def select_path(self, path: str, staged: bool) -> None:
        for r in self.rows:
            if r.fc.path == path and r.staged == staged:
                self.select(r.fc, staged)
                return

    def select(self, fc: FileChange, staged: bool) -> None:
        self.selected = (fc.path, staged)
        for r in self.rows:
            r.set_selected((r.fc.path, r.staged) == self.selected)
        self._show_diff(fc.path, self.source.diff(fc.path, staged))

    def _show_diff(self, path: str | None, lines: list[DiffLine]) -> None:
        has = path is not None
        self.diff_placeholder.setVisible(not has)
        self.diff_scroll.setVisible(has)
        self.diff_caption.setVisible(has)
        self.diff_view.set_lines(lines)
        if has:
            add = sum(ln.kind == "add" for ln in lines)
            rem = sum(ln.kind == "del" for ln in lines)
            self.diff_caption.setText(f"{path} · +{add} −{rem}")

    def _toggle_stage(self, fc: FileChange, staged: bool) -> None:
        if self.selected == (fc.path, staged):
            self.selected = (fc.path, not staged)
        (self.source.unstage if staged else self.source.stage)(fc.path)

    # —— 提交 ——
    def _update_commit_btn(self) -> None:
        n = len(self.status.staged)
        self.commit_btn.setText(f"提交 {n} 个文件")
        self.commit_btn.setEnabled(n > 0 and bool(self.commit_input.toPlainText().strip()))

    def commit(self) -> None:
        if not self.commit_btn.isEnabled():
            return
        msg = self.commit_input.toPlainText().strip()
        self.commit_input.clear()
        self.source.commit(msg)

    # —— 分支 / Pull / Push ——
    def _branch_menu(self) -> None:
        menu = RoundedMenu(self)
        for b in self.source.branches():
            a = menu.addAction(b)
            a.setCheckable(True)
            a.setChecked(b == self.status.branch)
            a.triggered.connect(lambda _=False, name=b: self.source.checkout(name))
        menu.popup(self.branch_chip.mapToGlobal(self.branch_chip.rect().bottomLeft()))
        self._menu = menu

    def _btn(self, op: str) -> QPushButton:
        return self.pull_btn if op == "pull" else self.push_btn

    def _on_busy(self, op: str, busy: bool) -> None:
        b = self._btn(op)
        b.setEnabled(not busy)
        if busy:
            self._busy[op] = 0
            self._tick()
            self._spin.start()
        else:
            self._busy.pop(op, None)
            b.setText(str(b.property("label")))
            if not self._busy:
                self._spin.stop()

    def _tick(self) -> None:
        for op, i in self._busy.items():
            b = self._btn(op)
            b.setText(f"{SPINNER[i % len(SPINNER)]} {str(b.property('label')).split(' ', 1)[1]}")
            self._busy[op] = i + 1
