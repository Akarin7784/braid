"""“模型与服务”设置页：左侧分组列表，右侧服务商卡片。

颜色在绘制/刷新时取当前主题 token；#13 合入后改为 ``braid.theme.palette.tokens``。
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core import secrets
from braid.core.providers import Provider, ProviderStore
from braid.theme.menu import RoundedMenu, is_dark
from braid.theme.nine_slice import NineSliceShadow

SIDE_W, CONTENT_MAX, CONTENT_PAD = 180, 640, 32
CARD_RADIUS, CARD_PAD, CARD_GAP, FIELD_H = 12, 20, 12, 36
SAVED_TEXT = "已保存到系统钥匙串"


@lru_cache(maxsize=2)
def _tokens(dark: bool) -> dict[str, str]:
    data = json.loads((files("braid.theme") / "tokens.json").read_text(encoding="utf-8"))
    return dict(data["dark" if dark else "light"])


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
        self.eye.setText("👁")
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

    def _show_stored(self) -> None:
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
            self.hint.setStyleSheet(f"color: {_tokens(is_dark())['success']};")
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
        p.setBrush(QColor(_tokens(dark)["surface"]))
        p.drawRoundedRect(self.rect(), CARD_RADIUS, CARD_RADIUS)


class AddProviderCard(QToolButton):
    """虚线占位卡。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("+ 添加服务商")
        self.setObjectName("addProviderCard")
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        t = _tokens(is_dark())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(t["text3"]), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(QRect(self.rect()).adjusted(1, 1, -1, -1), CARD_RADIUS, CARD_RADIUS)
        p.setPen(QColor(t["text2"]))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ModelsPage(QWidget):
    def __init__(self, store: ProviderStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setMaximumWidth(CONTENT_MAX + 2 * CONTENT_PAD)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(CONTENT_PAD, CONTENT_PAD, CONTENT_PAD, CONTENT_PAD)
        self._lay.setSpacing(CARD_GAP)
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
        for prov in self.store.list():
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
        self.stack = QStackedWidget(self)
        self.models = ModelsPage(self.store)
        scroll = QScrollArea(self)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.models)
        self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
