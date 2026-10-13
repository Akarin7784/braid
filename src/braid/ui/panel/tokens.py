"""右栏面板取色：转调 braid.theme.palette.tokens（带缓存，见其说明）。"""

from __future__ import annotations

from braid.theme.palette import tokens as _tokens


def tokens(mode: str = "light") -> dict[str, str]:
    return _tokens(mode == "dark")
