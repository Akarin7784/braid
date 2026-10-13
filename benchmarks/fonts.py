"""字体回落报告：在当前平台上查拉丁文、中文正文、600 字重标题实际落到哪个字体。

用法：python benchmarks/fonts.py [fonts.txt]
构建主窗口并打开设置页，用 QTextLayout 的 glyphRuns 取每段字形实际使用的 rawFont，
把族名/字重/字面写进 fonts.txt。以下情况退出码非 0：
- 拉丁文没落到随包的 Inter（标题降级为只用中文族时，标题拉丁只记录不算失败）；
- 中文没落到本平台预期的系统字体；
- 标题要了 600 字重，但中文实际字面不是真正的 Medium/Semibold/Bold（即合成粗体）。
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QTextLayout
from PySide6.QtWidgets import QApplication

from braid.backends.mock import MockBackend
from braid.theme import load_qss
from braid.theme.fonts import apply_app_font, register_bundled_fonts
from braid.ui.main_window import MainWindow
from braid.ui.settings.widgets import (
    _style_weight,
    resolved_cjk_family,
    title_degraded,
    title_faces,
    title_weight,
)

LATIN = "Braid settings: Model & Services 0123"
CJK_BODY = "模型与服务的接口地址和密钥"
TITLE = "模型与服务"
TITLE_LATIN = "Models & Services"
EXPECTED_CJK = {
    "darwin": ("PingFang SC",),
    "win32": ("Microsoft YaHei UI", "Microsoft YaHei"),
    "linux": ("Noto Sans CJK SC",),
}
# rawFont().weight() 回显的是请求字重（合成粗体时也一样），不能用来判断；
# 字面样式名（styleName）才反映实际用的是哪个字面文件。
IDEAL = {600: "SemiBold（理想）", 500: "Medium（可接受）", 700: "Bold（仅有 Bold，非理想但允许）"}


def settle(ms: int = 200) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def runs(font: QFont, text: str) -> list[tuple[str, int, str, int]]:
    """返回 [(族名, 字面字重, 字面样式名, 字形数)]，按 glyphRun 顺序。"""
    lay = QTextLayout(text, font)
    lay.beginLayout()
    line = lay.createLine()
    line.setLineWidth(10000)
    lay.endLayout()
    out = []
    for r in lay.glyphRuns():
        raw = r.rawFont()
        out.append((raw.familyName(), int(raw.weight()), raw.styleName(), len(r.glyphIndexes())))
    return out


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fonts.txt")
    # Windows 控制台默认 GBK/cp1252，打印中文会 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    app = QApplication(sys.argv[:1])
    apply_app_font(app)
    app.setStyleSheet(load_qss("light"))
    w = MainWindow(MockBackend())
    w.resize(1280, 800)
    w.show()
    w.show_settings(True)
    settle()
    page = w.settings_page
    title_label = page.models.title  # type: ignore[union-attr]
    title_font = QFont(title_label.font())
    body_font = QFont(app.font())

    lines: list[str] = []
    errors: list[str] = []
    lines.append(
        f"platform: {sys.platform} / {platform.platform()} / qpa={QGuiApplication.platformName()}"
    )
    lines.append(f"bundled: {', '.join(register_bundled_fonts()) or '(none)'}")
    lines.append(f"app families: {body_font.families()}")

    def report(name: str, font: QFont, text: str) -> list[tuple[str, int, str, int]]:
        rs = runs(font, text)
        lines.append(
            f"[{name}] text={text!r} requested weight={int(font.weight())} px={font.pixelSize()}"
        )
        for fam, wt, style, n in rs:
            lines.append(f"    -> {fam} | weight {wt} | style {style!r} | glyphs {n}")
        return rs

    lat = report("latin", body_font, LATIN)
    if not lat or any(fam != "Inter" for fam, *_ in lat):
        errors.append(f"拉丁文没有落到 Inter：{[r[0] for r in lat]}")

    exp = EXPECTED_CJK.get(sys.platform, ())
    cjk = report("cjk-body", body_font, CJK_BODY)
    cjk_fams = {fam for fam, *_ in cjk}
    if exp and not cjk_fams <= set(exp):
        errors.append(f"中文正文落到 {sorted(cjk_fams)}，预期 {exp}")

    want = title_weight(title_font)
    lines.append(
        f"title_weight(): {int(want)}  resolved_cjk_family: {resolved_cjk_family(title_font)}"
    )
    plan = ", ".join(f"{f} {st!r}({w})" for f, st, w in title_faces(title_font)) or "(none)"
    lines.append(f"title candidates: {plan}")
    lines.append(
        f"title font: families={title_font.families()} weight={int(title_font.weight())}"
        f" styleName={title_font.styleName()!r}"
    )
    if int(title_font.weight()) != int(want):
        # title_font() 验证首选字面不能真正用上时会降档；降档不是错误，合成粗体才是
        lines.append(f"  note: 首选 {int(want)} 用不上，降到 {int(title_font.weight())}")
    tl = report("title-latin", title_font, TITLE_LATIN)
    if title_degraded(title_font):
        # 只放宽标题拉丁：族链 [Inter, 中文] 选不上中文真实中间字重（见 _title_spec），
        # 标题降级为只用中文族；正文拉丁仍硬性要求 Inter
        lines.append(
            "  note: 降级——族链选不上中文真实字面，标题只用中文族，"
            f"标题拉丁字母用 {sorted({r[0] for r in tl})} 的拉丁字形（不算失败）"
        )
    elif not tl or any(fam != "Inter" for fam, *_ in tl):
        errors.append(f"标题拉丁文没有落到 Inter：{[r[0] for r in tl]}")
    tit = report("title", title_font, TITLE)
    for fam, _wt, style, _n in tit:
        lines.append(f"    styles({fam}): {QFontDatabase.styles(fam)}")
        if exp and not any(fam == e or fam == f"{e} {style}" for e in exp):
            errors.append(f"标题中文落到 {fam}，预期 {exp}")
        req = int(title_font.weight())
        got = _style_weight(style)
        if req > 400 and got != req:
            errors.append(f"标题请求 {req}，但 {fam} 实际字面是 {style!r}，会合成粗体")
        elif req == 400 and got is not None:
            errors.append(f"标题请求 400，却落到 {fam} 的 {style!r}")
        lines.append(f"    title face: {fam} {style!r} → {IDEAL.get(got or 0, 'Regular')}")

    lines.append("result: " + ("OK" if not errors else "FAIL"))
    lines.extend(f"  ! {e}" for e in errors)
    text = "\n".join(lines) + "\n"
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    w.close()
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
