"""无边框主窗口：左会话栏 / 中对话区 / 右面板，三栏 QSplitter 可拖动。"""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend


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

        chat = QFrame()
        chat.setObjectName("ChatArea")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(24, 12, 24, 16)
        top = QHBoxLayout()
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
        self.messages = QLabel("选择左侧会话开始", alignment=Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.messages, 1)
        composer = QFrame()
        composer.setObjectName("Composer")
        col = QVBoxLayout(composer)
        self.input = QTextEdit(placeholderText="输入消息，/ 唤起命令…")
        self.input.setFixedHeight(72)
        self.input.setObjectName("ComposerInput")
        col.addWidget(self.input)
        bar = QHBoxLayout()
        bar.addWidget(_btn("📎", "ghost"))
        self.model_box = QComboBox()
        self.model_box.addItems([m.name for m in backend.list_models()])
        bar.addWidget(self.model_box)
        bar.addStretch(1)
        self.send_btn = _btn("\u2191", "primary")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setFixedSize(34, 34)
        self.send_btn.setToolTip("发送")
        bar.addWidget(self.send_btn)
        col.addLayout(bar)
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
        split.setSizes([240, 760, 280])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        try:
            from braid.theme.shadows import apply_shadow

            apply_shadow(composer, "e2")
        except Exception:
            pass

    def _toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()
