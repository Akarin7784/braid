"""设置分区“快捷键”：搜索框 + 按 ``keymap.GROUPS`` 分组的卡片，每行一个动作。

数据只来自 ``braid.core.keymap``；配置分区 ``keybinds`` 只存用户改过的项
（id → ``QKeySequence.PortableText``，``""`` 表示清空）。显示时在 UI 层把
PortableText 转成平台写法：macOS 用 ⌘⌥⇧⌃ 符号，Windows / Linux 用 Ctrl / Alt / Shift。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QKeyCombination, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QFocusEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from braid.core import keymap
from braid.core.backend import AgentBackend
from braid.theme.menu import is_dark
from braid.theme.palette import qcolor
from braid.ui.settings.pages import SectionPage, register_page
from braid.ui.settings.widgets import ROW_H, SettingCard, make_scroll, mono_font

SECTION = "keybinds"
SEARCH_H = 36
CHIP_H = 22
CHIP_GAP = 4
NOTE_MS = 1500
RECORD_TEXT = "按下新的快捷键…"
UNCLEARABLE_TEXT = "此快捷键不可清空"
CLEARED_TEXT = "未设置"

MAC_MODS = {"Meta": "⌃", "Alt": "⌥", "Shift": "⇧", "Ctrl": "⌘"}
MAC_ORDER = ("Meta", "Alt", "Shift", "Ctrl")  # ⌃⌥⇧⌘，macOS 习惯顺序
PC_MODS = {"Ctrl": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Meta": "Win"}  # Windows
LINUX_MODS = {**PC_MODS, "Meta": "Super"}
PC_ORDER = ("Ctrl", "Alt", "Shift", "Meta")
MAC_KEYS = {
    "Return": "↩",
    "Enter": "↩",
    "Backspace": "⌫",
    "Del": "⌦",
    "Esc": "⎋",
    "Tab": "⇥",
    "Left": "←",
    "Right": "→",
    "Up": "↑",
    "Down": "↓",
    "Space": "Space",
}
PC_KEYS = {"Return": "Enter", "Del": "Delete", "Esc": "Esc"}
MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_unknown,
}


def is_mac() -> bool:
    return sys.platform == "darwin"


def split_portable(seq: str) -> tuple[list[str], str]:
    """'Ctrl+Shift+]' → (['Ctrl', 'Shift'], ']')；按键本身是 '+' 时（'Ctrl++'）也正确。"""
    if not seq:
        return [], ""
    first = seq.split(", ")[0]  # 只显示多段序列的第一段
    if first.endswith("++"):
        mods, key = first[:-2], "+"
    elif first == "+":
        mods, key = "", "+"
    else:
        mods, _, key = first.rpartition("+")
    return [m for m in mods.split("+") if m], key


def display_parts(seq: str, mac: bool | None = None, win: bool | None = None) -> list[str]:
    """PortableText → 每个键帽上的文字（不含 '+'）。

    Meta 键：macOS ⌃、Windows “Win”、Linux “Super”。``mac`` / ``win`` 为 None 时按当前平台。
    """
    mac = is_mac() if mac is None else mac
    win = sys.platform == "win32" if win is None else win
    mods, key = split_portable(seq)
    if not key:
        return []
    if mac:
        names, order, keys = MAC_MODS, MAC_ORDER, MAC_KEYS
    else:
        names, order, keys = (PC_MODS if win else LINUX_MODS), PC_ORDER, PC_KEYS
    parts = [names[m] for m in order if m in mods]
    return [*parts, keys.get(key, key)]


def event_portable(e: QKeyEvent) -> str:
    """按键事件 → PortableText；只按了修饰键时返回 ''。"""
    key = Qt.Key(e.key())
    if key in MODIFIER_KEYS:
        return ""
    mods = e.modifiers() & (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.MetaModifier
    )
    if key == Qt.Key.Key_Backtab:
        key = Qt.Key.Key_Tab
    return QKeySequence(QKeyCombination(mods, key)).toString(
        QKeySequence.SequenceFormat.PortableText
    )


class KeyChips(QWidget):
    """一组键帽：control 底、圆角 6、22px 高、12px 等宽、间距 4，不画 '+'。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(CHIP_GAP)
        self.chips: list[QLabel] = []

    def set_sequence(self, seq: str, mac: bool | None = None) -> None:
        for c in self.chips:
            self.lay.removeWidget(c)
            c.deleteLater()
        self.chips = []
        parts = display_parts(seq, mac)
        if not parts:
            lab = QLabel(CLEARED_TEXT, self)
            lab.setObjectName("keyCleared")
            self.chips.append(lab)
            self.lay.addWidget(lab)
            return
        for p in parts:
            lab = QLabel(p, self)
            lab.setObjectName("keyChip")
            lab.setFont(mono_font(px=12))
            lab.setFixedHeight(CHIP_H)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setMinimumWidth(CHIP_H)
            self.chips.append(lab)
            self.lay.addWidget(lab)

    def texts(self) -> list[str]:
        return [c.text() for c in self.chips if c.objectName() == "keyChip"]


