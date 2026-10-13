"""随包 Inter 的注册，以及标题 600 字重只用真实中文粗字面的规则。"""

from __future__ import annotations

from importlib.resources import files

import pytest
from PySide6.QtGui import QFont, QFontDatabase, QTextLayout

from braid.theme.fonts import apply_app_font, bundled_font_files, register_bundled_fonts
from braid.ui.settings import widgets as spw


def _faces(font: QFont, text: str) -> list[tuple[str, str]]:
    lay = QTextLayout(text, font)
    lay.beginLayout()
    lay.createLine().setLineWidth(10000)
    lay.endLayout()
    return [(r.rawFont().familyName(), r.rawFont().styleName()) for r in lay.glyphRuns()]


def test_bundled_files_shipped():
    root = files("braid.assets") / "fonts"
    for name in [*bundled_font_files(), "OFL.txt"]:
        assert (root / name).is_file(), name
    assert set(bundled_font_files()) == {"Inter-Regular.ttf", "Inter-SemiBold.ttf"}


def test_inter_registered_and_used_for_latin(qapp):
    fams = register_bundled_fonts()
    assert "Inter" in fams
    styles = {s.lower().replace(" ", "") for s in QFontDatabase.styles("Inter")}
    assert "regular" in styles and "semibold" in styles
    old = QFont(qapp.font())
    try:
        f = apply_app_font(qapp)
        assert f.families()[0] == "Inter"
        assert "sans-serif" not in f.families()
        assert {fam for fam, _ in _faces(f, "Braid 0123")} == {"Inter"}
        bold = QFont(f)
        bold.setWeight(QFont.Weight.DemiBold)
        assert _faces(bold, "Braid") == [("Inter", "SemiBold")]
    finally:
        qapp.setFont(old)


@pytest.mark.parametrize(
    ("styles", "want"),
    [
        (["Regular"], QFont.Weight.Normal),
        (["Regular", "Light"], QFont.Weight.Normal),
        (["Regular", "Medium"], QFont.Weight.Medium),
        (["Regular", "SemiBold"], QFont.Weight.DemiBold),
        (["Regular", "Demibold"], QFont.Weight.DemiBold),
        (["Regular", "Medium", "SemiBold", "Bold"], QFont.Weight.DemiBold),
        (["Regular", "Medium", "Bold"], QFont.Weight.Medium),
        (["Regular", "Bold"], QFont.Weight.Bold),
        (["Regular", "ExtraBold"], QFont.Weight.Normal),
    ],
)
def test_title_weight_rule(monkeypatch, styles, want):
    monkeypatch.setattr(spw, "resolved_cjk_family", lambda _f: "X")
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: styles))
    assert spw.title_weight(QFont()) == want


def test_title_weight_no_cjk(monkeypatch):
    monkeypatch.setattr(spw, "resolved_cjk_family", lambda _f: None)
    assert spw.title_weight(QFont()) == QFont.Weight.Normal


def test_title_font_uses_real_face(qapp):
    """真实字体库下：中文落到 title_font 请求字重对应的真实字面，拉丁字母仍是 Inter。"""
    register_bundled_fonts()
    base = QFont(qapp.font())
    base.setFamilies(["Inter", *spw.CJK_FALLBACK])
    f = spw.title_font(base, 18)
    w = int(f.weight())
    assert w <= int(spw.title_weight(base))
    if spw.resolved_cjk_family(base) is not None:
        for _fam, style in _faces(f, "模型与服务"):
            got = spw._style_weight(style)
            assert (got is None) if w == 400 else (got == w), (style, w)
    assert {fam for fam, _ in _faces(f, "Models")} == {"Inter"}


def test_title_font_style_name_from_db(monkeypatch, qapp):
    """样式名从字体库取，不写死；字体库只有 Regular 时用常规字重。"""
    monkeypatch.setattr(spw, "resolved_cjk_family", lambda _f: "X")
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular", "Semibold"]))
    assert spw.title_faces(QFont()) == [("X", "Semibold", 600)]
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular"]))
    assert spw.title_font(QFont(), 18).weight() == QFont.Weight.Normal
