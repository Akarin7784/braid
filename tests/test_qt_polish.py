"""Windows 真机反馈 4/5/6/7/9：边缘调整大小、产品标识、模型菜单、底栏按钮、输入框宽度与描边。"""

import json
from importlib.resources import files

import pytest
from PySide6.QtCore import QPointF, Qt

from braid.backends.mock import MOCK_EFFORTS, MockBackend
from braid.theme import load_qss
from braid.theme.menu import DESC_PROP, TAG_PROP, ModelMenu
from braid.ui.main_window import (
    COMPOSER_MAX_W,
    RESIZE_MARGIN,
    MainWindow,
    resize_cursor,
    resize_edges,
)

E = Qt.Edge
L, R, T, B = (int(e.value) for e in (E.LeftEdge, E.RightEdge, E.TopEdge, E.BottomEdge))
W, H = 1000, 700


@pytest.mark.parametrize(
    ("x", "y", "edges", "cursor"),
    [
        (500, 350, 0, None),
        (0, 350, L, Qt.CursorShape.SizeHorCursor),
        (RESIZE_MARGIN - 1, 350, L, Qt.CursorShape.SizeHorCursor),
        (RESIZE_MARGIN, 350, 0, None),
        (W - 1, 350, R, Qt.CursorShape.SizeHorCursor),
        (W - RESIZE_MARGIN, 350, R, Qt.CursorShape.SizeHorCursor),
        (W - RESIZE_MARGIN - 1, 350, 0, None),
        (500, 0, T, Qt.CursorShape.SizeVerCursor),
        (500, H - 1, B, Qt.CursorShape.SizeVerCursor),
        (2, 2, T | L, Qt.CursorShape.SizeFDiagCursor),
        (W - 2, H - 2, B | R, Qt.CursorShape.SizeFDiagCursor),
        (W - 2, 2, T | R, Qt.CursorShape.SizeBDiagCursor),
        (2, H - 2, B | L, Qt.CursorShape.SizeBDiagCursor),
        (-1, 350, 0, None),
        (W, 350, 0, None),
    ],
)
def test_resize_edges(x, y, edges, cursor):
    got = resize_edges(QPointF(x, y), W, H)
    assert got == edges
    assert resize_cursor(got) == cursor


@pytest.fixture
def win(qtbot):
    w = MainWindow(MockBackend())
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_resizer_installed_and_disabled_when_maximized(win):
    assert win._resizer_installed
    assert win.resizer.edges_at(QPointF(1, 400)) == L
    win.showMaximized()
    assert win.resizer.edges_at(QPointF(1, 400)) == 0


def test_composer_max_width_centered(win, qtbot):
    win.resize(1920, 1080)
    win.set_panel_open(False, animate=False)
    qtbot.wait(20)
    c = win.composer
    from braid.ui import chat_view

    assert COMPOSER_MAX_W == chat_view.MAX_WIDTH == 680
    assert c.maximumWidth() == COMPOSER_MAX_W
    assert c.width() == COMPOSER_MAX_W
    area = c.parentWidget()
    left = c.geometry().left()
    right = area.width() - c.geometry().right() - 1
    assert abs(left - right) <= 48  # 中栏左右内边距不对称（24 / 16），允许小偏差


def test_model_menu_two_lines_and_check_only(win):
    c = win.composer
    assert isinstance(c.model_menu, ModelMenu)
    large = c._model_actions["mock-large"]
    assert large.property(DESC_PROP) == "最强·适合复杂任务"
    assert large.property(TAG_PROP) == "高"
    assert isinstance(large.menu(), ModelMenu)
    for eff in MOCK_EFFORTS:
        a = c._level_actions[("mock-large", eff.id)]
        assert (a.text(), a.property(DESC_PROP)) == (eff.label, eff.description)
    c.set_selection("mock-fast", "low")
    assert c._model_actions["mock-fast"].isChecked()
    assert not large.isChecked()
    assert not any(a.font().bold() for a in c._model_actions.values())


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_qss_model_menu_and_bar_buttons(theme):
    qss = load_qss(theme)
    tok = json.loads((files("braid.theme") / "tokens.json").read_text(encoding="utf-8"))[theme]
    assert 'QMenu[role="modelMenu"]::item:checked { background: transparent;' in qss
    hover = f'#Composer QPushButton[bar="true"]:hover {{ background: {tok["hover"]};'
    assert hover in qss
    assert "border_subtle" in tok
    has_outline = f"#Composer {{ border: 1px solid {tok['border_subtle']};" in qss
    assert has_outline == (theme == "light")


