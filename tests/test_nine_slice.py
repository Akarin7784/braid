from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from braid.theme.nine_slice import NineSliceShadow


def test_nine_slice_paints_shadow_outside_card(qapp: object) -> None:
    img = QImage(300, 200, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    card = QRect(60, 50, 180, 90)
    for dark in (False, True):
        NineSliceShadow.get("e2", dark).paint(p, card)
    p.end()
    assert img.pixelColor(150, 145).red() < 255  # 卡片下方有阴影
    assert img.pixelColor(5, 5).red() == 255  # 远处无阴影
