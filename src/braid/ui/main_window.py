"""无边框主窗口：左会话栏 / 中对话区 / 右面板，三栏 QSplitter 可拖动。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtGui
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QCursor, QMouseEvent, QResizeEvent, QShowEvent
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
from braid.core import keymap
from braid.core.backend import AgentBackend, Session
from braid.core.session_store import SessionStore
from braid.core.settings import settings
from braid.ui.chat_controller import ChatController
from braid.ui.chat_view import MAX_WIDTH as CHAT_MAX_W
from braid.ui.chat_view import ChatView
from braid.ui.composer import Composer
from braid.ui.icon_button import IconButton
from braid.ui.panel import RightPanel
from braid.ui.panel.shell import MIN_WIDTH as PANEL_MIN
from braid.ui.panel.shell import PanelSplitter, splitter_min_width
from braid.ui.shortcuts import ShortcutRegistry
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


RESIZE_MARGIN = 6  # 无边框窗口四边 / 四角的拖拽调整大小命中宽度（逻辑像素）
COMPOSER_MAX_W = CHAT_MAX_W  # 输入框与消息列同宽（单一来源 chat_view.MAX_WIDTH），宽窗口下居中

_E = Qt.Edge
_CURSORS: dict[int, Qt.CursorShape] = {
    int(_E.LeftEdge.value): Qt.CursorShape.SizeHorCursor,
    int(_E.RightEdge.value): Qt.CursorShape.SizeHorCursor,
    int(_E.TopEdge.value): Qt.CursorShape.SizeVerCursor,
    int(_E.BottomEdge.value): Qt.CursorShape.SizeVerCursor,
    int(_E.TopEdge.value | _E.LeftEdge.value): Qt.CursorShape.SizeFDiagCursor,
    int(_E.BottomEdge.value | _E.RightEdge.value): Qt.CursorShape.SizeFDiagCursor,
    int(_E.TopEdge.value | _E.RightEdge.value): Qt.CursorShape.SizeBDiagCursor,
    int(_E.BottomEdge.value | _E.LeftEdge.value): Qt.CursorShape.SizeBDiagCursor,
}


def resize_edges(pos: QPointF, width: int, height: int, margin: int = RESIZE_MARGIN) -> int:
    """窗口内坐标 → 命中的边（Qt.Edge 位或的整数值）；0 表示不在边缘。"""
    x, y = pos.x(), pos.y()
    if x < 0 or y < 0 or x >= width or y >= height:
        return 0
    edges = 0
    if x < margin:
        edges |= _E.LeftEdge.value
    elif x >= width - margin:
        edges |= _E.RightEdge.value
    if y < margin:
        edges |= _E.TopEdge.value
    elif y >= height - margin:
        edges |= _E.BottomEdge.value
    return int(edges)


def resize_cursor(edges: int) -> Qt.CursorShape | None:
    return _CURSORS.get(edges)


def _as_edges(edges: int) -> Qt.Edge:
    out = Qt.Edge(0)
    for e in (_E.LeftEdge, _E.RightEdge, _E.TopEdge, _E.BottomEdge):
        if edges & e.value:
            out |= e
    return out


class EdgeResizer(QObject):
    """装在主窗口的 QWindow 上：所有鼠标事件（含子控件区域）都先经过它。
    边缘 6px 内显示调整大小光标，左键按下交给系统 startSystemResize
    （Windows / macOS / X11 / Wayland 通用）。"""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.cursor_on = False

    def _enabled(self) -> bool:
        w = self.window
        return not (w.isMaximized() or w.isFullScreen())

    def edges_at(self, pos: QPointF) -> int:
        if not self._enabled():
            return 0
        return resize_edges(pos, self.window.width(), self.window.height())

    def _set_cursor(self, shape: Qt.CursorShape | None) -> None:
        from PySide6.QtWidgets import QApplication

        if shape is not None:
            if self.cursor_on:
                QApplication.changeOverrideCursor(QCursor(shape))
            else:
                QApplication.setOverrideCursor(QCursor(shape))
                self.cursor_on = True
        elif self.cursor_on:
            QApplication.restoreOverrideCursor()
            self.cursor_on = False

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:  # noqa: N802
        t = e.type()
        if t == QEvent.Type.MouseMove and isinstance(e, QMouseEvent):
            if e.buttons() == Qt.MouseButton.NoButton:
                self._set_cursor(resize_cursor(self.edges_at(e.position())))
        elif t == QEvent.Type.MouseButtonPress and isinstance(e, QMouseEvent):
            edges = self.edges_at(e.position())
            left = e.button() == Qt.MouseButton.LeftButton
            if (
                edges
                and left
                and isinstance(obj, QtGui.QWindow)
                and obj.startSystemResize(_as_edges(edges))
            ):
                return True
        elif t == QEvent.Type.Leave:
            self._set_cursor(None)
        return False


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
        self.panel_toggle.clicked.connect(self.toggle_panel)
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
        # 宽窗口（全屏）下输入框与消息列同宽并水平居中
        composer.setMaximumWidth(COMPOSER_MAX_W)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(composer, 100)
        row.addStretch(1)
        cl.addLayout(row)

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
        backend.config_changed.connect(self._on_config_changed)
        self.shortcuts = ShortcutRegistry(self, backend, self._shortcut_handlers())
        self.shortcuts.bindingsChanged.connect(composer.set_key_bindings)
        composer.set_key_bindings(self.shortcuts.bindings)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        self._apply_composer_shadow(bool(app.property("braidDark")) if app else False)
        self.resizer = EdgeResizer(self)

        # 首个会话的渲染（Markdown 排版 + Pygments 上色，约 130ms）推到首帧之后；
        # 计时器归窗口所有，窗口先销毁则不会触发。
        QTimer.singleShot(0, self, self.open_initial_session)

    def _apply_composer_shadow(self, dark: bool) -> None:
        """亮色：0 2px 12px 10% 黑（配 QSS 的 1px border_subtle 描边）；暗色沿用 e3。"""
        from braid.theme.shadows import apply_shadow, apply_shadow_spec

        if dark:
            apply_shadow(self.composer, "e3", dark=True)
        else:
            apply_shadow_spec(self.composer, blur=12, dy=2, alpha=0.10)

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

            self.settings_page = SettingsPage(backend=self.backend)
            self._center_layout.insertWidget(
                self._center_layout.indexOf(self.chat_view), self.settings_page, 1
            )
        if self.settings_page is not None:
            self.settings_page.setVisible(on)
        if leaving and self.settings_page is not None:
            # 离开设置就销毁设置页：释放内存，之后切主题时也不用重新套用它那几百个控件的样式。
            # 下次进入重新构建（分区页按需构建，首开只建默认分区）。
            old = self.settings_page
            self.settings_page = None
            self._center_layout.removeWidget(old)
            old.deleteLater()
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

    def _on_config_changed(self, section: str) -> None:
        """“通用 → 主题”改动后切换整个应用的深浅色。"""
        if section != "general":
            return
        mode = str(self.backend.get_config("general").get("theme", "light"))
        from PySide6.QtWidgets import QApplication

        from braid.theme import apply_theme, resolve_dark

        app = QApplication.instance()
        if app is not None and bool(app.property("braidDark")) == resolve_dark(mode):
            return  # 只改了别的字段，或主题没变
        dark = apply_theme(mode)
        self.chat_view.set_dark(dark)
        self._apply_composer_shadow(dark)
        for w in self.findChildren(QWidget):
            w.update()

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
        if not attachments and self._typed_command(text):
            return
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
        elif name == "help":
            self._note(self.help_text())
        elif name == "model":
            self.model_command("")

    def _typed_command(self, text: str) -> bool:
        """整条消息是 ``/命令 [参数]`` 时按命令执行，例如 ``/model mock-fast``。"""
        if not text.startswith("/") or "\n" in text:
            return False
        name, _sp, arg = text[1:].partition(" ")
        if name not in {c.name for c in self.composer.commands}:
            return False
        if name == "model":
            self.model_command(arg.strip())
        else:
            self._command(name)
        return True

    def _note(self, text: str) -> None:
        """命令结果以本地助手消息显示，不发给后端。"""
        self.show_settings(False)
        m = self.chat_view.chat_model
        m.append("assistant", text)

    def help_text(self) -> str:
        lines = ["**可用命令**", ""]
        lines += [f"- `/{c.name}` {c.hint}" for c in self.composer.commands]
        lines += ["", "**快捷键**", ""]
        for gid, gname in keymap.GROUPS:
            items = []
            for a in keymap.ACTIONS:
                if a.group != gid:
                    continue
                key = self.shortcuts.display(a.id)
                items.append(f"- {a.name}：`{key}`" if key else f"- {a.name}：未设置")
            if items:
                lines += [f"*{gname}*", "", *items, ""]
        return "\n".join(lines).rstrip() + "\n"

    def _agent_model_note(self) -> str:
        try:
            cfg = self.backend.get_config("agents")
        except (KeyError, NotImplementedError):
            return ""
        agents = cfg.get("agents") if isinstance(cfg, dict) else None
        if not isinstance(agents, list):
            return ""
        aid = cfg.get("default_agent")
        agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == aid), None)
        if agent is None:
            return ""
        own = str(agent.get("model") or "")
        name = agent.get("name") or aid
        if not own:
            return f"当前智能体「{name}」跟随所选模型。"
        m = self.composer.models.get(own)
        return f"当前智能体「{name}」固定使用 {m.name if m else own}。"

    def model_command(self, arg: str) -> None:
        """``/model``：无参数时列出模型；带参数时按 id 或名称（不分大小写）切换。"""
        models = self.composer.models
        if arg:
            q = arg.lower()
            hit = models.get(arg) or next(
                (m for m in models.values() if q in (m.id.lower(), m.name.lower())), None
            )
            if hit is None:
                hit = next((m for m in models.values() if m.name.lower().startswith(q)), None)
            if hit is None:
                self._note(f"没有找到模型 `{arg}`。输入 `/model` 查看可用模型。")
                return
            self.composer.set_selection(hit.id, self.composer.reasoning)
            self._note(f"已切换到 **{self.composer.model_chip.text()}**。")
            return
        lines = ["**可用模型**", ""]
        for m in models.values():
            mark = "（当前）" if m.id == self.composer.model_id else ""
            lines.append(f"- {m.name} `{m.id}`{mark}")
        note = self._agent_model_note()
        key = self.shortcuts.display("input.model_menu")
        tail = "输入 `/model <id>` 切换"
        tail += f"，或按 `{key}` 打开模型菜单。" if key else "。"
        lines += ["", *([note] if note else []), tail]
        self._note("\n".join(lines) + "\n")

    def branch_current(self) -> Session | None:
        """从当前会话的最后一条消息开分支，归到同一个项目。"""
        cur = getattr(self, "_current", None)
        if cur is None:
            return None
        b = self.backend.branch_session(cur.id, len(cur.messages) - 1)
        if b.project_id is None:
            b.project_id = cur.project_id
        return self.sidebar.add_session(b)

    # ---- 快捷键 ----
    def _shortcut_handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "session.new": lambda: self._command("new"),
            "session.switch": self.switch_session,
            "session.search": self._focus_search,
            "input.command_palette": self._open_command_palette,
            "input.model_menu": self.composer.open_model_menu,
            "panel.toggle_sidebar": self.sidebar_toggle.click,
            # 与右上角收起按钮走同一个入口，进设置自动收起（#49）和按钮状态保持一致
            "panel.toggle_right": self.panel_toggle.click,
            "panel.next_tab": self._next_panel_tab,
            "app.settings": lambda: self.show_settings(not self.settings_open()),
            "app.toggle_theme": self._toggle_theme,
        }

    def switch_session(self) -> None:
        """切到下一个会话（循环）。"""
        if not self._sessions:
            return
        cur = getattr(self, "_current", None)
        ids = [s.id for s in self._sessions]
        i = ids.index(cur.id) if cur is not None and cur.id in ids else -1
        self.sidebar.select(ids[(i + 1) % len(ids)])

    def _focus_search(self) -> None:
        self.sidebar.setVisible(True)
        self.sidebar.search.setFocus()
        self.sidebar.search.selectAll()

    def _open_command_palette(self) -> None:
        if self.settings_open():
            self.show_settings(False)
        self.composer.set_text("/")

    def _next_panel_tab(self) -> None:
        if not self.panel_open():
            return
        n = self.panel_tabs.count()
        if n:
            self.panel.set_current((self.panel.current_index() + 1) % n)

    def _toggle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        dark = bool(app.property("braidDark")) if app is not None else False
        self.backend.set_config("general", {"theme": "light" if dark else "dark"})

    def toggle_panel(self) -> None:
        """右上角收起按钮与 ``panel.toggle_right`` 共用的唯一入口。"""
        self.set_panel_open(not self.panel_open())

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
        h = self.windowHandle()
        if h is not None and not getattr(self, "_resizer_installed", False):
            h.installEventFilter(self.resizer)
            self._resizer_installed = True
        self._place_controls()
