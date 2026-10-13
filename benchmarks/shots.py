"""在真实平台插件（Linux CI 上用 xvfb）下截固定的设计走查图。

输出：{main_panel_open,main_panel_closed,chip,menu,sidebar,settings}_{light,dark}.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QWidget

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.theme.menu import ChipButton
from braid.ui.main_window import MainWindow

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")


def settle(app: QApplication, ms: int = 300) -> None:
    QTimer.singleShot(ms, app.quit)
    app.exec()


def grab_screen(app: QApplication, w: QWidget, name: str) -> None:
    """把主窗口和当前弹出的顶层窗口（菜单）合成一张图；xvfb 没有合成器，不能直接抓屏。"""
    img = w.grab()
    p = QPainter(img)
    origin = w.mapToGlobal(QPoint(0, 0))
    for top in app.topLevelWidgets():
        if top is not w and top.isVisible() and top.isWindow() and top.inherits("QMenu"):
            p.drawPixmap(top.mapToGlobal(QPoint(0, 0)) - origin, top.grab())
    p.end()
    img.save(str(OUT / name))


def model_chip(w: MainWindow) -> ChipButton:
    chips = [c for c in w.findChildren(ChipButton) if c.property("role") == "modelChip"]
    if not chips:
        raise SystemExit("截图失败：找不到模型选择按钮（role=modelChip）")
    return chips[0]


def run(app: QApplication, theme: str) -> None:
    dark = theme == "dark"
    app.setProperty("braidDark", dark)
    app.setStyleSheet(load_qss(theme))
    w = MainWindow(MockBackend())
    w.chat_view.set_dark(dark)
    w.resize(1280, 800)
    w.move(0, 0)
    w.show()
    settle(app)
    w.set_panel_open(True, animate=False)
    settle(app)
    grab_screen(app, w, f"main_panel_open_{theme}.png")
    w.set_panel_open(False, animate=False)
    settle(app)
    grab_screen(app, w, f"main_panel_closed_{theme}.png")
    w.set_panel_open(True, animate=False)
    settle(app)

    chip = model_chip(w)
    pad = 24
    r = chip.rect().adjusted(-pad, -pad, pad, pad)
    w.grab(r.translated(chip.mapTo(w, QPoint(0, 0)))).save(str(OUT / f"chip_{theme}.png"))

    menu = chip.menu()
    if menu is None:
        raise SystemExit("截图失败：模型选择按钮没有菜单")
    # xvfb 没有窗口管理器，popup 会立刻被关掉；改为离屏渲染菜单并按弹出位置合成
    img = w.grab()
    p = QPainter(img)
    menu.adjustSize()
    m_pix = menu.grab()
    pos = chip.mapTo(w, QPoint(0, 0)) - QPoint(0, m_pix.height() + 6)
    p.drawPixmap(pos, m_pix)
    acts = [a for a in menu.actions() if a.menu() is not None]
    if not acts:
        raise SystemExit("截图失败：模型菜单里没有二级菜单")
    menu.setActiveAction(acts[0])
    sub = acts[0].menu()
    sub.adjustSize()
    p.drawPixmap(pos + menu.actionGeometry(acts[0]).topRight(), sub.grab())
    p.end()
    img.save(str(OUT / f"menu_{theme}.png"))

    # 侧栏整列：项目分组、选中态和左下角齿轮
    w.sidebar.grab().save(str(OUT / f"sidebar_{theme}.png"))

    # 设置页
    w.show_settings(True)
    settle(app)
    grab_screen(app, w, f"settings_{theme}.png")
    w.show_settings(False)
    w.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    for theme in ("light", "dark"):
        run(app, theme)
    names = ("main_panel_open", "main_panel_closed", "chip", "menu", "sidebar", "settings")
    want = {f"{n}_{t}.png" for n in names for t in ("light", "dark")}
    got = {p.name for p in OUT.glob("*.png")}
    print("\n".join(sorted(got)))
    if want - got:
        print(f"截图失败，缺少：{sorted(want - got)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
