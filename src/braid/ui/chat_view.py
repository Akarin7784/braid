"""消息列表：QListView + 自定义 delegate（天然虚拟化，只绘制可见行）。

- 流式输出：StreamBuffer 以 50ms 节流把增量合并进模型，只刷新最后一行。
- Markdown：QTextDocument.setMarkdown 渲染，按 (文本, 宽度, 主题) 缓存文档与高度。
- 悬停操作栏：复制 / 重试 / 编辑，以及多版本时的 `< 1/2 >` 分支切换。
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from importlib.resources import files

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrame,
    QTextFrameFormat,
    QTextLength,
    QTextTable,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from braid.theme.nine_slice import NineSliceShadow

MAX_WIDTH = 680  # 对话列最大宽度（设计偏差 B），居中
PAD = 12
ACTION_H = 24
THROTTLE_MS = 50
# 与 QSS 中 `*` 文字色、userBubble 底色保持一致（tokens.json）
CODE_COLLAPSE_LINES = 20
MONO = "'JetBrains Mono','Menlo','Consolas',monospace"
_FALLBACK = {
    False: {
        "text": "#1F1F1E",
        "text2": "#6B6B69",
        "text3": "#9E9E9B",
        "bubble": "#EFEFEE",
        "subtle": "#F3F3F2",
        "control": "#F0F0EF",
        "active": "#E9E9E8",
    },
    True: {
        "text": "#ECECEA",
        "text2": "#A3A3A0",
        "text3": "#73736F",
        "bubble": "#2F2F2E",
        "subtle": "#262625",
        "control": "#30302F",
        "active": "#3A3A39",
    },
}


def _load_theme() -> dict[bool, dict[str, str]]:
    """颜色取 braid/theme/tokens.json；文件缺失或字段不全时回退到内置值。"""
    out = {k: dict(v) for k, v in _FALLBACK.items()}
    try:
        data = json.loads((files("braid.theme") / "tokens.json").read_text(encoding="utf-8"))
    except Exception:
        return out
    for dark, name in ((False, "light"), (True, "dark")):
        sect = data.get(name, {}) if isinstance(data, dict) else {}
        for k in out[dark]:
            v = sect.get(k)
            if isinstance(v, str):
                out[dark][k] = v
    return out


THEME = _load_theme()

_FENCE_RE = re.compile(r"^(?P<ind> {0,3})(?P<f>`{3,}|~{3,})(?P<info>[^\n]*)$")


def parse_code_fences(text: str) -> list[tuple[int, int, str]]:
    """返回每个围栏代码块 (开始行号, 结束行号, 代码文本)，行号指源码行。"""
    lines = text.split("\n")
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence = m.group("f")
        j = i + 1
        while j < len(lines):
            n = lines[j].strip()
            if n.startswith(fence[0] * len(fence)) and not n.strip(fence[0]):
                break
            j += 1
        out.append((i, j, "\n".join(lines[i + 1 : j])))
        i = j + 1
    return out


def collapse_source(text: str, expanded: frozenset[int]) -> str:
    """把超过 20 行且未展开的代码块截到前 20 行（只影响渲染，不改模型文本）。"""
    fences = parse_code_fences(text)
    if not fences:
        return text
    lines = text.split("\n")
    for bi in range(len(fences) - 1, -1, -1):
        start, end, code = fences[bi]
        n = code.count("\n") + 1 if code else 0
        if n > CODE_COLLAPSE_LINES and bi not in expanded:
            del lines[start + 1 + CODE_COLLAPSE_LINES : min(end, len(lines))]
    return "\n".join(lines)


@dataclass
class ChatItem:
    role: str  # "user" | "assistant"
    variants: list[str] = field(default_factory=lambda: [""])
    current: int = 0
    streaming: bool = False
    # "plain"：流式阶段按纯文本排版（字号/行高同正文）；"markdown"：完整渲染。
    render_mode: str = "markdown"
    # 已展开的长代码块：(variant 下标, 代码块下标)
    code_expanded: set[tuple[int, int]] = field(default_factory=set)

    @property
    def text(self) -> str:
        return self.variants[self.current]


class ChatModel(QAbstractListModel):
    ItemRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.items: list[ChatItem] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> object:
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == self.ItemRole:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.text
        return None

    def set_messages(self, msgs: list[tuple[str, str]]) -> None:
        self.beginResetModel()
        self.items = [ChatItem(r, [t]) for r, t in msgs]
        self.endResetModel()

    def append(self, role: str, text: str = "", streaming: bool = False) -> int:
        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        mode = "plain" if streaming else "markdown"
        self.items.append(ChatItem(role, [text], streaming=streaming, render_mode=mode))
        self.endInsertRows()
        return row

    def append_text(self, row: int, chunk: str) -> None:
        it = self.items[row]
        it.variants[it.current] += chunk
        self._changed(row)

    def finish(self, row: int) -> None:
        self.items[row].streaming = False
        # mock：目前结束即切换；流式优化接手后可改为由调用方显式 finalize(row)。
        self.finalize(row)
        self._changed(row)

    def finalize(self, row: int) -> None:
        """生成结束后调用：把该行从纯文本排版切换为 Markdown 渲染（只触发一次重排）。"""
        it = self.items[row]
        if it.render_mode != "markdown":
            it.render_mode = "markdown"
            self._changed(row)

    def new_variant(self, row: int, text: str = "", streaming: bool = True) -> None:
        it = self.items[row]
        it.variants.append(text)
        it.current = len(it.variants) - 1
        it.streaming = streaming
        it.render_mode = "plain" if streaming else "markdown"
        self._changed(row)

    def toggle_code(self, row: int, block: int) -> None:
        it = self.items[row]
        key = (it.current, block)
        it.code_expanded.symmetric_difference_update({key})
        self.layoutAboutToBeChanged.emit()
        self.layoutChanged.emit()
        self._changed(row)

    def switch_variant(self, row: int, delta: int) -> None:
        it = self.items[row]
        n = it.current + delta
        if 0 <= n < len(it.variants):
            it.current = n
            self._changed(row)

    def _changed(self, row: int) -> None:
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)


class StreamBuffer(QObject):
    """把高频增量按 50ms 合并后写入模型，避免每个字符都触发重排。"""

    def __init__(self, model: ChatModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.row = -1
        self._pending: list[str] = []
        self._timer = QTimer(self, interval=THROTTLE_MS)
        self._timer.timeout.connect(self.flush)

    def start(self, row: int) -> None:
        self.row = row
        self._timer.start()

    def push(self, chunk: str) -> None:
        self._pending.append(chunk)

    def flush(self) -> None:
        if self._pending and self.row >= 0:
            self.model.append_text(self.row, "".join(self._pending))
            self._pending.clear()

    def stop(self) -> None:
        self.flush()
        self._timer.stop()
        if self.row >= 0:
            self.model.finish(self.row)
        self.row = -1


def highlight_code_blocks(doc: QTextDocument, dark: bool) -> None:
    """给 Markdown 渲染出的代码块按 Pygments token 上色（没装 Pygments 时跳过）。"""
    try:
        from pygments.lexers import TextLexer, get_lexer_by_name
        from pygments.styles import get_style_by_name
    except ImportError:
        return
    style = get_style_by_name("github-dark" if dark else "default")
    block = doc.begin()
    while block.isValid():
        lang = block.blockFormat().property(QTextFormat.Property.BlockCodeLanguage)
        if lang is None and not block.blockFormat().hasProperty(
            QTextFormat.Property.BlockCodeFence
        ):
            block = block.next()
            continue
        start = block
        lines = []
        while block.isValid() and block.blockFormat().hasProperty(
            QTextFormat.Property.BlockCodeFence
        ):
            lines.append(block.text())
            block = block.next()
        try:
            lexer = get_lexer_by_name(str(lang or "text"))
        except Exception:
            lexer = TextLexer()
        cur = QTextCursor(doc)
        pos = start.position()
        for ttype, value in lexer.get_tokens("\n".join(lines)):
            st = style.style_for_token(ttype)
            end = min(pos + len(value), doc.characterCount() - 1)
            if st["color"] and end > pos:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#" + st["color"]))
                cur.setPosition(pos)
                cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cur.mergeCharFormat(fmt)
            pos += len(value)


@dataclass
class CodeBlockInfo:
    index: int  # 第几个代码块（消息内）
    rect: QRect  # 文档坐标，含内边距
    code: str  # 完整代码（未截断）
    total_lines: int
    collapsed: bool

    @property
    def collapsible(self) -> bool:
        return self.total_lines > CODE_COLLAPSE_LINES


CODE_PAD = 10  # 代码块左右内边距
CODE_VPAD = 8  # 代码块上下内边距
TOGGLE_H = 22  # “展开 N 行”一栏高度


def style_markdown(doc: QTextDocument, dark: bool) -> None:
    """表格 / 引用 / 行内代码 / 代码块的排版样式（颜色来自 tokens）。"""
    t = THEME[dark]
    # 表格：单元格内边距、表头浅底、无网格线
    stack: list[QTextFrame] = [doc.rootFrame()]
    while stack:
        fr = stack.pop()
        for child in fr.childFrames():
            stack.append(child)
            if isinstance(child, QTextTable):
                tf = child.format()
                tf.setBorder(0)
                tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_None)
                tf.setCellSpacing(0)
                tf.setCellPadding(6)
                tf.setBorderCollapse(True)
                tf.setWidth(QTextLength(QTextLength.Type.VariableLength, 0))
                tf.setTopMargin(4)
                tf.setBottomMargin(8)
                child.setFormat(tf)
                for c in range(child.columns()):
                    cell = child.cellAt(0, c)
                    cf = cell.format()
                    cf.setBackground(QColor(t["subtle"]))
                    cell.setFormat(cf)
    block = doc.begin()
    cur = QTextCursor(doc)
    code_bg = QColor(t["control"])
    while block.isValid():
        bf = block.blockFormat()
        is_code = bf.hasProperty(QTextFormat.Property.BlockCodeFence) or bf.hasProperty(
            QTextFormat.Property.BlockCodeLanguage
        )
        if is_code:
            # 底色由 delegate 画圆角矩形；这里只留内边距
            nf = bf
            nf.clearBackground()
            nf.setLeftMargin(CODE_PAD)
            nf.setRightMargin(CODE_PAD)
            cur.setPosition(block.position())
            cur.setBlockFormat(nf)
        elif bf.hasProperty(QTextFormat.Property.BlockQuoteLevel):
            level = int(bf.property(QTextFormat.Property.BlockQuoteLevel) or 1)
            nf = bf
            nf.setLeftMargin(14 * level)
            nf.setIndent(0)
            cur.setPosition(block.position())
            cur.setBlockFormat(nf)
            cur.setPosition(block.position())
            cur.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            cf = QTextCharFormat()
            cf.setForeground(QColor(t["text2"]))
            cur.mergeCharFormat(cf)
        else:
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().fontFixedPitch():
                    cf = QTextCharFormat()
                    cf.setBackground(QBrush(code_bg))
                    cf.setFontFamilies(["JetBrains Mono", "Menlo", "Consolas", "monospace"])
                    cur.setPosition(frag.position())
                    cur.setPosition(
                        frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor
                    )
                    cur.mergeCharFormat(cf)
                it += 1
        block = block.next()


def _code_groups(doc: QTextDocument) -> list[list[int]]:
    """文档中连续的代码块段落，按出现顺序返回 block 编号列表。"""
    groups: list[list[int]] = []
    prev = False
    block = doc.begin()
    while block.isValid():
        bf = block.blockFormat()
        is_code = bf.hasProperty(QTextFormat.Property.BlockCodeFence)
        if is_code:
            if not prev:
                groups.append([])
            groups[-1].append(block.blockNumber())
        prev = is_code
        block = block.next()
    return groups


def _split_groups(
    groups: list[list[int]], fences: list[tuple[int, int, str]], expanded: frozenset[int]
) -> list[list[int]]:
    """相邻代码块在文档里会连成一段；按源码中每块（截断后）的行数切开。"""
    sizes = []
    for i, (_s, _e, code) in enumerate(fences):
        n = code.count("\n") + 1 if code else 1
        if n > CODE_COLLAPSE_LINES and i not in expanded:
            n = CODE_COLLAPSE_LINES
        sizes.append(n)
    out: list[list[int]] = []
    k = 0
    for g in groups:
        pos = 0
        while pos < len(g):
            n = sizes[k] if k < len(sizes) else len(g) - pos
            out.append(g[pos : pos + n])
            pos += n
            k += 1
    return [g for g in out if g]


def _pad_code_blocks(doc: QTextDocument, groups: list[list[int]], collapsed: list[bool]) -> None:
    for g, col in zip(groups, collapsed, strict=False):
        for num, extra in ((g[0], "top"), (g[-1], "bottom")):
            b = doc.findBlockByNumber(num)
            bf = b.blockFormat()
            if extra == "top":
                bf.setTopMargin(2 * CODE_VPAD + 6)  # 相邻块 margin 会折叠，留出间隙
            else:
                bf.setBottomMargin(CODE_VPAD + 6 + (TOGGLE_H if col else 0))
            c = QTextCursor(b)
            c.setBlockFormat(bf)


class _DocCache:
    def __init__(self, cap: int = 512) -> None:
        self.cap = cap
        self._d: OrderedDict[tuple[str, int, bool, str, frozenset[int]], QTextDocument] = (
            OrderedDict()
        )
        self._blocks: dict[int, list[CodeBlockInfo]] = {}

    def get(
        self,
        text: str,
        width: int,
        dark: bool,
        mode: str = "markdown",
        expanded: frozenset[int] = frozenset(),
    ) -> QTextDocument:
        key = (text, width, dark, mode, expanded if mode == "markdown" else frozenset())
        doc = self._d.get(key)
        if doc is None:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(f"pre, code {{ font-family: {MONO}; }}")
            blocks: list[CodeBlockInfo] = []
            if mode == "plain":
                doc.setPlainText(text)
                doc.setTextWidth(width)
            else:
                fences = parse_code_fences(text)
                doc.setMarkdown(collapse_source(text, expanded))
                highlight_code_blocks(doc, dark)
                style_markdown(doc, dark)
                groups = _split_groups(_code_groups(doc), fences, expanded)
                infos = []
                for i, (_s, _e, code) in enumerate(fences[: len(groups)]):
                    n = code.count("\n") + 1 if code else 0
                    infos.append((code, n, n > CODE_COLLAPSE_LINES and i not in expanded))
                _pad_code_blocks(doc, groups, [c for _a, _b, c in infos])
                doc.setTextWidth(width)
                lay = doc.documentLayout()
                for i, (g, (code, n, col)) in enumerate(zip(groups, infos, strict=False)):
                    b0 = doc.findBlockByNumber(g[0])
                    b1 = doc.findBlockByNumber(g[-1])
                    r0 = lay.blockBoundingRect(b0)
                    r1 = lay.blockBoundingRect(b1)
                    top = int(r0.top()) - CODE_VPAD
                    bottom = int(r1.bottom()) + CODE_VPAD
                    rect = QRect(0, top, width, max(1, bottom - top))
                    blocks.append(CodeBlockInfo(i, rect, code, n, col))
            self._d[key] = doc
            self._blocks[id(doc)] = blocks
            if len(self._d) > self.cap:
                _k, old = self._d.popitem(last=False)
                self._blocks.pop(id(old), None)
        else:
            self._d.move_to_end(key)
        return doc

    def code_blocks(self, doc: QTextDocument) -> list[CodeBlockInfo]:
        return self._blocks.get(id(doc), [])


class ChatDelegate(QStyledItemDelegate):
    actionTriggered = Signal(int, str)  # row, action: copy/retry/edit/prev/next

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = _DocCache()
        self.hover_row = -1
        self.dark = False
        self.hover_pos: QPoint | None = None  # 视图坐标，用于代码块悬停“复制”
        self.shadow_opacity = 0.55  # 用户气泡阴影保持很淡

    # 布局
    def _column(self, rect: QRect) -> QRect:
        w = min(MAX_WIDTH, rect.width() - 2 * PAD)
        x = rect.x() + (rect.width() - w) // 2
        return QRect(x, rect.y(), w, rect.height())

    def _text_width(self, item: ChatItem, col_w: int) -> int:
        return int(col_w * 0.8) - 2 * PAD if item.role == "user" else col_w

    def _doc(self, item: ChatItem, tw: int) -> QTextDocument:
        exp = frozenset(b for v, b in item.code_expanded if v == item.current)
        return self.cache.get(item.text or " ", tw, self.dark, item.render_mode, exp)

    def _code_rects(
        self, item: ChatItem, bubble: QRect, doc: QTextDocument
    ) -> list[tuple[CodeBlockInfo, QRect, QRect, QRect]]:
        """每个代码块：(信息, 底色矩形, 复制按钮矩形, 展开/收起矩形)，视图坐标。"""
        if item.render_mode != "markdown":
            return []
        ox, oy = bubble.x() + PAD, bubble.y() + PAD
        out = []
        for info in self.cache.code_blocks(doc):
            r = info.rect.translated(ox, oy)
            copy = QRect(r.right() - 44, r.top() + 4, 40, 20)
            tog = QRect(r.x(), r.bottom() + 1, r.width(), TOGGLE_H) if info.collapsible else QRect()
            if info.collapsible and not info.collapsed:
                tog = QRect(r.right() - 92, r.top() + 4, 44, 20)
            out.append((info, r, copy, tog))
        return out

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        item: ChatItem = index.data(ChatModel.ItemRole)
        col = self._column(option.rect)
        tw = max(80, self._text_width(item, col.width()))
        doc = self._doc(item, tw)
        h = int(doc.size().height()) + 2 * PAD + ACTION_H
        return QSize(option.rect.width(), h)

    def _bubble_rect(self, item: ChatItem, col: QRect, doc: QTextDocument) -> QRect:
        w = int(doc.idealWidth()) + 2 * PAD
        h = int(doc.size().height()) + 2 * PAD
        if item.role == "user":
            return QRect(col.right() - w, col.y(), w, h)
        return QRect(col.x() - PAD, col.y(), col.width() + 2 * PAD, h)

    def _actions(
        self, item: ChatItem, row_rect: QRect, bubble: QRect
    ) -> list[tuple[str, str, QRect]]:
        names: list[tuple[str, str]] = [("copy", "复制")]
        names.append(("edit", "编辑") if item.role == "user" else ("retry", "重试"))
        y = bubble.bottom() + 2
        out: list[tuple[str, str, QRect]] = []
        x = bubble.x() + (0 if item.role == "assistant" else 0)
        if item.role == "user":
            x = bubble.right() - 160
        if len(item.variants) > 1:
            for key, label in (
                ("prev", "‹"),
                ("_", f"{item.current + 1}/{len(item.variants)}"),
                ("next", "›"),
            ):
                w = 28 if key != "_" else 36
                out.append((key, label, QRect(x, y, w, ACTION_H - 4)))
                x += w
        for key, label in names:
            out.append((key, label, QRect(x, y, 40, ACTION_H - 4)))
            x += 44
        return out

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        item: ChatItem = index.data(ChatModel.ItemRole)
        rect: QRect = option.rect
        col = self._column(rect.adjusted(0, PAD // 2, 0, 0))
        doc = self._doc(item, max(80, self._text_width(item, col.width())))
        bubble = self._bubble_rect(item, col, doc)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = option.palette
        t = THEME[self.dark]
        if item.role == "user":
            painter.save()
            painter.setOpacity(self.shadow_opacity)
            NineSliceShadow.get("e2", self.dark).paint(painter, bubble)
            painter.restore()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["bubble"]))
            painter.drawRoundedRect(bubble, 12, 12)
        codes = self._code_rects(item, bubble, doc)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["control"] if item.role == "user" else t["subtle"]))
        for info, r, _c, _t in codes:
            full = r.adjusted(0, 0, 0, TOGGLE_H if info.collapsed else 0)
            painter.drawRoundedRect(full, 8, 8)
        painter.save()
        painter.translate(bubble.x() + PAD, bubble.y() + PAD)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(THEME[self.dark]["text"]))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()
        small = QFont(option.font)
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        painter.setFont(small)
        for info, r, copy, tog in codes:
            if info.collapsed:
                painter.setPen(QColor(t["text2"]))
                n = info.total_lines - CODE_COLLAPSE_LINES
                painter.drawText(tog, Qt.AlignmentFlag.AlignCenter, f"展开 {n} 行")
            hovered = self.hover_pos is not None and r.contains(self.hover_pos)
            if hovered and not item.streaming:
                painter.setPen(QColor(t["text3"]))
                painter.drawText(copy, Qt.AlignmentFlag.AlignCenter, "复制")
                if info.collapsible and not info.collapsed:
                    painter.drawText(tog, Qt.AlignmentFlag.AlignCenter, "收起")
        painter.restore()
        if item.streaming:
            painter.fillRect(
                QRect(bubble.x() + PAD, bubble.bottom() - PAD + 2, 8, 2), pal.highlight()
            )
        if index.row() == self.hover_row and not item.streaming:
            painter.save()
            painter.setPen(QColor(pal.placeholderText().color()))
            for _key, label, r in self._actions(item, rect, bubble):
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()

    def hit(self, option_rect: QRect, item: ChatItem, pos) -> str | None:  # noqa: ANN001
        col = self._column(option_rect.adjusted(0, PAD // 2, 0, 0))
        doc = self._doc(item, max(80, self._text_width(item, col.width())))
        bubble = self._bubble_rect(item, col, doc)
        if not item.streaming:
            for info, r, copy, tog in self._code_rects(item, bubble, doc):
                if copy.contains(pos) and r.contains(pos):
                    return f"code_copy:{info.index}"
                if not tog.isNull() and tog.contains(pos):
                    return f"code_toggle:{info.index}"
        for key, _l, r in self._actions(item, option_rect, bubble):
            if key != "_" and r.contains(pos):
                return key
        return None


class ChatView(QListView):
    """消息列表视图。外部通过 `actionTriggered(row, action)` 处理重试/编辑等。"""

    actionTriggered = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.chat_model = ChatModel(self)
        self.setModel(self.chat_model)
        self.delegate = ChatDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(False)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.stream = StreamBuffer(self.chat_model, self)
        self.chat_model.rowsInserted.connect(lambda *_: self._stick_bottom())
        self.chat_model.dataChanged.connect(lambda *_: self._stick_bottom())
        self._at_bottom = True
        self.verticalScrollBar().valueChanged.connect(self._track_bottom)

    def _track_bottom(self, v: int) -> None:
        self._at_bottom = v >= self.verticalScrollBar().maximum() - 4

    def _stick_bottom(self) -> None:
        if self._at_bottom:
            QTimer.singleShot(0, self.scrollToBottom)

    def set_dark(self, dark: bool) -> None:
        self.delegate.dark = dark
        self.doItemsLayout()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self.delegate.hover_pos = e.position().toPoint()
        row = self.indexAt(e.position().toPoint()).row()
        if row >= 0:
            self.update(self.chat_model.index(row))
        if row != self.delegate.hover_row:
            old, self.delegate.hover_row = self.delegate.hover_row, row
            for r in (old, row):
                if r >= 0:
                    self.update(self.chat_model.index(r))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e: QEvent) -> None:
        self.delegate.hover_pos = None
        if self.delegate.hover_row >= 0:
            r, self.delegate.hover_row = self.delegate.hover_row, -1
            self.update(self.chat_model.index(r))
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid() and e.button() == Qt.MouseButton.LeftButton:
            item = self.chat_model.items[idx.row()]
            action = self.delegate.hit(self.visualRect(idx), item, pos)
            if action:
                self.trigger(idx.row(), action)
                return
        super().mouseReleaseEvent(e)

    def trigger(self, row: int, action: str) -> None:
        if action == "copy":
            QGuiApplication.clipboard().setText(self.chat_model.items[row].text)
        elif action.startswith("code_copy:"):
            item = self.chat_model.items[row]
            idx = int(action.split(":", 1)[1])
            fences = parse_code_fences(item.text)
            if idx < len(fences):
                QGuiApplication.clipboard().setText(fences[idx][2])
        elif action.startswith("code_toggle:"):
            self.chat_model.toggle_code(row, int(action.split(":", 1)[1]))
        elif action == "prev":
            self.chat_model.switch_variant(row, -1)
        elif action == "next":
            self.chat_model.switch_variant(row, 1)
        self.actionTriggered.emit(row, action)
