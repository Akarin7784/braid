"""无边框主窗口：左会话栏 / 中对话区 / 右面板，三栏 QSplitter 可拖动。"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QMouseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from braid.backends.mock_artifacts import MockArtifactSource
from braid.backends.mock_browser import MockBrowserController
from braid.backends.mock_git import MockGitSource
from braid.core.backend import AgentBackend, Session
from braid.core.session_store import SessionStore
from braid.core.settings import settings
from braid.ui.chat_controller import ChatController
from braid.ui.chat_view import ChatView
from braid.ui.composer import Composer
from braid.ui.icon_button import IconButton
from braid.ui.panel import RightPanel
from braid.ui.panel.shell import MIN_WIDTH as PANEL_MIN
from braid.ui.panel.shell import PanelSplitter, splitter_min_width
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


TITLE_H = 44


class MainWindow(QMainWindow):
    def __init__(self, backend: AgentBackend) -> None:
        super().__init__()
        self.backend = backend
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1280, 800)
        self.setMinimumSize(900, 560)

        self.sidebar = sidebar = Sidebar(backend, store=SessionStore())
        sidebar.layout().insertWidget(0, DragArea(minimumHeight=24))  # type: ignore[union-attr]
        sidebar.sessionSelected.connect(self._open_session)
        sidebar.settingsRequested.connect(lambda: self.show_settings(not self.settings_open()))
        self._sessions = sidebar.sessions

        chat = QFrame()
        chat.setObjectName("ChatArea")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(24, 0, 16, 16)
        # 标题行：固定 44px，所有元素以 y=22 为中心线垂直居中
        self.title_bar = bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(TITLE_H)
        top = QHBoxLayout(bar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        center = Qt.AlignmentFlag.AlignVCenter
        self.sidebar_toggle = IconButton("sidebar")
        self.sidebar_toggle.setObjectName("SidebarToggle")
        self.sidebar_toggle.clicked.connect(lambda: sidebar.setVisible(not sidebar.isVisible()))
        top.addWidget(self.sidebar_toggle, 0, center)
        self.title = QLabel("")
        self.title.setObjectName("SessionTitle")
        # 按字形框居中：标签高度=字形高度，再整体垂直居中
        self.title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title.setFixedHeight(28)
        top.addWidget(self.title, 0, center)
        top.addWidget(DragArea(minimumHeight=24), 1)
        self.panel_toggle = IconButton("panel")
        self.panel_toggle.setObjectName("PanelToggle")
        self.panel_toggle.clicked.connect(lambda: self.set_panel_open(not self.panel_open()))
        top.addWidget(self.panel_toggle, 0, center)
        # 右栏收起时窗口按钮浮在这里：开关距按钮 8px；右栏打开时开关贴中栏右缘 16px
        self._top_spacer = QSpacerItem(0, 0)
        top.addSpacerItem(self._top_spacer)
        self._top_bar = top
        cl.addWidget(bar)
        self.chat_view = ChatView()
        cl.addWidget(self.chat_view, 1)
        # 设置页与对话同处中栏：打开时隐藏消息区和输入框（首次打开时创建）
        self.settings_page: QWidget | None = None
        self._center_layout = cl
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

        self.artifact_source = MockArtifactSource()
        self.panel = panel = RightPanel(
            artifact_source=self.artifact_source,
            git_source=MockGitSource(),
            browser_controller=MockBrowserController(),
            lazy_pages=True,
        )
        self.panel_tabs = panel.tab_row
        # 最后一个标签与浮层按钮至少 16px
        panel.set_trailing_reserve(WindowControls.reserved_width() + 16)

        split = PanelSplitter(Qt.Orientation.Horizontal, handleWidth=4, childrenCollapsible=False)
        for w in (sidebar, chat, panel):
            split.addWidget(w)
        split.setSizes([240, 620, 420])
        split.setStretchFactor(1, 1)
        self.splitter = split
        self.setCentralWidget(split)
        self._update_min_width()
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
        self._panel_before_settings: bool | None = None
        self._place_controls()
        try:
            from braid.theme.shadows import apply_shadow

            apply_shadow(composer, "e3")
        except Exception:
            pass

        # 首个会话的渲染（Markdown 排版 + Pygments 上色，约 130ms）推到首帧之后；
        # 计时器归窗口所有，窗口先销毁则不会触发。
        QTimer.singleShot(0, self, self.open_initial_session)

    def open_initial_session(self) -> None:
        """选中第一个会话；用户已先打开设置页或选了别的会话则什么也不做。"""
        if not self._sessions or self.settings_open() or getattr(self, "_current", None):
            return
        self.sidebar.select(self._sessions[0].id)

    def _open(self, row: int) -> None:
        self.sidebar.select(self._sessions[row].id)

    def settings_open(self) -> bool:
        return self.settings_page is not None and not self.settings_page.isHidden()

    def show_settings(self, on: bool = True) -> None:
        entering = on and not self.settings_open()
        leaving = not on and self.settings_open()
        if entering:
            # 进设置时永远先收起右栏，内容区更宽；离开时按进设置前的状态恢复。
            # 设置页里手动打开过右栏也不记成默认。
            self._panel_before_settings = self.panel_open()
            self.set_panel_open(False, animate=False)
        if on and self.settings_page is None:
            from braid.ui.settings_page import SettingsPage

            self.settings_page = SettingsPage()
            self._center_layout.insertWidget(
                self._center_layout.indexOf(self.chat_view), self.settings_page, 1
            )
        if self.settings_page is not None:
            self.settings_page.setVisible(on)
        self.chat_view.setVisible(not on)
        self.composer.setVisible(not on)
        # 设置页的最小宽度比对话区大，切换后重算窗口下限，避免中栏被裁切
        self._update_min_width()
        if on:
            self.title.setText("设置")
        elif (cur := getattr(self, "_current", None)) is not None:
            self.title.setText(cur.title)
        if leaving:
            was = getattr(self, "_panel_before_settings", True)
            self._panel_before_settings = None
            self.set_panel_open(bool(was), animate=False)

    def _open_session(self, s: Session) -> None:
        self.show_settings(False)
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
        elif name == "new":
            self.sidebar.new_session()
        elif name == "branch":
            self.branch_current()

    def branch_current(self) -> Session | None:
        """从当前会话的最后一条消息开分支，归到同一个项目。"""
        cur = getattr(self, "_current", None)
        if cur is None:
            return None
        b = self.backend.branch_session(cur.id, len(cur.messages) - 1)
        if b.project_id is None:
            b.project_id = cur.project_id
        return self.sidebar.add_session(b)

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
        # 动画期间放开右栏下限，才能平滑缩到 0 / 从 0 展开；结束后恢复 320
        if animate:
            self.panel.setMinimumWidth(1)
        self._sync_top_spacer()

        def step(v: object) -> None:
            cur = self.splitter.sizes()
            total = sum(cur)
            w = int(v)  # type: ignore[call-overload]
            self.splitter.setSizes([cur[0], max(total - cur[0] - w, 1), w])
            self._place_controls()

        def done() -> None:
            self.panel.setMinimumWidth(PANEL_MIN)
            if not open_:
                self.panel.setVisible(False)
            self._update_min_width()
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

    def _update_min_width(self) -> None:
        """窗口最小宽度 = 各可见栏在分割器里的最小宽度 + 分割条，避免中栏被压到下限以下。"""
        sp = self.splitter
        ws = [sp.widget(i) for i in range(sp.count())]
        vis = [w for w in ws if w is not None and not w.isHidden()]
        need = sum(splitter_min_width(w) for w in vis) + sp.handleWidth() * max(len(vis) - 1, 0)
        self.setMinimumWidth(max(need, 560))

    def _controls_on_panel(self) -> bool:
        """窗口按钮是否落在右栏标签行上；否则浮在中栏标题行右端，标题行要给它让位。

        用 isHidden() 而不是 isVisible()：窗口还没 show（或截图时直接 grab）时
        isVisible() 恒为 False，会让标题行误留出按钮的位置，收起按钮被挤到中栏中间。
        """
        p = self.panel
        return not p.isHidden() and p.width() > WindowControls.total_width() + RIGHT_MARGIN

    def _sync_top_spacer(self) -> None:
        sp = getattr(self, "_top_spacer", None)
        if sp is None:
            return
        w = 0 if self._controls_on_panel() else WindowControls.reserved_width() + 8 - 16
        if sp.sizeHint().width() == w:
            return
        sp.changeSize(w, 0)
        self._top_bar.invalidate()

    def _place_controls(self) -> None:
        self._sync_top_spacer()
        c = getattr(self, "controls", None)
        if c is None:
            return
        x = self.width() - RIGHT_MARGIN - c.width()
        if self._controls_on_panel():
            tb = self.panel_tabs
            cy = tb.mapTo(self, QRectF(tb.rect()).center()).y()  # QRect.center() 偶数高度偏上 1px
        else:
            b = self.title_bar
            cy = b.mapTo(self, QPoint(0, 0)).y() + TITLE_H // 2
        c.move(x, round(cy - c.height() / 2))
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
