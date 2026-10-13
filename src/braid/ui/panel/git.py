"""Git 页（panel_spec §4）：分支行 + 文件列表卡片 + Diff 卡片 + 提交区。只依赖 GitSource。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
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
from braid.theme.menu import RoundedMenu, is_dark
from braid.theme.palette import qcolor
from braid.theme.palette import tokens as palette
from braid.ui.panel.shell import card_shadow

ROW_H = 28  # 文件行高
DIFF_FONT_PX, DIFF_LINE_H, LINENO_W = 12, 20, 26
COMMIT_MAX_LINES = 6
COMMIT_PAD_V = 10  # 提交输入框上下内边距
STATUS_TOKEN = {"A": "success", "M": "warning", "D": "danger"}
SPIN_SIZE, SPIN_WIDTH, SPIN_TICK_MS, SPIN_PERIOD_MS = 12, 1.5, 16, 800
ARROW_PX = 12
CONT_MARK = "↪"


def tinted(name: str, dark: bool, alpha: int) -> QColor:
    """token 色叠指定透明度（diff 加/删行底：success 12–15%、danger 10–15%）。"""
    c = qcolor(name, dark)
    c.setAlpha(alpha)
    return c


def mono_font(px: int = DIFF_FONT_PX) -> QFont:
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    return f


def git_qss(mode: str = "light") -> str:
    t = palette(mode == "dark")
    return f"""
#GitFilesCard, #GitDiffCard, #GitCommitCard {{ background: {t["surface"]}; border-radius: 14px; }}
#BranchChip {{ background: {t["control"]}; color: {t["text"]}; border: none;
    border-radius: 12px; padding: 4px 10px; font-size: 12px; }}
#AheadBehind, QLabel[role="groupTitle"], #DiffCaption {{ color: {t["text3"]}; font-size: 12px; }}
QPushButton[variant="secondary"] {{ background: {t["control"]}; color: {t["text"]};
    border: none; border-radius: 10px; padding: 4px 12px; }}
QPushButton[variant="secondary"][emphasis="true"] {{ color: {t["brand"]}; }}
QPushButton[variant="secondary"]:disabled {{ color: {t["text3"]}; }}
QFrame[role="fileRow"] {{ border-radius: 10px; background: transparent; }}
QFrame[role="fileRow"]:hover {{ background: {t["hover"]}; }}
QFrame[role="fileRow"][selected="true"] {{ background: {t["active"]}; }}
QFrame[role="fileRow"] QLabel[role="path"] {{ color: {t["text2"]}; }}
QFrame[role="fileRow"][selected="true"] QLabel[role="path"] {{ color: {t["text"]}; }}
QPushButton[role="stageToggle"] {{ border: none; background: transparent; color: {t["text2"]};
    font-weight: 600; }}
#CommitInput {{ background: transparent; border: none; color: {t["text"]}; font-size: 13px;
    padding: {COMMIT_PAD_V}px 0; }}
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


class StatusLetter(QWidget):
    """状态字母 A/M/D：颜色在 paint 时从 palette 取，主题切换后自动跟随。"""

    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status
        f = QFont()
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setFixedSize(12, 20)

    def color(self) -> QColor:
        return QColor(palette(is_dark())[STATUS_TOKEN[self.status]])

    def text(self) -> str:
        return self.status

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.color())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.status)
        p.end()


