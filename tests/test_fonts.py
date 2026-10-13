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


def test_title_600_never_synthesized(qapp):
    """真实字体库下：中文字形必须落到 title_weight 选中的那个真实字面。"""
    register_bundled_fonts()
    f = QFont(qapp.font())
    f.setFamilies(["Inter", *spw.CJK_FALLBACK])
    f.setPixelSize(18)
    w = spw.title_weight(f)
    f.setWeight(w)
    for _fam, style in _faces(f, "模型与服务"):
        got = spw._style_weight(style)
        if w == QFont.Weight.Normal:
            assert got is None, style
        else:
            assert got == int(w.value), (style, w)
