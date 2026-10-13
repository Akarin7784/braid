"""产物页（panel_spec §5）：上方预览卡片 + 下方产物卡片列表。"""

from __future__ import annotations

import difflib
import html
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from braid.core.artifacts import Artifact, ArtifactSource
from braid.theme.palette import tokens as palette
from braid.ui.panel.shell import card_shadow

MODES = ("preview", "source", "diff")
MODE_LABELS = {"preview": "预览", "source": "源码", "diff": "Diff"}
COPIED_TEXT, COPIED_MS, FADE_MS = "已复制 ✓", 1500, 220


def artifacts_qss(mode: str = "light") -> str:
    t = palette(mode == "dark")
    return f"""
#PreviewCard, QFrame[role="artifactCard"] {{ background: {t["surface"]}; border-radius: 14px; }}
QFrame[role="artifactCard"][selected="true"] {{ background: {t["active"]}; }}
QFrame[role="artifactCard"]:hover {{ background: {t["surface"]}; }}
QFrame[role="artifactCard"][selected="true"]:hover {{ background: {t["active"]}; }}
#PreviewTitle {{ font-size: 13px; font-weight: 600; color: {t["text"]}; }}
#Segmented {{ background: {t["control"]}; border-radius: 10px; }}
QPushButton[role="segment"] {{ border: none; border-radius: 8px; padding: 2px 10px;
    color: {t["text2"]}; background: transparent; font-size: 12px; }}
QPushButton[role="segment"]:checked {{ background: {t["surface"]}; color: {t["text"]}; }}
QPushButton[role="segment"]:disabled {{ color: {t["text3"]}; }}
#PreviewBody {{ background: {t["subtle"]}; border: none; border-radius: 12px;
    color: {t["text"]}; padding: 8px; }}
QPushButton[variant="secondary"] {{ background: {t["control"]}; color: {t["text"]};
    border: none; border-radius: 10px; padding: 4px 12px; }}
QPushButton[variant="primary"] {{ background: {t["accent"]}; color: {t["accent_text"]};
    border: none; border-radius: 10px; padding: 4px 12px; }}
QPushButton[variant="primary"]:hover {{ background: {t["accent_hover"]}; }}
QPushButton:disabled {{ background: {t["control"]}; color: {t["text3"]}; }}
#ArtifactIcon {{ background: {t["subtle"]}; border-radius: 10px; color: {t["text2"]}; }}
#ArtifactName {{ font-size: 13px; color: {t["text"]}; }}
#ListTitle, QLabel[role="caption"] {{ font-size: 12px; color: {t["text3"]}; }}
#EmptyState {{ color: {t["text3"]}; font-size: 13px; }}
"""


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def diff_html(old: str, new: str, mode: str = "light") -> str:
    """与 Git 面板一致的 diff 着色：加行 success 底、删行 danger 底。"""
    add_bg, del_bg = ("#5CC28A26", "#E2685B26") if mode == "dark" else ("#2E8B571F", "#C0392B1A")
    t = palette(mode == "dark")
    rows = []
    for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=3):
        if ln.startswith(("---", "+++")):
            continue
        bg = ""
        if ln.startswith("+"):
            bg = add_bg
        elif ln.startswith("-"):
            bg = del_bg
        color = t["text3"] if ln.startswith("@@") else t["text"]
        # Qt 富文本用 #AARRGGBB，tokens 是 #RRGGBBAA
        bgq = f"#{bg[7:9]}{bg[1:7]}" if bg else "transparent"
        rows.append(
            f'<tr><td style="background:{bgq};color:{color};white-space:pre">'
            f"{html.escape(ln) or '&nbsp;'}</td></tr>"
        )
    return (
        "<table width='100%' cellspacing='0' cellpadding='0' "
        "style='font-family:monospace;font-size:12px'>" + "".join(rows) + "</table>"
    )


