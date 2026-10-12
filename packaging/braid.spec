# PyInstaller spec：pyinstaller packaging/braid.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
icon = str(Path(SPECPATH) / ("braid_light.icns" if sys.platform == "darwin" else "braid_light.ico"))

a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "src")],
    datas=collect_data_files("braid"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="braid",
          console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="braid")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Braid.app", icon=icon, bundle_identifier="dev.braid.app")
