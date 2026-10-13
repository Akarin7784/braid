"""左侧会话栏：新建、搜索、重命名、删除、置顶；按项目分组（无项目归入"未分配"），组可折叠。"""

from __future__ import annotations

from PySide6.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend, Session
from braid.core.session_store import SessionStore
from braid.theme.palette import qcolor, tokens

SID = Qt.ItemDataRole.UserRole
HEADER = Qt.ItemDataRole.UserRole + 1
GROUP = Qt.ItemDataRole.UserRole + 2  # 组标题：组 key
FIRST = Qt.ItemDataRole.UserRole + 3  # 是否第一组（上方只留 8px）
COLLAPSED = Qt.ItemDataRole.UserRole + 4

UNASSIGNED = "未分配"
ROW_H = 32
ROW_GAP = 2
HEADER_TOP, HEADER_TOP_FIRST, HEADER_BOTTOM, HEADER_TEXT_H = 20, 8, 8, 14
ARROW = 12


def _c(name: str, dark: bool) -> QColor:
    return qcolor(name, dark)


SELECTED_BG = {d: tokens(d)["row_sel"] for d in (False, True)}


def _hover(dark: bool) -> QColor:
    c = _c("row_sel", dark)
    c.setAlphaF(c.alphaF() * 0.6)
    return c


def _dark() -> bool:
    app = QApplication.instance()
    return bool(app.property("braidDark")) if app else False