def test_bar_buttons_flagged(win):
    c = win.composer
    for b in (c.attach_btn, c.model_chip, c.perm_chip):
        assert b.property("bar") is True


def test_brand_header_above_new_chat(win):
    sb = win.sidebar
    assert sb.brand.text == "Braid"
    assert sb.brand.geometry().bottom() < sb.new_btn.geometry().top()
    assert sb.brand.font().pixelSize() == 16
    assert not sb.brand.logo_pixmap(False).isNull()
    assert not sb.brand.logo_pixmap(True).isNull()


def test_model_chip_text_not_elided(win):
    chip = win.composer.model_chip
    fm = chip.fontMetrics()
    avail = chip.width() - chip.PAD_LEFT - chip._reserved()
    assert fm.horizontalAdvance(chip.text()) < avail


@pytest.mark.parametrize("dark", [False, True])
def test_logo_recolour_keeps_per_stroke_opacity(win, dark):
    from braid.theme.palette import qcolor

    brand = win.sidebar.brand
    raw = brand._icon.pixmap(18, 18).toImage()
    tinted = brand.logo_pixmap(dark).toImage()
    assert raw.size() == tinted.size()
    want = qcolor("text", dark)
    alphas = set()
    for y in range(raw.height()):
        for x in range(raw.width()):
            a0 = raw.pixelColor(x, y).alpha()
            c = tinted.pixelColor(x, y)
            assert abs(c.alpha() - a0) <= 1  # 不压平透明度
            if a0 > 200:
                got, exp = (c.red(), c.green(), c.blue()), (want.red(), want.green(), want.blue())
                assert all(abs(g - e) <= 2 for g, e in zip(got, exp, strict=True))  # 预乘取整
            if a0:
                alphas.add(a0 // 32)
    # 三股线 opacity 1 / 0.55 / 0.3：着色后仍有多档 alpha，而不是全部不透明
    assert len(alphas) >= 3
    assert any(4 <= b <= 5 for b in alphas)  # 0.55 那股（约 140）
    assert any(2 <= b <= 3 for b in alphas)  # 0.3 那股（约 77）


def test_model_menu_no_row_highlighted_on_open(win, qtbot):
    """打开菜单时没有任何行处于 active（悬停）状态：当前模型只打勾、不带灰底。"""
    from PySide6.QtCore import QTimer

    menu = win.composer.model_menu
    seen: list[object] = []

    def check() -> None:
        seen.append((menu.isVisible(), menu.activeAction()))
        menu.close()

    QTimer.singleShot(50, check)
    win.composer.open_model_menu()  # 与快捷键 / 点击模型按钮同一入口
    qtbot.waitUntil(lambda: bool(seen))
    assert seen[0] == (True, None)
    assert win.composer._model_actions["mock-large"].isChecked()


# —— 模型菜单数据全部来自后端（不写死模型 / 档位文案） ——
from braid.core.backend import EffortOption, ModelInfo  # noqa: E402
from braid.ui.composer import Composer  # noqa: E402

FAKE = [
    ModelInfo(
        "z1",
        "Zeta Pro",
        group="Zeta Labs",
        tier="旗舰",
        description="自定义说明一",
        efforts=(EffortOption("e1", "轻", "说明 e1"), EffortOption("e2", "重", "说明 e2")),
    ),
    ModelInfo("z2", "Zeta Mini", group="Zeta Labs", tier="", description="自定义说明二"),
]


def _menu_texts(menu):
    return [a.text() for a in menu.actions()]


def test_menu_built_entirely_from_backend_models(qtbot):
    c = Composer(FAKE)
    qtbot.addWidget(c)
    assert _menu_texts(c.model_menu) == ["Zeta Labs", "Zeta Pro", "Zeta Mini"]
    pro = c._model_actions["z1"]
    assert (pro.property(DESC_PROP), pro.property(TAG_PROP)) == ("自定义说明一", "旗舰")
    sub = pro.menu()
    assert _menu_texts(sub) == ["轻", "重"]
    assert [a.property(DESC_PROP) for a in sub.actions()] == ["说明 e1", "说明 e2"]
    c.set_selection("z1", "e2")
    assert c.model_chip.text() == "Zeta Pro · 重"
    # 界面里不应再出现 mock 的模型名或默认档位文案
    all_text = " ".join(_menu_texts(c.model_menu) + _menu_texts(sub))
    for s in ("Mock", "Local 7B", "低", "中", "最高"):
        assert s not in all_text


def test_no_effort_model_has_no_submenu_and_chip_shows_name_only(qtbot):
    c = Composer(FAKE)
    qtbot.addWidget(c)
    mini = c._model_actions["z2"]
    assert mini.menu() is None
    assert not any(k[0] == "z2" for k in c._level_actions)
    c.set_selection("z2", "e1")
    assert c.reasoning == ""
    assert c.model_chip.text() == "Zeta Mini"


def test_mock_local_7b_has_no_efforts(win):
    c = win.composer
    assert c.models["local-7b"].efforts == ()
    assert c._model_actions["local-7b"].menu() is None
    c.set_selection("local-7b")
    assert c.model_chip.text() == "Local 7B"


def test_legacy_reasoning_levels_still_supported():
    m = ModelInfo("a", "A", "P1", ("low", "max"))
    assert [e.label for e in m.efforts] == ["低", "最高"]
    assert m.group == "P1"
    n = ModelInfo("b", "B", efforts=(EffortOption("x", "X"),))
    assert n.reasoning_levels == ("x",)


@pytest.mark.parametrize("dark", [False, True])
def test_tier_tag_has_no_background(qtbot, dark):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from braid.theme.palette import qcolor

    app = QApplication.instance()
    app.setProperty("braidDark", dark)
    app.setStyleSheet(load_qss("dark" if dark else "light"))
    try:
        c = Composer(FAKE)
        qtbot.addWidget(c)
        menu = c.model_menu
        menu.popup(QPoint(100, 100))
        qtbot.waitExposed(menu)
        img = menu.grab().toImage()
        dpr = img.devicePixelRatio()
        r = menu.actionGeometry(c._model_actions["z1"])
        # 标签所在区域（行右上）只能有行底色和 text3 文字色，不能出现 control 底色块
        surface = qcolor("surface", dark)
        control = qcolor("control", dark)
        x0, x1 = int((r.right() - 90) * dpr), int((r.right() - 30) * dpr)
        y0, y1 = int((r.top() + 6) * dpr), int((r.top() + 24) * dpr)
        n_control = sum(
            img.pixelColor(x, y).rgb() == control.rgb()
            for x in range(x0, x1)
            for y in range(y0, y1)
        )
        assert n_control < 20  # 旧版底色块有几百个像素；个别抗锯齿像素可能恰好同色
        assert img.pixelColor(x0, y0).rgb() == surface.rgb()
        menu.close()
    finally:
        app.setProperty("braidDark", False)
        app.setStyleSheet("")


def test_effort_items_use_same_font_as_model_names(win):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    app.setStyleSheet(load_qss("light"))
    try:
        m = win.composer.model_menu
        sub = win.composer._model_actions["mock-large"].menu()
        m.ensurePolished()
        sub.ensurePolished()
        f1, f2 = m.font(), sub.font()
        assert (f1.families(), f1.pixelSize(), f1.weight()) == (
            f2.families(),
            f2.pixelSize(),
            f2.weight(),
        )
        rule = 'QMenu[role="modelMenu"]::item { padding: 6px 30px 24px 32px; min-width: 230px; '
        assert rule + "font-size: 13px; font-weight: normal; }" in load_qss("light")
    finally:
        app.setStyleSheet("")
