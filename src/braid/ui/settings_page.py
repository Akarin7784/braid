"""设置页：左栏 8 个分区导航，右侧分区页面；本模块实现“模型与服务”。

其它分区页在 ``braid.ui.settings.pages``，通用控件在 ``braid.ui.settings.widgets``。
页面只经 ``AgentBackend.get_config / set_config`` 读写配置；服务商列表与 Key 仍走
ProviderStore / secrets（原有持久化）。
"""

from __future__ import annotations

import threading
from importlib.resources import files
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import (
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
from braid.core.backend import AgentBackend
from braid.core.providers import Provider, ProviderStore
from braid.theme.menu import RoundedMenu, is_dark
from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import qcolor
from braid.ui.settings import mcp as _mcp  # noqa: F401  注册“MCP 服务”页
from braid.ui.settings.pages import NAV, PAGE_FACTORIES, PlaceholderPage
from braid.ui.settings.widgets import (  # noqa: F401  旧路径兼容再导出
    BAR_W,
    AddCard,
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
    warm_mono_font,
)

SIDE_W, CONTENT_MAX, CONTENT_PAD = 180, 640, 24
CARD_RADIUS, CARD_PAD, CARD_GAP, FIELD_H = 12, 16, 12, 32
CARD_INNER_GAP = 6
WARM_DELAY_MS = 120  # 打开设置后多久预热等宽字体
TEST_DELAY_MS = 400
SAVED_TEXT = "已保存到系统钥匙串"
PAGE_TITLE = "模型与服务"
PAGE_SUBTITLE = "配置服务商的 API 端点与 Key，Key 只保存在系统钥匙串"
EMPTY_TEXT = "还没有服务商，添加一个开始使用"
ADD_CARD_H, HEADER_GAP = 64, 20
KEYRING_CHECKING = "检查中…"
KEYRING_OK = "钥匙串可用"
KEYRING_FAIL = "钥匙串不可用"


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
        self.loaded = False
        self._update_eye()
        # Key 要经钥匙串读取；由所在 ModelsPage 在首帧后统一检查完再 load()，
        # 避免建页时导入 keyring。还没检查时先禁用并留空。
        self.edit.setEnabled(False)

    def load(self) -> None:
        self.loaded = True
        self.edit.setEnabled(True)
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
        if not self.loaded:
            return
        self._revealed = not self._revealed
        self._show_stored()

    def _commit(self) -> None:
        if not self.loaded:
            return
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


class AddProviderCard(AddCard):
    """兼容旧名：等同 ``AddCard("+ 添加服务商")``。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("+ 添加服务商", parent)
        self.setObjectName("addProviderCard")


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
        self.notice.hide()  # 钥匙串检查完、确认不可用时才出现
        # 钥匙串状态：首帧后由本页的计时器检查（导入 keyring 约 150ms，不放在建页里）。
        # 检查前显示 text3“检查中…”；宽度固定为结果文字的最大宽度，行不位移。
        self.keyring_status = QLabel(KEYRING_CHECKING, self)
        self.keyring_status.setObjectName("keyringStatus")
        self.keyring_status.setProperty("state", "checking")
        self.keyring_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._fit_status_width()
        self.keyring_ok: bool | None = None
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(0)
        self._check_timer.timeout.connect(self._start_keyring_check)
        # 后台线程跑检查（导入 keyring 及其后端约 160ms），本页的定时器轮询结果
        self._check_result: list[bool] = []
        self._check_thread: threading.Thread | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(16)
        self._poll_timer.timeout.connect(self._poll_keyring_check)
        self._painted = False
        # 状态放在标题行右侧（与标题同行，不挤占副标题宽度，副标题换行不受影响）
        hl = self.header.layout()
        assert isinstance(hl, QVBoxLayout)
        hl.removeWidget(self.header.title)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)
        title_row.addWidget(self.header.title, 1)
        title_row.addWidget(self.keyring_status, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.insertLayout(0, title_row)
        self.model_card = SettingCard("", self)
        self.model_combo = self._combo("model")
        self.small_combo = self._combo("small_model")
        self.model_card.add_row("默认模型", self.model_combo)
        self.model_card.add_row("轻量模型", self.small_combo)
        self.empty = QLabel(EMPTY_TEXT, self)
        self.empty.setObjectName("settingsEmpty")
        self.add_card = AddCard("+ 添加服务商", self)
        self.add_card.clicked.connect(self.add_provider)
        self.rebuild()

    def _fit_status_width(self) -> None:
        fm = self.keyring_status.fontMetrics()
        w = max(fm.horizontalAdvance(t) for t in (KEYRING_CHECKING, KEYRING_OK, KEYRING_FAIL))
        self.keyring_status.setFixedWidth(w + 2)

    def changeEvent(self, e: QEvent) -> None:  # noqa: N802
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_status_width()
        super().changeEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(e)
        if not self._painted:
            self._painted = True
            if self.keyring_ok is None:
                self._check_timer.start()  # 首帧画完后的下一轮事件循环再检查

    def _start_keyring_check(self) -> None:
        """首帧之后：在后台线程检查钥匙串，不阻塞界面线程。"""
        if self.keyring_ok is not None or self._check_thread is not None:
            return
        out = self._check_result

        def work() -> None:
            # 任何异常（如打包漏了 keyring 后端的 ImportError / NoKeyringError）都按不可用处理，
            # 不能让异常逃出线程，否则状态位会一直停在“检查中…”
            try:
                ok = bool(secrets.keyring_available())
            except Exception:
                ok = False
            out.append(ok)

        self._check_thread = threading.Thread(
            target=work,
            name="braid-keyring-check",
            daemon=True,
        )
        self._check_thread.start()
        self._poll_timer.start()

    def _poll_keyring_check(self) -> None:
        if not self._check_result:
            return
        self._poll_timer.stop()
        if self.keyring_ok is None:
            self._apply_keyring_result(self._check_result[0])

    def run_keyring_check(self) -> bool:
        """同步检查钥匙串（会导入 keyring），更新状态、提示条，并让各 Key 输入框读取。"""
        self._check_timer.stop()
        self._poll_timer.stop()
        if self._check_result:
            ok = self._check_result[0]
        else:
            try:
                ok = bool(secrets.keyring_available())
            except Exception:
                ok = False
        self._apply_keyring_result(ok)
        return ok

    def _apply_keyring_result(self, ok: bool) -> None:
        self.keyring_ok = ok
        self.keyring_status.setText(KEYRING_OK if ok else KEYRING_FAIL)
        self.keyring_status.setProperty("state", "ok" if ok else "fail")
        st = self.keyring_status.style()
        st.unpolish(self.keyring_status)
        st.polish(self.keyring_status)
        self.notice.setVisible(not ok)
        for c in self.cards():
            c.key.load()

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
            if self.keyring_ok is not None:
                card.key.load()
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


class _LazyDict(dict[str, Any]):
    """缺 key 时调用 factory(key) 构建（factory 负责写回本 dict）。"""

    def __init__(self, factory: Any) -> None:
        super().__init__()
        self._factory = factory

    def __missing__(self, key: str) -> Any:
        return self._factory(key)


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
        # 分区页按需构建：首次显示前同步建好再切换（不闪白）。pages / scrolls 访问
        # 未建的 key 时也会当场构建，旧代码和测试照常可用；built() 只列已建的。
        self.pages: dict[str, QWidget] = _LazyDict(self._ensure)
        self.scrolls: dict[str, QScrollArea] = _LazyDict(lambda k: self._ensure_scroll(k))
        for _key, _label in NAV:
            self.stack.addWidget(QWidget(self.stack))  # 轻量占位，首次显示时替换
        self._install("models", self.models)
        scroll = self.scrolls["models"]
        # 视口至少容得下卡片的最小宽度：分割器据此给中栏留位（窗口最小宽度随之计算），
        # 输入框只在这个下限以上伸缩，不会被压成 0 宽而裁掉眼睛按钮。
        scroll.setMinimumWidth(self.models.minimumSizeHint().width())
        self.scroll_area = scroll
        self.vbar: OverlayScrollBar = scroll.overlay_bar
        self.nav.currentRowChanged.connect(self._on_row)
        self.nav.setCurrentRow(0)
        # 首次显示后稍等再预热等宽字体（智能体/规则/快捷键/MCP 首次进入不再付这笔）。
        # 不用 0ms：那样会和首帧后的钥匙串检查挤在打开设置的同一段里，打开会多卡约 50ms。
        self._warm_timer = QTimer(self)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.setInterval(WARM_DELAY_MS)
        self._warm_timer.timeout.connect(lambda: warm_mono_font(self))
        self._warmed = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)

    def showEvent(self, e: QShowEvent) -> None:  # noqa: N802
        super().showEvent(e)
        if not self._warmed:
            self._warmed = True
            self._warm_timer.start()

    def built(self) -> list[str]:
        """已经构建的分区 key（按 NAV 顺序）。"""
        return [k for k, _ in NAV if dict.__contains__(self.pages, k)]

    def ensure_page(self, key: str) -> QWidget:
        """强制构建某个分区页（测试与预热用）；已建则直接返回。"""
        return self._ensure(key)

    def _ensure(self, key: str) -> QWidget:
        if dict.__contains__(self.pages, key):
            return dict.__getitem__(self.pages, key)
        labels = dict(NAV)
        if key not in labels:
            raise KeyError(key)
        if key == "models":
            w: QWidget = self.models
        elif key in PAGE_FACTORIES:
            w = self._make_page(key)
        else:
            w = PlaceholderPage(labels[key])
        self._install(key, w)
        return w

    def _ensure_scroll(self, key: str) -> QScrollArea:
        self._ensure(key)
        return dict.__getitem__(self.scrolls, key)

    def _on_row(self, row: int) -> None:
        if row < 0:
            return
        self._ensure(NAV[row][0])  # 同步构建，切换后页头立即可见
        self.stack.setCurrentIndex(row)

    def _make_page(self, key: str) -> QWidget:
        w = PAGE_FACTORIES[key](self.backend)
        attach = getattr(w, "attach_settings", None)
        if attach is not None:
            attach(self)
        return w

    def reload_pages(self) -> None:
        """重置全部设置后重建各分区页（服务商页除外，它的数据不受重置影响）。

        推迟到下一轮事件循环：触发它的信号可能来自即将被替换的页面自身。
        """
        QTimer.singleShot(0, self, self._reload_pages_now)

    def _reload_pages_now(self) -> None:
        cur = self.nav.currentRow()
        for key in self.built():  # 没建过的分区下次显示时自然用新配置构建
            if key != "models" and key in PAGE_FACTORIES:
                self._install(key, self._make_page(key))
        self.stack.setCurrentIndex(cur)

    def _install(self, key: str, widget: QWidget) -> None:
        scroll = make_scroll(widget)  # 先在无父状态下装好，插入 stack 时只 polish 一次
        idx = [k for k, _ in NAV].index(key)
        old = self.stack.widget(idx)  # 占位或旧页
        cur = self.stack.currentIndex()
        self.stack.insertWidget(idx, scroll)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        if cur == idx:
            self.stack.setCurrentIndex(idx)
        dict.__setitem__(self.pages, key, widget)
        dict.__setitem__(self.scrolls, key, scroll)

    def register_page(self, key: str, widget: QWidget) -> None:
        """把占位页换成真实页面（key 见 NAV）；也可用模块级 register_page 注册工厂。"""
        if key not in dict(NAV):
            raise KeyError(key)
        cur = self.nav.currentRow()
        self._install(key, widget)
        self.stack.setCurrentIndex(cur)

    def show_section(self, key: str) -> None:
        self.nav.setCurrentRow([k for k, _ in NAV].index(key))
