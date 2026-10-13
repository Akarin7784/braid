"""随包 Inter 的注册，以及标题 600 字重只用真实中文粗字面的规则。"""

from __future__ import annotations

from importlib.resources import files

import pytest
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QTextLayout

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


def _resolves(fam: str, style: str, w: int) -> bool:
    """独立探测（QFontInfo，不经 title_font）：只含中文族的 QFont 按字重 w
    （或再加样式名）时，Qt 是否真的选中 style 这个字面。"""
    for use_style in (False, True):
        f = QFont()
        f.setFamilies([fam])
        f.setPixelSize(18)
        f.setWeight(QFont.Weight(w))
        if use_style:
            f.setStyleName(style)
        info = QFontInfo(f)
        if info.family() == fam and info.styleName() == style and int(info.weight()) == w:
            return True
    return False


def test_title_font_uses_real_face(qapp):
    """真实字体库下：标题中文落到真实字面且不合成；字重是 600→500→700 中第一个真正选得上的。"""
    register_bundled_fonts()
    base = QFont(qapp.font())
    base.setFamilies(["Inter", *spw.CJK_FALLBACK])
    f = spw.title_font(base, 18)
    w = int(f.weight())
    fam = spw.resolved_cjk_family(base)
    if fam is not None:
        # 1. 落到的字面真实存在于该族，且字面字重等于请求字重（没有合成粗体）
        real = QFontDatabase.styles(fam)
        for gf, style in _faces(f, "模型与服务"):
            assert gf == fam, gf
            assert style in real, (style, real)
            assert (spw._style_weight(style) or 400) == w, (style, w)
        # 2. 存在但 Qt 选不上的候选（如 CI 上的 Medium）跳过，取第一个选得上的，否则 400
        expected = next((cw for cf, cs, cw in spw.title_faces(base) if _resolves(cf, cs, cw)), 400)
        assert w == expected, (w, expected, spw.title_faces(base))
    # 标题拉丁走 Inter；仅当族链选不上中文真实字面、降级为只用中文族时例外（正文拉丁不受影响）
    if spw.title_degraded(f):
        assert fam is not None and f.families() == [fam]
    else:
        assert {fam for fam, _ in _faces(f, "Models")} == {"Inter"}


def test_title_font_probe_cached(qapp, monkeypatch):
    """同一 (族, 候选, 字号) 只探测一次：设置页每个分区标题都会调 title_font()。"""
    register_bundled_fonts()
    base = QFont(qapp.font())
    base.setFamilies(["Inter", *spw.CJK_FALLBACK])
    spw._title_spec.cache_clear()
    calls = []
    real = spw.cjk_faces
    monkeypatch.setattr(spw, "cjk_faces", lambda *a: calls.append(1) or real(*a))
    a = spw.title_font(base, 18)
    n = len(calls)
    b = spw.title_font(base, 18)
    assert len(calls) == n and a == b
    spw._title_spec.cache_clear()


def test_title_font_style_name_from_db(monkeypatch, qapp):
    """样式名从字体库取，不写死；字体库只有 Regular 时用常规字重。"""
    monkeypatch.setattr(spw, "resolved_cjk_family", lambda _f: "X")
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular", "Semibold"]))
    assert spw.title_faces(QFont()) == [("X", "Semibold", 600)]
    monkeypatch.setattr(QFontDatabase, "styles", staticmethod(lambda _f: ["Regular"]))
    assert spw.title_font(QFont(), 18).weight() == QFont.Weight.Normal
