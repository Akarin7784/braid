"""“模型与服务”设置页：左侧分组列表，右侧服务商卡片。

颜色在绘制/刷新时取当前主题 token；#13 合入后改为 ``braid.theme.palette.tokens``。
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core import secrets
from braid.core.providers import Provider, ProviderStore
from braid.theme.menu import RoundedMenu, is_dark
from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import qcolor

SIDE_W, CONTENT_MAX, CONTENT_PAD = 180, 640, 32
CARD_RADIUS, CARD_PAD, CARD_GAP, FIELD_H = 12, 20, 12, 36
SAVED_TEXT = "已保存到系统钥匙串"
PAGE_TITLE = "模型与服务"
PAGE_SUBTITLE = "配置服务商的 API 端点与 Key，Key 只保存在系统钥匙串"
EMPTY_TEXT = "还没有服务商，添加一个开始使用"
ADD_CARD_H, HEADER_GAP = 64, 20
BAR_W, BAR_IDLE_MS, BAR_ALPHA = 6, 800, 0.4

CJK_FALLBACK = ("PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC")
_HEAVY_STYLES = ("semibold", "demibold", "medium", "bold")


def resolved_cjk_family(font: QFont) -> str | None:
    """字体链里第一个能显示简体中文的族（即中文字形实际落到的字体）。"""
    cjk = set(QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese))
    for fam in [*font.families(), font.family(), *CJK_FALLBACK]:
        if fam in cjk:
            return fam
    return None


def title_weight(font: QFont) -> QFont.Weight:
    """中文字体有真实的 Semibold/Medium/Bold 字面才用 600，否则 Normal，避免合成粗体。"""
    fam = resolved_cjk_family(font)
    if fam is None:
        return QFont.Weight.Normal
    styles = [s.lower().replace(" ", "") for s in QFontDatabase.styles(fam)]
    if any(h in st for st in styles for h in _HEAVY_STYLES):
        return QFont.Weight.DemiBold
    return QFont.Weight.Normal


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    return "••••" + key[-4:]


class KeyField(QWidget):
    """Key 输入框：默认显示掩码，眼睛按钮切换明文；编辑完成后写入 secrets。"""

    saved = Signal(bool)  # True=进了钥匙串

    def __init__(self, provider_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pid = provider_id
        self._revealed = False
        self.edit = QLineEdit(self)
        self.edit.setObjectName("settingsField")
        self.edit.setFixedHeight(FIELD_H)
        self.edit.setPlaceholderText("API Key")
        self.eye = QToolButton(self)
        self.eye.setObjectName("keyEye")
        self.eye.setIconSize(QSize(16, 16))
        self.eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self.eye.clicked.connect(self.toggle_reveal)
        self.hint = QLabel("", self)
        self.hint.setObjectName("keySavedHint")
        self._fx = QGraphicsOpacityEffect(self.hint)
        self.hint.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._fade = QTimer(self)
        self._fade.setSingleShot(True)
        self._fade.setInterval(1500)
        self._fade.timeout.connect(lambda: self._fx.setOpacity(0.0))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(self.eye)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(row)
        lay.addWidget(self.hint)
        self.edit.editingFinished.connect(self._commit)
        self._show_stored()

    def _update_eye(self) -> None:
        state = "open" if self._revealed else "closed"
        theme = "dark" if is_dark() else "light"
        res = files("braid.assets") / "icons" / f"eye_{state}_{theme}.png"
        self.eye.setIcon(QIcon(str(res)))
        self.eye.setProperty("eyeState", state)
        self.eye.setToolTip("隐藏 Key" if self._revealed else "显示 Key")

    def _show_stored(self) -> None:
        self._update_eye()
        key = secrets.get_key(self._pid)
        self.edit.setText(key if self._revealed else mask_key(key))

    def toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._show_stored()

    def _commit(self) -> None:
        text = self.edit.text().strip()
        if not text or text == mask_key(secrets.get_key(self._pid)):
            return
        in_keyring = secrets.set_key(self._pid, text)
        self._revealed = False
        self._show_stored()
        if in_keyring:
            self.hint.setText(SAVED_TEXT)
            self.hint.setStyleSheet(f"color: {qcolor('success', is_dark()).name()};")
            self._fx.setOpacity(1.0)
            self._fade.start()
        self.saved.emit(in_keyring)


class ProviderCard(QWidget):
    removed = Signal(str)

    def __init__(self, store: ProviderStore, provider: Provider, parent: QWidget | None = None):
        super().__init__(parent)
        self.store, self.provider = store, provider
        self.setObjectName("providerCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(CARD_PAD, CARD_PAD, CARD_PAD, CARD_PAD)
        lay.setSpacing(CARD_GAP)

        self.warning = QLabel(secrets.INSTALL_HINT, self)
        self.warning.setObjectName("keyringWarning")
        self.warning.setWordWrap(True)
        self.warning.setVisible(not secrets.keyring_available())
        lay.addWidget(self.warning)

        head = QHBoxLayout()
        self.name = QLabel(provider.name, self)
        self.name.setObjectName("providerName")
        self.enabled = QCheckBox(self)
        self.enabled.setObjectName("providerSwitch")
        self.enabled.setChecked(provider.enabled)
        self.enabled.toggled.connect(self._on_enabled)
        self.more = QToolButton(self)
        self.more.setText("⋯")
        self.more.setObjectName("providerMore")
        self.more.clicked.connect(self._open_menu)
        head.addWidget(self.name, 1)
        head.addWidget(self.enabled)
        head.addWidget(self.more)
        lay.addLayout(head)

        self.base_url = QLineEdit(provider.base_url, self)
        self.base_url.setObjectName("settingsField")
        self.base_url.setFixedHeight(FIELD_H)
        self.base_url.setPlaceholderText("API 端点")
        self.base_url.editingFinished.connect(self._on_url)
        lay.addWidget(self.base_url)
        self.key = KeyField(provider.id, self)
        lay.addWidget(self.key)

    def _on_enabled(self, on: bool) -> None:
        self.provider.enabled = on
        self.store.upsert(self.provider)

    def _on_url(self) -> None:
        url = self.base_url.text().strip()
        if url != self.provider.base_url:
            self.provider.base_url = url
            self.store.upsert(self.provider)

    def build_menu(self) -> RoundedMenu:
        menu = RoundedMenu(self)
        menu.setProperty("danger", True)  # 只有删除一项，整菜单用 danger 色
        act = menu.addAction("删除服务商")
        act.triggered.connect(self.confirm_remove)
        return menu

    def _open_menu(self) -> None:
        self.build_menu().exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def confirm_remove(self) -> None:
        ans = QMessageBox.question(
            self, "删除服务商", f"删除“{self.provider.name}”？对应的 API Key 也会一起删除。"
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.store.remove(self.provider.id)
            self.removed.emit(self.provider.id)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        NineSliceShadow.get("e1", dark).paint(p, self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("surface", dark))
        p.drawRoundedRect(self.rect(), CARD_RADIUS, CARD_RADIUS)


class AddProviderCard(QToolButton):
    """虚线占位卡。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("+ 添加服务商")
        self.setObjectName("addProviderCard")
        self.setFixedHeight(ADD_CARD_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(qcolor("text3", dark), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(QRect(self.rect()).adjusted(1, 1, -1, -1), CARD_RADIUS, CARD_RADIUS)
        p.setPen(qcolor("text2", dark))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class OverlayScrollBar(QScrollBar):
    """6px 浮层滚动条：无轨道，滑块 text3@40%，悬停或滚动时出现，空闲 800ms 后隐藏。

    浮在视口右侧之上、不占布局宽度；与滚动区自带的纵向滚动条（已设为 AlwaysOff）双向同步。
    """

    def __init__(self, area: QScrollArea) -> None:
        super().__init__(Qt.Orientation.Vertical, area)
        self.setObjectName("overlayScrollBar")
        self._area = area
        self.setFixedWidth(BAR_W)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(BAR_IDLE_MS)
        self.idle_timer.timeout.connect(self._idle)
        real = area.verticalScrollBar()
        real.rangeChanged.connect(self._sync_range)
        real.valueChanged.connect(self._on_real_value)
        self.valueChanged.connect(real.setValue)
        self._sync_range(real.minimum(), real.maximum())
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)
        self.hide()

    def _sync_range(self, lo: int, hi: int) -> None:
        real = self._area.verticalScrollBar()
        self.setRange(lo, hi)
        self.setPageStep(real.pageStep())
        self.setSingleStep(real.singleStep())
        if hi <= lo:
            self.hide()

    def _on_real_value(self, v: int) -> None:
        self.setValue(v)
        self.flash()

    def _place(self) -> None:
        vp = self._area.viewport()
        self.setGeometry(vp.x() + vp.width() - BAR_W - 2, vp.y() + 2, BAR_W, vp.height() - 4)

    def flash(self) -> None:
        """显示并重新计时。"""
        if self.maximum() <= self.minimum():
            return
        self._place()
        self.show()
        self.raise_()
        self.idle_timer.start()

    def _idle(self) -> None:
        if self.underMouse() or self.isSliderDown():
            self.idle_timer.start()
            return
        self.hide()

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:  # noqa: N802
        t = e.type()
        if t in (QEvent.Type.Enter, QEvent.Type.MouseMove, QEvent.Type.Wheel):
            self.flash()
        elif t == QEvent.Type.Resize:
            self._place()
        return False

    def handle_rect(self) -> QRectF:
        span = self.maximum() - self.minimum()
        h = self.height()
        hh = max(24.0, h * self.pageStep() / max(1, span + self.pageStep()))
        y = 0.0 if span <= 0 else (h - hh) * (self.value() - self.minimum()) / span
        return QRectF(0, y, self.width(), hh)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = qcolor("text3", is_dark())
        c.setAlphaF(c.alphaF() * BAR_ALPHA)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(self.handle_rect(), BAR_W / 2, BAR_W / 2)


class ModelsPage(QWidget):
    def __init__(self, store: ProviderStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setMaximumWidth(CONTENT_MAX + 2 * CONTENT_PAD)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(CONTENT_PAD, CONTENT_PAD, CONTENT_PAD, CONTENT_PAD)
        self._lay.setSpacing(CARD_GAP)
        self.title = QLabel(PAGE_TITLE, self)
        self.title.setObjectName("settingsTitle")
        tf = QFont(self.title.font())
        tf.setPixelSize(18)
        tf.setWeight(title_weight(tf))
        self.title.setFont(tf)
        self.subtitle = QLabel(PAGE_SUBTITLE, self)
        self.subtitle.setObjectName("settingsSubtitle")
        self.subtitle.setWordWrap(True)
        sf = QFont(self.subtitle.font())
        sf.setPixelSize(13)
        self.subtitle.setFont(sf)
        self.empty = QLabel(EMPTY_TEXT, self)
        self.empty.setObjectName("settingsEmpty")
        self.empty.setFont(sf)
        self.add_card = AddProviderCard(self)
        self.add_card.clicked.connect(self.add_provider)
        self.rebuild()

    def cards(self) -> list[ProviderCard]:
        return self.findChildren(ProviderCard)

    def rebuild(self) -> None:
        for c in self.cards():
            c.setParent(None)
            c.deleteLater()
        while self._lay.count():
            self._lay.takeAt(0)
        head = QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)
        head.addWidget(self.title)
        head.addWidget(self.subtitle)
        self._lay.addLayout(head)
        self._lay.addSpacing(HEADER_GAP - CARD_GAP)
        provs = self.store.list()
        self.empty.setHidden(bool(provs))
        if not provs:
            self._lay.addWidget(self.empty)
        for prov in provs:
            card = ProviderCard(self.store, prov, self)
            card.removed.connect(self._on_removed)
            self._lay.addWidget(card)
        self._lay.addWidget(self.add_card)
        self._lay.addStretch(1)

    def _on_removed(self, _id: str) -> None:
        QTimer.singleShot(0, self, self.rebuild)

    def add_provider(self) -> Provider:
        prov = Provider(name=f"服务商 {len(self.store.list()) + 1}")
        self.store.upsert(prov)
        self.rebuild()
        return prov


class SettingsPage(QWidget):
    GROUPS = ("模型与服务",)

    def __init__(self, store: ProviderStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.store = store or ProviderStore()
        self.nav = QListWidget(self)
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(SIDE_W)
        self.nav.setFrameShape(QListWidget.Shape.NoFrame)
        self.nav.addItems(list(self.GROUPS))
        self.nav.setMouseTracking(True)
        self.stack = QStackedWidget(self)
        self.models = ModelsPage(self.store)
        scroll = QScrollArea(self)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        # 内容宽度随视口收缩，窄窗口下不再露出横向滚动条（只保留纵向滚动）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 视口至少容得下卡片的最小宽度：分割器据此给中栏留位（窗口最小宽度随之计算），
        # 输入框只在这个下限以上伸缩，不会被压成 0 宽而裁掉眼睛按钮。
        scroll.setMinimumWidth(self.models.minimumSizeHint().width())
        # 自带纵向滚动条不占位，改由浮层滚动条显示（滚轮仍驱动自带的那根）
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area = scroll
        self.vbar = OverlayScrollBar(scroll)
        scroll.setWidget(self.models)
        self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
