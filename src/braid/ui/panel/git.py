"""Git 页（只读，GitHub「Files changed」样式）：分支名 + 整体滚动的文件列表（点击行原地展开 diff）。
只依赖 GitSource；颜色在 paint 时按 is_dark() 从 palette 取。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from braid.core.git import DiffLine, FileChange, GitSource
from braid.theme.menu import is_dark
from braid.theme.palette import qcolor
from braid.theme.palette import tokens as palette

ROW_H = 32  # 文件行高
ROW_RADIUS = 8
DIFF_FONT_PX, DIFF_LINE_H, LINENO_W = 12, 20, 32
DIFF_INDENT, DIFF_PAD = 4, 2  # diff 左缩进 4px，不套卡片
BIG_DIFF_LINES = 400  # 超过即默认折叠，点击加载
BIG_HINT = "改动较大，点击加载"
BIG_TAG = "较大"
NAME_TOKEN = {"A": "success", "D": "danger"}  # 文件名色；修改沿用 text
CONT_MARK = "↪"


def tinted(name: str, dark: bool, alpha: int) -> QColor:
    """token 色叠指定透明度（diff 加/删行底：暗色 15%）。"""
    c = qcolor(name, dark)
    c.setAlpha(alpha)
    return c


def diff_bg(kind: str, dark: bool) -> QColor | None:
    """增/删行底色；上下文与 @@ 行无底色。"""
    if kind == "add":
        return tinted("success", dark, 0x26 if dark else 0x1F)
    if kind == "del":
        return tinted("danger", dark, 0x26 if dark else 0x1A)
    return None


_DIFF_FAMILIES: list[str] | None = None


def diff_families() -> list[str]:
    """diff 字体族链：等宽西文族在前（不含 CJK 族，免得中文落到粗的等宽 CJK 字体），
    之后接标题字体链所用的中文族（resolved_cjk_family，Regular）。进程内算一次。"""
    global _DIFF_FAMILIES
    if _DIFF_FAMILIES is None:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication

        from braid.ui.settings.widgets import CJK_FALLBACK, mono_families, resolved_cjk_family

        cjk_db = set(QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese))
        latin = [f for f in mono_families() if f not in cjk_db and f not in CJK_FALLBACK]
        cjk = resolved_cjk_family(QApplication.font())
        tail = [cjk] if cjk else [f for f in CJK_FALLBACK if f in cjk_db]
        _DIFF_FAMILIES = latin + [f for f in tail if f not in latin]
    return list(_DIFF_FAMILIES)


def mono_font(px: int = DIFF_FONT_PX) -> QFont:
    f = QFont()
    f.setFamilies(diff_families())
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setWeight(QFont.Weight.Normal)
    f.setPixelSize(px)
    return f


def git_qss(mode: str = "light") -> str:
    t = palette(mode == "dark")
    return f"""
#GitFileScroll, #GitFileList {{ background: transparent; }}
#BranchLabel {{ background: transparent; color: {t["text2"]}; border: none;
    padding: 0; font-size: 12px; }}