class SessionDelegate(QStyledItemDelegate):
    """组标题：12px 箭头 + 11px text3；会话行：row_sel 淡底，常规字重。"""

    def paint(
        self, p: QPainter, opt: QStyleOptionViewItem, idx: QModelIndex | QPersistentModelIndex
    ) -> None:
        dark = _dark()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if idx.data(HEADER):
            top = HEADER_TOP_FIRST if idx.data(FIRST) else HEADER_TOP
            band = QRectF(
                opt.rect.x() + 8, opt.rect.y() + top, opt.rect.width() - 16, HEADER_TEXT_H
            )
            c = _c("text3", dark)
            pen = QPen(c, 1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            cx, cy = band.x() + ARROW / 2, band.center().y()
            if idx.data(COLLAPSED):
                pts = [QPointF(cx - 1.5, cy - 3), QPointF(cx + 1.5, cy), QPointF(cx - 1.5, cy + 3)]
            else:
                pts = [QPointF(cx - 3, cy - 1.5), QPointF(cx, cy + 1.5), QPointF(cx + 3, cy - 1.5)]
            p.drawPolyline(pts)
            f = QFont(opt.font)
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.Normal)
            p.setFont(f)
            p.drawText(
                band.adjusted(ARROW + 4, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                idx.data(),
            )
            p.restore()
            return
        r = QRectF(opt.rect).adjusted(2, ROW_GAP / 2, -2, -ROW_GAP / 2)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        if sel:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("row_sel", dark))
            p.drawRoundedRect(r, 8, 8)
        elif opt.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_hover(dark))
            p.drawRoundedRect(r, 8, 8)
        f = QFont(opt.font)
        f.setWeight(QFont.Weight.Normal)
        f.setBold(False)
        p.setFont(f)
        p.setPen(_c("text" if sel else "text2", dark))
        text = p.fontMetrics().elidedText(
            idx.data() or "", Qt.TextElideMode.ElideRight, int(r.width()) - 20
        )
        p.drawText(
            r.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        p.restore()


class Sidebar(QFrame):
    sessionSelected = Signal(object)  # Session
    entryTriggered = Signal(str)  # projects / artifacts / schedules

    def __init__(
        self,
        backend: AgentBackend,
        parent: QWidget | None = None,
        store: SessionStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.backend = backend
        self.store = store
        self.sessions: list[Session] = list(backend.list_sessions())
        self.pinned: set[str] = set()
        if store is not None:
            known = {r.id: r for r in store.list_sessions()}
            for sess in self.sessions:
                r = known.get(sess.id)
                if r is None:
                    store.upsert(sess.id, sess.title, project_id=sess.project_id)
                else:
                    if r.pinned:
                        self.pinned.add(sess.id)
                    if r.project_id is not None:
                        sess.project_id = r.project_id
        self._current: str | None = None
        self._rebuilding = False
        self.collapsed: set[str] = set()  # 折叠的组 key

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        self.new_btn = QPushButton("＋ 新对话")
        self.new_btn.setProperty("variant", "secondary")
        self.new_btn.setObjectName("NewSession")
        self.new_btn.clicked.connect(self.new_session)
        lay.addWidget(self.new_btn)
        self.search = QLineEdit(placeholderText="搜索会话")
        self.search.setObjectName("SessionSearch")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.rebuild())
        lay.addWidget(self.search)
        self.entries: dict[str, QPushButton] = {}
        for key, text in (("projects", "项目"), ("artifacts", "产物"), ("schedules", "定时任务")):
            b = QPushButton(text)
            b.setProperty("variant", "ghost")
            b.setObjectName(f"Entry_{key}")
            b.setStyleSheet("text-align: left; padding: 6px 10px;")
            b.clicked.connect(lambda _c=False, k=key: self.entryTriggered.emit(k))
            lay.addWidget(b)
            self.entries[key] = b
        self.list = QListWidget()
        self.list.setObjectName("SessionList")
        self.list.setItemDelegate(SessionDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setEditTriggers(
            QListWidget.EditTrigger.DoubleClicked | QListWidget.EditTrigger.EditKeyPressed
        )
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemChanged.connect(self._on_edited)
        self.list.itemClicked.connect(self._on_clicked)
        lay.addWidget(self.list, 1)
        self.rebuild()

    # ---- 数据操作 ----
    def session(self, sid: str) -> Session | None:
        return next((s for s in self.sessions if s.id == sid), None)

    def new_session(self) -> Session:
        s = self.backend.create_session()
        self.sessions.insert(0, s)
        if self.store is not None:
            self.store.upsert(s.id, s.title, project_id=s.project_id)
        self.search.clear()
        self.rebuild()
        self.select(s.id)
        return s

    def rename_session(self, sid: str, title: str) -> None:
        s = self.session(sid)
        if s and title.strip():
            s.title = title.strip()
            if self.store is not None:
                self.store.upsert(s.id, s.title)
        self.rebuild()

    def delete_session(self, sid: str) -> None:
        s = self.session(sid)
        if not s:
            return
        idx = self.sessions.index(s)
        self.sessions.remove(s)
        self.pinned.discard(sid)
        if self.store is not None:
            self.store.delete_session(sid)
        delete = getattr(self.backend, "delete_session", None)
        if callable(delete):
            delete(sid)
        was_current = sid == self._current
        if was_current:
            self._current = None
        self.rebuild()
        if was_current and self.sessions:
            self.select(self.sessions[min(idx, len(self.sessions) - 1)].id)

    def toggle_pin(self, sid: str) -> None:
        self.pinned.symmetric_difference_update({sid})
        if self.store is not None:
            self.store.set_pinned(sid, sid in self.pinned)
        self.rebuild()

    def select(self, sid: str) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(SID) == sid:
                self.list.setCurrentItem(it)
                return

    def groups(self) -> dict[str, list[str]]:
        """当前可见的分组 -> 会话标题（测试与调试用；折叠组为空列表）。"""
        out: dict[str, list[str]] = {}
        g = ""
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(HEADER):
                g = it.text()
                out[g] = []
            else:
                out[g].append(it.text())
        return out

    def toggle_group(self, key: str) -> None:
        self.collapsed.symmetric_difference_update({key})
        self.rebuild()

    def _grouped(self, vis: list[Session]) -> list[tuple[str, list[Session]]]:
        if self.store is not None:
            by_id = {s.id: s for s in vis}
            out: list[tuple[str, list[Session]]] = []
            for key, recs in self.store.grouped():
                items = [by_id[r.id] for r in recs if r.id in by_id]
                if items:
                    out.append((key or "", items))
            return out
        order: list[str] = []
        buckets: dict[str, list[Session]] = {}
        for s in vis:
            key = s.project_id or ""
            if key not in buckets:
                buckets[key] = []
                if key:
                    order.append(key)
            buckets[key].append(s)
        if "" in buckets:
            order.append("")
        pos = {s.id: i for i, s in enumerate(self.sessions)}

        def rank(s: Session) -> tuple[int, float, int]:
            ts: object = getattr(s, "updated_at", None)
            stamp = 0.0
            if hasattr(ts, "timestamp"):
                stamp = -float(ts.timestamp())
            elif isinstance(ts, (int, float)):
                stamp = -float(ts)
            return (0 if s.id in self.pinned else 1, stamp, pos[s.id])

        return [(k, sorted(buckets[k], key=rank)) for k in order]

    # ---- 视图 ----
    def rebuild(self) -> None:
        self._rebuilding = True
        self.list.clear()
        q = self.search.text().strip().lower()
        vis = [s for s in self.sessions if q in s.title.lower()]
        for n, (key, items) in enumerate(self._grouped(vis)):
            h = QListWidgetItem(key or UNASSIGNED)
            h.setData(HEADER, True)
            h.setData(GROUP, key)
            h.setData(FIRST, n == 0)
            folded = key in self.collapsed and not q
            h.setData(COLLAPSED, folded)
            h.setFlags(Qt.ItemFlag.ItemIsEnabled)
            top = HEADER_TOP_FIRST if n == 0 else HEADER_TOP
            h.setSizeHint(QSize(0, top + HEADER_TEXT_H + HEADER_BOTTOM))
            self.list.addItem(h)
            if folded:
                continue
            for s in items:
                it = QListWidgetItem(s.title)
                it.setData(SID, s.id)
                it.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
                it.setSizeHint(QSize(0, ROW_H + ROW_GAP))
                self.list.addItem(it)
        self._rebuilding = False
        if self._current:
            self.select(self._current)

    def _on_clicked(self, it: QListWidgetItem) -> None:
        if it.data(HEADER):
            self.toggle_group(it.data(GROUP))

    def _on_current(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if self._rebuilding or cur is None or cur.data(HEADER):
            return
        sid = cur.data(SID)
        if sid == self._current:
            return
        self._current = sid
        s = self.session(sid)
        if s:
            self.sessionSelected.emit(s)

    def _on_edited(self, it: QListWidgetItem) -> None:
        if self._rebuilding or it.data(HEADER):
            return
        s = self.session(it.data(SID))
        if s and it.text().strip() and it.text().strip() != s.title:
            self.rename_session(s.id, it.text())

    def _context_menu(self, pos: QPoint) -> None:
        it = self.list.itemAt(pos)
        if it is None or it.data(HEADER):
            return
        sid = it.data(SID)
        from braid.theme.menu import RoundedMenu

        m = RoundedMenu(self)
        m.addAction("取消置顶" if sid in self.pinned else "置顶", lambda: self.toggle_pin(sid))
        m.addAction("重命名", lambda: self.list.editItem(it))
        m.addAction("删除", lambda: self.delete_session(sid))
        m.exec(self.list.viewport().mapToGlobal(pos))
