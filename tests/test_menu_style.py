from PySide6.QtWidgets import QApplication

from braid.theme import load_qss
from braid.theme.menu import RoundedMenu


def test_rounded_menu_theme_and_submenu(qapp: QApplication) -> None:
    for theme, surface in (("light", "#FFFFFF"), ("dark", "#2A2A29")):
        qss = load_qss(theme)
        assert "${assets}" not in qss
        qapp.setStyleSheet(qss)
        m = RoundedMenu()
        header = m.addGroupHeader("Anthropic")
        sub = m.addMenu("Claude Sonnet")
        m.ensurePolished()
        assert not header.isEnabled()
        assert isinstance(sub, RoundedMenu)
        assert m.property("surfaceColor").upper() == surface
    qapp.setStyleSheet("")


def test_chip_button_draws_arrow(qapp: QApplication) -> None:
    from braid.theme.menu import ChipButton

    qapp.setProperty("braidDark", True)
    qapp.setStyleSheet(load_qss("dark"))
    b = ChipButton()
    b.setText("Mock Large · 中")
    b.setMenu(RoundedMenu(b))
    b.resize(160, 28)
    img = b.grab().toImage()
    bright = sum(
        1
        for x in range(160 - 24, 160 - 10)
        for y in range(28)
        if img.pixelColor(x, y).lightness() > 120
    )
    assert bright > 5
    qapp.setStyleSheet("")
    qapp.setProperty("braidDark", False)
