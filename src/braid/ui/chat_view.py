"""消息列表：QListView + 自定义 delegate（天然虚拟化，只绘制可见行）。

- 流式输出：StreamBuffer 以 50ms 节流把增量合并进模型，只刷新最后一行。
- Markdown：QTextDocument.setMarkdown 渲染，按 (文本, 宽度, 主题) 缓存文档与高度。
- 悬停操作栏：复制 / 重试 / 编辑，以及多版本时的 `< 1/2 >` 分支切换。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

MAX_WIDTH = 680  # 对话列最大宽度（设计偏差 B），居中
PAD = 12
ACTION_H = 24
THROTTLE_MS = 50
# 与 QSS 中 `*` 文字色、userBubble 底色保持一致（tokens.json）
THEME = {
    False: {"text": "#1F1F1E", "bubble": "#EFEFEE"},
    True: {"text": "#ECECEA", "bubble": "#2F2F2E"},
}


@dataclass
class ChatItem:
    role: str  # "user" | "assistant"
    variants: list[str] = field(default_factory=lambda: [""])
    current: int = 0
    streaming: bool = False

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
        self.items.append(ChatItem(role, [text], streaming=streaming))
        self.endInsertRows()
        return row

    def append_text(self, row: int, chunk: str) -> None:
        it = self.items[row]
        it.variants[it.current] += chunk
        self._changed(row)

    def finish(self, row: int) -> None:
        self.items[row].streaming = False
        self._changed(row)

    def new_variant(self, row: int, text: str = "", streaming: bool = True) -> None:
        it = self.items[row]
        it.variants.append(text)
        it.current = len(it.variants) - 1
        it.streaming = streaming
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


class _DocCache:
    def __init__(self, cap: int = 512) -> None:
        self.cap = cap
        self._d: OrderedDict[tuple[str, int, bool], QTextDocument] = OrderedDict()

    def get(self, text: str, width: int, dark: bool) -> QTextDocument:
        key = (text, width, dark)
        doc = self._d.get(key)
        if doc is None:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(
                "pre, code { font-family: 'JetBrains Mono','Menlo','Consolas',monospace; }"
            )
            doc.setMarkdown(text)
            highlight_code_blocks(doc, dark)
            doc.setTextWidth(width)
            self._d[key] = doc
            if len(self._d) > self.cap:
                self._d.popitem(last=False)
        else:
            self._d.move_to_end(key)
        return doc


class ChatDelegate(QStyledItemDelegate):
    actionTriggered = Signal(int, str)  # row, action: copy/retry/edit/prev/next

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = _DocCache()
        self.hover_row = -1
        self.dark = False
        self.bubble_pixmap = None  # 预留：UI 提供的九宫格阴影图

    # 布局
    def _column(self, rect: QRect) -> QRect:
        w = min(MAX_WIDTH, rect.width() - 2 * PAD)
        x = rect.x() + (rect.width() - w) // 2
        return QRect(x, rect.y(), w, rect.height())

    def _text_width(self, item: ChatItem, col_w: int) -> int:
        return int(col_w * 0.8) - 2 * PAD if item.role == "user" else col_w

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        item: ChatItem = index.data(ChatModel.ItemRole)
        col = self._column(option.rect)
        tw = max(80, self._text_width(item, col.width()))
        doc = self.cache.get(item.text or " ", tw, self.dark)
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
        doc = self.cache.get(
            item.text or " ", max(80, self._text_width(item, col.width())), self.dark
        )
        bubble = self._bubble_rect(item, col, doc)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = option.palette
        if item.role == "user":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME[self.dark]["bubble"]))
            painter.drawRoundedRect(bubble, 12, 12)
        painter.translate(bubble.x() + PAD, bubble.y() + PAD)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(THEME[self.dark]["text"]))
        doc.documentLayout().draw(painter, ctx)
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
        doc = self.cache.get(
            item.text or " ", max(80, self._text_width(item, col.width())), self.dark
        )
        for key, _l, r in self._actions(item, option_rect, self._bubble_rect(item, col, doc)):
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
        row = self.indexAt(e.position().toPoint()).row()
        if row != self.delegate.hover_row:
            old, self.delegate.hover_row = self.delegate.hover_row, row
            for r in (old, row):
                if r >= 0:
                    self.update(self.chat_model.index(r))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e: QEvent) -> None:
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
        elif action == "prev":
            self.chat_model.switch_variant(row, -1)
        elif action == "next":
            self.chat_model.switch_variant(row, 1)
        self.actionTriggered.emit(row, action)