class PreviewCard(QFrame):
    """预览卡片：标题 + 预览/源码/Diff 分段 + 内容 + 复制/在文件夹中显示/下载。"""

    modeChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, theme: str = "light") -> None:
        super().__init__(parent)
        self.setObjectName("PreviewCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.theme = theme
        self.artifact: Artifact | None = None
        self.mode = "preview"
        # 可替换以便测试：返回保存路径或空串
        self.ask_save_path: Callable[[str], str] = lambda name: QFileDialog.getSaveFileName(
            self, "下载产物", name
        )[0]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        self.title = QLabel("未选择产物")
        self.title.setObjectName("PreviewTitle")
        head.addWidget(self.title, 1)
        seg = QFrame()
        seg.setObjectName("Segmented")
        seg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.seg_group = QButtonGroup(self)
        self.segments: dict[str, QPushButton] = {}
        for i, m in enumerate(MODES):
            b = QPushButton(MODE_LABELS[m])
            b.setCheckable(True)
            b.setProperty("role", "segment")
            self.seg_group.addButton(b, i)
            self.segments[m] = b
            sl.addWidget(b)
        self.seg_group.idClicked.connect(lambda i: self.set_mode(MODES[i]))
        head.addWidget(seg)
        lay.addLayout(head)

        self.body = QTextBrowser()
        self.body.setObjectName("PreviewBody")
        self.body.setOpenExternalLinks(True)
        lay.addWidget(self.body, 1)

        acts = QHBoxLayout()
        self.copy_btn = QPushButton("复制")
        self.reveal_btn = QPushButton("在文件夹中显示")
        self.download_btn = QPushButton("下载")
        for b in (self.copy_btn, self.reveal_btn):
            b.setProperty("variant", "secondary")
            acts.addWidget(b)
        acts.addStretch(1)
        self.download_btn.setProperty("variant", "primary")
        acts.addWidget(self.download_btn)
        lay.addLayout(acts)
        self.copy_btn.clicked.connect(self.copy)
        self.reveal_btn.clicked.connect(self.reveal)
        self.download_btn.clicked.connect(self.download)
        self._copy_timer = QTimer(self, singleShot=True, interval=COPIED_MS)
        self._copy_timer.timeout.connect(lambda: self.copy_btn.setText("复制"))
        card_shadow(self)
        self.set_artifact(None)

    def set_artifact(self, a: Artifact | None) -> None:
        self.artifact = a
        has = a is not None
        for b in (self.copy_btn, self.download_btn, *self.segments.values()):
            b.setEnabled(has)
        self.reveal_btn.setEnabled(bool(a and a.path))
        self.segments["diff"].setEnabled(bool(a and a.previous is not None))
        self.title.setText(a.name if a else "未选择产物")
        if self.mode == "diff" and not self.segments["diff"].isEnabled():
            self.mode = "preview"
        self.segments[self.mode].setChecked(True)
        self._render()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES or not self.segments[mode].isEnabled():
            return
        self.segments[mode].setChecked(True)
        if mode != self.mode:
            self.mode = mode
            self._render()
            self.modeChanged.emit(mode)

    def _render(self) -> None:
        a = self.artifact
        self.body.document().setDefaultFont(QFont())
        if a is None:
            self.body.setPlainText("")
            return
        if self.mode == "diff" and a.previous is not None:
            self.body.setHtml(diff_html(a.previous, a.content, self.theme))
            return
        kind = a.resolved_kind
        if self.mode == "source" or kind == "code":
            mono = QFont("monospace")
            mono.setStyleHint(QFont.StyleHint.Monospace)
            mono.setPixelSize(12)
            self.body.document().setDefaultFont(mono)
            self.body.setPlainText(a.content)
        elif kind == "markdown":
            self.body.setMarkdown(a.content)
        elif kind == "image" and a.path:
            url = QUrl.fromLocalFile(a.path).toString()
            self.body.setHtml(f'<img src="{html.escape(url)}" width="100%">')
        else:
            self.body.setHtml(a.content)

    def copy(self) -> None:
        if self.artifact is None:
            return
        if cb := QGuiApplication.clipboard():
            cb.setText(self.artifact.content)
        self.copy_btn.setText(COPIED_TEXT)
        self._copy_timer.start()

    def reveal(self) -> None:
        if self.artifact and self.artifact.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.artifact.path).parent)))

    def download(self) -> None:
        if self.artifact is None:
            return
        dest = self.ask_save_path(self.artifact.name)
        if dest:
            Path(dest).write_text(self.artifact.content, encoding="utf-8")


