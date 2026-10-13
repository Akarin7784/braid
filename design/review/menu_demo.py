"""渲染多级菜单效果图：python design/review/menu_demo.py [light|dark]"""

import sys

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QActionGroup, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from braid.theme import load_qss
from braid.theme.menu import RoundedMenu

theme = sys.argv[1] if len(sys.argv) > 1 else "light"
app = QApplication([])
app.setProperty("braidDark", theme == "dark")
app.setStyleSheet(load_qss(theme))
menu = RoundedMenu()
group = QActionGroup(menu)
levels = ["低", "中", "高", "最高"]
models = {"Anthropic": ["Claude Opus", "Claude Sonnet"], "OpenAI": ["GPT-5"], "本地": ["Qwen 7B"]}
open_sub = None
for prov, names in models.items():
    menu.addGroupHeader(prov)
    for n in names:
        if n == "Qwen 7B":
            a = menu.addAction(n)
            a.setCheckable(True)
            continue
        sub = menu.addMenu(n)
        for lv in levels:
            a = sub.addAction(lv)
            a.setCheckable(True)
            group.addAction(a)
            if n == "Claude Sonnet" and lv == "中":
                a.setChecked(True)
                sub.menuAction().setCheckable(True)
                sub.menuAction().setChecked(True)
                open_sub = sub
menu.popup(QPoint(0, 0))


def shot() -> None:
    menu.setActiveAction(open_sub.menuAction())
    m1 = menu.grab()
    m2 = open_sub.grab()
    canvas = QPixmap(m1.width() + m2.width() - 30, max(m1.height(), m2.height() + 120))
    canvas.fill(QColor("#1B1B1A" if theme == "dark" else "#FDFDFD"))
    p = QPainter(canvas)
    p.drawPixmap(0, 0, m1)
    p.drawPixmap(m1.width() - 44, 120, m2)
    p.end()
    canvas.save(f"design/review/menu_{theme}.png")
    app.quit()


QTimer.singleShot(400, shot)
app.exec()
