"""Git 页（GitHub「Files changed」样式）：分支行 + 整体滚动的文件列表（点击行原地展开 diff）
+ 底部固定提交区。只依赖 GitSource；颜色在 paint 时按 is_dark() 从 palette 取。"""

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
    QPainterPath,
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

ROW_H = 32  # 文件行高
ROW_RADIUS = 8
DIFF_FONT_PX, DIFF_LINE_H, LINENO_W = 12, 20, 32
DIFF_INDENT, DIFF_PAD = 4, 2  # diff 左缩进 4px，不套卡片
BIG_DIFF_LINES = 400  # 超过即默认折叠，点击加载
BIG_HINT = "改动较大，点击加载"
BIG_TAG = "较大"
DOT_PX = 14  # 行内暂存圆圈
COMMIT_MAX_LINES = 6
COMMIT_PAD_V = 10  # 提交输入框上下内边距
NAME_TOKEN = {"A": "success", "D": "danger"}  # 文件名色；修改沿用 text
SPIN_SIZE, SPIN_WIDTH, SPIN_TICK_MS, SPIN_PERIOD_MS = 12, 1.5, 16, 800
ARROW_PX = 12
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
#GitCommitCard {{ background: {t["surface"]}; border-radius: 14px; }}
#GitFileScroll, #GitFileList {{ background: transparent; }}
#BranchChip {{ background: {t["control"]}; color: {t["text"]}; border: none;
    border-radius: 12px; padding: 4px 10px; font-size: 12px; }}
#AheadBehind {{ color: {t["text3"]}; font-size: 12px; }}
QPushButton[variant="secondary"] {{ background: {t["control"]}; color: {t["text"]};
    border: none; border-radius: 10px; padding: 4px 12px; }}
QPushButton[variant="secondary"][emphasis="true"] {{ color: {t["brand"]}; }}
QPushButton[variant="secondary"]:disabled {{ color: {t["text3"]}; }}
QPushButton[role="stageToggle"] {{ border: none; background: transparent; border-radius: 6px; }}
QPushButton[role="stageToggle"]:hover {{ background: {t["active"]}; }}
#CommitInput {{ background: transparent; border: none; color: {t["text"]}; font-size: 13px;
    padding: {COMMIT_PAD_V}px 0; }}
#CommitButton {{ background: {t["accent"]}; color: {t["accent_text"]}; border: none;
    border-radius: 10px; padding: 4px 12px; font-weight: 600; }}
