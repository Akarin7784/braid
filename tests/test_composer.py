"""输入框：Enter 发送、Shift+Enter 换行、停止、附件、chip、/ 命令菜单。"""

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QImage

from braid.core.backend import ModelInfo
from braid.ui.composer import Composer

MODELS = [ModelInfo("a", "Model A"), ModelInfo("b", "Model B")]


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
    f.write_text("x")
    md2 = QMimeData()
    md2.setUrls([QUrl.fromLocalFile(str(f))])
    c.input.insertFromMimeData(md2)
    assert len(c.attachments) == 2 and c.attachments[1] == str(f)
    with qtbot.waitSignal(c.submitted) as sig:
        qtbot.keyClick(c.input, Qt.Key.Key_Return)
    assert len(sig.args[1]) == 2 and c.attachments == []


def test_chips_change_state(qtbot):
    c = _make(qtbot)
    c.model_chip.menu().actions()[1].trigger()
    c.reason_chip.menu().actions()[2].trigger()
    assert c.model_id == "b" and c.model_chip.text() == "Model B"
    assert c.reasoning == "high"


def test_slash_menu(qtbot):
    c = _make(qtbot)
    qtbot.keyClicks(c.input, "/cl")
    assert c.cmd_menu.isVisible() and c.cmd_menu.count() == 1
    with qtbot.waitSignal(c.commandTriggered) as sig:
        qtbot.keyClick(c.input, Qt.Key.Key_Return)
    assert sig.args == ["clear"] and not c.cmd_menu.isVisible()