class Spinner(QWidget):
    """12px 圆弧转圈：线宽 1.5、text2 色，16ms 一帧、0.8s 一圈。父按钮禁用时仍保持原色。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(SPIN_SIZE, SPIN_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.angle = 0.0
        self.timer = QTimer(self, interval=SPIN_TICK_MS)
        self.timer.timeout.connect(self._step)
        self.hide()

    def _step(self) -> None:
        self.angle = (self.angle + 360.0 * SPIN_TICK_MS / SPIN_PERIOD_MS) % 360.0
        self.update()

    def start(self) -> None:
        self.angle = 0.0
        self.show()
        self.raise_()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def color(self) -> QColor:
        return qcolor("text2", is_dark())

    def paintEvent(self, e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.color(), SPIN_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = SPIN_WIDTH / 2
        r = QRectF(m, m, SPIN_SIZE - 2 * m, SPIN_SIZE - 2 * m)
        p.drawArc(r, int(-self.angle * 16), 270 * 16)
        p.end()


def arrow_pixmap(up: bool, color: QColor, dpr: float = 2.0) -> QPixmap:
    """12px 线性小箭头 ↑/↓。"""
    pm = QPixmap(int(ARROW_PX * dpr), int(ARROW_PX * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    c, top, bot = 6.0, 2.0, 10.0
    tip, tail = (top, bot) if up else (bot, top)
    d = 3.5 if up else -3.5
    p.drawLine(QRectF(c, tail, 0, 0).topLeft(), QRectF(c, tip, 0, 0).topLeft())
    p.drawLine(QRectF(c - 3.5, tip + d, 0, 0).topLeft(), QRectF(c, tip, 0, 0).topLeft())
    p.drawLine(QRectF(c + 3.5, tip + d, 0, 0).topLeft(), QRectF(c, tip, 0, 0).topLeft())
    p.end()
    return pm


class SyncButton(QPushButton):
    """Pull / Push：左侧 12px 箭头图标（与文字同色）；执行中图标位置换成圆弧转圈，宽度不变。"""

    def __init__(self, text: str, up: bool) -> None:
        super().__init__(text)
        self.up = up
        self.setProperty("variant", "secondary")
        self.setIconSize(QSize(ARROW_PX, ARROW_PX))
        self.spinner = Spinner(self)
        self.busy = False
        self.refresh_icon()

    def text_color(self) -> QColor:
        dark = is_dark()
        if not self.isEnabled():
            return qcolor("text3", dark)
        return qcolor("brand" if self.property("emphasis") else "text2", dark)

    def refresh_icon(self) -> None:
        if self.busy:
            # 透明占位图标保持宽度不变，转圈画在原图标位置
            pm = QPixmap(ARROW_PX, ARROW_PX)
            pm.fill(Qt.GlobalColor.transparent)
            self.setIcon(QIcon(pm))
        else:
            self.setIcon(QIcon(arrow_pixmap(self.up, self.text_color())))

    def set_emphasis(self, on: bool) -> None:
        if bool(self.property("emphasis")) != on:
            self.setProperty("emphasis", on)
            _repolish(self)
        self.refresh_icon()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.setEnabled(not busy)
        self.refresh_icon()
        if busy:
            self._place_spinner()
            self.spinner.start()
        else:
            self.spinner.stop()

    def _place_spinner(self) -> None:
        fm = QFontMetrics(self.font())
        content = ARROW_PX + 4 + fm.horizontalAdvance(self.text())
        x = max(0, (self.width() - content) // 2)
        self.spinner.move(x, (self.height() - SPIN_SIZE) // 2)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        if self.busy:
            self._place_spinner()


class StageToggle(QPushButton):
    """行尾暂存(+)/取消暂存(−)按钮：自绘 1.5px 线性符号，text2 色（paint 时取）。"""

    def __init__(self, plus: bool) -> None:
        super().__init__()
        self.plus = plus
        self.setProperty("role", "stageToggle")
        self.setProperty("sign", "+" if plus else "-")

    def paintEvent(self, e: QPaintEvent) -> None:
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(qcolor("text2", is_dark()), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = QRectF(self.rect()).center()
        p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() + 4, c.y()))
        if self.plus:
            p.drawLine(QPointF(c.x(), c.y() - 4), QPointF(c.x(), c.y() + 4))
        p.end()


class FileRow(QFrame):
    """文件行：路径（等宽 12 text2）+ hover 时的 +/− + 状态字母。"""

    clicked = Signal(object, bool)  # FileChange, staged
    toggleStage = Signal(object, bool)

    def __init__(self, fc: FileChange, staged: bool) -> None:
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
        self.toggle = StageToggle(plus=not staged)
        self.toggle.setFixedSize(20, 20)
        self.toggle.setToolTip("取消暂存" if staged else "暂存")
        self.toggle.hide()
        self.toggle.clicked.connect(lambda: self.toggleStage.emit(self.fc, self.staged))
        lay.addWidget(self.toggle)
        self.letter = StatusLetter(fc.status)
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
    """自绘 diff：等宽 12px、行高 20，行号 26 宽 text3；长行软换行，续行行号列显示 ↪。
    颜色在 paint 时从 palette 取。"""

    TEXT_X = 4 + LINENO_W + 4

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[DiffLine] = []
        self.rows: list[tuple[int, str, bool]] = []  # (源行下标, 文本片段, 是否续行)
        self.setFont(mono_font())

    def set_lines(self, lines: list[DiffLine]) -> None:
        self.lines = list(lines)
        self._relayout()

    def _relayout(self) -> None:
        sign = {"add": "+", "del": "-", "ctx": " "}
        fm = QFontMetrics(self.font())
        avail = max(fm.horizontalAdvance("M") * 8, self.width() - self.TEXT_X - 4)
        rows: list[tuple[int, str, bool]] = []
        for i, ln in enumerate(self.lines):
            text = f"{sign[ln.kind]} {ln.text}"
            first = True
            while True:
                n = len(text)
                while n > 1 and fm.horizontalAdvance(text[:n]) > avail:
                    n -= 1
                rows.append((i, text[:n], not first))
                text, first = text[n:], False
                if not text:
                    break
        self.rows = rows
        h = len(rows) * DIFF_LINE_H
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
            self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(200, len(self.rows) * DIFF_LINE_H)

    def line_rect(self, i: int) -> QRect:
        return QRect(0, i * DIFF_LINE_H, self.width(), DIFF_LINE_H)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            self._relayout()

    def paintEvent(self, e: QPaintEvent) -> None:
        dark = is_dark()
        bg = {
            "add": tinted("success", dark, 0x26 if dark else 0x1F),
            "del": tinted("danger", dark, 0x26 if dark else 0x1A),
        }
        left = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        p = QPainter(self)
        p.setFont(self.font())
        for r_i, (src, seg, cont) in enumerate(self.rows):
            ln = self.lines[src]
            r = self.line_rect(r_i)
            if ln.kind in bg:
                p.fillRect(r, bg[ln.kind])
            p.setPen(qcolor("text3", dark))
            p.drawText(
                QRect(4, r.y(), LINENO_W, DIFF_LINE_H), left, CONT_MARK if cont else str(ln.lineno)
            )
            p.setPen(qcolor("text", dark))
            p.drawText(QRect(self.TEXT_X, r.y(), r.width(), DIFF_LINE_H), left, seg)
        p.end()


class CommitInput(QPlainTextEdit):
    """单行起步、最多 6 行；Ctrl+Enter 提交。"""

    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CommitInput")
        self.setPlaceholderText("提交信息（Ctrl+Enter 提交）")
        # 未超过最大行数时不显示滚动条（否则 Windows 上会在按钮左边留一根竖条）
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        doc = self.document()
        if doc is not None:
            doc.setDocumentMargin(0)
        self.textChanged.connect(self._fit)
        self._fit()

    def _line_h(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _fit(self) -> None:
        doc = self.document()
        lines = doc.lineCount() if doc else 1
        n = max(1, min(COMMIT_MAX_LINES, lines))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if lines > COMMIT_MAX_LINES
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # 按实际字体行高算（Windows 雅黑行距比 Noto 大），不写死像素；
        # contentsMargins 已含 QSS padding 与边框
        m = self.contentsMargins()
        self.setFixedHeight(n * self._line_h() + m.top() + m.bottom())

    def changeEvent(self, e: QEvent) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class GitPage(QWidget):
    def set_theme(self, mode: str) -> None:
        """切换深浅色：QSS 重设；文件行与 diff 在 paint 时按 is_dark() 取色。"""
        self.theme = mode
        self.setStyleSheet(git_qss(mode))
        self.pull_btn.refresh_icon()
        self.push_btn.refresh_icon()
        for w in self.findChildren(QWidget):
            w.update()

    def __init__(
        self, source: GitSource, parent: QWidget | None = None, theme: str = "light"
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.theme = theme
        self.setStyleSheet(git_qss(theme))
        self.rows: list[FileRow] = []
        self.selected: tuple[str, bool] | None = None  # (path, staged)

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
        self.ahead_lbl = QLabel()
        self.behind_lbl = QLabel()
        for lb in (self.ahead_lbl, self.behind_lbl):
            lb.setObjectName("AheadBehind")
            top.addWidget(lb)
        top.addStretch(1)
        self.pull_btn = SyncButton("Pull", up=False)
        self.push_btn = SyncButton("Push", up=True)
        for b, op in ((self.pull_btn, "pull"), (self.push_btn, "push")):
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
        self.diff_view = DiffView()
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
        cl.addWidget(self.commit_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card_shadow(commit_card)
        lay.addWidget(commit_card)

        self.commit_btn.clicked.connect(self.commit)
        self.commit_input.submitted.connect(self.commit)
        self.commit_input.textChanged.connect(self._update_commit_btn)
        self._stale = False
        source.changed.connect(self._on_changed)
        source.busyChanged.connect(self._on_busy)
        self.refresh()

    # —— 数据 ——
    def _on_changed(self) -> None:
        # 所在窗口已显示但本页不可见（在别的标签/面板收起）时不查询仓库，等显示时再刷新
        win = self.window()
        if win is not self and win.isVisible() and not self.isVisible():
            self._stale = True
            return
        self.refresh()

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        if self._stale:
            self._stale = False
            self.refresh()

    def refresh(self) -> None:
        st = self.source.status()
        self.status = st
        self.branch_chip.setText(f"⎇ {st.branch} ▾")
        self.ahead_lbl.setText(f"↑{st.ahead}")
        self.ahead_lbl.setVisible(st.ahead > 0)
        self.behind_lbl.setText(f"↓{st.behind}")
        self.behind_lbl.setVisible(st.behind > 0)
        self.push_btn.set_emphasis(st.ahead > 0)
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
                row = FileRow(fc, staged)
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

    def _btn(self, op: str) -> SyncButton:
        return self.pull_btn if op == "pull" else self.push_btn

    def _on_busy(self, op: str, busy: bool) -> None:
        self._btn(op).set_busy(busy)
