"""右栏面板颜色 token 读取。

优先读 ``files("braid.theme") / "tokens.json"``（由 #12 引入）；
包内尚无该文件时退回下方与 design/menu-style 一致的内置值。
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

_FALLBACK: dict[str, dict[str, str]] = {
    "light": {
        "bg_app": "#FDFDFD",
        "pn_a": "#FBFBFA",
        "pn_b": "#F6F6F5",
        "surface": "#FFFFFF",
        "subtle": "#F3F3F2",
        "control": "#F0F0EF",
        "hover": "#ECECEB",
        "active": "#E9E9E8",
        "text": "#1F1F1E",
        "text2": "#6B6B69",
        "text3": "#9E9E9B",
        "accent": "#555555",
        "accent_text": "#FFFFFF",
        "accent_hover": "#444444",
        "brand": "#C96442",
        "success": "#2E8B57",
        "warning": "#B26A00",
        "danger": "#C0392B",
        "sel": "#C9643233",
    },
    "dark": {
        "bg_app": "#1B1B1A",
        "pn_a": "#1E1E1D",
        "pn_b": "#232322",
        "surface": "#2A2A29",
        "subtle": "#262625",
        "control": "#30302F",
        "hover": "#343433",
        "active": "#3A3A39",
        "text": "#ECECEA",
        "text2": "#A3A3A0",
        "text3": "#73736F",
        "accent": "#E6E6E3",
        "accent_text": "#1B1B1A",
        "accent_hover": "#FFFFFF",
        "brand": "#D97757",
        "success": "#5CC28A",
        "warning": "#E0A54A",
        "danger": "#E2685B",
        "sel": "#D9775744",
    },
}


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads((files("braid.theme") / "tokens.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return _FALLBACK
    return {m: {**_FALLBACK[m], **data.get(m, {})} for m in _FALLBACK}


def tokens(mode: str = "light") -> dict[str, str]:
    return _load()["dark" if mode == "dark" else "light"]
