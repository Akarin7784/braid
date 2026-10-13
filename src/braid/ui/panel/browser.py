"""浏览器标签页（占位）。

将来接 QtWebEngine：只能在本模块的函数/类内部导入，禁止放到模块顶层；
本模块本身也只由 RightPanel 在首次切到浏览器标签时导入。
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from braid.ui.panel.shell import placeholder_page


class BrowserPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(placeholder_page("浏览器（即将推出）"))
