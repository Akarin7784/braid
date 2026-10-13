"""从 tokens.json 生成 app_light.qss / app_dark.qss。用法: python build_qss.py"""

import json
import pathlib
import string

here = pathlib.Path(__file__).parent
tokens = json.loads((here.parent / "tokens.json").read_text())
tpl = string.Template((here / "app.qss.tpl").read_text())
for name, t in tokens.items():
    (here.parent.parent / "src/braid/theme" / f"app_{name}.qss").write_text(
        tpl.substitute(t, name=name)
    )
    print("wrote", f"app_{name}.qss")
