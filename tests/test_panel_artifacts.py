from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QGraphicsOpacityEffect

from braid.backends.mock_artifacts import MockArtifactSource
from braid.core.artifacts import Artifact
from braid.ui.panel import RightPanel
from braid.ui.panel.artifacts import COPIED_TEXT, ArtifactsPage


def _page(qtbot, src=None):
    p = ArtifactsPage(src)
    qtbot.addWidget(p)
    return p


def test_empty_state(qtbot):
    p = _page(qtbot)
    assert p.list_title.text() == "本次会话产物（0）"
    assert not p.empty.isHidden() and p.list_scroll.isHidden()
    assert not p.preview.download_btn.isEnabled()


def test_artifact_added_inserts_on_top_and_fades(qtbot):
    src = MockArtifactSource()
    p = _page(qtbot, src)
    a1 = src.produce()
    a2 = src.produce()
    assert [c.artifact for c in p.cards] == [a2, a1]
    assert p.list_layout.itemAt(0).widget() is p.cards[0]
    assert p.list_title.text() == "本次会话产物（2）"
    assert isinstance(p.cards[0].graphicsEffect(), QGraphicsOpacityEffect)
    assert p.selected is a2 and p.preview.title.text() == "app.py"
    qtbot.waitUntil(lambda: not isinstance(p.cards[0].graphicsEffect(), QGraphicsOpacityEffect))


def test_existing_artifacts_loaded(qtbot):
    src = MockArtifactSource()
    src.seed(3)
    p = _page(qtbot, src)
    assert len(p.cards) == 3


def test_preview_mode_switch(qtbot):
    src = MockArtifactSource()
    p = _page(qtbot, src)
    md = src.produce()  # README.md，无前版本
    pv = p.preview
    assert pv.mode == "preview" and not pv.segments["diff"].isEnabled()
    assert "Braid" in pv.body.toPlainText() and "#" not in pv.body.toPlainText()
    qtbot.mouseClick(pv.segments["source"], Qt.MouseButton.LeftButton)
    assert pv.mode == "source" and pv.body.toPlainText().startswith("# Braid")
    pv.set_mode("diff")  # 禁用段不可切
    assert pv.mode == "source"
    code = src.produce()  # app.py，有前版本
    assert pv.segments["diff"].isEnabled()
    with qtbot.waitSignal(pv.modeChanged):
        qtbot.mouseClick(pv.segments["diff"], Qt.MouseButton.LeftButton)
    assert pv.mode == "diff" and 'print("hello, braid")' in pv.body.toPlainText()
    p.select(md)  # 切回无前版本的产物，diff 自动退回预览
    assert pv.mode == "preview"
    p.select(code)
    assert pv.title.text() == "app.py"


def test_copy_and_download(qtbot, tmp_path):
    p = _page(qtbot)
    a = Artifact(id="x", name="n.txt", content="内容")
    p.add_artifact(a, animate=False)
    qtbot.mouseClick(p.preview.copy_btn, Qt.MouseButton.LeftButton)
    assert QGuiApplication.clipboard().text() == "内容"
    assert p.preview.copy_btn.text() == COPIED_TEXT
    dest = tmp_path / "out.txt"
    p.preview.ask_save_path = lambda name: str(dest)
    p.preview.download()
    assert dest.read_text(encoding="utf-8") == "内容"
    assert not p.preview.reveal_btn.isEnabled()  # 无路径


def test_click_card_selects(qtbot):
    src = MockArtifactSource()
    src.seed(2)
    p = _page(qtbot, src)
    first = p.cards[-1]
    qtbot.mouseClick(first, Qt.MouseButton.LeftButton)
    assert p.selected is first.artifact and first.property("selected") is True


def test_panel_has_artifacts_page(qtbot):
    src = MockArtifactSource()
    panel = RightPanel(artifact_source=src)
    qtbot.addWidget(panel)
    src.produce()
    assert panel.stack.currentWidget() is panel.artifacts
    assert len(panel.artifacts.cards) == 1