"""


class FileRow(QWidget):
    """文件行（自绘）：展开箭头 · 路径（目录 text3、文件名 text；新增 success、删除 danger
    加删除线）· 右侧 +a −d。悬停出 hover 浅底。"""

    clicked = Signal(object)  # FileChange

    PAD = 8
    CHEVRON_W = 12

    def __init__(self, fc: FileChange) -> None:
        super().__init__()
        self.fc = fc
        self.expanded = False
        self.hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono_font(12))

    @classmethod
    def path_x(cls) -> int:
        """路径文字在行内的起始 x（顶部分支名与之左对齐）。"""
        return cls.PAD + cls.CHEVRON_W + 8

    def dir_and_name(self) -> tuple[str, str]:
        d, sep, name = self.fc.path.rpartition("/")
        return (d + sep, name)

    def stats_text(self) -> tuple[str, str]:
        return (f"+{self.fc.additions}", f"−{self.fc.deletions}")

    @property
    def big(self) -> bool:
        return self.fc.changed_lines > BIG_DIFF_LINES

    def name_color(self) -> QColor:
        return qcolor(NAME_TOKEN.get(self.fc.status, "text"), is_dark())

    def set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.update()

    def event(self, e: QEvent) -> bool:
        if e.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self.hovered = e.type() == QEvent.Type.HoverEnter
            self.update()
        return super().event(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.fc)

    def paintEvent(self, e: QPaintEvent) -> None:
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.hovered:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), ROW_RADIUS, ROW_RADIUS)
            p.fillPath(path, qcolor("hover", dark))
        pen = QPen(qcolor("text3", dark), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.PAD + self.CHEVRON_W / 2, ROW_H / 2
        if self.expanded:
            pts = [
                QPointF(cx - 3.5, cy - 1.75),
                QPointF(cx, cy + 1.75),
                QPointF(cx + 3.5, cy - 1.75),
            ]
        else:
            pts = [
                QPointF(cx - 1.75, cy - 3.5),
                QPointF(cx + 1.75, cy),
                QPointF(cx - 1.75, cy + 3.5),
            ]
        p.drawPolyline(pts)
        fm = QFontMetrics(self.font())
        mid = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        p.setFont(self.font())
        add_t, del_t = self.stats_text()
        x_end = self.width() - self.PAD
        del_w, add_w = fm.horizontalAdvance(del_t), fm.horizontalAdvance(add_t)
        p.setPen(qcolor("danger", dark))
        p.drawText(QRect(x_end - del_w, 0, del_w, ROW_H), mid, del_t)
        x_add = x_end - del_w - 6 - add_w
        p.setPen(qcolor("success", dark))
        p.drawText(QRect(x_add, 0, add_w, ROW_H), mid, add_t)
        if self.big:
            tag_w = fm.horizontalAdvance(BIG_TAG)
            x_add -= tag_w + 8
            p.setPen(qcolor("text3", dark))
            p.drawText(QRect(x_add, 0, tag_w, ROW_H), mid, BIG_TAG)
        x0 = self.path_x()
        avail = max(0, x_add - 12 - x0)
        d, name = self.dir_and_name()
        name_w = fm.horizontalAdvance(name)
        if name_w >= avail:
            d, name = "", fm.elidedText(name, Qt.TextElideMode.ElideMiddle, avail)
            name_w = fm.horizontalAdvance(name)
        else:
            d = fm.elidedText(d, Qt.TextElideMode.ElideLeft, avail - name_w) if d else ""
        dw = fm.horizontalAdvance(d)
        p.setPen(qcolor("text3", dark))
        p.drawText(QRect(x0, 0, dw, ROW_H), mid, d)
        nf = QFont(self.font())
        nf.setStrikeOut(self.fc.status == "D")
        p.setFont(nf)
        p.setPen(self.name_color())
        p.drawText(QRect(x0 + dw, 0, name_w + 2, ROW_H), mid, name)
        p.end()


class DiffView(QWidget):
    """原地展开的 diff（不套卡片，左缩进 4px）：两列旧/新行号（text3），增删行 15% 底色；
    @@ 行画一条细分隔线加 text3 范围。
    长行软换行，续行行号列显示 ↪。改动超过 BIG_DIFF_LINES 时先只显示「点击加载」。"""

    TEXT_X = DIFF_INDENT + LINENO_W * 2 + 8
    loadRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[DiffLine] = []
        self.rows: list[tuple[int, str, bool]] = []  # (源行下标, 文本片段, 是否续行)
        self.placeholder: str | None = None
        self.setFont(mono_font())

    def set_lines(self, lines: list[DiffLine]) -> None:
        self.placeholder = None
        self.lines = list(lines)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._relayout()

    def set_placeholder(self, text: str) -> None:
        self.placeholder = text
        self.lines = []
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._relayout()

    def _relayout(self) -> None:
        sign = {"add": "+", "del": "-", "ctx": " ", "hunk": ""}
        fm = QFontMetrics(self.font())
        avail = max(fm.horizontalAdvance("M") * 8, self.width() - self.TEXT_X - DIFF_PAD)
        rows: list[tuple[int, str, bool]] = []
        for i, ln in enumerate(self.lines):
            text = ln.text if ln.kind == "hunk" else f"{sign[ln.kind]} {ln.text}"
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
        h = self._content_h()
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
            self.setMaximumHeight(h)
            self.updateGeometry()
        self.update()

    def _content_h(self) -> int:
        n = 1 if self.placeholder is not None else len(self.rows)
        return n * DIFF_LINE_H + 2 * DIFF_PAD + (8 if self.placeholder is not None else 0)

    def sizeHint(self) -> QSize:
        return QSize(200, self._content_h())

    def line_rect(self, i: int) -> QRect:
        return QRect(0, DIFF_PAD + i * DIFF_LINE_H, self.width(), DIFF_LINE_H)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            self._relayout()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.placeholder is not None and e.button() == Qt.MouseButton.LeftButton:
            self.loadRequested.emit()

    def paintEvent(self, e: QPaintEvent) -> None:
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self.font())
        if self.placeholder is not None:
            p.setPen(qcolor("text3", dark))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.placeholder)
            p.end()
            return
        left = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        num = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        text3, text = qcolor("text3", dark), qcolor("text", dark)
        vis = e.rect()
        for r_i, (src, seg, cont) in enumerate(self.rows):
            r = self.line_rect(r_i)
            if not r.intersects(vis):
                continue
            ln = self.lines[src]
            if (bg := diff_bg(ln.kind, dark)) is not None:
                p.fillRect(r.adjusted(DIFF_INDENT, 0, 0, 0), bg)
            if ln.kind == "hunk" and not cont:
                # 细分隔线在范围文字两侧，文字处断开
                tw = QFontMetrics(self.font()).horizontalAdvance(seg)
                y, line = r.y() + r.height() // 2, qcolor("border_subtle", dark)
                p.fillRect(QRect(DIFF_INDENT, y, self.TEXT_X - 8 - DIFF_INDENT, 1), line)
                x1 = self.TEXT_X + tw + 8
                p.fillRect(QRect(x1, y, r.width() - x1, 1), line)
            p.setPen(text3)
            if ln.kind != "hunk":
                old = CONT_MARK if cont else ("" if ln.old is None else str(ln.old))
                new = CONT_MARK if cont else ("" if ln.new is None else str(ln.new))
                p.drawText(QRect(DIFF_INDENT, r.y(), LINENO_W - 4, DIFF_LINE_H), num, old)
                p.drawText(
                    QRect(DIFF_INDENT + LINENO_W, r.y(), LINENO_W - 4, DIFF_LINE_H), num, new
                )
                p.setPen(text)
            p.drawText(QRect(self.TEXT_X, r.y(), r.width(), DIFF_LINE_H), left, seg)
        p.end()


class FileEntry(QWidget):
    """一个文件：行 + 其下方可展开的 diff 卡片。diff 首次展开时才向仓库查询。"""

    def __init__(self, page: GitPage, fc: FileChange) -> None:
        super().__init__()
        self.page, self.fc = page, fc
        self.big = fc.changed_lines > BIG_DIFF_LINES
        self.loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.row = FileRow(fc)
        lay.addWidget(self.row)
        self.diff: DiffView | None = None
        self._lay = lay

    @property
    def key(self) -> str:
        return self.fc.path

    @property
    def expanded(self) -> bool:
        return self.row.expanded

    def set_expanded(self, on: bool, load: bool = False) -> None:
        self.row.set_expanded(on)
        if on and self.diff is None:
            self.diff = DiffView()
            self.diff.loadRequested.connect(self.load)
            self._lay.addWidget(self.diff)
            self._lay.addSpacing(6)
        if self.diff is None:
            return
        if on:
            if self.loaded or not self.big or load:
                self.load()
            else:
                self.diff.set_placeholder(BIG_HINT)
        self.diff.setVisible(on)

    def load(self) -> None:
        if self.diff is None:
            return
        self.loaded = True
        self.page.loaded.add(self.key)
        self.diff.set_lines(self.page.source.diff(self.fc.path))


class GitPage(QWidget):
    """只读 Git 页：不提供暂存、提交、Pull/Push、切换分支等写操作。"""

    def set_theme(self, mode: str) -> None:
        """切换深浅色：QSS 重设；文件行与 diff 在 paint 时按 is_dark() 取色。"""
        self.theme = mode
        self.setStyleSheet(git_qss(mode))
        for w in self.findChildren(QWidget):
            w.update()

    def __init__(
        self, source: GitSource, parent: QWidget | None = None, theme: str = "light"
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.theme = theme
        self.setStyleSheet(git_qss(theme))
        self.entries: list[FileEntry] = []
        self.expanded: set[str] = set()  # 刷新后保持展开
        self.loaded: set[str] = set()  # 已手动加载的大文件

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        top = QHBoxLayout()
        top.setContentsMargins(FileRow.path_x(), 0, 0, 0)  # 与文件路径起始 x 对齐
        self.branch_label = QLabel()
        self.branch_label.setIndent(0)
        self.branch_label.setMargin(0)
        self.branch_label.setObjectName("BranchLabel")
        top.addWidget(self.branch_label)
        top.addStretch(1)
        lay.addLayout(top)

        self.file_list = QWidget()
        self.file_list.setObjectName("GitFileList")
        self.files_layout = QVBoxLayout(self.file_list)
        self.files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_layout.setSpacing(0)
        self.list_scroll = QScrollArea()
        self.list_scroll.setObjectName("GitFileScroll")
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_scroll.setWidget(self.file_list)
        if vp := self.list_scroll.viewport():
            vp.setAutoFillBackground(False)
        lay.addWidget(self.list_scroll, 1)

        self._stale = False
        source.changed.connect(self._on_changed)
        self.refresh()

    @property
    def rows(self) -> list[FileRow]:
        return [e.row for e in self.entries]

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
        self.branch_label.setText(f"⎇ {st.branch}")
        while (item := self.files_layout.takeAt(0)) is not None:
            if w := item.widget():
                w.deleteLater()
        self.entries = []
        for fc in sorted(st.files, key=lambda f: f.path):
            ent = FileEntry(self, fc)
            ent.row.clicked.connect(self.toggle_file)
            self.files_layout.addWidget(ent)
            self.entries.append(ent)
            if ent.key in self.expanded:
                ent.set_expanded(True, load=ent.key in self.loaded)
        keys = {e.key for e in self.entries}
        self.expanded &= keys
        self.loaded &= keys
        self.files_layout.addStretch(1)

    def entry(self, path: str) -> FileEntry | None:
        return next((e for e in self.entries if e.key == path), None)

    def toggle_file(self, fc: FileChange) -> None:
        ent = self.entry(fc.path)
        if ent is None:
            return
        on = not ent.expanded
        (self.expanded.add if on else self.expanded.discard)(ent.key)
        ent.set_expanded(on)
