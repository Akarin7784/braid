"""右栏外框 + 标签行（panel_spec §1、§2）。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from braid.core.artifacts import ArtifactSource
from braid.core.browser import BrowserController
from braid.core.git import GitSource
from braid.theme.palette import tokens as palette

DEFAULT_WIDTH, MIN_WIDTH, MAX_WIDTH = 420, 320, 720
TAB_ROW_H, TAB_H = 44, 28
TAB_NAMES = ("浏览器", "Git", "产物")
BROWSER_TAB, GIT_TAB, ARTIFACTS_TAB = 0, 1, 2
DEFAULT_TAB = ARTIFACTS_TAB  # 默认不落在浏览器，避免冷启动加载 WebEngine


def clamp_width(w: int) -> int:
    return max(MIN_WIDTH, min(MAX_WIDTH, int(w)))


def panel_qss(mode: str = "light") -> str:
    t = palette(mode == "dark")
    return f"""
#RightPanel {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 {t["pn_a"]}, stop:1 {t["pn_b"]}); border: none; }}
#PanelTabRow {{ background: transparent; }}
QPushButton[role="panelTab"] {{ height: {TAB_H}px; min-height: {TAB_H}px; max-height: {TAB_H}px;
    padding: 0 12px; border: none; border-radius: 10px; font-size: 13px;
    color: {t["text2"]}; background: transparent; }}
QPushButton[role="panelTab"]:hover {{ background: {t["hover"]}; }}
QPushButton[role="panelTab"]:checked {{ background: {t["active"]}; color: {t["text"]};
    font-weight: 600; }}
#PanelCard {{ background: {t["surface"]}; border-radius: 14px; }}
QLabel[role="placeholder"] {{ color: {t["text3"]}; font-size: 13px; }}
QLabel[role="caption"] {{ color: {t["text3"]}; font-size: 12px; }}
"""


def card_shadow(w: QWidget) -> None:
    eff = QGraphicsDropShadowEffect(w, blurRadius=18, xOffset=0, yOffset=6)
    eff.setColor(QColor(0, 0, 0, 0x0D))
    w.setGraphicsEffect(eff)


def placeholder_page(text: str) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    card = QFrame()
    card.setObjectName("PanelCard")
    cl = QVBoxLayout(card)
    lab = QLabel(text, alignment=Qt.AlignmentFlag.AlignCenter)
    lab.setProperty("role", "placeholder")
    cl.addWidget(lab)
    card_shadow(card)
    lay.addWidget(card)
    return page


class ResizeGrip(QWidget):
    """右栏左缘的透明拖拽条（不画线），拖动改变面板宽度。"""

    def __init__(self, panel: RightPanel) -> None:
        super().__init__(panel)
        self._panel = panel
        self._start: tuple[float, int] | None = None
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._start = (e.globalPosition().x(), self._panel.width())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._start is not None:
            x0, w0 = self._start
            self._panel.set_panel_width(int(w0 - (e.globalPosition().x() - x0)))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._start = None


class PanelTabRow(QWidget):
    """标签行。提供与 QTabBar 相同的 ``count()`` / ``tabRect(i)``，供主窗口定位浮层按钮。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons: list[QPushButton] = []

    def count(self) -> int:
        return len(self.buttons)

    def tabRect(self, i: int) -> QRect:  # noqa: N802
        return self.buttons[i].geometry()


