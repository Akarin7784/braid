from functools import cache
from importlib.resources import files


@cache
def load_qss(theme: str = "light") -> str:
    """读取主题 QSS，并把 ${assets} 替换成图标资源目录的绝对路径（按主题缓存）。"""
    qss = (files(__package__) / f"app_{theme}.qss").read_text(encoding="utf-8")
    assets = str(files("braid.assets")).replace("\\", "/")
    return qss.replace("${assets}", assets)


def resolve_dark(mode: str) -> bool:
    """主题模式 system / light / dark → 是否深色。system 读系统配色。"""
    if mode == "dark":
        return True
    if mode == "light":
        return False
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    hints = QGuiApplication.styleHints()
    return bool(hints and hints.colorScheme() == Qt.ColorScheme.Dark)


def apply_theme(mode: str) -> bool:
    """运行时切主题：设 app 的 braidDark 并换样式表（与启动时 app.py 同一套机制）。"""
    from PySide6.QtWidgets import QApplication

    dark = resolve_dark(mode)
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.setProperty("braidDark", dark)
        app.setStyleSheet(load_qss("dark" if dark else "light"))
    return dark
