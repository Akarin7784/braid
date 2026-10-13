"""设置页通用控件：ToggleSwitch、SegmentedControl、SettingRow、SettingCard。

颜色一律经 palette.qcolor 取 tokens，深浅色跟随 app 的 braidDark。
"""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from importlib.resources import files

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QEnterEvent,
    QFont,
    QFontDatabase,
    QIntValidator,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QTextLayout,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from braid.theme.menu import SHADOW_MARGIN, RoundedMenu, is_dark
from braid.theme.nine_slice import NineSliceShadow
from braid.theme.palette import qcolor

ROW_H = 44
CARD_RADIUS = 12
CARD_PAD_H, CARD_PAD_V = 16, 2
SWITCH_W, SWITCH_H = 32, 18
SEG_H, SEG_PAD, SEG_RADIUS = 28, 2, 8
NUMBER_W = 64
COMBO_ARROW, COMBO_ARROW_RIGHT, POPUP_RADIUS = 12, 10, 10
BAR_W, BAR_IDLE_MS, BAR_ALPHA = 6, 800, 0.4

CJK_FALLBACK = ("PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC")


def resolved_cjk_family(font: QFont) -> str | None:
    """字体链里第一个能显示简体中文的族（即中文字形实际落到的字体）。"""
    cjk = set(QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese))
    for fam in [*font.families(), font.family(), *CJK_FALLBACK]:
        if fam in cjk:
            return fam
    return None


def _style_weight(style: str) -> int | None:
    """字面样式名 → 字重；只识别标题可能用到的 Medium/SemiBold/Bold。"""
    st = style.lower().replace(" ", "").replace("-", "")
    if "semibold" in st or "demibold" in st:
        return 600
    if "medium" in st:
        return 500
    if st == "bold" or (st.endswith("bold") and not st.startswith(("extra", "ultra"))):
        return 700
    return None


_TITLE_ORDER = (600, 500, 700)
_WEIGHT_ENUM = {
    400: QFont.Weight.Normal,
    500: QFont.Weight.Medium,
    600: QFont.Weight.DemiBold,
    700: QFont.Weight.Bold,
}
TITLE_SAMPLE = "模型与服务"


def title_faces(font: QFont) -> list[tuple[str, str, int]]:
    """中文字体里可用作标题的真实字面 [(族, 实际样式名, 字重)]，按 600 > 500 > 700 排序。

    样式名取自 QFontDatabase.styles()，不写死（Inter 叫 SemiBold，PingFang 叫 Semibold）。
    """
    fam = resolved_cjk_family(font)
    if fam is None:
        return []
    found: dict[int, str] = {}
    for st in QFontDatabase.styles(fam):
        w = _style_weight(st)
        if w is not None and w not in found:
            found[w] = st
    return [(fam, found[w], w) for w in _TITLE_ORDER if w in found]


def title_weight(font: QFont) -> QFont.Weight:
    """标题计划用的字重：SemiBold(600) > Medium(500) > 仅有 Bold 时 700 > Normal(400)。

    只看字体库里存在的真实字面，禁止合成粗体；实际字体用 title_font() 构造。
    """
    faces = title_faces(font)
    return _WEIGHT_ENUM[faces[0][2]] if faces else QFont.Weight.Normal


def cjk_faces(font: QFont, text: str = TITLE_SAMPLE) -> list[tuple[str, str]]:
    """用 glyphRuns 查 text 实际落到的 [(族, 字面样式名)]。"""
    lay = QTextLayout(text, font)
    lay.beginLayout()
    lay.createLine().setLineWidth(100000)
    lay.endLayout()
    return [(r.rawFont().familyName(), r.rawFont().styleName()) for r in lay.glyphRuns()]


def _same_face(got_fam: str, got_style: str, fam: str, style: str, w: int) -> bool:
    """glyphRuns 落到的字面是否就是 (fam, style)。

    Linux fontconfig 会把非 Regular/Bold 的字面按 typographic 名报成独立族
    （如 "Noto Sans CJK SC Medium"），它与 "Noto Sans CJK SC" + Medium 是同一个真实字面。
    """
    if _style_weight(got_style) != w:
        return False
    return got_fam == fam or got_fam == f"{fam} {style}"


def _title_attempt(families: list[str], px: int, w: int, style: str) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(px)
    f.setWeight(_WEIGHT_ENUM[w])
    if style:
        f.setStyleName(style)
    return f


