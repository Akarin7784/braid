"""消息列表：QListView + 自定义 delegate（天然虚拟化，只绘制可见行）。

- 流式输出：StreamBuffer 以 THROTTLE_MS（50ms）节流把增量合并进模型，只刷新最后一行。
- Markdown：QTextDocument.setMarkdown 渲染，按 (文本, 宽度, 主题) 缓存文档与高度。
- 悬停操作栏：复制 / 重试 / 编辑，以及多版本时的 `< 1/2 >` 分支切换。
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
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
    QLinearGradient,
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
    QApplication,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import tokens as palette_tokens

MAX_WIDTH = 680  # 对话列最大宽度（设计偏差 B），居中
PAD = 12
ACTION_H = 24
THROTTLE_MS = 50  # 每帧约 30ms，更小的间隔只会让排版连着跑；增量排版后再按基准调整
# 与 QSS 中 `*` 文字色、userBubble 底色保持一致（tokens.json）
CODE_COLLAPSE_LINES = 20
MONO = "'JetBrains Mono','Menlo','Consolas',monospace"


class _Theme:
    """按需读 tokens.json（palette.tokens 带缓存）；主题切换后 cache_clear 即可生效。"""

    def __getitem__(self, dark: bool) -> dict[str, str]:
        return palette_tokens(dark)


THEME = _Theme()
_FIXED_LH = 2  # QTextBlockFormat.LineHeightTypes.FixedHeight

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
        """标记流式结束；不切换渲染模式，由流结束路径显式调用 finalize(row)。"""
        self.items[row].streaming = False
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
    """把高频增量缓冲起来，按 THROTTLE_MS 合并写入模型，避免每个 token 都触发重排。

    定时器归本对象所有（随 ChatView 销毁），只在有待写入内容时运行。
    """

    def __init__(self, model: ChatModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.row = -1
        self._pending: list[str] = []
        self._timer = QTimer(self)
        self._timer.setInterval(THROTTLE_MS)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)

    @property
    def active(self) -> bool:
        return self.row >= 0

    def start(self, row: int) -> None:
        if self.active and self.row != row:
            self.stop()
        self._pending.clear()
        self.row = row

    def push(self, chunk: str) -> None:
        if not chunk or not self.active:
            return
        self._pending.append(chunk)
        if not self._timer.isActive():
            self._timer.start()

    def flush(self) -> None:
        self._timer.stop()
        if self._pending and self.active:
            self.model.append_text(self.row, "".join(self._pending))
        self._pending.clear()

    def stop(self) -> None:
        """流结束：写完剩余内容，标记结束，再显式切换到 Markdown 渲染（只一次）。"""
        if not self.active:
            return
        self.flush()
        row, self.row = self.row, -1
        self.model.finish(row)
        self.model.finalize(row)


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


CODE_PAD = 12  # 代码块左右内边距
CODE_VPAD = 12  # 代码块上下内边距
CODE_FONT_PX = 12
CODE_LINE_H = 20
TOGGLE_H = 24  # “展开 N 行”一栏高度（叠在渐隐区上）
FADE_H = 48  # 折叠代码块底部渐隐高度（约两行半，“展开 N 行”叠在其底部）
TOGGLE_BOTTOM = 8  # “展开 N 行”距代码块底边
GAP = 12  # 段落 / 表格 / 代码块之间的统一间距
COPIED_MS = 1500


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
                tf.setCellPadding(0)
                tf.setBorderCollapse(True)
                tf.setWidth(QTextLength(QTextLength.Type.VariableLength, 0))
                tf.setTopMargin(GAP)
                tf.setBottomMargin(GAP)
                child.setFormat(tf)
                for r in range(child.rows()):
                    for c in range(child.columns()):
                        cell = child.cellAt(r, c)
                        tcf = cell.format().toTableCellFormat()
                        tcf.setLeftPadding(12)
                        tcf.setRightPadding(12)
                        tcf.setTopPadding(4)
                        tcf.setBottomPadding(4)
                        if r == 0:
                            tcf.setBackground(QColor(t["subtle"]))
                        cell.setFormat(tcf)
                        # 行高 28 = 4 + 20 + 4
                        cc = cell.firstCursorPosition()
                        bf = cc.blockFormat()
                        bf.setLineHeight(20, _FIXED_LH)
                        bf.setTopMargin(0)
                        bf.setBottomMargin(0)
                        cc.setBlockFormat(bf)
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
            nf.setTopMargin(0)
            nf.setBottomMargin(0)
            nf.setLineHeight(CODE_LINE_H, _FIXED_LH)
            cur.setPosition(block.position())
            cur.setBlockFormat(nf)
            cur.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            cf = QTextCharFormat()
            f = QFont()
            f.setFamilies(["JetBrains Mono", "Menlo", "Consolas", "monospace"])
            f.setPixelSize(CODE_FONT_PX)
            cf.setFont(
                f, QTextCharFormat.FontPropertiesInheritanceBehavior.FontPropertiesSpecifiedOnly
            )
            cur.mergeCharFormat(cf)
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


def _uniform_spacing(doc: QTextDocument) -> None:
    """普通段落上下 margin 统一为 GAP（相邻 margin 折叠，最终间距即 GAP）。"""
    cur = QTextCursor(doc)
    block = doc.begin()
    while block.isValid():
        bf = block.blockFormat()
        cur.setPosition(block.position())
        in_table = cur.currentTable() is not None
        if not in_table and not bf.hasProperty(QTextFormat.Property.BlockCodeFence):
            bf.setTopMargin(GAP)
            bf.setBottomMargin(GAP)
            cur.setBlockFormat(bf)
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
    # margin 会折叠（取较大值），所以：段落↔代码块 = VPAD+GAP；代码块↔代码块要再加一个 VPAD
    ends = {g[-1] for g in groups}
    for g, col in zip(groups, collapsed, strict=False):
        for num, extra in ((g[0], "top"), (g[-1], "bottom")):
            b = doc.findBlockByNumber(num)
            bf = b.blockFormat()
            if extra == "top":
                adj = (num - 1) in ends
                bf.setTopMargin(CODE_VPAD + GAP + (CODE_VPAD if adj else 0))
            else:
                bf.setBottomMargin(CODE_VPAD + GAP + (TOGGLE_H if col else 0))
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
                _uniform_spacing(doc)
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
                    bottom = int(r1.top()) + CODE_LINE_H + CODE_VPAD + (TOGGLE_H if col else 0)
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


class _StreamDoc:
    """流式行的增量排版：只把新增尾部插入同一个 QTextDocument。

    QTextDocumentLayout 只重排受影响的段落，前面已排好的段落与高度都保留，
    所以每帧成本与新增文本量相关，而不是与整条消息长度相关。不进 _DocCache
    （它按完整文本做键，流式时每帧都会生成一份新文档）。
    """

    def __init__(self) -> None:
        self.text = ""
        self.width = -1
        self.doc = QTextDocument()
        self.doc.setDocumentMargin(0)
        self.doc.setUndoRedoEnabled(False)
        self._cursor = QTextCursor(self.doc)

    def update(self, text: str, width: int) -> QTextDocument:
        if width != self.width:
            self.width = width
            self.doc.setTextWidth(width)
        if text == self.text:
            return self.doc
        if self.text and text.startswith(self.text):
            # 光标在上次插入后已停在末尾；只在被意外移动时才重新定位
            if self._cursor.position() != self.doc.characterCount() - 1:
                self._cursor.movePosition(QTextCursor.MoveOperation.End)
            self._cursor.insertText(text[len(self.text) :])
        else:
            self.doc.setPlainText(text)
            self.doc.setTextWidth(width)
        self.text = text
        return self.doc


class ChatDelegate(QStyledItemDelegate):
    actionTriggered = Signal(int, str)  # row, action: copy/retry/edit/prev/next

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = _DocCache()
        # 正在流式输出的行（按 ChatItem 身份）-> 增量文档
        self._streams: dict[int, tuple[ChatItem, _StreamDoc]] = {}
        # 已结束消息的行高缓存：id(item) -> (键, 高度)。键含文本/变体/展开状态、宽度和 dark，
        # 任一变化（编辑、切变体、展开代码块、改宽、切主题）都自然失效；流式行不缓存。
        self._heights: dict[int, tuple[tuple[object, ...], int]] = {}
        self.height_hits = 0
        self.hover_row = -1
        self.dark_override: bool | None = None  # None 表示跟随 app 的 braidDark
        self.hover_pos: QPoint | None = None  # 视图坐标，用于代码块悬停“复制”
        self.shadow_opacity = 0.55  # 用户气泡阴影保持很淡
        # (row, 代码块下标) -> 计时器；存在即显示“已复制 ✓”
        self.copied: dict[tuple[int, int], QTimer] = {}
        self.copiedChanged_cb: list[Callable[[int], None]] = []  # 视图注册刷新回调

    @property
    def dark(self) -> bool:
        if self.dark_override is not None:
            return self.dark_override
        app = QApplication.instance()
        return bool(app.property("braidDark")) if app else False

    def mark_copied(self, row: int, block: int) -> None:
        key = (row, block)
        old = self.copied.pop(key, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(COPIED_MS)
        timer.timeout.connect(lambda: self._unmark(key))
        self.copied[key] = timer
        timer.start()
        self._notify(row)

    def _unmark(self, key: tuple[int, int]) -> None:
        t = self.copied.pop(key, None)
        if t is not None:
            t.deleteLater()
        self._notify(key[0])

    def _notify(self, row: int) -> None:
        for cb in self.copiedChanged_cb:
            cb(row)

    def copy_label(self, row: int, block: int) -> str:
        return "已复制 ✓" if (row, block) in self.copied else "复制"

    # 布局
    def _column(self, rect: QRect) -> QRect:
        w = min(MAX_WIDTH, rect.width() - 2 * PAD)
        x = rect.x() + (rect.width() - w) // 2
        return QRect(x, rect.y(), w, rect.height())

    def _text_width(self, item: ChatItem, col_w: int) -> int:
        return int(col_w * 0.8) - 2 * PAD if item.role == "user" else col_w

    def _doc(self, item: ChatItem, tw: int) -> QTextDocument:
        if item.streaming and item.render_mode == "plain" and item.text:
            return self._stream_doc(item, tw)
        if self._streams:
            self._prune_streams()
        exp = frozenset(b for v, b in item.code_expanded if v == item.current)
        return self.cache.get(item.text or " ", tw, self.dark, item.render_mode, exp)

    def _prune_streams(self) -> None:
        """释放已结束流式的增量文档。"""
        for k in [k for k, (it, _s) in self._streams.items() if not it.streaming]:
            del self._streams[k]

    def _stream_doc(self, item: ChatItem, tw: int) -> QTextDocument:
        self._prune_streams()
        entry = self._streams.get(id(item))
        if entry is None or entry[0] is not item:
            entry = (item, _StreamDoc())
            self._streams[id(item)] = entry
        return entry[1].update(item.text, tw)

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
            copy = QRect(r.right() - 68, r.top() + 4, 64, 20)
            tog = QRect()
            if info.collapsed:
                tog = QRect(r.x(), r.bottom() - TOGGLE_BOTTOM - TOGGLE_H + 1, r.width(), TOGGLE_H)
            elif info.collapsible:
                tog = QRect(r.right() - 116, r.top() + 4, 44, 20)
            out.append((info, r, copy, tog))
        return out

    @staticmethod
    def fade_rect(code_rect: QRect) -> QRect:
        """折叠代码块底部渐隐区：最后 FADE_H，“展开 N 行”叠在其底部。"""
        h = FADE_H
        return QRect(code_rect.x(), code_rect.bottom() - h + 1, code_rect.width(), h)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        item: ChatItem = index.data(ChatModel.ItemRole)
        width = option.rect.width()
        key: tuple[object, ...] | None = None
        if not item.streaming:
            exp = frozenset(b for v, b in item.code_expanded if v == item.current)
            key = (item.role, item.current, item.text, item.render_mode, exp, width, self.dark)
            hit = self._heights.get(id(item))
            if hit is not None and hit[0] == key:
                self.height_hits += 1
                return QSize(width, hit[1])
        else:
            self._heights.pop(id(item), None)
        col = self._column(option.rect)
        tw = max(80, self._text_width(item, col.width()))
        doc = self._doc(item, tw)
        h = int(doc.size().height()) + 2 * PAD + ACTION_H
        if key is not None:
            if len(self._heights) > 4096:
                self._heights.clear()
            self._heights[id(item)] = (key, h)
        return QSize(width, h)

    def clear_height_cache(self) -> None:
        self._heights.clear()

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
            painter.setBrush(QColor(t["subtle"] if self.dark else t["bubble"]))
            painter.drawRoundedRect(bubble, 12, 12)
        codes = self._code_rects(item, bubble, doc)
        painter.setPen(Qt.PenStyle.NoPen)
        code_bg = QColor(t["control"] if item.role == "user" else t["subtle"])
        painter.setBrush(code_bg)
        for _info, r, _c, _t in codes:
            painter.drawRoundedRect(r, 8, 8)
        painter.save()
        painter.translate(bubble.x() + PAD, bubble.y() + PAD)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        # 只绘制视口内可见的部分：长消息（尤其流式中的最后一行）不再整篇重画
        widget = option.widget
        if isinstance(widget, QAbstractItemView):
            vis = widget.viewport().rect().intersected(rect)
            if not vis.isEmpty():
                ctx.clip = QRectF(vis.translated(-(bubble.x() + PAD), -(bubble.y() + PAD)))
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(THEME[self.dark]["text"]))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()
        small = QFont(option.font)
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        painter.setFont(small)
        for info, r, copy, tog in codes:
            if info.collapsed:
                # 底部渐隐：透明 → 代码块底色，“展开 N 行”叠在上面
                fade = self.fade_rect(r)
                grad = QLinearGradient(0, fade.top(), 0, fade.bottom())
                clear = QColor(code_bg)
                clear.setAlpha(0)
                grad.setColorAt(0.0, clear)
                grad.setColorAt(0.7, code_bg)
                grad.setColorAt(1.0, code_bg)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(grad))
                painter.drawRoundedRect(fade, 8, 8)
                painter.setPen(QColor(t["text2"]))
                n = info.total_lines - CODE_COLLAPSE_LINES
                painter.drawText(tog, Qt.AlignmentFlag.AlignCenter, f"展开 {n} 行")
            hovered = self.hover_pos is not None and r.contains(self.hover_pos)
            done = (index.row(), info.index) in self.copied
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            if done:
                painter.setPen(QColor(t["success"]))
                painter.drawText(copy, align, "已复制 ✓")
            elif hovered and not item.streaming:
                painter.setPen(QColor(t["text3"]))
                painter.drawText(copy, align, "复制")
            if hovered and not item.streaming:
                painter.setPen(QColor(t["text3"]))
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
        self.delegate.copiedChanged_cb.append(
            lambda r: (
                self.update(self.chat_model.index(r)) if r < self.chat_model.rowCount() else None
            )
        )
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

    def set_dark(self, dark: bool | None) -> None:
        """手动覆盖深浅色；传 None 恢复跟随 app 的 braidDark。"""
        self.delegate.dark_override = dark
        self.doItemsLayout()

    def changeEvent(self, e: QEvent) -> None:
        # 运行时切主题会换样式表/调色板，重新排版以取新的 braidDark
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.doItemsLayout()
        super().changeEvent(e)

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
                self.delegate.mark_copied(row, idx)
        elif action.startswith("code_toggle:"):
            self.chat_model.toggle_code(row, int(action.split(":", 1)[1]))
        elif action == "prev":
            self.chat_model.switch_variant(row, -1)
        elif action == "next":
            self.chat_model.switch_variant(row, 1)
        self.actionTriggered.emit(row, action)
