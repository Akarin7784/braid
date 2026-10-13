"""设置分区“高级”：上下文压缩、文件快照、文件监听忽略规则、重置全部设置。

配置分区 ``advanced``（对应 opencode 的 compaction / snapshot / watcher）::

    {"auto_compact": bool, "keep_tokens": int, "snapshot": bool,
     "watcher_ignore": list[str], ...}

重置只调用 ``AgentBackend.reset_config()``；钥匙串里的 API Key 只有勾选
“同时删除钥匙串里的 API Key”时才删（``secrets`` 模块导入时不触碰 keyring）。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QMargins, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QStyleOptionButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core.backend import AgentBackend
from braid.theme.menu import RADIUS, SHADOW_MARGIN, is_dark
from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import qcolor
from braid.ui.settings.pages import SectionPage, register_page
from braid.ui.settings.rules import InstructionRow
from braid.ui.settings.widgets import (
    ROW_H,
    NumberField,
    SettingCard,
    ToggleSwitch,
    mono_font,
    number_with_unit,
    title_font,
)

SECTION = "advanced"
DIALOG_W = 400
RESET_GAP = 32
IGNORE_HINT = "已自动忽略 node_modules、.git 等常见目录"
SNAPSHOT_NOTE = "关闭后无法撤销智能体的改动"
KEEP_MIN, KEEP_MAX = 1000, 200000


CHECK_PX = 12


class DangerCheckBox(QCheckBox):
    """勾选时在指示框里画 ~12px ✓（笔画路径，不依赖字体字形），颜色 on_danger。"""

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(e)
        if not self.isChecked():
            return
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        box = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, self)
        # 单位正方形上的 ✓：左中 → 底中偏左 → 右上；缩放到 CHECK_PX 后居中
        side = float(CHECK_PX)
        ox = box.center().x() - side / 2
        oy = box.center().y() - side / 2
        path = QPainterPath()
        path.moveTo(ox + 0.12 * side, oy + 0.50 * side)
        path.lineTo(ox + 0.40 * side, oy + 0.78 * side)
        path.lineTo(ox + 0.88 * side, oy + 0.22 * side)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(qcolor("on_danger", is_dark()))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


class ResetDialog(QDialog):
    """重置确认框：RoundedMenu 同款圆角 + e2 阴影，内容宽 400。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resetDialog")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        m = SHADOW_MARGIN
        self.setFixedWidth(DIALOG_W + 2 * m)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(m + 20, m + 20, m + 20, m + 16)
        lay.setSpacing(8)
        self.title = QLabel("重置全部设置？", self)
        self.title.setObjectName("dialogTitle")
        self.title.setFont(title_font(self.title.font(), 15))
        lay.addWidget(self.title)
        self.desc = QLabel("所有设置项恢复为默认值，服务商列表保留。", self)
        self.desc.setObjectName("dialogDesc")
        lay.addWidget(self.desc)
        lay.addSpacing(4)
        self.delete_keys = DangerCheckBox("同时删除钥匙串里的 API Key", self)
        self.delete_keys.setChecked(False)
        self.delete_keys.toggled.connect(self._sync)
        lay.addWidget(self.delete_keys)
        lay.addSpacing(8)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        self.cancel_btn = QToolButton(self)
        self.cancel_btn.setObjectName("dialogCancel")
        self.cancel_btn.setText("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.cancel_btn)
        self.ok_btn = QToolButton(self)
        self.ok_btn.setObjectName("dangerButton")
        self.ok_btn.setText("重置")
        self.ok_btn.clicked.connect(self.accept)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)
        for b in (self.cancel_btn, self.ok_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(30)

    def center_on_window(self) -> None:
        """在整个顶层窗口上水平、垂直居中（阴影外扩四边相等，对话框中心即卡片中心）。"""
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        top = parent.window()
        center = top.mapToGlobal(top.rect().center())
        self.move(center - self.rect().center())

    def showEvent(self, e: QShowEvent) -> None:  # noqa: N802
        self.center_on_window()
        super().showEvent(e)

    def _sync(self, on: bool) -> None:
        self.ok_btn.setText("重置并删除 Key" if on else "重置")

    def card_rect(self) -> QRectF:
        m = SHADOW_MARGIN
        return QRectF(self.rect().marginsRemoved(QMargins(m, m, m, m)))

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.card_rect()
        NineSliceShadow.get("e2", dark).paint(p, card.toRect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("surface", dark))
        p.drawRoundedRect(card, RADIUS, RADIUS)
        p.end()


def _default_provider_ids() -> list[str]:
    from braid.core.providers import ProviderStore

    return [p.id for p in ProviderStore().list()]


class AdvancedPage(SectionPage):
    SECTION = SECTION
    reset_done = Signal()

    def __init__(self, backend: AgentBackend, parent: QWidget | None = None) -> None:
        super().__init__("高级", "上下文、快照与文件监听；以及重置全部设置", parent)
        self.backend = backend
        self.provider_ids: Callable[[], list[str]] = _default_provider_ids
        cfg = backend.get_config(SECTION)
        # 上下文
        self.ctx_card = SettingCard("上下文", self)
        self.auto_compact = ToggleSwitch(self.ctx_card)
        self.auto_compact.setChecked(bool(cfg.get("auto_compact", True)))
        self.auto_compact.toggled.connect(self._on_auto_compact)
        self.ctx_card.add_row("自动压缩上下文", self.auto_compact)
        self.keep_tokens = NumberField(int(cfg.get("keep_tokens", 20000)), KEEP_MIN, KEEP_MAX)
        self.keep_tokens.setFixedWidth(80)
        self.keep_tokens.valueChanged.connect(
            lambda v: self.backend.set_config(SECTION, {"keep_tokens": v})
        )
        self.keep_box = number_with_unit(self.keep_tokens, "tokens")
        self.keep_row = self.ctx_card.add_row("压缩时保留的 token 数", self.keep_box)
        self.lay.addWidget(self.ctx_card)
        # 文件快照
        self.snap_card = SettingCard("文件快照", self)
        self.snapshot = ToggleSwitch(self.snap_card)
        self.snapshot.setChecked(bool(cfg.get("snapshot", True)))
        self.snapshot.toggled.connect(lambda on: self.backend.set_config(SECTION, {"snapshot": on}))
        self.snap_card.add_row("记录文件快照", self.snapshot)
        self.snap_note = QLabel(SNAPSHOT_NOTE, self.snap_card)
        self.snap_note.setObjectName("snapshotNote")
        self.snap_card.add_widget(self.snap_note)
        self.snap_card.lay.addSpacing(8)
        self.lay.addWidget(self.snap_card)
        # 文件监听
        self.watch_card = SettingCard("文件监听", self)
        self.ignore_hint = QLabel(IGNORE_HINT, self.watch_card)
        self.ignore_hint.setObjectName("settingsEmpty")
        self.ignore_hint.setFixedHeight(28)
        self.watch_card.add_widget(self.ignore_hint)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(0)
        self.watch_card.lay.addLayout(self.rows_box)
        self.add_row = QWidget(self.watch_card)
        self.add_row.setFixedHeight(ROW_H)
        ar = QHBoxLayout(self.add_row)
        ar.setContentsMargins(0, 0, 0, 0)
        self.input = QLineEdit(self.add_row)
        self.input.setObjectName("settingsField")
        self.input.setFont(mono_font(px=12))
        self.input.setFixedHeight(30)
        self.input.setPlaceholderText("忽略规则，如 dist/**，回车确认")
        self.input.returnPressed.connect(self._confirm_input)
        ar.addWidget(self.input, 1)
        self.add_row.hide()
        self.watch_card.add_widget(self.add_row)
        self.add_btn = QToolButton(self.watch_card)
        self.add_btn.setObjectName("textButton")
        self.add_btn.setText("+ 添加忽略规则")
        self.add_btn.setFixedHeight(36)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self.start_add)
        bar = QHBoxLayout()
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        self.watch_card.lay.addLayout(bar)
        self.lay.addWidget(self.watch_card)
        # 重置（与上方隔 32px）
        self.lay.addSpacing(RESET_GAP - self.lay.spacing())
        self.reset_card = SettingCard("", self)
        self.reset_btn = QToolButton(self.reset_card)
        self.reset_btn.setObjectName("dangerTextButton")
        self.reset_btn.setText("重置…")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.clicked.connect(self.open_reset_dialog)
        info = QWidget(self.reset_card)
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 10, 0, 10)
        il.setSpacing(2)
        self.reset_label = QLabel("重置全部设置", info)
        self.reset_label.setObjectName("settingLabel")
        self.reset_desc = QLabel("所有设置恢复为默认值；API Key 默认保留", info)
        self.reset_desc.setObjectName("settingDesc")
        il.addWidget(self.reset_label)
        il.addWidget(self.reset_desc)
        rl = QHBoxLayout()
        rl.addWidget(info, 1)
        rl.addWidget(self.reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.reset_card.lay.addLayout(rl)
        self.lay.addWidget(self.reset_card)
        self.finish()
        self.dialog: ResetDialog | None = None
        self._sync_keep()
        self.rebuild_ignore()

    # ---- 上下文 ----
    def _on_auto_compact(self, on: bool) -> None:
        self.backend.set_config(SECTION, {"auto_compact": on})
        self._sync_keep()

    def _sync_keep(self) -> None:
        on = self.auto_compact.isChecked()
        self.keep_row.setEnabled(on)
        self.keep_row.setProperty("dim", not on)
        for w in (self.keep_row, self.keep_row.label, self.keep_box.unit):  # type: ignore[attr-defined]
            w.style().unpolish(w)
            w.style().polish(w)

    # ---- 忽略规则 ----
    def ignores(self) -> list[str]:
        return list(self.backend.get_config(SECTION).get("watcher_ignore", []))

    def ignore_rows(self) -> list[InstructionRow]:
        return [
            w
            for i in range(self.rows_box.count())
            if (it := self.rows_box.itemAt(i)) is not None
            and isinstance(w := it.widget(), InstructionRow)
        ]

    def rebuild_ignore(self) -> None:
        for r in self.ignore_rows():
            self.rows_box.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        for pat in self.ignores():
            row = InstructionRow(pat, None, self.watch_card)
            row.removed.connect(self.remove_ignore)
            self.rows_box.addWidget(row)

    def add_ignore(self, pattern: str) -> bool:
        pattern = pattern.strip()
        cur = self.ignores()
        if not pattern or pattern in cur:
            return False
        self.backend.set_config(SECTION, {"watcher_ignore": [*cur, pattern]})
        self.rebuild_ignore()
        return True

    def remove_ignore(self, pattern: str) -> None:
        self.backend.set_config(
            SECTION, {"watcher_ignore": [p for p in self.ignores() if p != pattern]}
        )
        QTimer.singleShot(0, self, self.rebuild_ignore)  # 不在 × 自己的 clicked 里删掉它

    def start_add(self) -> None:
        self.add_row.show()
        self.input.setFocus()

    def _confirm_input(self) -> None:
        self.add_ignore(self.input.text())
        self.input.clear()
        self.add_row.hide()

    # ---- 重置 ----
    def make_reset_dialog(self) -> ResetDialog:
        self.dialog = ResetDialog(self.window())
        self.dialog.accepted.connect(self._do_reset)
        return self.dialog

    def open_reset_dialog(self) -> ResetDialog:
        dlg = self.make_reset_dialog()
        dlg.open()
        return dlg

    def _do_reset(self) -> None:
        delete = self.dialog is not None and self.dialog.delete_keys.isChecked()
        self.reset_all(delete_keys=delete)

    def reset_all(self, delete_keys: bool = False) -> None:
        self.backend.reset_config()
        if delete_keys:
            from braid.core import secrets

            for pid in self.provider_ids():
                secrets.delete_key(pid)
        self.reset_done.emit()

    def attach_settings(self, settings: QWidget) -> None:
        """SettingsPage 安装本页时调用：用它的 ProviderStore，并在重置后让它重建各页。"""
        store = getattr(settings, "store", None)
        if store is not None:
            self.provider_ids = lambda: [p.id for p in store.list()]
        reload = getattr(settings, "reload_pages", None)
        if reload is not None:
            self.reset_done.connect(reload)


register_page("advanced", AdvancedPage)
