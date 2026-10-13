"""左侧会话栏：新建、搜索、重命名、删除、置顶；分组"置顶/最近"；项目/产物/定时任务入口。"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
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

SID = Qt.ItemDataRole.UserRole
HEADER = Qt.ItemDataRole.UserRole + 1
SELECTED_BG = {False: "#E4E4E2", True: "#3A3A38"}
HOVER_BG = {False: "#ECECEB", True: "#2E2E2C"}
HEADER_FG = {False: "#8A8A87", True: "#8A8A87"}


def _dark() -> bool:
    app = QApplication.instance()
    return bool(app.property("braidDark")) if app else False


class SessionDelegate(QStyledItemDelegate):
    """选中项画明显的浅色圆角底（深浅主题都有），分组标题画小号灰字。"""

    def paint(
        self, p: QPainter, opt: QStyleOptionViewItem, idx: QModelIndex | QPersistentModelIndex
    ) -> None:
        dark = _dark()
        r = QRectF(opt.rect).adjusted(2, 1, -2, -1)
        if idx.data(HEADER):
            p.save()
            f = opt.font
            f.setPointSizeF(max(f.pointSizeF() - 1.5, 7))
            p.setFont(f)
            p.setPen(QColor(HEADER_FG[dark]))
            p.drawText(
                r.adjusted(8, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                idx.data(),
            )
            p.restore()
            return
        state = opt.state
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = None
        if state & QStyle.StateFlag.State_Selected:
            bg = SELECTED_BG[dark]
        elif state & QStyle.StateFlag.State_MouseOver:
            bg = HOVER_BG[dark]
        if bg:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(r, 8, 8)
        p.restore()
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        o.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        o.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)
        o.rect = opt.rect.adjusted(10, 0, -6, 0)
        w = o.widget
        style = w.style() if w else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, o, p, w)


class Sidebar(QFrame):
    sessionSelected = Signal(object)  # Session
    entryTriggered = Signal(str)  # projects / artifacts / schedules

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.backend = backend
        self.sessions: list[Session] = list(backend.list_sessions())
        self.pinned: set[str] = set()
        self._current: str | None = None
        self._rebuilding = False

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
        lay.addWidget(self.list, 1)
        self.rebuild()

    # ---- 数据操作 ----
    def session(self, sid: str) -> Session | None:
        return next((s for s in self.sessions if s.id == sid), None)

    def new_session(self) -> Session:
        s = self.backend.create_session()
        self.sessions.insert(0, s)
        self.search.clear()
        self.rebuild()
        self.select(s.id)
        return s

    def rename_session(self, sid: str, title: str) -> None:
        s = self.session(sid)
        if s and title.strip():
            s.title = title.strip()
        self.rebuild()

    def delete_session(self, sid: str) -> None:
        s = self.session(sid)
        if not s:
            return
        idx = self.sessions.index(s)
        self.sessions.remove(s)
        self.pinned.discard(sid)
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
        self.rebuild()

    def select(self, sid: str) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(SID) == sid:
                self.list.setCurrentItem(it)
                return

    def groups(self) -> dict[str, list[str]]:
        """当前可见的分组 -> 会话标题（测试与调试用）。"""
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

    # ---- 视图 ----
    def rebuild(self) -> None:
        self._rebuilding = True
        self.list.clear()
        q = self.search.text().strip().lower()
        vis = [s for s in self.sessions if q in s.title.lower()]
        for name, items in (
            ("置顶", [s for s in vis if s.id in self.pinned]),
            ("最近", [s for s in vis if s.id not in self.pinned]),
        ):
            if not items:
                continue
            h = QListWidgetItem(name)
            h.setData(HEADER, True)
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            h.setSizeHint(QSize(0, 28))
            self.list.addItem(h)
            for s in items:
                it = QListWidgetItem(s.title)
                it.setData(SID, s.id)
                it.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
                it.setSizeHint(QSize(0, 32))
                self.list.addItem(it)
        self._rebuilding = False
        if self._current:
            self.select(self._current)

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
