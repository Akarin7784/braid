"""Windows 首次打开浏览器标签时窗口闪烁的规避。"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def prewarm_gl_surface(window: QWidget, force: bool = False) -> QWidget | None:
    """Windows：顶层窗口首次出现 GL/RHI 子控件（QWebEngineView）时会重建原生窗口，
    表现为整个窗口闪一下消失。显示前先挂一个 1×1 的 QOpenGLWidget，让窗口一创建
    就是 GL 合成模式，首次打开浏览器标签就不再重建。其他平台无此问题，不做。"""
    if not (force or sys.platform == "win32"):
        return None
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
    except ImportError:
        return None
    gl = QOpenGLWidget(window)
    gl.setObjectName("GlPrewarm")
    gl.setFixedSize(1, 1)
    gl.move(0, 0)
    gl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    gl.lower()
    return gl
