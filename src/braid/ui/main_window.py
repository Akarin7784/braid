"""无边框主窗口：左会话栏 / 中对话区 / 右面板，三栏 QSplitter 可拖动。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, Qt, QVariantAnimation
from PySide6.QtGui import QMouseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpacerItem,
    QSplitter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend, Session
from braid.core.settings import settings
from braid.ui.chat_controller import ChatController
from braid.ui.chat_view import ChatView
from braid.ui.composer import Composer
from braid.ui.sidebar import Sidebar
from braid.ui.window_controls import RIGHT_MARGIN, WindowControls


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

        self.sidebar = sidebar = Sidebar(backend)
        sidebar.layout().insertWidget(0, DragArea(minimumHeight=24))  # type: ignore[union-attr]
        sidebar.sessionSelected.connect(self._open_session)
        self._sessions = sidebar.sessions

        chat = QFrame()
        chat.setObjectName("ChatArea")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(24, 12, 16, 16)
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
        self.panel_toggle = _btn("\u25e8", "ghost")
        self.panel_toggle.setObjectName("PanelToggle")
        self.panel_toggle.setFixedSize(32, 28)
        self.panel_toggle.clicked.connect(lambda: self.set_panel_open(not self.panel_open()))
        top.addWidget(self.panel_toggle)
        # 给浮层窗口控制按钮留位置（收起侧面板时按钮在这里）
        # 右栏收起时按钮浮在这里：开关距按钮 8px；右栏打开时开关贴中栏右缘 16px
        self._top_spacer = QSpacerItem(0, 0)
        top.addSpacerItem(self._top_spacer)
        self._top_bar = top
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
        composer.selectionChanged.connect(self._remember_selection)
        self.chat.editRequested.connect(composer.set_text)
        cl.addWidget(composer)

        self.panel = panel = QFrame()
        panel.setObjectName("SidePanel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        self.panel_tabs = tabs = QTabBar()
        tabs.setObjectName("PanelTabs")
        tabs.setDrawBase(False)
        for t in ("浏览器", "Git", "Diff", "终端", "任务"):
            tabs.addTab(t)
        tab_row = QHBoxLayout()
        tab_row.addWidget(tabs)
        tab_row.addWidget(DragArea(minimumHeight=24), 1)
        # 最后一个标签与按钮至少 16px；面板右内边距 12px 已计入
        tab_row.addSpacing(WindowControls.reserved_width() + 16 - 12)
        pl.addLayout(tab_row)
        pl.addWidget(QLabel("面板内容（模拟）", alignment=Qt.AlignmentFlag.AlignCenter), 1)

        split = QSplitter(Qt.Orientation.Horizontal, handleWidth=4, childrenCollapsible=False)
        for w in (sidebar, chat, panel):
            split.addWidget(w)
        split.setSizes([240, 620, 420])
        split.setStretchFactor(1, 1)
        self.splitter = split
        self.setCentralWidget(split)
        self._panel_width = 420

        # 唯一一份窗口控制按钮：主窗口的浮层子控件
        self.controls = WindowControls(self)
        self.controls.minimizeRequested.connect(self.showMinimized)
        self.controls.maximizeRequested.connect(self._toggle_max)
        self.controls.closeRequested.connect(self.close)
        for w in (panel, chat, split):
            w.installEventFilter(self)
        split.splitterMoved.connect(lambda *_: self._place_controls())
        self._anim: QVariantAnimation | None = None
        self._place_controls()
        try:
            from braid.theme.shadows import apply_shadow

            apply_shadow(composer, "e3")
        except Exception:
            pass

        if self._sessions:
            sidebar.select(self._sessions[0].id)

    def _open(self, row: int) -> None:
        self.sidebar.select(self._sessions[row].id)

    def _open_session(self, s: Session) -> None:
        self.title.setText(s.title)
        self.chat.open_session(s.id)
        self._current = s
        self.composer.set_selection(
            s.model_id or settings.default_model, s.reasoning or settings.default_reasoning
        )

    def _remember_selection(self, model_id: str, reasoning: str) -> None:
        s = getattr(self, "_current", None)
        if s is not None:
            s.model_id, s.reasoning = model_id, reasoning

    def _submit(self, text: str, attachments: list[str]) -> None:
        self.chat.model_id = self.composer.model_id
        self.chat.reasoning = self.composer.reasoning
        if attachments:
            names = ", ".join(a.rsplit("/", 1)[-1] for a in attachments)
            text = f"{text}\n\n附件：{names}".strip()
        self.chat.send(text)

    def _command(self, name: str) -> None:
        if name == "clear":
            self.chat_view.chat_model.set_messages([])

    def _toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # ---- 侧面板与浮层按钮 ----
    def panel_open(self) -> bool:
        return self.panel.isVisible() and self.panel.width() > 0

    def set_panel_open(self, open_: bool, animate: bool = True) -> None:
        if self._anim:
            self._anim.stop()
            self._anim = None
        sizes = self.splitter.sizes()
        if not open_ and self.panel.isVisible() and sizes[2] > 0:
            self._panel_width = max(sizes[2], 240)
        target = self._panel_width if open_ else 0
        start = sizes[2] if self.panel.isVisible() else 0
        self.panel.setVisible(True)
        self._sync_top_spacer()

        def step(v: object) -> None:
            cur = self.splitter.sizes()
            total = sum(cur)
            w = int(v)  # type: ignore[call-overload]
            self.splitter.setSizes([cur[0], max(total - cur[0] - w, 1), w])
            self._place_controls()

        def done() -> None:
            if not open_:
                self.panel.setVisible(False)
            self._place_controls()
            self._sync_top_spacer()

        if not animate:
            step(target)
            done()
            return
        a = QVariantAnimation(self, startValue=start, endValue=target, duration=180)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(step)
        a.finished.connect(done)
        self._anim = a
        a.start()

    def _sync_top_spacer(self) -> None:
        sp = getattr(self, "_top_spacer", None)
        if sp is None:
            return
        w = 0 if self.panel.isVisible() else WindowControls.reserved_width() + 8 - 16
        sp.changeSize(w, 0)
        self._top_bar.invalidate()

    def _place_controls(self) -> None:
        self._sync_top_spacer()
        c = getattr(self, "controls", None)
        if c is None:
            return
        x = self.width() - RIGHT_MARGIN - c.width()
        if self.panel.isVisible() and self.panel.width() > c.width() + RIGHT_MARGIN:
            tb = self.panel_tabs
            cy = tb.mapTo(self, tb.rect().center()).y()
        else:
            t = self.title
            cy = t.mapTo(self, t.rect().center()).y()
        c.move(x, int(cy - c.height() / 2 + 0.5))
        c.raise_()

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Move):
            self._place_controls()
        return super().eventFilter(obj, e)

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self._place_controls()

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        self._place_controls()