class RecordBox(QLabel):
    """录制态：虚线框 + text3 “按下新的快捷键…”。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(RECORD_TEXT, parent)
        self.setObjectName("keyRecord")
        self.setFixedHeight(CHIP_H + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(10, 0, 10, 0)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(qcolor("text3", is_dark()), 1, Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.end()
        super().paintEvent(e)


class KeyRow(QWidget):
    """一行：名称 | ↺（改过才显示） 键帽 / 录制框；下方可出现提示或冲突行。"""

    clicked = Signal(object)  # self
    recorded = Signal(str, str)  # id, PortableText
    cleared = Signal(str)
    reset_requested = Signal(str)
    replace_requested = Signal(str, str, str)  # id, seq, other id

    def __init__(self, action: keymap.Action, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action = action
        self.seq = action.default
        self.recording = False
        self.pending: tuple[str, str] | None = None  # (seq, 冲突的 id)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.main = QWidget(self)
        self.main.setFixedHeight(ROW_H)
        h = QHBoxLayout(self.main)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.name = QLabel(action.name, self.main)
        self.name.setObjectName("settingLabel")
        h.addWidget(self.name, 1)
        self.reset = QToolButton(self.main)
        self.reset.setObjectName("keyReset")
        self.reset.setText("↺")
        self.reset.setToolTip("恢复默认")
        self.reset.setFixedSize(16, 16)
        self.reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset.clicked.connect(lambda: self.reset_requested.emit(self.action.id))
        self.reset.hide()
        h.addWidget(self.reset)
        self.chips = KeyChips(self.main)
        h.addWidget(self.chips)
        self.record_box = RecordBox(self.main)
        self.record_box.hide()
        h.addWidget(self.record_box)
        outer.addWidget(self.main)
        # 不可清空提示：text3 小字，1.5 秒后消失（计时器属于本行）
        self.note = QLabel(UNCLEARABLE_TEXT, self)
        self.note.setObjectName("keyNote")
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.note.hide()
        outer.addWidget(self.note)
        self.note_timer = QTimer(self)
        self.note_timer.setSingleShot(True)
        self.note_timer.setInterval(NOTE_MS)
        self.note_timer.timeout.connect(self.note.hide)
        # 冲突行：12px 警告 + “替换”
        self.conflict = QWidget(self)
        cl = QHBoxLayout(self.conflict)
        cl.setContentsMargins(0, 0, 0, 6)
        cl.setSpacing(6)
        cl.addStretch(1)
        self.conflict_label = QLabel("", self.conflict)
        self.conflict_label.setObjectName("keyConflict")
        cl.addWidget(self.conflict_label)
        self.replace_btn = QToolButton(self.conflict)
        self.replace_btn.setObjectName("textButton")
        self.replace_btn.setText("替换")
        self.replace_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_btn.clicked.connect(self._replace)
        cl.addWidget(self.replace_btn)
        self.conflict.hide()
        outer.addWidget(self.conflict)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_state(self, seq: str, modified: bool, mac: bool | None = None) -> None:
        self.seq = seq
        self.chips.set_sequence(seq, mac)
        self.reset.setVisible(modified)

    def matches(self, text: str, mac: bool | None = None) -> bool:
        """搜索：名称包含整段文字，或每个词都是某个键帽 / PortableText 键名的前缀。"""
        t = text.strip().lower()
        if not t:
            return True
        if t in self.action.name.lower():
            return True
        mods, key = split_portable(self.seq)
        parts = {p.lower() for p in [*mods, key, *display_parts(self.seq, mac)] if p}
        tokens = [x for x in t.replace("+", " ").split() if x]
        return bool(tokens) and all(any(p.startswith(x) for p in parts) for x in tokens)

    # ---- 录制 ----
    def start_recording(self) -> None:
        self.clear_conflict()
        self.recording = True
        self.chips.hide()
        self.reset.hide()
        self.record_box.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def stop_recording(self) -> None:
        if not self.recording:
            return
        self.recording = False
        self.record_box.hide()
        self.chips.show()

    def show_unclearable(self) -> None:
        self.note.show()
        self.note_timer.start()

    def show_conflict(self, seq: str, other: keymap.Action) -> None:
        self.pending = (seq, other.id)
        self.conflict_label.setText(f"与「{other.name}」冲突")
        self.replace_btn.setVisible(other.clearable)
        self.conflict.show()

    def clear_conflict(self) -> None:
        self.pending = None
        self.conflict.hide()

    def _replace(self) -> None:
        if self.pending is not None:
            seq, other = self.pending
            self.clear_conflict()
            self.replace_requested.emit(self.action.id, seq, other)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.main.geometry().contains(e.position().toPoint()):
            self.clicked.emit(self)
        super().mousePressEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if not self.recording:
            super().keyPressEvent(e)
            return
        plain = not (e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
        if e.key() == Qt.Key.Key_Escape and plain:
            self.stop_recording()
            self.reset.setVisible(self.property("modified") is True)
            return
        if e.key() == Qt.Key.Key_Backspace and plain:
            self.stop_recording()
            if self.action.clearable:
                self.cleared.emit(self.action.id)
            else:
                self.reset.setVisible(self.property("modified") is True)
                self.show_unclearable()
            return
        seq = event_portable(e)
        if not seq:
            return  # 只按了修饰键，继续等
        self.stop_recording()
        self.recorded.emit(self.action.id, seq)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002, N802
        # 录制时 Tab / Shift+Tab 也要能录进去，不让焦点链吃掉
        return False if self.recording else super().focusNextPrevChild(next)

    def focusOutEvent(self, e: QFocusEvent) -> None:  # noqa: N802
        if self.recording and e.reason() != Qt.FocusReason.PopupFocusReason:
            self.stop_recording()
            self.reset.setVisible(self.property("modified") is True)
        super().focusOutEvent(e)


class KeybindsPage(SectionPage):
    SECTION = SECTION

    def __init__(
        self, backend: AgentBackend, parent: QWidget | None = None, mac: bool | None = None
    ) -> None:
        super().__init__("快捷键", "点击一行录制新的快捷键：Esc 取消，Backspace 清空", parent)
        self.backend = backend
        self.mac = is_mac() if mac is None else mac
        # 标题行右侧“全部恢复默认”
        self.lay.removeWidget(self.header)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.header, 1)
        self.reset_all_btn = QToolButton(self)
        self.reset_all_btn.setObjectName("textButton")
        self.reset_all_btn.setText("全部恢复默认")
        self.reset_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_all_btn.clicked.connect(self.reset_all)
        top.addWidget(self.reset_all_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.lay.insertLayout(0, top)
        self.search = QLineEdit(self)
        self.search.setObjectName("settingsField")
        self.search.setFixedHeight(SEARCH_H)
        self.search.setPlaceholderText("搜索动作或按键")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.lay.addWidget(self.search)
        # 只有卡片列表区滚动
        self.list_body = QWidget()
        self.list_lay = QVBoxLayout(self.list_body)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(12)
        self.cards: dict[str, SettingCard] = {}
        self.rows: dict[str, KeyRow] = {}
        for gid, gname in keymap.GROUPS:
            card = SettingCard(gname, self.list_body)
            assert card.title is not None
            card.title.setObjectName("keyGroupTitle")
            self.cards[gid] = card
            for a in keymap.ACTIONS:
                if a.group != gid:
                    continue
                row = KeyRow(a, card)
                row.clicked.connect(self.toggle_record)
                row.recorded.connect(self.on_recorded)
                row.cleared.connect(lambda aid: self._set(aid, ""))
                row.reset_requested.connect(self.reset_one)
                row.replace_requested.connect(self.replace)
                card.add_widget(row)
                self.rows[a.id] = row
            self.list_lay.addWidget(card)
        self.empty = QLabel("没有匹配的快捷键", self.list_body)
        self.empty.setObjectName("settingsEmpty")
        self.empty.hide()
        self.list_lay.addWidget(self.empty)
        self.list_lay.addStretch(1)
        self.list_scroll = make_scroll(self.list_body, self)
        self.list_scroll.setMinimumHeight(ROW_H * 2)
        self.list_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.lay.addWidget(self.list_scroll, 1)
        backend.config_changed.connect(self._on_config_changed)
        self.refresh()

    # ---- 数据 ----
    def overrides(self) -> dict[str, str]:
        raw = self.backend.get_config(SECTION)
        return {k: v for k, v in raw.items() if k in keymap.BY_ID and isinstance(v, str)}

    def effective(self) -> dict[str, str]:
        return keymap.effective(self.overrides())

    def _save(self, ov: dict[str, str]) -> None:
        clean = {k: v for k, v in ov.items() if v != keymap.BY_ID[k].default}
        self.backend.replace_config(SECTION, clean)

    def _set(self, aid: str, seq: str) -> None:
        ov = self.overrides()
        ov[aid] = seq
        self._save(ov)

    def _on_config_changed(self, section: str) -> None:
        if section == SECTION:
            self.refresh()

    def refresh(self) -> None:
        eff, ov = self.effective(), self.overrides()
        for aid, row in self.rows.items():
            modified = aid in ov and ov[aid] != keymap.BY_ID[aid].default
            row.setProperty("modified", modified)
            if not row.recording:
                row.set_state(eff[aid], modified, self.mac)
        self.reset_all_btn.setEnabled(bool(ov))
        self.apply_filter(self.search.text())

    def apply_filter(self, text: str) -> None:
        any_vis = False
        for gid, card in self.cards.items():
            vis = False
            for a in keymap.ACTIONS:
                if a.group == gid:
                    ok = self.rows[a.id].matches(text, self.mac)
                    self.rows[a.id].setVisible(ok)
                    vis = vis or ok
            card.setVisible(vis)
            any_vis = any_vis or vis
        self.empty.setVisible(not any_vis)

    # ---- 交互 ----
    def recording_row(self) -> KeyRow | None:
        return next((r for r in self.rows.values() if r.recording), None)

    def toggle_record(self, row: KeyRow) -> None:
        cur = self.recording_row()
        if cur is not None:
            cur.stop_recording()
            cur.reset.setVisible(cur.property("modified") is True)
            if cur is row:
                return
        for r in self.rows.values():
            if r is not row:
                r.clear_conflict()
        row.start_recording()

    def conflict_of(self, aid: str, seq: str) -> keymap.Action | None:
        if not seq:
            return None
        target = QKeySequence.fromString(seq, QKeySequence.SequenceFormat.PortableText)
        for oid, oseq in self.effective().items():
            if oid == aid or not oseq:
                continue
            other = QKeySequence.fromString(oseq, QKeySequence.SequenceFormat.PortableText)
            if other.matches(target) == QKeySequence.SequenceMatch.ExactMatch:
                return keymap.BY_ID[oid]
        return None

    def on_recorded(self, aid: str, seq: str) -> None:
        row = self.rows[aid]
        other = self.conflict_of(aid, seq)
        if other is not None:
            row.reset.setVisible(row.property("modified") is True)
            row.show_conflict(seq, other)
            return
        row.clear_conflict()
        self._set(aid, seq)

    def replace(self, aid: str, seq: str, other_id: str) -> None:
        if not keymap.BY_ID[other_id].clearable:
            return  # 不可清空的动作不能被替换
        ov = self.overrides()
        ov[aid] = seq
        ov[other_id] = ""
        self._save(ov)

    def reset_one(self, aid: str) -> None:
        ov = self.overrides()
        ov.pop(aid, None)
        self._save(ov)

    def reset_all(self) -> None:
        for r in self.rows.values():
            r.clear_conflict()
        self._save({})


register_page("keybinds", KeybindsPage)
