"""托盘图标：按系统配色切换浅/深版本。"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def _tray_icon() -> QIcon:
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    # 深色系统用浅色线条版
    variant = "light" if dark else "dark"
    d = files("braid.assets")
    icon = QIcon()
    for s in (16, 32):
        icon.addFile(str(d / f"braid_tray_{variant}_{s}.png"))
    return icon


class Tray(QSystemTrayIcon):
    def __init__(self, window: QWidget) -> None:
        super().__init__(_tray_icon(), window)
        menu = QMenu()
        menu.addAction("显示 Braid", window.showNormal)
        menu.addAction("退出", window.close)
        self.setContextMenu(menu)
        self.setToolTip("Braid")
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _: self.setIcon(_tray_icon())
        )
