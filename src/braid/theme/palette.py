"""带缓存的颜色 token 读取：唯一来源是包内 ``braid/theme/tokens.json``。

调用方应在 paint 时取色，不要在初始化时缓存；
主题切换（或 tokens.json 变更）后调用 ``tokens.cache_clear()`` 再触发重绘。
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files

from PySide6.QtGui import QColor


@cache
def tokens(dark: bool = False) -> dict[str, str]:
    raw = (files("braid.theme") / "tokens.json").read_text(encoding="utf-8")
    data: dict[str, dict[str, str]] = json.loads(raw)
    return dict(data["dark" if dark else "light"])


def qcolor(name: str, dark: bool = False) -> QColor:
    """按 token 名返回 QColor。

    tokens 用 CSS 的 ``#RRGGBBAA``，Qt 会当成 ``#AARRGGBB``，这里转好。
    """
    v = tokens(dark)[name]
    if v.startswith("#") and len(v) == 9:
        r, g, b, a = (int(v[i : i + 2], 16) for i in (1, 3, 5, 7))
        return QColor(r, g, b, a)
    return QColor(v)