@functools.lru_cache(maxsize=32)
def _title_spec(
    latin: tuple[str, ...], faces: tuple[tuple[str, str, int], ...], px: int
) -> tuple[tuple[str, ...], int, str]:
    """标题字体方案 (族链, 字重, 样式名)。

    按进程缓存：glyphRuns 探测较贵，设置页每个分区标题都会调。

    每档候选依次尝试：
    1. 族链 [Inter, 中文族] 只设字重 → 再加样式名；
    2. 降级：只用中文族（拉丁字母随之用中文字体自带的拉丁字形）。
       Qt 的回落引擎沿用首选族的实际字重：随包 Inter 只有 Regular/SemiBold，
       请求 500 时 Inter 解析成 Regular，中文回落随之也是 Regular；请求 600 时
       Inter 为 SemiBold，fontconfig 给没有 SemiBold 的 Noto CJK 配到 Bold。
       所以族链永远选不上 Noto 的 Medium，只能单用中文族。
    用 glyphRuns 验证中文确实落到那个真实字面；都不行降到下一档，最后用常规字重。
    """
    for fam, style, w in faces:
        for fams in ([*latin, fam], [fam]):
            for st in ("", style):
                got = cjk_faces(_title_attempt(fams, px, w, st))
                if got and all(_same_face(gf, gs, fam, style, w) for gf, gs in got):
                    return tuple(fams), w, st
    return tuple([*latin, faces[0][0]] if faces else []), 400, ""


def title_font(base: QFont, px: int) -> QFont:
    """构造标题字体：拉丁字母走 base 的首选族（Inter），中文用 title_faces() 选中的真实字面。

    规则见 _title_spec()；族链选不上时降级为只用中文族，此时 title_degraded() 为真。
    """
    latin = tuple([f for f in base.families() if f not in CJK_FALLBACK][:1] or ["Inter"])
    fams, w, st = _title_spec(latin, tuple(title_faces(base)), px)
    f = QFont(base)
    if fams:
        f.setFamilies(list(fams))
    f.setPixelSize(px)
    f.setWeight(_WEIGHT_ENUM[w])
    if st:
        f.setStyleName(st)
    return f


def title_degraded(font: QFont) -> bool:
    """title_font() 结果是否走了降级（族链里没有拉丁族，标题拉丁字母用中文字体的字形）。"""
    fams = font.families()
    return bool(fams) and all(f in CJK_FALLBACK for f in fams)


def _over(base: QColor, top: QColor, alpha: float) -> QColor:
    """把 top 以 alpha 叠在 base 上，得到不透明色。"""
    a = top.alphaF() * alpha
    return QColor.fromRgbF(
        base.redF() * (1 - a) + top.redF() * a,
        base.greenF() * (1 - a) + top.greenF() * a,
        base.blueF() * (1 - a) + top.blueF() * a,
        base.alphaF(),
    )


