"""从 tokens.json 生成 app_light.qss / app_dark.qss。用法: python build_qss.py"""

import json
import pathlib
import string

here = pathlib.Path(__file__).parent
tokens = json.loads(
    (here.parent.parent / "src/braid/theme/tokens.json").read_text(encoding="utf-8")
)
tpl = string.Template((here / "app.qss.tpl").read_text(encoding="utf-8"))


def _qss_color(v: str) -> str:
    """tokens 用 CSS 的 #RRGGBBAA；Qt 把 8 位十六进制当 #AARRGGBB，这里转成 rgba()。"""
    if isinstance(v, str) and v.startswith("#") and len(v) == 9:
        r, g, b, a = (int(v[i : i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {a})"
    return v


def _alpha(v: str, a: float) -> str:
    r, g, b = (int(v[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {round(a * 255)})"


for name in ("light", "dark"):
    t = {k: _qss_color(v) for k, v in tokens[name].items()}
    t["danger_hover"] = _alpha(tokens[name]["danger"], 0.12)
    (here.parent.parent / "src/braid/theme" / f"app_{name}.qss").write_text(
        tpl.substitute(t, name=name), encoding="utf-8"
    )
    print("wrote", f"app_{name}.qss")
