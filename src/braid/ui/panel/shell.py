"""右栏外框 + 标签行（panel_spec §1、§2）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from braid.core.artifacts import ArtifactSource
from braid.ui.panel.tokens import tokens

DEFAULT_WIDTH, MIN_WIDTH, MAX_WIDTH = 420, 320, 720
TAB_ROW_H, TAB_H = 52, 28
TAB_NAMES = ("浏览器", "Git", "产物")
BROWSER_TAB, GIT_TAB, ARTIFACTS_TAB = 0, 1, 2
DEFAULT_TAB = ARTIFACTS_TAB  # 默认不落在浏览器，避免冷启动加载 WebEngine


def clamp_width(w: int) -> int:
    return max(MIN_WIDTH, min(MAX_WIDTH, int(w)))


def panel_qss(mode: str = "light") -> str:
    t = tokens(mode)
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


class RightPanel(QFrame):
    """右栏：标签行 + 堆叠页面。宽度 420，可拖 320–720。"""

    currentChanged = Signal(int)
    widthChanged = Signal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        mode: str = "light",
        artifact_source: ArtifactSource | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RightPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(panel_qss(mode))
        self.setMinimumWidth(MIN_WIDTH)
        self.setMaximumWidth(MAX_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 0, 18, 18)
        root.setSpacing(12)

        row = QWidget()
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
            rl.addWidget(b)
        rl.addStretch(1)
        root.addWidget(row)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        # 浏览器页延迟创建：首次切到该标签才 import（将来 QtWebEngine 在那里导入）
        self.stack.addWidget(QWidget())
        self.browser_loaded = False
        self.stack.addWidget(placeholder_page("Git（即将推出）"))
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
        self.set_page(BROWSER_TAB, BrowserPage())

    def set_current(self, index: int) -> None:
        if index == BROWSER_TAB:
            self._ensure_browser()
        self.tabs[index].setChecked(True)
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            self.currentChanged.emit(index)

    def set_panel_width(self, w: int) -> int:
        w = clamp_width(w)
        self.setFixedWidth(w)
        self.widthChanged.emit(w)
        return w

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self.grip.setGeometry(0, 0, self.grip.width(), self.height())
        self.grip.raise_()