#CommitButton:hover {{ background: {t["accent_hover"]}; }}
#CommitButton:disabled {{ background: {t["control"]}; color: {t["text3"]}; }}
#GitEmpty {{ color: {t["text3"]}; font-size: 13px; }}
"""


def _repolish(w: QWidget) -> None:
    if st := w.style():
        st.unpolish(w)
        st.polish(w)


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


class FileRow(QWidget):
    """文件行（自绘）：展开箭头 · 路径（目录 text3、文件名 text；新增 success、删除 danger
    加删除线）· 右侧 +a −d。悬停出 hover 浅底。"""

    clicked = Signal(object, bool)  # FileChange, staged
    toggleStage = Signal(object, bool)  # 点圆圈：单独暂存/取消暂存

    PAD = 8
    CHEVRON_W = 12

    def __init__(self, fc: FileChange, staged: bool) -> None:
        super().__init__()
        self.fc, self.staged = fc, staged
        self.expanded = False
        self.hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono_font(12))

    def dir_and_name(self) -> tuple[str, str]:
        d, sep, name = self.fc.path.rpartition("/")
        return (d + sep, name)

    def stats_text(self) -> tuple[str, str]:
        return (f"+{self.fc.additions}", f"−{self.fc.deletions}")

    @property
    def big(self) -> bool:
        return self.fc.changed_lines > BIG_DIFF_LINES

    def dot_rect(self) -> QRect:
        x = self.PAD + self.CHEVRON_W + 6
        return QRect(x, (ROW_H - DOT_PX) // 2, DOT_PX, DOT_PX)

    def dot_colors(self) -> tuple[QColor, QColor | None]:
        """(圆圈/填充色, 勾色)：已暂存 brand 实心 + 白勾；未暂存 text3 空心。"""
        dark = is_dark()
        if self.staged:
            return qcolor("brand", dark), QColor("#FFFFFF")
        return qcolor("text3", dark), None

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
        pos = e.position().toPoint()
        if e.button() != Qt.MouseButton.LeftButton or not self.rect().contains(pos):
            return
        if self.dot_rect().adjusted(-4, -6, 4, 6).contains(pos):
            self.toggleStage.emit(self.fc, self.staged)  # 点圆圈不展开
        else:
            self.clicked.emit(self.fc, self.staged)

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
        # 暂存圆圈
        ring, tick = self.dot_colors()
        dr = QRectF(self.dot_rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        if tick is None:
            p.setPen(QPen(ring, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(dr)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            p.drawEllipse(QRectF(self.dot_rect()))
            tp = QPen(tick, 1.5)
            tp.setCapStyle(Qt.PenCapStyle.RoundCap)
            tp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(tp)
            c = dr.center()
            p.drawPolyline(
                [
                    QPointF(c.x() - 3, c.y()),
                    QPointF(c.x() - 0.8, c.y() + 2.3),
                    QPointF(c.x() + 3.2, c.y() - 2.2),
                ]
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
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
        x0 = self.dot_rect().right() + 1 + 8
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

    def __init__(self, page: GitPage, fc: FileChange, staged: bool) -> None:
        super().__init__()
        self.page, self.fc, self.staged = page, fc, staged
        self.big = fc.changed_lines > BIG_DIFF_LINES
        self.loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.row = FileRow(fc, staged)
        lay.addWidget(self.row)
        self.diff: DiffView | None = None
        self._lay = lay

    @property
    def key(self) -> tuple[str, bool]:
        return (self.fc.path, self.staged)

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
        self.diff.set_lines(self.page.source.diff(self.fc.path, self.staged))


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
        self.entries: list[FileEntry] = []
        self.expanded: set[tuple[str, bool]] = set()  # 刷新后保持展开
        self.loaded: set[tuple[str, bool]] = set()  # 已手动加载的大文件

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
        self.stage_btn = QPushButton()
        self.stage_btn.setProperty("variant", "secondary")
        self.stage_btn.clicked.connect(self.toggle_stage_all)
        top.addWidget(self.stage_btn)
        self.pull_btn = SyncButton("Pull", up=False)
        self.push_btn = SyncButton("Push", up=True)
        for b, op in ((self.pull_btn, "pull"), (self.push_btn, "push")):
            b.clicked.connect(getattr(source, op))
            top.addWidget(b)
        lay.addLayout(top)

        # 整体滚动的文件列表
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

        # 提交区（固定在底部）
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
        self._batch = False
        source.changed.connect(self._on_changed)
        source.busyChanged.connect(self._on_busy)
        self.refresh()

    @property
    def rows(self) -> list[FileRow]:
        return [e.row for e in self.entries]

    # —— 数据 ——
    def _on_changed(self) -> None:
        if self._batch:
            return
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
        self.entries = []
        keys: set[tuple[str, bool]] = set()
        files = [(f, True) for f in st.staged] + [(f, False) for f in st.unstaged]
        for fc, staged in files:
            ent = FileEntry(self, fc, staged)
            ent.row.clicked.connect(self.toggle_file)
            ent.row.toggleStage.connect(self.toggle_stage)
            self.files_layout.addWidget(ent)
            self.entries.append(ent)
            keys.add(ent.key)
            if ent.key in self.expanded:
                ent.set_expanded(True, load=ent.key in self.loaded)
        self.expanded &= keys
        self.loaded &= keys
        self.files_layout.addStretch(1)
        self._update_commit_btn()
        self.stage_btn.setText("全部暂存" if st.unstaged else "取消暂存")
        self.stage_btn.setEnabled(bool(st.unstaged or st.staged))

    def entry(self, path: str, staged: bool) -> FileEntry | None:
        return next((e for e in self.entries if e.key == (path, staged)), None)

    def toggle_file(self, fc: FileChange, staged: bool) -> None:
        ent = self.entry(fc.path, staged)
        if ent is None:
            return
        on = not ent.expanded
        (self.expanded.add if on else self.expanded.discard)(ent.key)
        ent.set_expanded(on)

    def toggle_stage(self, fc: FileChange, staged: bool) -> None:
        """单独暂存/取消暂存一个文件；展开状态跟着文件走。"""
        for s in (self.expanded, self.loaded):
            if (fc.path, staged) in s:
                s.discard((fc.path, staged))
                s.add((fc.path, not staged))
        (self.source.unstage if staged else self.source.stage)(fc.path)

    def toggle_stage_all(self) -> None:
        """有未暂存的就全部暂存，否则全部取消暂存；展开状态跟着文件走。"""
        st = self.status
        staged = not st.unstaged
        files = st.staged if staged else st.unstaged
        for s in (self.expanded, self.loaded):
            moved = {(f.path, staged) for f in files} & s
            s -= moved
            s |= {(path, not staged) for path, _ in moved}
        self._batch = True  # 逐个暂存时不中途刷新，最后统一刷新一次
        try:
            for f in files:
                (self.source.unstage if staged else self.source.stage)(f.path)
        finally:
            self._batch = False
        self.refresh()

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
