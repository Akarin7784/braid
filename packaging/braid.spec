# PyInstaller spec：pyinstaller packaging/braid.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
icon = str(Path(SPECPATH) / ("braid_light.icns" if sys.platform == "darwin" else "braid_light.ico"))

# 随包字体（Inter + OFL 许可证）经 collect_data_files 打进包；缺了直接报错，别打出没有字体的包
datas = collect_data_files("braid")
for _f in ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "OFL.txt"):
    assert any(Path(src).name == _f and "fonts" in Path(dst).parts for src, dst in datas), f"缺少字体资源 {_f}"

a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "src")],
    datas=datas,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="braid",
          console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="braid")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Braid.app", icon=icon, bundle_identifier="dev.braid.app")
