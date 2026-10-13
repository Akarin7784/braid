"""输入框：Enter 发送、Shift+Enter 换行、停止、附件、chip、/ 命令菜单。"""

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QImage

from braid.core.backend import ModelInfo
from braid.ui.composer import Composer

MODELS = [
    ModelInfo("a", "Model A", "P1", ("low", "medium", "high", "max")),
    ModelInfo("b", "Model B", "P1", ("low", "medium")),
    ModelInfo("c", "Model C", "P2"),
]


def _make(qtbot):
    c = Composer(MODELS)
    qtbot.addWidget(c)
    c.show()
    return c


def test_enter_sends_shift_enter_newline(qtbot):
    c = _make(qtbot)
    qtbot.keyClicks(c.input, "hi")
    qtbot.keyClick(c.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClicks(c.input, "there")
    assert c.input.toPlainText() == "hi\nthere"
    with qtbot.waitSignal(c.submitted) as sig:
        qtbot.keyClick(c.input, Qt.Key.Key_Return)
    assert sig.args == ["hi\nthere", []]
    assert c.input.toPlainText() == ""


def test_empty_not_sent(qtbot):
    c = _make(qtbot)
    with qtbot.assertNotEmitted(c.submitted):
        qtbot.keyClick(c.input, Qt.Key.Key_Return)


def test_stop_when_busy(qtbot):
    c = _make(qtbot)
    c.set_busy(True)
    with qtbot.waitSignal(c.stopRequested):
        c.send_btn.click()


def test_paste_image_and_urls(qtbot, tmp_path):
    c = _make(qtbot)
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    md = QMimeData()
    md.setImageData(img)
    c.input.insertFromMimeData(md)
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    md2 = QMimeData()
    md2.setUrls([QUrl.fromLocalFile(str(f))])
    c.input.insertFromMimeData(md2)
    assert len(c.attachments) == 2 and c.attachments[1] == str(f)
    with qtbot.waitSignal(c.submitted) as sig:
        qtbot.keyClick(c.input, Qt.Key.Key_Return)
    assert len(sig.args[1]) == 2 and c.attachments == []


def _sub(c, mid):
    return c._model_actions[mid].menu()


def test_default_selection_text(qtbot):
    c = _make(qtbot)
    assert (c.model_id, c.reasoning) == ("a", "medium")
    assert c.model_chip.text() == "Model A · 中"


def test_submenu_and_pick_updates_chip(qtbot):
    c = _make(qtbot)
    sub = _sub(c, "b")
    assert [a.text() for a in sub.actions()] == ["低", "中"]
    with qtbot.waitSignal(c.selectionChanged) as sig:
        sub.actions()[0].trigger()
    assert sig.args == ["b", "low"]
    assert c.model_chip.text() == "Model B · 低"
    assert c._model_actions["b"].isChecked() and not c._model_actions["a"].isChecked()
    assert sub.actions()[0].isChecked()


def test_model_without_reasoning_has_no_submenu(qtbot):
    c = _make(qtbot)
    act = c._model_actions["c"]
    assert act.menu() is None
    act.trigger()
    assert (c.model_id, c.reasoning) == ("c", None) and c.model_chip.text() == "Model C"


def test_provider_headers(qtbot):
    c = _make(qtbot)
    headers = [a.text() for a in c.model_menu.actions() if not a.isEnabled()]
    assert headers == ["P1", "P2"]


def test_unsupported_level_falls_back(qtbot):
    c = _make(qtbot)
    c.set_selection("b", "max")
    assert c.reasoning == "medium"


def test_per_session_selection_persists(qtbot):
    from braid.backends.mock import MockBackend
    from braid.ui.main_window import MainWindow

    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w._open(0)
    w.composer.set_selection("mock-fast", "low")
    w._open(1)
    assert w.composer.model_id == "mock-large"  # 新会话用默认值
    w._open(0)
    assert (w.composer.model_id, w.composer.reasoning) == ("mock-fast", "low")


def test_slash_menu(qtbot):
    c = _make(qtbot)
    qtbot.keyClicks(c.input, "/cl")
    assert c.cmd_menu.isVisible() and c.cmd_menu.count() == 1
    with qtbot.waitSignal(c.commandTriggered) as sig:
        qtbot.keyClick(c.input, Qt.Key.Key_Return)
    assert sig.args == ["clear"] and not c.cmd_menu.isVisible()


def test_chip_text_does_not_overlap_arrow(qtbot):
    from braid.theme.menu import ChipButton

    b = ChipButton()
    qtbot.addWidget(b)
    b.setText("Mock Large · 最高")
    text_w = b.fontMetrics().horizontalAdvance(b.text())
    assert b.sizeHint().width() >= b.PAD_LEFT + text_w + b.GAP + b.ARROW + b.ARROW_RIGHT
