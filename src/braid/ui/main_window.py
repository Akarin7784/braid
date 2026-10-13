"""无边框主窗口：左会话栏 / 中对话区 / 右面板，三栏 QSplitter 可拖动。"""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend
from braid.ui.chat_controller import ChatController
from braid.ui.chat_view import ChatView
from braid.ui.composer import Composer


class DragArea(QWidget):
    """顶部留白拖拽区（无标题栏），双击最大化。"""

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and (h := self.window().windowHandle()):
            h.startSystemMove()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()


def _btn(text: str, variant: str) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", variant)
    return b


class MainWindow(QMainWindow):
    def __init__(self, backend: AgentBackend) -> None:
        super().__init__()
        self.backend = backend
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1280, 800)
        self.setMinimumSize(900, 560)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.addWidget(DragArea(minimumHeight=24))
        sl.addWidget(_btn("＋ 新对话", "secondary"))
        self.session_list = QListView()
        self.session_list.setObjectName("SessionList")
        self.session_list.setModel(QStringListModel([s.title for s in backend.list_sessions()]))
        sl.addWidget(self.session_list)
        self._sessions = backend.list_sessions()
        self.session_list.clicked.connect(lambda i: self._open(i.row()))

        chat = QFrame()
        chat.setObjectName("ChatArea")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(24, 12, 24, 16)
        top = QHBoxLayout()
        self.sidebar_toggle = _btn("\u2630", "ghost")
        self.sidebar_toggle.setObjectName("SidebarToggle")
        self.sidebar_toggle.setFixedSize(32, 28)
        self.sidebar_toggle.clicked.connect(lambda: sidebar.setVisible(not sidebar.isVisible()))
        top.addWidget(self.sidebar_toggle)
        self.title = QLabel("")
        self.title.setObjectName("SessionTitle")
        top.addWidget(self.title)
        top.addWidget(DragArea(minimumHeight=24), 1)
        for t, slot in (
            ("\u2212", self.showMinimized),
            ("\u25a1", self._toggle_max),
            ("\u2715", self.close),
        ):
            b = _btn(t, "ghost")
            b.setFixedSize(32, 28)
            b.clicked.connect(slot)
            top.addWidget(b)
        cl.addLayout(top)
        self.chat_view = ChatView()
        cl.addWidget(self.chat_view, 1)
        models = backend.list_models()
        self.composer = composer = Composer(models)
        self.chat = ChatController(backend, self.chat_view, composer.model_id)
        composer.submitted.connect(self._submit)
        composer.stopRequested.connect(self.chat.stop)
        composer.commandTriggered.connect(self._command)
        self.chat.busyChanged.connect(composer.set_busy)
        self.chat.editRequested.connect(composer.set_text)
        cl.addWidget(composer)

        panel = QFrame()
        panel.setObjectName("SidePanel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        tabs = QTabBar()
        tabs.setObjectName("PanelTabs")
        for t in ("浏览器", "Git", "Diff", "终端", "任务"):
            tabs.addTab(t)
        pl.addWidget(tabs)
        pl.addWidget(QLabel("面板内容（模拟）", alignment=Qt.AlignmentFlag.AlignCenter), 1)

        split = QSplitter(Qt.Orientation.Horizontal, handleWidth=4, childrenCollapsible=False)
        for w in (sidebar, chat, panel):
            split.addWidget(w)
        split.setSizes([240, 620, 420])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        try:
            from braid.theme.shadows import apply_shadow

            apply_shadow(composer, "e3")
        except Exception:
            pass

        if self._sessions:
            self._open(0)

    def _open(self, row: int) -> None:
        s = self._sessions[row]
        self.title.setText(s.title)
        self.chat.open_session(s.id)

    def _submit(self, text: str, attachments: list[str]) -> None:
        self.chat.model_id = self.composer.model_id
        if attachments:
            names = ", ".join(a.rsplit("/", 1)[-1] for a in attachments)
            text = f"{text}\n\n附件：{names}".strip()
        self.chat.send(text)

    def _command(self, name: str) -> None:
        if name == "clear":
            self.chat_view.chat_model.set_messages([])

    def _toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()
