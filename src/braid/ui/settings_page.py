"""设置页：左栏 8 个分区导航，右侧分区页面；本模块实现“模型与服务”。

其它分区页在 ``braid.ui.settings.pages``，通用控件在 ``braid.ui.settings.widgets``。
页面只经 ``AgentBackend.get_config / set_config`` 读写配置；服务商列表与 Key 仍走
ProviderStore / secrets（原有持久化）。
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from PySide6.QtCore import (
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core import secrets
from braid.core.backend import AgentBackend
from braid.core.providers import Provider, ProviderStore
from braid.theme.menu import RoundedMenu, is_dark
from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import qcolor
from braid.ui.settings.pages import NAV, PAGE_FACTORIES, PlaceholderPage
from braid.ui.settings.widgets import (  # noqa: F401  旧路径兼容再导出
    BAR_W,
    NumberField,
    OverlayScrollBar,
    PageHeader,
    SettingCard,
    SettingsCombo,
    ToggleSwitch,
    make_scroll,
    number_with_unit,
    resolved_cjk_family,
    title_weight,
)

SIDE_W, CONTENT_MAX, CONTENT_PAD = 180, 640, 24
CARD_RADIUS, CARD_PAD, CARD_GAP, FIELD_H = 12, 16, 12, 32
CARD_INNER_GAP = 6
TEST_DELAY_MS = 400
SAVED_TEXT = "已保存到系统钥匙串"
PAGE_TITLE = "模型与服务"
PAGE_SUBTITLE = "配置服务商的 API 端点与 Key，Key 只保存在系统钥匙串"
EMPTY_TEXT = "还没有服务商，添加一个开始使用"
ADD_CARD_H, HEADER_GAP = 64, 20


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
        self._fade.timeout.connect(self._hide_hint)
        self.hint.hide()  # 不占高度，保存成功时才出现
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

    def _hide_hint(self) -> None:
        self._fx.setOpacity(0.0)
        self.hint.hide()

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
            self.hint.show()
            self._fx.setOpacity(1.0)
            self._fade.start()
        self.saved.emit(in_keyring)


class ProviderCard(QWidget):
    """一个服务商：名称 + 启用开关 + 更多菜单；端点、Key；超时与“测试连接”。"""

    removed = Signal(str)

    def __init__(
        self,
        store: ProviderStore,
        provider: Provider,
        parent: QWidget | None = None,
        backend: AgentBackend | None = None,
    ):
        super().__init__(parent)
        self.store, self.provider, self.backend = store, provider, backend
        self.setObjectName("providerCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(CARD_PAD, CARD_PAD - 6, CARD_PAD, CARD_PAD - 6)
        lay.setSpacing(CARD_INNER_GAP)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = QLabel(provider.name, self)
        self.name.setObjectName("providerName")
        self.enabled = ToggleSwitch(self, provider.enabled)
        self.enabled.setObjectName("providerSwitch")
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
        self.base_url.setMinimumWidth(40)
        self.base_url.setPlaceholderText("API 端点")
        self.base_url.editingFinished.connect(self._on_url)
        lay.addWidget(self.base_url)
        self.key = KeyField(provider.id, self)
        lay.addWidget(self.key)

        conf = self._conf()
        self.timeout = self._spin(conf.get("timeout", 300), 10, 3600, "总超时（秒）")
        self.chunk_timeout = self._spin(conf.get("chunk_timeout", 30), 1, 600, "流式分块超时（秒）")
        self.timeout.valueChanged.connect(lambda v: self._save_conf(timeout=v))
        self.chunk_timeout.valueChanged.connect(lambda v: self._save_conf(chunk_timeout=v))
        self.test_btn = QToolButton(self)
        self.test_btn.setObjectName("textButton")
        self.test_btn.setText("测试连接")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.clicked.connect(self.test_connection)
        self.test_result = QLabel("", self)
        self.test_result.setObjectName("testResult")
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.setInterval(TEST_DELAY_MS)
        self._test_timer.timeout.connect(self._finish_test)
        foot = QHBoxLayout()
        foot.setSpacing(6)
        for text, w in (("超时", self.timeout), ("分块", self.chunk_timeout)):
            lab = QLabel(text, self)
            lab.setObjectName("fieldLabel")
            foot.addWidget(lab)
            foot.addWidget(number_with_unit(w, "秒", self))
            foot.addSpacing(6)
        foot.addStretch(1)
        foot.addWidget(self.test_result)
        foot.addWidget(self.test_btn)
        lay.addLayout(foot)

    def _spin(self, value: int, lo: int, hi: int, tip: str) -> NumberField:
        sb = NumberField(int(value), lo, hi, parent=self)
        sb.setToolTip(tip)
        return sb

    def _conf(self) -> dict[str, Any]:
        if self.backend is None:
            return {}
        provs = self.backend.get_config("models").get("providers", {})
        return dict(provs.get(self.provider.id, {}))

    def _save_conf(self, **kw: Any) -> None:
        if self.backend is None:
            return
        provs = self.backend.get_config("models").get("providers", {})
        cur = dict(provs.get(self.provider.id, {}))
        cur.update(kw)
        provs[self.provider.id] = cur
        self.backend.set_config("models", {"providers": provs})

    def test_connection(self) -> None:
        """异步展示结果：先显示“测试中…”，由卡片自己的 QTimer 回填。"""
        self._set_result("测试中…", "text3")
        self.test_btn.setEnabled(False)
        self._test_timer.start()

    def _finish_test(self) -> None:
        self.test_btn.setEnabled(True)
        if self.backend is None:
            self._set_result("没有后端", "danger")
            return
        res = self.backend.test_connection(self.provider.id, self.base_url.text())
        self._set_result(res.message, "success" if res.ok else "danger")

    def _set_result(self, text: str, token: str) -> None:
        self.test_result.setText(text)
        self.test_result.setProperty("tone", token)
        self.test_result.setStyleSheet(f"color: {qcolor(token, is_dark()).name()};")

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


class ModelsPage(QWidget):
    """模型与服务：页头、钥匙串提示（全页一条）、默认/轻量模型、服务商卡片。"""

    def __init__(
        self,
        store: ProviderStore,
        parent: QWidget | None = None,
        backend: AgentBackend | None = None,
    ) -> None:
        super().__init__(parent)
        self.store, self.backend = store, backend
        self.setMaximumWidth(CONTENT_MAX + 2 * CONTENT_PAD)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(CONTENT_PAD, CONTENT_PAD, CONTENT_PAD, 16)
        self._lay.setSpacing(CARD_GAP)
        self.header = PageHeader(PAGE_TITLE, PAGE_SUBTITLE, self)
        self.title, self.subtitle = self.header.title, self.header.subtitle
        self.notice = QLabel(secrets.INSTALL_HINT, self)
        self.notice.setObjectName("keyringWarning")
        self.notice.setWordWrap(True)
        self.notice.setVisible(not secrets.keyring_available())
        self.model_card = SettingCard("", self)
        self.model_combo = self._combo("model")
        self.small_combo = self._combo("small_model")
        self.model_card.add_row("默认模型", self.model_combo)
        self.model_card.add_row("轻量模型", self.small_combo)
        self.empty = QLabel(EMPTY_TEXT, self)
        self.empty.setObjectName("settingsEmpty")
        self.add_card = AddProviderCard(self)
        self.add_card.clicked.connect(self.add_provider)
        self.rebuild()

    def _combo(self, field: str) -> SettingsCombo:
        cb = SettingsCombo(self)
        cb.setMinimumWidth(60)
        cb.setSizeAdjustPolicy(SettingsCombo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(8)
        if self.backend is not None:
            for m in self.backend.list_models():
                cb.addItem(m.name, m.id)
            cur = self.backend.get_config("models").get(field)
            i = cb.findData(cur)
            if i >= 0:
                cb.setCurrentIndex(i)
            cb.currentIndexChanged.connect(
                lambda _i, f=field, c=cb: self._set_model(f, c.currentData())
            )
        return cb

    def _set_model(self, field: str, model_id: str) -> None:
        if self.backend is not None:
            self.backend.set_config("models", {field: model_id})

    def cards(self) -> list[ProviderCard]:
        return self.findChildren(ProviderCard)

    def rebuild(self) -> None:
        for c in self.cards():
            c.setParent(None)
            c.deleteLater()
        while self._lay.count():
            self._lay.takeAt(0)
        self._lay.addWidget(self.header)
        self._lay.addWidget(self.notice)
        self._lay.addSpacing(HEADER_GAP - CARD_GAP)
        self._lay.addWidget(self.model_card)
        provs = self.store.list()
        self.empty.setHidden(bool(provs))
        if not provs:
            self._lay.addWidget(self.empty)
        for prov in provs:
            card = ProviderCard(self.store, prov, self, self.backend)
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
    """左栏 8 个分区 + 右侧堆叠页。分区 key 与 AgentBackend 配置分区一致。"""

    GROUPS = tuple(label for _key, label in NAV)

    def __init__(
        self,
        store: ProviderStore | None = None,
        parent: QWidget | None = None,
        backend: AgentBackend | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        if backend is None:
            from braid.backends.mock import MockBackend

            backend = MockBackend()
        self.backend = backend
        self.store = store or ProviderStore()
        self.nav = QListWidget(self)
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(SIDE_W)
        self.nav.setFrameShape(QListWidget.Shape.NoFrame)
        self.nav.addItems(list(self.GROUPS))
        self.nav.setMouseTracking(True)
        self.stack = QStackedWidget(self)
        self.models = ModelsPage(self.store, backend=self.backend)
        self.pages: dict[str, QWidget] = {}
        self.scrolls: dict[str, QScrollArea] = {}
        for key, label in NAV:
            w: QWidget
            if key == "models":
                w = self.models
            elif key in PAGE_FACTORIES:
                w = PAGE_FACTORIES[key](self.backend)
            else:
                w = PlaceholderPage(label)
            self._install(key, w)
        scroll = self.scrolls["models"]
        # 视口至少容得下卡片的最小宽度：分割器据此给中栏留位（窗口最小宽度随之计算），
        # 输入框只在这个下限以上伸缩，不会被压成 0 宽而裁掉眼睛按钮。
        scroll.setMinimumWidth(self.models.minimumSizeHint().width())
        self.scroll_area = scroll
        self.vbar: OverlayScrollBar = scroll.overlay_bar  # type: ignore[attr-defined]
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)

    def _install(self, key: str, widget: QWidget) -> None:
        scroll = make_scroll(widget, self)
        idx = [k for k, _ in NAV].index(key)
        old = self.scrolls.get(key)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        self.stack.insertWidget(idx, scroll)
        self.pages[key], self.scrolls[key] = widget, scroll

    def register_page(self, key: str, widget: QWidget) -> None:
        """把占位页换成真实页面（key 见 NAV）；也可用模块级 register_page 注册工厂。"""
        if key not in dict(NAV):
            raise KeyError(key)
        cur = self.nav.currentRow()
        self._install(key, widget)
        self.stack.setCurrentIndex(cur)

    def show_section(self, key: str) -> None:
        self.nav.setCurrentRow([k for k, _ in NAV].index(key))