class ArtifactCard(QFrame):
    clicked = Signal(object)

    def __init__(self, a: Artifact, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.artifact = a
        self.setProperty("role", "artifactCard")
        self.setProperty("selected", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        icon = QLabel(Path(a.name).suffix.lstrip(".")[:3].upper() or "•")
        icon.setObjectName("ArtifactIcon")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(a.name)
        name.setObjectName("ArtifactName")
        meta = QLabel(f"{human_size(a.size)} · {a.created:%H:%M}")
        meta.setProperty("role", "caption")
        col.addWidget(name)
        col.addWidget(meta)
        lay.addLayout(col, 1)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        # 选中去阴影，未选中恢复卡片阴影
        if on:
            self.setGraphicsEffect(None)  # type: ignore[arg-type]
        elif not isinstance(self.graphicsEffect(), QGraphicsOpacityEffect):
            card_shadow(self)
        if st := self.style():
            st.unpolish(self)
            st.polish(self)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.artifact)


class ArtifactsPage(QWidget):
    """产物页。接一个 ArtifactSource，新产物插到列表顶部并淡入、自动选中。"""

    selectionChanged = Signal(object)

    def __init__(
        self,
        source: ArtifactSource | None = None,
        parent: QWidget | None = None,
        theme: str = "light",
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(artifacts_qss(theme))
        self.cards: list[ArtifactCard] = []  # 顺序同界面，从上到下
        self.selected: Artifact | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.preview = PreviewCard(theme=theme)
        lay.addWidget(self.preview, 1)

        self.list_title = QLabel()
        self.list_title.setObjectName("ListTitle")
        lay.addWidget(self.list_title)
        self.empty = QLabel("本次会话还没有产物", alignment=Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("EmptyState")
        lay.addWidget(self.empty)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setMaximumHeight(260)
        self.list_scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget {background: transparent;}"
        )
        holder = QWidget()
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.list_scroll.setWidget(holder)
        lay.addWidget(self.list_scroll)
        self._update_count()

        self.source = source
        if source is not None:
            for a in source.list_artifacts():
                self.add_artifact(a, animate=False)
            source.artifact_added.connect(self.add_artifact)

    def _update_count(self) -> None:
        n = len(self.cards)
        self.list_title.setText(f"本次会话产物（{n}）")
        self.empty.setVisible(n == 0)
        self.list_scroll.setVisible(n > 0)

    def add_artifact(self, a: Artifact, animate: bool = True) -> ArtifactCard:
        card = ArtifactCard(a)
        card.clicked.connect(self.select)
        self.list_layout.insertWidget(0, card)
        self.cards.insert(0, card)
        if animate:
            eff = QGraphicsOpacityEffect(card, opacity=0.0)
            card.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", card)
            anim.setDuration(FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda c=card: c.set_selected(c.artifact is self.selected))
            card._fade = anim  # type: ignore[attr-defined]
            anim.start()
        else:
            card_shadow(card)
        self._update_count()
        self.select(a)
        return card

    def select(self, a: Artifact) -> None:
        self.selected = a
        for c in self.cards:
            if not isinstance(c.graphicsEffect(), QGraphicsOpacityEffect):
                c.set_selected(c.artifact is a)
            else:
                c.setProperty("selected", c.artifact is a)
        self.preview.set_artifact(a)
        self.selectionChanged.emit(a)
