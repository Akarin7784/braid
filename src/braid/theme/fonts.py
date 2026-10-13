"""随包字体（Inter）注册与应用级 UI 字体。

拉丁字母用随包的 Inter，中文按 tokens.json font.ui 的顺序回落到系统字体
（PingFang SC / Microsoft YaHei UI / Noto Sans CJK SC …）。
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import as_file, files

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication


def _font_tokens() -> dict:
    data = json.loads((files("braid.theme") / "tokens.json").read_text(encoding="utf-8"))
    return dict(data["font"])


def bundled_font_files() -> list[str]:
    return list(_font_tokens().get("bundled", []))


def ui_families() -> list[str]:
    """tokens 里的 UI 字体链，去掉 CSS 通用名（Qt 不认 sans-serif 这类名字）。"""
    return [f for f in _font_tokens()["ui"] if f not in ("sans-serif", "serif", "monospace")]


@cache
def register_bundled_fonts() -> tuple[str, ...]:
    """把随包字体加进 QFontDatabase，返回注册得到的族名。需在 QGuiApplication 之后调用。"""
    fams: list[str] = []
    root = files("braid.assets") / "fonts"
    for name in bundled_font_files():
        with as_file(root / name) as path:
            fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            fams.extend(QFontDatabase.applicationFontFamilies(fid))
    return tuple(dict.fromkeys(fams))


def apply_app_font(app: QGuiApplication) -> QFont:
    """注册随包字体并把应用默认字体设成 tokens 的 UI 字体链（保留原字号）。"""
    register_bundled_fonts()
    f = QFont(app.font())
    f.setFamilies(ui_families())
    f.setPixelSize(int(_font_tokens()["size_ui"]))
    app.setFont(f)
    return f