class _SeamlessHandle(QSplitterHandle):
    """零宽、禁用的分割条：不画线也不可拖（右栏宽度由 ResizeGrip 调整）。"""

    def __init__(self, o: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(o, parent)
        self.setEnabled(False)

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def paintEvent(self, e: QPaintEvent) -> None:
        pass


class PanelSplitter(QSplitter):
    """主窗口三栏分割器：``seamless_index`` 处（默认中栏|右栏之间）的分割条宽 0、不画线。"""

    def __init__(self, *args: Any, seamless_index: int = 2, **kw: Any) -> None:
        self.seamless_index = seamless_index
        super().__init__(*args, **kw)

    def createHandle(self) -> QSplitterHandle:
        # createHandle 在新控件插入前调用，此时 count() 即新控件的下标
        if self.count() == self.seamless_index:
            return _SeamlessHandle(self.orientation(), self)
        return super().createHandle()


class RightPanel(QFrame):
    """右栏：标签行 + 堆叠页面。宽度 420，可拖 320–720。"""

    currentChanged = Signal(int)
    widthChanged = Signal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        mode: str | None = None,
        artifact_source: ArtifactSource | None = None,
        git_source: GitSource | None = None,
        browser_controller: BrowserController | None = None,
    ) -> None:
        super().__init__(parent)
        if mode is None:  # 未指定时跟随应用主题（app 属性 braidDark）
            from braid.theme.menu import is_dark

            mode = "dark" if is_dark() else "light"
        self.setObjectName("RightPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(panel_qss(mode))
        # 不设最小宽度：主窗口收起/展开动画需要把宽度压到 0；拖动范围由 ResizeGrip 钳制
        self.setMaximumWidth(MAX_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 0, 18, 18)
        root.setSpacing(12)

        self.tab_row = row = PanelTabRow(self)
        row.setObjectName("PanelTabRow")
        row.setFixedHeight(TAB_ROW_H)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.tab_group = QButtonGroup(self, exclusive=True)
        self.tabs: list[QPushButton] = []
        for i, name in enumerate(TAB_NAMES):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setProperty("role", "panelTab")
            b.setFixedHeight(TAB_H)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tab_group.addButton(b, i)
            self.tabs.append(b)
            row.buttons.append(b)
            rl.addWidget(b)
        rl.addStretch(1)
        # 标签行最右侧的公开占位（窗口控制按钮）；为空时隐藏，不占宽度
        self.trailing = QWidget()
        self.trailing.setObjectName("PanelTrailing")
        tl = QHBoxLayout(self.trailing)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.trailing.hide()
        rl.addWidget(self.trailing, 0, Qt.AlignmentFlag.AlignVCenter)
        self._trailing_w: QWidget | None = None
        # 右侧留空（给主窗口的浮层窗口控制按钮）；从面板右边缘算起，已含 18px 内边距
        self._reserve = 0
        self._reserve_item = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        rl.addItem(self._reserve_item)
        root.addWidget(row)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        # 浏览器页延迟创建：首次切到该标签才 import（将来 QtWebEngine 在那里导入）
        self.stack.addWidget(QWidget())
        self.browser_loaded = False
        self.browser_controller = browser_controller
        self.theme_mode = mode
        if git_source is not None:
            from braid.ui.panel.git import GitPage

            self.git: QWidget = GitPage(git_source, theme=mode)
        else:
            self.git = placeholder_page("Git（未连接仓库）")
        self.stack.addWidget(self.git)
        from braid.ui.panel.artifacts import ArtifactsPage

        self.artifacts = ArtifactsPage(artifact_source, theme=mode)
        self.stack.addWidget(self.artifacts)
        self.tab_group.idClicked.connect(self.set_current)

        self.grip = ResizeGrip(self)
        self._apply_shadow()
        self.set_current(DEFAULT_TAB)
        self.set_panel_width(DEFAULT_WIDTH)

    def _apply_shadow(self) -> None:
        # 与中栏之间只用向左的极淡阴影（-8px 0 24px -12px #00000014），不画线
        eff = QGraphicsDropShadowEffect(self, blurRadius=24, xOffset=-8, yOffset=0)
        eff.setColor(QColor(0, 0, 0, 0x14))
        self.setGraphicsEffect(eff)

    def set_trailing_reserve(self, px: int) -> None:
        """标签行右侧为浮层按钮留出 ``px``（自面板右边缘起，含面板 18px 右内边距）。"""
        self._reserve = max(0, int(px))
        lay = self.layout()
        pad = lay.contentsMargins().right() if lay is not None else 0
        self._reserve_item.changeSize(
            max(0, self._reserve - pad), 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
        )
        if row_lay := self.tab_row.layout():
            row_lay.invalidate()

    def trailing_reserve(self) -> int:
        return self._reserve

    def trailing_widget(self) -> QWidget | None:
        return self._trailing_w

    def set_trailing_widget(self, w: QWidget | None) -> None:
        """在标签行最右侧放一个控件（如窗口控制按钮），按其 sizeHint 垂直居中；None 移除。"""
        lay = self.trailing.layout()
        assert lay is not None
        old = self._trailing_w
        if old is w:
            return
        if old is not None:
            lay.removeWidget(old)
            old.setParent(None)
        self._trailing_w = w
        if w is not None:
            lay.addWidget(w)
            lay.setAlignment(w, Qt.AlignmentFlag.AlignVCenter)
            w.show()
        self.trailing.setVisible(w is not None)

    def set_page(self, index: int, page: QWidget) -> None:
        old = self.stack.widget(index)
        self.stack.insertWidget(index, page)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        if self.current_index() >= 0:
            self.stack.setCurrentIndex(self.current_index())

    def current_index(self) -> int:
        return self.tab_group.checkedId()

    def _ensure_browser(self) -> None:
        if self.browser_loaded:
            return
        from braid.ui.panel.browser import BrowserPage  # 延迟导入

        self.browser_loaded = True
        self.browser: QWidget = BrowserPage(self.browser_controller, theme=self.theme_mode)
        self.set_page(BROWSER_TAB, self.browser)

    def set_current(self, index: int) -> None:
        if index == BROWSER_TAB:
            self._ensure_browser()
        self.tabs[index].setChecked(True)
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            self.currentChanged.emit(index)

    def set_panel_width(self, w: int) -> int:
        """设置右栏宽度（钳制到 320–720）。在 QSplitter 中时调整分割尺寸，中栏吸收差值。"""
        w = clamp_width(w)
        split = self.parentWidget()
        if isinstance(split, QSplitter) and (i := split.indexOf(self)) >= 0:
            sizes = split.sizes()
            delta = w - sizes[i]
            j = i - 1 if i > 0 else i + 1
            sizes[i] = w
            sizes[j] = max(1, sizes[j] - delta)
            split.setSizes(sizes)
        else:
            self.resize(w, self.height())
        self.widthChanged.emit(w)
        return w

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self.grip.setGeometry(0, 0, self.grip.width(), self.height())
        self.grip.raise_()