class ToggleSwitch(QAbstractButton):
    """32×18 胶囊开关，单色：开为 accent，关为 control 叠 text3@30%。"""

    def __init__(self, parent: QWidget | None = None, checked: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(SWITCH_W, SWITCH_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(SWITCH_W, SWITCH_H)

    def track_color(self, dark: bool) -> QColor:
        """开：accent（浅色为深灰、深色为近白），单色不加彩；关：control 叠 text3@30% 作描边感。"""
        if self.isChecked():
            return qcolor("accent", dark)
        return _over(qcolor("control", dark), qcolor("text3", dark), 0.3)

    def knob_color(self, dark: bool) -> QColor:
        if self.isChecked():
            return qcolor("surface" if dark else "accent_text", dark)
        return qcolor("surface", dark)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        track = self.track_color(dark)
        if not self.isEnabled():
            track.setAlphaF(track.alphaF() * 0.5)
        p.setBrush(track)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.width() - d - 2 if self.isChecked() else 2.0
        p.setBrush(self.knob_color(dark))
        p.drawEllipse(QRectF(x, 2, d, d))


class SegmentedControl(QWidget):
    """分段选择：底色 control；选中块浅色 surface + e1、深色 active；文字常规字重。"""

    changed = Signal(str)

    def __init__(
        self,
        options: Sequence[tuple[str, str]],
        current: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keys = [k for k, _ in options]
        self._labels = [t for _, t in options]
        self._index = self._keys.index(current) if current in self._keys else 0
        self.setFixedHeight(SEG_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        fm = self.fontMetrics()
        self._seg_w = max(fm.horizontalAdvance(t) for t in self._labels) + 20
        self.setFixedWidth(self._seg_w * len(self._keys) + 2 * SEG_PAD)

    def keys(self) -> list[str]:
        return list(self._keys)

    def value(self) -> str:
        return self._keys[self._index]

    def set_value(self, key: str, emit: bool = False) -> None:
        i = self._keys.index(key)
        if i == self._index:
            return
        self._index = i
        self.update()
        if emit:
            self.changed.emit(key)

    @staticmethod
    def block_color(dark: bool) -> QColor:
        """选中块：浅色 surface（另加 e1 阴影），深色 active（无阴影）。"""
        return qcolor("active" if dark else "surface", dark)

    def segment_rect(self, i: int) -> QRect:
        return QRect(SEG_PAD + i * self._seg_w, SEG_PAD, self._seg_w, self.height() - 2 * SEG_PAD)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        for i in range(len(self._keys)):
            if self.segment_rect(i).contains(e.position().toPoint()):
                self.set_value(self._keys[i], emit=True)
                return

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("control", dark))
        p.drawRoundedRect(QRectF(self.rect()), SEG_RADIUS, SEG_RADIUS)
        sel = self.segment_rect(self._index)
        if not dark:
            NineSliceShadow.get("e1", dark).paint(p, sel)
        p.setBrush(self.block_color(dark))
        p.drawRoundedRect(QRectF(sel), SEG_RADIUS - SEG_PAD, SEG_RADIUS - SEG_PAD)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.Normal)  # 选中也不加粗，只换色
        p.setFont(f)
        for i, t in enumerate(self._labels):
            p.setPen(qcolor("text" if i == self._index else "text2", dark))
            p.drawText(self.segment_rect(i), Qt.AlignmentFlag.AlignCenter, t)


class SettingRow(QWidget):
    """44px 一行：左标签，右控件，无分隔线。"""

    def __init__(self, label: str, control: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.setFixedHeight(ROW_H)
        self.label = QLabel(label, self)
        self.label.setObjectName("settingLabel")
        lf = QFont(self.label.font())
        lf.setWeight(QFont.Weight.Normal)  # 行标签常规字重，只有页标题加粗
        self.label.setFont(lf)
        self.control = control
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self.label, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingCard(QWidget):
    """一组设置一张卡：surface 底 + e1 阴影，圆角 12。"""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingCard")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(CARD_PAD_H, CARD_PAD_V, CARD_PAD_H, CARD_PAD_V)
        self.lay.setSpacing(0)
        self.title: QLabel | None = None
        if title:
            self.title = QLabel(title, self)
            self.title.setObjectName("settingCardTitle")
            self.title.setFixedHeight(32)
            self.lay.addWidget(self.title)

    def add_row(self, label: str, control: QWidget) -> SettingRow:
        row = SettingRow(label, control, self)
        self.lay.addWidget(row)
        return row

    def add_widget(self, w: QWidget) -> QWidget:
        self.lay.addWidget(w)
        return w

    def rows(self) -> list[SettingRow]:
        return self.findChildren(SettingRow)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        NineSliceShadow.get("e1", dark).paint(p, self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("surface", dark))
        p.drawRoundedRect(QRectF(self.rect()), CARD_RADIUS, CARD_RADIUS)


class PageHeader(QWidget):
    """页头：18px 标题（有真实中文粗字面才 600）+ 13px text2 副标题。"""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel(title, self)
        self.title.setObjectName("settingsTitle")
        self.title.setFont(title_font(self.title.font(), 18))
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("settingsSubtitle")
        self.subtitle.setWordWrap(True)
        sf = QFont(self.subtitle.font())
        sf.setPixelSize(13)
        self.subtitle.setFont(sf)
        self.subtitle.setVisible(bool(subtitle))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)


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


def make_scroll(content: QWidget, parent: QWidget | None = None) -> QScrollArea:
    """设置页内容滚动区：无边框、横向关闭、纵向用 OverlayScrollBar（area.overlay_bar）。"""
    scroll = QScrollArea(parent)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    scroll.overlay_bar = OverlayScrollBar(scroll)  # type: ignore[attr-defined]
    return scroll


class NumberField(QLineEdit):
    """整数输入框（带范围校验），接口仿 QSpinBox：value / setValue / valueChanged。

    不用 QSpinBox：全局 QSS 下它的内嵌编辑框会被挤成 1px 宽。
    """

    valueChanged = Signal(int)  # noqa: N815

    def __init__(
        self,
        value: int,
        lo: int,
        hi: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsNumber")
        self._lo, self._hi = lo, hi
        self.setValidator(QIntValidator(lo, hi, self))
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedHeight(28)
        self.setFixedWidth(NUMBER_W)
        self._value = lo
        self.setValue(value)
        self.editingFinished.connect(self._commit)

    def minimum(self) -> int:
        return self._lo

    def maximum(self) -> int:
        return self._hi

    def value(self) -> int:
        return self._value

    def setValue(self, v: int) -> None:  # noqa: N802
        v = max(self._lo, min(self._hi, int(v)))
        changed = v != self._value
        self._value = v
        self.setText(str(v))
        if changed:
            self.valueChanged.emit(v)

    def _commit(self) -> None:
        txt = self.text().strip()
        self.setValue(int(txt) if txt.lstrip("-").isdigit() else self._value)


def number_with_unit(field: NumberField, unit: str, parent: QWidget | None = None) -> QWidget:
    """NumberField 后面跟一个 text3 单位标签（如“秒”）；标签在返回控件的 ``unit`` 属性上。"""
    box = QWidget(parent)
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    field.setParent(box)
    lab = QLabel(unit, box)
    lab.setObjectName("fieldUnit")
    lay.addWidget(field)
    lay.addWidget(lab)
    box.unit = lab  # type: ignore[attr-defined]
    return box


class SettingsCombo(QComboBox):
    """设置页下拉框：右侧自绘 12px text3 箭头；弹层用 RoundedMenu（圆角 10、e2 阴影、32px 行）。

    接口与 QComboBox 相同（addItem / currentData / currentIndexChanged …）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCombo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popup_menu: RoundedMenu | None = None

    def build_popup(self) -> RoundedMenu:
        menu = RoundedMenu(self)
        menu.radius = POPUP_RADIUS
        menu.setProperty("role", "comboPopup")
        for i in range(self.count()):
            act = QAction(self.itemText(i), menu)
            act.setCheckable(True)
            act.setChecked(i == self.currentIndex())
            act.triggered.connect(lambda _c=False, j=i: self.setCurrentIndex(j))
            menu.addAction(act)
        self.popup_menu = menu
        return menu

    def showPopup(self) -> None:  # noqa: N802
        menu = self.build_popup()
        menu.setMinimumWidth(self.width() + 2 * SHADOW_MARGIN)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        pos.setX(pos.x() - SHADOW_MARGIN)
        pos.setY(pos.y() - SHADOW_MARGIN + 4)
        menu.exec(pos)

    def hidePopup(self) -> None:  # noqa: N802
        if self.popup_menu is not None:
            self.popup_menu.close()

    def arrow_rect(self) -> QRect:
        s = COMBO_ARROW
        return QRect(self.width() - COMBO_ARROW_RIGHT - s, (self.height() - s) // 2, s, s)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(qcolor("text3", is_dark()), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = QRectF(self.arrow_rect()).center()
        pts = [QPointF(c.x() - 3.5, c.y() - 1.75), QPointF(c.x(), c.y() + 1.75)]
        p.drawPolyline([*pts, QPointF(c.x() + 3.5, c.y() - 1.75)])


class CloseIconButton(QAbstractButton):
    """16px × 图标按钮：平时 text3，悬停 danger。"""

    SIZE = 16

    def __init__(self, parent: QWidget | None = None, tip: str = "删除") -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hovered = False

    def icon_color(self) -> QColor:
        return qcolor("danger" if self.hovered else "text3", is_dark())

    def enterEvent(self, e: QEnterEvent) -> None:  # noqa: N802
        self.hovered = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e: QEvent) -> None:  # noqa: N802
        self.hovered = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.icon_color(), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        a, b = 4.5, self.SIZE - 4.5
        p.drawLine(QPointF(a, a), QPointF(b, b))
        p.drawLine(QPointF(a, b), QPointF(b, a))


ADD_CARD_H = 64


class AddCard(QAbstractButton):
    """虚线“+ …”占位卡：64px 高、与卡片同宽，点击发 clicked()（服务商 / 智能体 / MCP 共用）。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setObjectName("addCard")
        self.setFixedHeight(ADD_CARD_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 32, ADD_CARD_H)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        dark = is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(qcolor("text3", dark), 1, Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), CARD_RADIUS, CARD_RADIUS)
        p.setPen(qcolor("text2", dark))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


# 各平台自带的等宽字体，放在 tokens 的 CJK 回退之前：没装 JetBrains Mono 时，
# 不能让 Qt 先选中 PingFang / 微软雅黑这类比例字体（macOS / Windows 上
# 平台主题给的 FixedFont 可能只是通用名 "monospace"，fontconfig 以外解析不了）。
# Menlo 排在 SF Mono 前：macOS 上 SF Mono 常常不是可直接按名解析的字体族，
# 放在前面会让 Qt 先做一次约 67ms 的别名扫描（mac CI 实测）。
PLATFORM_MONO = (
    "Menlo",
    "SF Mono",
    "Monaco",
    "Cascadia Mono",
    "Consolas",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Noto Sans Mono",
    "Courier New",
)


def mono_families() -> list[str]:
    """等宽字体族的回退顺序。

    tokens.font.mono 的等宽项 → 系统 FixedFont → 平台等宽 → 任意已装等宽 → CJK 回退。
    """
    raw = (files("braid.theme") / "tokens.json").read_text(encoding="utf-8")
    token_list: list[str] = list(json.loads(raw).get("font", {}).get("mono", []))
    db = set(QFontDatabase.families())
    head = [f for f in token_list if f in db and QFontDatabase.isFixedPitch(f)]
    sys_fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    rest = [f for f in token_list if f not in head]
    # 兜底：上面都没装时，用字体库里任意一款等宽字体，排在比例 CJK 回退之前
    any_fixed = next((f for f in sorted(db) if QFontDatabase.isFixedPitch(f)), "")
    out: list[str] = []
    for f in [*head, sys_fixed, *PLATFORM_MONO, any_fixed, *rest]:
        if f and f not in out:
            out.append(f)
    return out


def mono_font(base: QFont | None = None, px: int = 12) -> QFont:
    """等宽字体（路径、提示词用），按 :func:`mono_families` 的顺序回退。"""
    f = QFont()
    f.setFamilies(mono_families())
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    if base is not None:
        f.setWeight(base.weight())
    f.setPixelSize(px)
    return f


class ChipMultiSelect(QWidget):
    """胶囊多选：每项一个可勾选胶囊，选中底色 active。信号 changed(list[str])。"""

    changed = Signal(list)

    def __init__(
        self,
        options: Sequence[tuple[str, str]],
        selected: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QToolButton

        self._keys = [k for k, _ in options]
        self.chips: dict[str, QToolButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for key, label in options:
            b = QToolButton(self)
            b.setObjectName("toolChip")
            b.setText(label)
            b.setCheckable(True)
            b.setChecked(key in selected)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.toggled.connect(lambda _on: self.changed.emit(self.selected()))
            lay.addWidget(b)
            self.chips[key] = b
        lay.addStretch(1)

    def selected(self) -> list[str]:
        return [k for k in self._keys if self.chips[k].isChecked()]

    def set_selected(self, keys: Sequence[str]) -> None:
        for k, b in self.chips.items():
            b.blockSignals(True)
            b.setChecked(k in keys)
            b.blockSignals(False)


class GrowHandle(QWidget):
    """拖动把手：上下拖改变 target 的高度（不低于 minimum）。"""

    def __init__(self, target: QWidget, minimum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("growHandle")
        self.target, self.minimum = target, minimum
        self.setFixedHeight(10)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._y0: float | None = None
        self._h0 = 0

    def grow_to(self, h: int) -> None:
        self.target.setFixedHeight(max(self.minimum, h))

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._y0, self._h0 = e.globalPosition().y(), self.target.height()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._y0 is not None:
            self.grow_to(int(self._h0 + e.globalPosition().y() - self._y0))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._y0 = None

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("text3", is_dark()))
        cx, cy = self.width() / 2, self.height() / 2
        p.drawRoundedRect(QRectF(cx - 12, cy - 1, 24, 2), 1, 1)


class ElidedLabel(QLabel):
    """单行文字，放不下时中间省略；完整文字在 full_text() 和 tooltip。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setToolTip(text)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._refit()

    def full_text(self) -> str:
        return self._full

    def _refit(self) -> None:
        w = max(10, self.width())
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, w))

    def resizeEvent(self, e: QResizeEvent) -> None:  # noqa: N802
        self._refit()
        super().resizeEvent(e)

    def changeEvent(self, e: QEvent) -> None:  # noqa: N802
        if e.type() == QEvent.Type.FontChange:
            self._refit()
        super().changeEvent(e)
