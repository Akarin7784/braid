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
